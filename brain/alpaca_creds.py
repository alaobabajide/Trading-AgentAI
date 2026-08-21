"""Per-user Alpaca credential management.

Responsibilities:
  • AES-256-GCM encryption / decryption of Alpaca API credentials (reuses
    encrypt/decrypt helpers from llm_creds.py — same key derivation from BRAIN_API_KEY).
  • File-based per-user settings store (JSON, in the app's persistent data dir).
  • get_effective_alpaca_creds(): returns the right Alpaca key pair for a given
    user_id, falling back to the system credentials from Railway env vars.

Security properties:
  • Credential values are NEVER returned to callers — only presence indicators.
  • Encryption key is derived from BRAIN_API_KEY via HKDF-SHA-256 (same key as LLM creds).
  • Each ciphertext includes a random 12-byte GCM nonce.
  • The settings file is chmod 0o600 after every write.

Orchestrator safety:
  • The orchestrator sends X-Api-Key (no user_id) — get_effective_alpaca_creds()
    always returns system credentials when user_id is None.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass

log = logging.getLogger(__name__)

_PAPER_BASE_URL = "https://paper-api.alpaca.markets"
_LIVE_BASE_URL  = "https://api.alpaca.markets"


@dataclass
class UserAlpacaSettings:
    api_key_enc:    str | None = None   # AES-256-GCM encrypted, base64
    secret_key_enc: str | None = None   # AES-256-GCM encrypted, base64
    paper_mode:     bool = True


@dataclass
class EffectiveAlpacaCreds:
    api_key:          str
    secret_key:       str
    alpaca_base_url:  str
    is_paper:         bool
    using_system_keys: bool
    keys_configured:   bool


# ── File-based settings store ─────────────────────────────────────────────────

_STORE_LOCK = threading.Lock()
_STORE_PATH: str | None = None


def _store_path() -> str:
    global _STORE_PATH
    if _STORE_PATH:
        return _STORE_PATH
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
            probe = os.path.join(p, ".alpaca_probe")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
            _STORE_PATH = os.path.join(p, "user_alpaca_settings.json")
            return _STORE_PATH
        except Exception:
            continue
    _STORE_PATH = "/tmp/user_alpaca_settings.json"
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
        log.warning("Could not read Alpaca settings store %s: %s", path, exc)
        return {}


def _write_store(data: dict) -> None:
    path = _store_path()
    try:
        with open(path, "w") as f:
            json.dump(data, f)
        os.chmod(path, 0o600)
    except Exception as exc:
        log.warning("Could not write Alpaca settings store %s: %s", path, exc)


def load_user_alpaca_settings(user_id: str) -> UserAlpacaSettings:
    with _STORE_LOCK:
        store = _read_store()
    row = store.get(user_id, {})
    return UserAlpacaSettings(
        api_key_enc=row.get("api_key_enc"),
        secret_key_enc=row.get("secret_key_enc"),
        paper_mode=row.get("paper_mode", True),
    )


def save_user_alpaca_settings(
    user_id: str,
    paper_mode: bool,
    new_api_key: str,       # plaintext; empty string = "don't change"
    new_secret_key: str,    # plaintext; empty string = "don't change"
    enc_key: bytes,
) -> None:
    """Merge paper_mode + encrypted keys into the persistent store."""
    from brain.llm_creds import encrypt_api_key
    with _STORE_LOCK:
        store = _read_store()
        row = store.get(user_id, {})
        if new_api_key:
            row["api_key_enc"] = encrypt_api_key(new_api_key, enc_key)
        if new_secret_key:
            row["secret_key_enc"] = encrypt_api_key(new_secret_key, enc_key)
        row["paper_mode"] = paper_mode
        store[user_id] = row
        _write_store(store)


def get_effective_alpaca_creds(user_id: str | None, enc_key: bytes, cfg) -> EffectiveAlpacaCreds:
    """Return the Alpaca credentials for a request.

    Priority:
      1. User's per-user settings (if user_id is not None and user has both keys stored)
      2. System fallback: credentials from Railway env vars

    Falls back to system defaults silently on missing or invalid keys.
    """
    from brain.llm_creds import decrypt_api_key

    if user_id:
        settings = load_user_alpaca_settings(user_id)
        api_key = secret_key = None
        if settings.api_key_enc:
            try:
                api_key = decrypt_api_key(settings.api_key_enc, enc_key)
            except Exception as exc:
                log.warning("Cannot decrypt Alpaca API key for user %s: %s", user_id, exc)
        if settings.secret_key_enc:
            try:
                secret_key = decrypt_api_key(settings.secret_key_enc, enc_key)
            except Exception as exc:
                log.warning("Cannot decrypt Alpaca secret key for user %s: %s", user_id, exc)

        if api_key and secret_key:
            base_url = _PAPER_BASE_URL if settings.paper_mode else _LIVE_BASE_URL
            return EffectiveAlpacaCreds(
                api_key=api_key,
                secret_key=secret_key,
                alpaca_base_url=base_url,
                is_paper=settings.paper_mode,
                using_system_keys=False,
                keys_configured=True,
            )

    # System fallback — always used for orchestrator (user_id = None)
    return EffectiveAlpacaCreds(
        api_key=cfg.alpaca_api_key or "",
        secret_key=cfg.alpaca_secret_key or "",
        alpaca_base_url=cfg.alpaca_base_url or _PAPER_BASE_URL,
        is_paper="paper" in (cfg.alpaca_base_url or "").lower(),
        using_system_keys=True,
        keys_configured=bool(cfg.alpaca_api_key),
    )
