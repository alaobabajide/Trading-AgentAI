"""Per-user TradingView webhook secret management.

Each browser user can generate a unique secret that appears exactly once.
Secrets are stored as SHA-256 hashes — the plaintext is never persisted.

Webhook URL format:
  POST /webhook/tradingview/{user_id}/{secret}

Security properties:
  • Generated secret: 32-byte URL-safe random (secrets.token_urlsafe(32))
  • Storage: SHA-256(secret) only — plaintext never persisted after generation
  • Comparison: hmac.compare_digest to prevent timing attacks
  • File: chmod 0o600, atomic write (tmp + os.replace)

Orchestrator invariant:
  The webhook endpoint resolves user_id from the URL path, never from
  request.state — this code path is structurally separate from orchestrator
  auth (X-Api-Key sets no user_id in state).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
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
        os.path.normpath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
        ),
        "/tmp",
    ]
    for p in (c for c in candidates if c):
        try:
            os.makedirs(p, exist_ok=True)
            probe = os.path.join(p, ".webhook_probe")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
            _STORE_PATH = os.path.join(p, "user_webhook_secrets.json")
            return _STORE_PATH
        except Exception:
            continue
    _STORE_PATH = "/tmp/user_webhook_secrets.json"
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
        log.warning("Could not read webhook secret store %s: %s", path, exc)
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
        log.warning("Could not write webhook secret store %s: %s", path, exc)


def _hash_secret(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def generate_secret(user_id: str) -> str:
    """Generate and store a new secret. Returns the plaintext — shown to the user once."""
    plaintext = secrets.token_urlsafe(32)
    with _STORE_LOCK:
        store = _read_store()
        store[user_id] = {"secret_hash": _hash_secret(plaintext)}
        _write_store(store)
    return plaintext


def validate_secret(user_id: str, candidate: str) -> bool:
    """Timing-safe validation of candidate against the stored hash."""
    with _STORE_LOCK:
        store = _read_store()
    row = store.get(user_id)
    if not row or not row.get("secret_hash"):
        return False
    return hmac.compare_digest(row["secret_hash"], _hash_secret(candidate))


def revoke_secret(user_id: str) -> bool:
    """Remove the user's secret. Returns True if one existed."""
    with _STORE_LOCK:
        store = _read_store()
        if user_id not in store:
            return False
        del store[user_id]
        _write_store(store)
    return True


def has_secret(user_id: str) -> bool:
    """Return True if a secret hash is stored for this user."""
    with _STORE_LOCK:
        store = _read_store()
    return bool(store.get(user_id, {}).get("secret_hash"))
