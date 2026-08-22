"""System-level NGX Pulse API key management.

Stores the NGX Pulse market-data API key used to fetch Nigerian Exchange
(NGX) price history for the Technical Analysis charts.

Priority order in get_ngx_pulse_key():
  1. Stored encrypted key (written via /ngx-settings endpoint)
  2. NGX_PULSE_API_KEY environment variable
  3. None — caller should raise an appropriate 503

Security: key values are NEVER returned in API responses.
"""
from __future__ import annotations

import json
import logging
import os
import threading

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
            probe = os.path.join(p, ".ngx_probe")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
            _STORE_PATH = os.path.join(p, "ngx_pulse_settings.json")
            return _STORE_PATH
        except Exception:
            continue
    _STORE_PATH = "/tmp/ngx_pulse_settings.json"
    return _STORE_PATH


def _read_store() -> dict:
    path = _store_path()
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("Could not read NGX Pulse settings: %s", exc)
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
        log.warning("Could not write NGX Pulse settings: %s", exc)


def save_ngx_pulse_key(api_key: str, enc_key: bytes) -> None:
    """Encrypt and persist the NGX Pulse API key."""
    from brain.llm_creds import encrypt_api_key
    with _STORE_LOCK:
        store = _read_store()
        store["api_key_enc"] = encrypt_api_key(api_key, enc_key)
        _write_store(store)
    log.info("NGX Pulse API key saved")


def delete_ngx_pulse_key() -> bool:
    """Remove the stored key. Returns True if one existed."""
    with _STORE_LOCK:
        store = _read_store()
        existed = "api_key_enc" in store
        if existed:
            del store["api_key_enc"]
            _write_store(store)
    if existed:
        log.info("NGX Pulse API key removed")
    return existed


def get_ngx_pulse_key(enc_key: bytes | None = None) -> str | None:
    """Return the active NGX Pulse API key, or None if unconfigured."""
    if enc_key:
        with _STORE_LOCK:
            store = _read_store()
        enc = store.get("api_key_enc")
        if enc:
            try:
                from brain.llm_creds import decrypt_api_key
                return decrypt_api_key(enc, enc_key)
            except Exception as exc:
                log.warning("Cannot decrypt NGX Pulse key: %s", exc)
    return os.environ.get("NGX_PULSE_API_KEY") or None


def get_ngx_pulse_settings_info(enc_key: bytes | None = None) -> dict:
    """Return settings metadata — no key values included."""
    with _STORE_LOCK:
        store = _read_store()
    stored = bool(store.get("api_key_enc"))
    env    = bool(os.environ.get("NGX_PULSE_API_KEY"))
    source = "stored" if stored else ("env" if env else "none")
    return {
        "key_configured": stored or env,
        "stored_key":     stored,
        "env_key":        env,
        "source":         source,
    }
