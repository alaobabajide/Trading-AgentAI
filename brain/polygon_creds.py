"""Per-user Polygon.io API key management.

Responsibilities:
  • AES-256-GCM encryption of the Polygon API key (same key derivation as
    llm_creds.py / alpaca_creds.py — HKDF-SHA-256 from BRAIN_API_KEY).
  • File-based per-user settings store (JSON, in the persistent data dir).
  • get_effective_polygon_key(): returns the best key for a given user:
      1. Per-user key (if configured)
      2. System POLYGON_API_KEY env var (if set)
      3. None (caller falls back to Alpaca market data)

Security: API key values are NEVER returned in API responses.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass
class UserPolygonSettings:
    api_key_enc: str | None = None   # AES-256-GCM encrypted, base64


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
            probe = os.path.join(p, ".poly_probe")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
            _STORE_PATH = os.path.join(p, "user_polygon_settings.json")
            return _STORE_PATH
        except Exception:
            continue
    _STORE_PATH = "/tmp/user_polygon_settings.json"
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
        log.warning("Could not read Polygon settings store %s: %s", path, exc)
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
        log.warning("Could not write Polygon settings store %s: %s", path, exc)


# ── Public API ────────────────────────────────────────────────────────────────

def load_user_polygon_settings(user_id: str) -> UserPolygonSettings:
    with _STORE_LOCK:
        store = _read_store()
    row = store.get(user_id, {})
    return UserPolygonSettings(api_key_enc=row.get("api_key_enc"))


def save_user_polygon_key(user_id: str, new_api_key: str, enc_key: bytes) -> None:
    """Encrypt and persist the user's Polygon API key."""
    from brain.llm_creds import encrypt_api_key
    with _STORE_LOCK:
        store = _read_store()
        row   = store.get(user_id, {})
        if new_api_key:
            row["api_key_enc"] = encrypt_api_key(new_api_key, enc_key)
        store[user_id] = row
        _write_store(store)
    log.info("Polygon API key saved for user %s", user_id[:8])


def delete_user_polygon_key(user_id: str) -> bool:
    """Remove the user's stored Polygon key. Returns True if one existed."""
    with _STORE_LOCK:
        store = _read_store()
        if user_id not in store:
            return False
        del store[user_id]
        _write_store(store)
    log.info("Polygon API key removed for user %s", user_id[:8])
    return True


def get_effective_polygon_key(user_id: str | None, enc_key: bytes, cfg) -> str | None:
    """Return the best Polygon API key for this request, or None.

    Priority:
      1. Per-user key (JWT user with key stored)
      2. System POLYGON_API_KEY env var
      3. None → caller should fall back to Alpaca market data
    """
    from brain.llm_creds import decrypt_api_key

    if user_id:
        settings = load_user_polygon_settings(user_id)
        if settings.api_key_enc:
            try:
                key = decrypt_api_key(settings.api_key_enc, enc_key)
                if key:
                    return key
            except Exception as exc:
                log.warning("Cannot decrypt Polygon key for user %s: %s", user_id, exc)

    system_key = getattr(cfg, "polygon_api_key", "") or os.environ.get("POLYGON_API_KEY", "")
    return system_key or None
