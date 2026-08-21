"""Per-user LLM credential management.

Responsibilities:
  • AES-256-GCM encryption / decryption of API keys at the application layer.
  • File-based per-user settings store (JSON, in the app's persistent data dir).
  • Unified LLM client that wraps OpenAI-compatible SDKs and the Anthropic native SDK
    behind a single .chat.completions.create() interface.
  • get_effective_llm_config(): returns the right provider/model/client pair for a
    given user_id, falling back to the system OpenRouter key when the user has no
    per-user configuration.

Security properties:
  • API key values are NEVER returned to callers — only presence indicators.
  • Encryption key is derived from BRAIN_API_KEY via HKDF-SHA-256 (32 bytes / AES-256).
  • Each ciphertext includes a random 12-byte GCM nonce, so encrypting the same key
    twice produces different ciphertext.
  • The settings file is chmod 0o600 after every write.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

# ── Encryption helpers ────────────────────────────────────────────────────────

def _derive_enc_key(secret: str) -> bytes:
    """Derive a 32-byte AES-256 key from a high-entropy secret using HKDF-SHA-256."""
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives import hashes
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"trading-agent-llm-keys-v1",
        info=b"llm-credential-encryption",
    ).derive(secret.encode())


def encrypt_api_key(plaintext: str, key: bytes) -> str:
    """AES-256-GCM encrypt. Returns base64(nonce || ciphertext)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()


