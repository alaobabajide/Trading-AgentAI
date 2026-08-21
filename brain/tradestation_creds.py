"""Per-user TradeStation OAuth token + account settings management.

Tokens (access + refresh) are AES-256-GCM encrypted at rest.
Account number is stored plaintext (not a secret).
Paper mode is derived from whether the account number starts with "SIM".
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)
_STORE_LOCK = threading.Lock()
_STORE_PATH: str | None = None


@dataclass
class EffectiveTSTokens:
    access_token:       str
    refresh_token:      str
    access_token_exp:   float   # Unix timestamp
    refresh_token_exp:  float
    account_number:     str
    paper_mode:         bool
    configured:         bool

    @property
    def access_expired(self) -> bool:
        return time.time() >= self.access_token_exp

    @property
    def refresh_expired(self) -> bool:
        return time.time() >= self.refresh_token_exp


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
            probe = os.path.join(p, ".ts_probe")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
            _STORE_PATH = os.path.join(p, "user_tradestation_tokens.json")
            return _STORE_PATH
        except Exception:
            continue
    _STORE_PATH = "/tmp/user_tradestation_tokens.json"
    return _STORE_PATH


def _read() -> dict:
    try:
        with open(_store_path()) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("Cannot read TradeStation settings: %s", exc)
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
        log.warning("Cannot write TradeStation settings: %s", exc)


def save_ts_tokens(
    user_id: str,
    enc_key: bytes,
    access_token: str,
    refresh_token: str,
    access_token_exp: float,
    refresh_token_exp: float,
    account_number: str = "",
) -> None:
    from brain.llm_creds import encrypt_api_key
    with _STORE_LOCK:
        store = _read()
        row   = store.get(user_id, {})
        row["access_token_enc"]  = encrypt_api_key(access_token, enc_key)
        row["refresh_token_enc"] = encrypt_api_key(refresh_token, enc_key)
        row["access_token_exp"]  = access_token_exp
        row["refresh_token_exp"] = refresh_token_exp
        if account_number:
            row["account_number"] = account_number
        store[user_id] = row
        _write(store)


def update_ts_access_token(
    user_id: str,
    enc_key: bytes,
    access_token: str,
    access_token_exp: float,
) -> None:
    from brain.llm_creds import encrypt_api_key
    with _STORE_LOCK:
        store = _read()
        row   = store.get(user_id, {})
        row["access_token_enc"] = encrypt_api_key(access_token, enc_key)
        row["access_token_exp"] = access_token_exp
        store[user_id] = row
        _write(store)


def save_ts_account(user_id: str, account_number: str) -> None:
    with _STORE_LOCK:
        store = _read()
        row   = store.get(user_id, {})
        row["account_number"] = account_number
        store[user_id] = row
        _write(store)


def load_ts_tokens(user_id: str, enc_key: bytes) -> EffectiveTSTokens | None:
    from brain.llm_creds import decrypt_api_key
    with _STORE_LOCK:
        store = _read()
    row = store.get(user_id, {})
    if not row.get("access_token_enc"):
        return None
    try:
        access_token  = decrypt_api_key(row["access_token_enc"], enc_key)
        refresh_token = decrypt_api_key(row.get("refresh_token_enc", ""), enc_key)
    except Exception as exc:
        log.warning("Cannot decrypt TradeStation tokens for %s: %s", user_id, exc)
        return None
    account_number = row.get("account_number", "")
    paper_mode     = account_number.upper().startswith("SIM")
    return EffectiveTSTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        access_token_exp=float(row.get("access_token_exp", 0)),
        refresh_token_exp=float(row.get("refresh_token_exp", 0)),
        account_number=account_number,
        paper_mode=paper_mode,
        configured=bool(access_token and account_number),
    )


def delete_ts_tokens(user_id: str) -> bool:
    with _STORE_LOCK:
        store = _read()
        if user_id not in store:
            return False
        del store[user_id]
        _write(store)
    return True
