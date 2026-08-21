"""Per-user Charles Schwab OAuth token storage.

Tokens are encrypted at rest (AES-256-GCM via HKDF from BRAIN_API_KEY).
Expiry timestamps are stored as Unix floats (plaintext — not secret).
account_hash (the Schwab encrypted account identifier) is stored plaintext.

Access token lifetime: ~30 minutes.
Refresh token lifetime: ~7 days.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from brain.llm_creds import decrypt_api_key, encrypt_api_key

_DATA_DIR = os.environ.get("DATA_DIR", "/tmp/brain_data")
_STORE    = Path(_DATA_DIR) / "user_schwab_tokens.json"


# ── Data types ─────────────────────────────────────────────────────────────────

@dataclass
class UserSchwabTokens:
    """Raw record stored to disk (all values already encrypted or plaintext)."""
    access_token_enc:    str = ""   # AES-256-GCM encrypted
    refresh_token_enc:   str = ""   # AES-256-GCM encrypted
    access_token_exp:    float = 0.0  # Unix timestamp — when access token expires
    refresh_token_exp:   float = 0.0  # Unix timestamp — when refresh token expires
    account_hash:        str = ""   # Schwab hashValue for API calls (plaintext, not secret)


@dataclass
class EffectiveSchwabTokens:
    """Decrypted view used at runtime."""
    access_token:        str
    refresh_token:       str
    access_token_exp:    float
    refresh_token_exp:   float
    account_hash:        str
    configured:          bool       # True if both tokens are present
    access_expired:      bool       # True if access token has expired
    refresh_expired:     bool       # True if refresh token has expired


# ── Storage helpers ────────────────────────────────────────────────────────────

def _load_store() -> dict:
    try:
        return json.loads(_STORE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_store(data: dict) -> None:
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(_STORE) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, str(_STORE))
    os.chmod(str(_STORE), 0o600)


# ── Public API ─────────────────────────────────────────────────────────────────

def save_schwab_tokens(
    user_id:          str,
    enc_key:          bytes,
    access_token:     str,
    refresh_token:    str,
    access_token_exp: float,
    refresh_token_exp: float,
    account_hash:     str,
) -> None:
    data = _load_store()
    data[user_id] = {
        "access_token_enc":  encrypt_api_key(access_token,  enc_key) if access_token  else "",
        "refresh_token_enc": encrypt_api_key(refresh_token, enc_key) if refresh_token else "",
        "access_token_exp":  access_token_exp,
        "refresh_token_exp": refresh_token_exp,
        "account_hash":      account_hash,
    }
    _write_store(data)


def load_schwab_tokens(user_id: str, enc_key: bytes) -> EffectiveSchwabTokens | None:
    """Return decrypted tokens, or None if this user has no stored tokens."""
    data  = _load_store()
    entry = data.get(user_id)
    if not entry:
        return None

    raw = UserSchwabTokens(
        access_token_enc  = entry.get("access_token_enc",  ""),
        refresh_token_enc = entry.get("refresh_token_enc", ""),
        access_token_exp  = float(entry.get("access_token_exp",  0) or 0),
        refresh_token_exp = float(entry.get("refresh_token_exp", 0) or 0),
        account_hash      = entry.get("account_hash", ""),
    )

    access_token  = decrypt_api_key(raw.access_token_enc,  enc_key) if raw.access_token_enc  else ""
    refresh_token = decrypt_api_key(raw.refresh_token_enc, enc_key) if raw.refresh_token_enc else ""

    now = time.time()
    return EffectiveSchwabTokens(
        access_token      = access_token,
        refresh_token     = refresh_token,
        access_token_exp  = raw.access_token_exp,
        refresh_token_exp = raw.refresh_token_exp,
        account_hash      = raw.account_hash,
        configured        = bool(access_token and refresh_token),
        access_expired    = bool(raw.access_token_exp and now >= raw.access_token_exp),
        refresh_expired   = bool(raw.refresh_token_exp and now >= raw.refresh_token_exp),
    )


def delete_schwab_tokens(user_id: str) -> bool:
    """Remove stored tokens for user. Returns True if a record existed."""
    data = _load_store()
    if user_id not in data:
        return False
    del data[user_id]
    _write_store(data)
    return True


def update_schwab_access_token(
    user_id:          str,
    enc_key:          bytes,
    access_token:     str,
    access_token_exp: float,
) -> None:
    """Atomically replace only the access token (after a refresh grant)."""
    data  = _load_store()
    entry = data.get(user_id, {})
    entry["access_token_enc"] = encrypt_api_key(access_token, enc_key) if access_token else ""
    entry["access_token_exp"] = access_token_exp
    data[user_id] = entry
    _write_store(data)
