"""Per-user Financial Modeling Prep (FMP) API key management.

Each user can store their own FMP API key, encrypted at rest with AES-256-GCM
(same HKDF derivation used across the rest of the credential stores).

Resolution order in get_effective_fmp_key():
  1. User's stored key (per-user, encrypted)
  2. FMP_API_KEY environment variable (system/shared key set by owner)
  3. None — FMP free tier with no key (very limited quota)

Security:
  • Key values are NEVER returned in API responses.
  • Each user's key is looked up strictly by their own user_id — there is
    no path by which one user's key is returned for a different user_id.
  • Store file is chmod 0o600.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass

log = logging.getLogger(__name__)

_STORE_LOCK = threading.Lock()
_STORE_PATH: str | None = None


def _store_path() -> str:
    global _STORE_PATH
    if _STORE_PATH:
        return _STORE_PATH
    candidates = [
        os.environ.get("DATA_DIR", ""),
        "/data",
        os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")),
        "/tmp",
    ]
    for p in (c for c in candidates if c):
        try:
            os.makedirs(p, exist_ok=True)
            probe = os.path.join(p, ".fmp_probe")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
            _STORE_PATH = os.path.join(p, "user_fmp_settings.json")
            return _STORE_PATH
        except Exception:
            continue
    _STORE_PATH = "/tmp/user_fmp_settings.json"
    return _STORE_PATH


def _read_store() -> dict:
    path = _store_path()
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("Could not read FMP settings store: %s", exc)
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
        log.warning("Could not write FMP settings store: %s", exc)


@dataclass
class UserFmpSettings:
    api_key_enc: str | None = None


def load_user_fmp_settings(user_id: str) -> UserFmpSettings:
    """Load settings for a specific user — never touches other users' rows."""
    with _STORE_LOCK:
        store = _read_store()
    row = store.get(user_id, {})
    return UserFmpSettings(api_key_enc=row.get("api_key_enc"))


def save_user_fmp_key(user_id: str, api_key: str, enc_key: bytes) -> None:
    """Encrypt and persist this user's FMP API key. Other users' rows untouched."""
    from brain.llm_creds import encrypt_api_key
    encrypted = encrypt_api_key(api_key, enc_key)
    with _STORE_LOCK:
        store = _read_store()
        row = store.get(user_id, {})
        row["api_key_enc"] = encrypted
        store[user_id] = row
        _write_store(store)
    log.info("FMP API key saved for user %s", user_id[:8])


def delete_user_fmp_key(user_id: str) -> bool:
    """Remove this user's FMP API key. Returns True if one existed."""
    with _STORE_LOCK:
        store = _read_store()
        row = store.get(user_id, {})
        if "api_key_enc" not in row:
            return False
        del row["api_key_enc"]
        if row:
            store[user_id] = row
        else:
            del store[user_id]
        _write_store(store)
    log.info("FMP API key removed for user %s", user_id[:8])
    return True


def get_effective_fmp_key(user_id: str | None, enc_key: bytes | None = None) -> str | None:
    """Return the best FMP API key available for this user (value never logged).

    Priority: user's stored key → FMP_API_KEY env var → None.
    """
    if user_id and enc_key:
        try:
            settings = load_user_fmp_settings(user_id)
            if settings.api_key_enc:
                from brain.llm_creds import decrypt_api_key
                return decrypt_api_key(settings.api_key_enc, enc_key)
        except Exception as exc:
            log.warning("Cannot decrypt FMP key for user %s: %s", user_id[:8], exc)
    return os.environ.get("FMP_API_KEY") or None
