"""Per-user Kraken credential management (API key + base64 secret).

Both values are AES-256-GCM encrypted at rest. Neither is ever returned
to API callers — only a presence indicator and key prefix are exposed.
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


@dataclass
class EffectiveKrakenCreds:
    api_key:    str
    api_secret: str
    configured: bool


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
            probe = os.path.join(p, ".kraken_probe")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
            _STORE_PATH = os.path.join(p, "user_kraken_settings.json")
            return _STORE_PATH
        except Exception:
            continue
    _STORE_PATH = "/tmp/user_kraken_settings.json"
    return _STORE_PATH


def _read() -> dict:
    try:
        with open(_store_path()) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("Cannot read Kraken settings: %s", exc)
        return {}


def _write(data: dict) -> None:
    path = _store_path()
    tmp  = path + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    except Exception as exc:
        log.warning("Cannot write Kraken settings: %s", exc)


def load_kraken_settings(user_id: str) -> dict:
    with _STORE_LOCK:
        return _read().get(user_id, {})


def save_kraken_settings(
    user_id: str,
    api_key: str,
    api_secret: str,
    enc_key: bytes,
) -> None:
    from brain.llm_creds import encrypt_api_key
    with _STORE_LOCK:
        store = _read()
        row   = store.get(user_id, {})
        if api_key:
            row["api_key_enc"] = encrypt_api_key(api_key, enc_key)
        if api_secret:
            row["api_secret_enc"] = encrypt_api_key(api_secret, enc_key)
        store[user_id] = row
        _write(store)


def delete_kraken_settings(user_id: str) -> bool:
    with _STORE_LOCK:
        store = _read()
        if user_id not in store:
            return False
        del store[user_id]
        _write(store)
    return True


def get_effective_kraken_creds(user_id: str, enc_key: bytes) -> EffectiveKrakenCreds:
    from brain.llm_creds import decrypt_api_key
    row        = load_kraken_settings(user_id)
    api_key    = ""
    api_secret = ""
    if row.get("api_key_enc"):
        try:
            api_key = decrypt_api_key(row["api_key_enc"], enc_key)
        except Exception as exc:
            log.warning("Cannot decrypt Kraken key for %s: %s", user_id, exc)
    if row.get("api_secret_enc"):
        try:
            api_secret = decrypt_api_key(row["api_secret_enc"], enc_key)
        except Exception as exc:
            log.warning("Cannot decrypt Kraken secret for %s: %s", user_id, exc)
    return EffectiveKrakenCreds(
        api_key=api_key,
        api_secret=api_secret,
        configured=bool(api_key and api_secret),
    )
