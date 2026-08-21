"""Per-user Coinbase Advanced Trade credential management.

Stores CDP API key name (plaintext) and EC private key PEM (encrypted).
The private key is AES-256-GCM encrypted at rest and never returned to callers.
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
class EffectiveCoinbaseCreds:
    api_key_name: str
    private_key:  str
    configured:   bool


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
            probe = os.path.join(p, ".cb_probe")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
            _STORE_PATH = os.path.join(p, "user_coinbase_settings.json")
            return _STORE_PATH
        except Exception:
            continue
    _STORE_PATH = "/tmp/user_coinbase_settings.json"
    return _STORE_PATH


def _read() -> dict:
    try:
        with open(_store_path()) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("Cannot read Coinbase settings: %s", exc)
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
        log.warning("Cannot write Coinbase settings: %s", exc)


def load_coinbase_settings(user_id: str) -> dict:
    with _STORE_LOCK:
        return _read().get(user_id, {})


def save_coinbase_settings(
    user_id: str,
    api_key_name: str,
    private_key: str,
    enc_key: bytes,
) -> None:
    from brain.llm_creds import encrypt_api_key
    with _STORE_LOCK:
        store = _read()
        row   = store.get(user_id, {})
        # Key name is non-secret; store plaintext for display
        if api_key_name:
            row["api_key_name"] = api_key_name
        # Private key is a secret — encrypt it
        if private_key:
            row["private_key_enc"] = encrypt_api_key(private_key, enc_key)
        store[user_id] = row
        _write(store)


def delete_coinbase_settings(user_id: str) -> bool:
    with _STORE_LOCK:
        store = _read()
        if user_id not in store:
            return False
        del store[user_id]
        _write(store)
    return True


def get_effective_coinbase_creds(user_id: str, enc_key: bytes) -> EffectiveCoinbaseCreds:
    from brain.llm_creds import decrypt_api_key
    row         = load_coinbase_settings(user_id)
    api_key     = row.get("api_key_name", "")
    private_key = ""
    if row.get("private_key_enc"):
        try:
            private_key = decrypt_api_key(row["private_key_enc"], enc_key)
        except Exception as exc:
            log.warning("Cannot decrypt Coinbase private key for %s: %s", user_id, exc)
    return EffectiveCoinbaseCreds(
        api_key_name=api_key,
        private_key=private_key,
        configured=bool(api_key and private_key),
    )