def decrypt_api_key(ciphertext: str, key: bytes) -> str:
    """AES-256-GCM decrypt. Raises InvalidTag / ValueError on tampered data."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    raw = base64.b64decode(ciphertext)
    nonce, ct = raw[:12], raw[12:]
    return AESGCM(key).decrypt(nonce, ct, None).decode()


# ── Anthropic response adapter ────────────────────────────────────────────────

class _AnthropicUsage:
    def __init__(self, in_tok: int, out_tok: int) -> None:
        self.prompt_tokens = in_tok
        self.completion_tokens = out_tok


class _AnthropicMessage:
    def __init__(self, text: str) -> None:
        self.content = text


class _AnthropicChoice:
    def __init__(self, text: str) -> None:
        self.message = _AnthropicMessage(text)


class _AnthropicResponse:
    """Wraps an anthropic.Message to look like an openai ChatCompletion."""

    def __init__(self, resp: Any) -> None:
        text = resp.content[0].text if resp.content else ""
        self.choices = [_AnthropicChoice(text)]
        self.usage = _AnthropicUsage(
            resp.usage.input_tokens if resp.usage else 0,
            resp.usage.output_tokens if resp.usage else 0,
        )


# ── Unified LLM client ────────────────────────────────────────────────────────

class _UnifiedCompletions:
    def __init__(self, parent: "_UnifiedClient") -> None:
        self._parent = parent

    def create(self, model: str, messages: list, max_tokens: int = 1024, **_kw) -> Any:
        return self._parent._create(model, messages, max_tokens)


class _UnifiedChat:
    def __init__(self, parent: "_UnifiedClient") -> None:
        self.completions = _UnifiedCompletions(parent)


class _UnifiedClient:
    """Single interface over all 7 LLM providers.

    Exposes `.chat.completions.create(model, messages, max_tokens)` regardless of
    the underlying SDK — Anthropic native or OpenAI-compatible.
    """

    def __init__(self, provider: str, api_key: str, base_url: str | None) -> None:
        self.chat = _UnifiedChat(self)
        self._provider = provider
        if provider == "anthropic":
            import anthropic
            self._client = anthropic.Anthropic(api_key=api_key)
        else:
            from openai import OpenAI
            self._client = OpenAI(base_url=base_url, api_key=api_key)

    def _create(self, model: str, messages: list, max_tokens: int) -> Any:
        if self._provider == "anthropic":
            system = next((m["content"] for m in messages if m["role"] == "system"), "")
            user_msgs = [m for m in messages if m["role"] != "system"]
            resp = self._client.messages.create(
                model=model, max_tokens=max_tokens, system=system, messages=user_msgs,
            )
            return _AnthropicResponse(resp)
        return self._client.chat.completions.create(
            model=model, max_tokens=max_tokens, messages=messages,
        )


# ── Settings data class ───────────────────────────────────────────────────────

@dataclass
class UserLLMSettings:
    tactical_provider: str = "openrouter"
    tactical_model:    str = "google/gemini-2.5-flash-lite"
    synthesis_provider: str = "openrouter"
    synthesis_model:    str = "deepseek/deepseek-chat-v3-0324"
    # Encrypted key blobs — None means "use system fallback"
    enc_keys: dict[str, str] = field(default_factory=dict)


@dataclass
class EffectiveLLMConfig:
    tactical_provider:  str
    tactical_model:     str
    synthesis_provider: str
    synthesis_model:    str
    tactical_client:    Any
    synthesis_client:   Any
    keys_configured:    list[str]   # provider names that have keys set
    using_system_keys:  bool        # True = fell back to system env-var keys


# ── File-based settings store ─────────────────────────────────────────────────

_STORE_LOCK = threading.Lock()
_STORE_PATH: str | None = None


def _store_path() -> str:
    global _STORE_PATH
    if _STORE_PATH:
        return _STORE_PATH
    # Mirror brain/api.py's _find_data_dir() precedence
    candidates = [
        os.environ.get("DATA_DIR", ""),
        "/data",
        os.path.normpath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
        ),
        "/tmp",
    ]
    for p in (c for c in candidates if c):
        try:
            os.makedirs(p, exist_ok=True)
            probe = os.path.join(p, ".llm_probe")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
            _STORE_PATH = os.path.join(p, "user_llm_settings.json")
            return _STORE_PATH
        except Exception:
            continue
    _STORE_PATH = "/tmp/user_llm_settings.json"
    return _STORE_PATH


def _read_store() -> dict:
    path = _store_path()
    try:
        with open(path) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("Could not read LLM settings store %s: %s", path, exc)
        return {}


def _write_store(data: dict) -> None:
    path = _store_path()
    try:
        with open(path, "w") as f:
            json.dump(data, f)
        os.chmod(path, 0o600)
    except Exception as exc:
        log.warning("Could not write LLM settings store %s: %s", path, exc)


def load_user_settings(user_id: str) -> UserLLMSettings:
    with _STORE_LOCK:
        store = _read_store()
    row = store.get(user_id, {})
    return UserLLMSettings(
        tactical_provider=row.get("tactical_provider", "openrouter"),
        tactical_model=row.get("tactical_model", "google/gemini-2.5-flash-lite"),
        synthesis_provider=row.get("synthesis_provider", "openrouter"),
        synthesis_model=row.get("synthesis_model", "deepseek/deepseek-chat-v3-0324"),
        enc_keys=row.get("enc_keys", {}),
    )


def save_user_settings(
    user_id: str,
    tactical_provider: str,
    tactical_model: str,
    synthesis_provider: str,
    synthesis_model: str,
    new_api_keys: dict[str, str],   # provider → plaintext key (only keys being updated)
    enc_key: bytes,
) -> None:
    """Merge new settings + encrypted keys into the persistent store."""
    with _STORE_LOCK:
        store = _read_store()
        row = store.get(user_id, {})
        # Merge new encrypted keys on top of existing ones
        existing_enc = row.get("enc_keys", {})
        for provider, plaintext in new_api_keys.items():
            if plaintext:  # empty string = "don't change"
                existing_enc[provider] = encrypt_api_key(plaintext, enc_key)
        store[user_id] = {
            "tactical_provider":  tactical_provider,
            "tactical_model":     tactical_model,
            "synthesis_provider": synthesis_provider,
            "synthesis_model":    synthesis_model,
            "enc_keys":           existing_enc,
        }
        _write_store(store)


def get_keys_configured(user_id: str) -> list[str]:
    """Return list of provider names for which the user has a stored key."""
    with _STORE_LOCK:
        store = _read_store()
    return list(store.get(user_id, {}).get("enc_keys", {}).keys())


# ── Effective config resolver ─────────────────────────────────────────────────

def _build_client(provider: str, api_key: str) -> _UnifiedClient:
    from watchlist import PROVIDER_BASE_URLS
    base_url = PROVIDER_BASE_URLS.get(provider)
    return _UnifiedClient(provider, api_key, base_url)


def get_effective_llm_config(
    user_id: str | None,
    openrouter_api_key: str,
    enc_key: bytes,
) -> EffectiveLLMConfig:
    """Return the LLM provider/model/client pair for a request.

    Priority:
      1. User's per-user settings (if user_id is not None and user has stored keys)
      2. System fallback: OpenRouter with OPENROUTER_API_KEY env var

    Falls back to system defaults silently if the user has no key for their chosen
    provider (avoids breaking the signal flow on misconfiguration).
    """
    if user_id:
        settings = load_user_settings(user_id)
        t_key = None
        s_key = None
        # Decrypt tactical provider key
        enc_t = settings.enc_keys.get(settings.tactical_provider)
        if enc_t:
            try:
                t_key = decrypt_api_key(enc_t, enc_key)
            except Exception as exc:
                log.warning("Cannot decrypt tactical key for user %s: %s", user_id, exc)
        # Decrypt synthesis provider key
        enc_s = settings.enc_keys.get(settings.synthesis_provider)
        if enc_s:
            try:
                s_key = decrypt_api_key(enc_s, enc_key)
            except Exception as exc:
                log.warning("Cannot decrypt synthesis key for user %s: %s", user_id, exc)

        if t_key and s_key:
            return EffectiveLLMConfig(
                tactical_provider=settings.tactical_provider,
                tactical_model=settings.tactical_model,
                synthesis_provider=settings.synthesis_provider,
                synthesis_model=settings.synthesis_model,
                tactical_client=_build_client(settings.tactical_provider, t_key),
                synthesis_client=_build_client(settings.synthesis_provider, s_key),
                keys_configured=list(settings.enc_keys.keys()),
                using_system_keys=False,
            )
        if t_key and not s_key:
            # Tactical key present but synthesis key missing → use tactical key for both
            log.info("User %s: no synthesis key for %s — using tactical key for synthesis too",
                     user_id, settings.synthesis_provider)
            client = _build_client(settings.tactical_provider, t_key)
            return EffectiveLLMConfig(
                tactical_provider=settings.tactical_provider,
                tactical_model=settings.tactical_model,
                synthesis_provider=settings.tactical_provider,
                synthesis_model=settings.tactical_model,
                tactical_client=client,
                synthesis_client=client,
                keys_configured=list(settings.enc_keys.keys()),
                using_system_keys=False,
            )

    # System fallback — OpenRouter with env-var key
    client = _build_client("openrouter", openrouter_api_key)
    return EffectiveLLMConfig(
        tactical_provider="openrouter",
        tactical_model="google/gemini-2.5-flash-lite",
        synthesis_provider="openrouter",
        synthesis_model="deepseek/deepseek-chat-v3-0324",
        tactical_client=client,
        synthesis_client=client,
        keys_configured=[],
        using_system_keys=True,
    )
