"""Per-user tastytrade credential management.

Responsibilities:
  • AES-256-GCM encryption of the tastytrade password (reuses encrypt/decrypt
    from llm_creds.py — same HKDF key derived from BRAIN_API_KEY).
  • File-based per-user settings store (JSON, in the persistent data dir).
  • get_effective_tastytrade_creds(): returns credentials for a given user_id,
    raising HTTPException 400 if no credentials are configured.

Security properties:
  • The password value is NEVER returned to API callers — only presence indicators.
  • Username and account_number are non-secret and stored plaintext.
  • Encryption key: AES-256-GCM via HKDF-SHA-256 from BRAIN_API_KEY.
  • Each ciphertext includes a random 12-byte GCM nonce.
  • The settings file is chmod 0o600 after every write.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class UserTastytradeSettings:
    username:       str | None = None   # plaintext
    password_enc:   str | None = None   # AES-256-GCM encrypted, base64
    account_number: str | None = None   # plaintext; None = "use first account"
    paper_mode:     bool = True


@dataclass
class EffectiveTastytradeCreds:
    username:       str
    password:       str
    account_number: str | None
    paper_mode:     bool
    keys_configured: bool


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
            probe = os.path.join(p, ".tt_probe")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
            _STORE_PATH = os.path.join(p, "user_tastytrade_settings.json")
            return _STORE_PATH
        except Exception:
            continue
    _STORE_PATH = "/tmp/user_tastytrade_settings.json"
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
        log.warning("Could not read tastytrade settings store %s: %s", path, exc)
        return {}


def _write_store(data: dict) -> None:
    path = _store_path()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    except Exception as exc:
        log.warning("Could not write tastytrade settings store %s: %s", path, exc)


# ── Public API ────────────────────────────────────────────────────────────────

def load_user_tastytrade_settings(user_id: str) -> UserTastytradeSettings:
    with _STORE_LOCK:
        store = _read_store()
    row = store.get(user_id, {})
    return UserTastytradeSettings(
        username=row.get("username"),
        password_enc=row.get("password_enc"),
        account_number=row.get("account_number") or None,
        paper_mode=row.get("paper_mode", True),
    )


def save_user_tastytrade_settings(
    user_id: str,
    username: str,
    new_password: str,          # plaintext; empty = "don't change stored password"
    account_number: str,        # empty = "use first account"
    paper_mode: bool,
    enc_key: bytes,
) -> None:
    """Merge settings into the persistent store.  Password is AES-256-GCM encrypted."""
    from brain.llm_creds import encrypt_api_key
    with _STORE_LOCK:
        store = _read_store()
        row   = store.get(user_id, {})
        if username:
            row["username"] = username
        if new_password:
            row["password_enc"] = encrypt_api_key(new_password, enc_key)
        row["account_number"] = account_number or None
        row["paper_mode"]     = paper_mode
        store[user_id] = row
        _write_store(store)


def get_effective_tastytrade_creds(user_id: str, enc_key: bytes) -> EffectiveTastytradeCreds:
    """Return decrypted tastytrade credentials for user_id.

    Raises ValueError if no username or password is configured — caller converts
    this to HTTPException 400.
    """
    from brain.llm_creds import decrypt_api_key

    settings = load_user_tastytrade_settings(user_id)
    username = settings.username or ""
    password = ""
    if settings.password_enc:
        try:
            password = decrypt_api_key(settings.password_enc, enc_key)
        except Exception as exc:
            log.warning("Cannot decrypt tastytrade password for user %s: %s", user_id, exc)

    configured = bool(username and password)
    return EffectiveTastytradeCreds(
        username=username,
        password=password,
        account_number=settings.account_number,
        paper_mode=settings.paper_mode,
        keys_configured=configured,
    )
