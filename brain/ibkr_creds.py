"""Per-user Interactive Brokers connection settings.

Stores IB Gateway host/port/clientId — these are connection parameters, not secrets.
Authentication is managed entirely by IB Gateway (user logs in once there).
No values are encrypted; account_id is IBKR's own account identifier
(visible in the IBKR UI and not considered sensitive).

File: {DATA_DIR}/user_ibkr_settings.json (chmod 0o600)
Schema: { "<user_id>": { "host": ..., "port": ..., "client_id": ...,
                          "account_id": ..., "paper_mode": ... } }
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

log = logging.getLogger(__name__)

_DATA_DIR = os.environ.get("DATA_DIR", "/tmp/brain_data")
_STORE = os.path.join(_DATA_DIR, "user_ibkr_settings.json")

_DEFAULT_PAPER_PORT = 4002
_DEFAULT_LIVE_PORT  = 4001


@dataclass
class UserIBKRSettings:
    host:       str  = "127.0.0.1"
    port:       int  = _DEFAULT_PAPER_PORT
    client_id:  int  = 1
    account_id: str  = ""
    paper_mode: bool = True
    configured: bool = False


def _load_store() -> dict:
    try:
        with open(_STORE) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("Could not read IBKR settings store: %s", exc)
        return {}


def _write_store(data: dict) -> None:
    os.makedirs(os.path.dirname(_STORE) if os.path.dirname(_STORE) else ".", exist_ok=True)
    tmp = _STORE + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, _STORE)
        os.chmod(_STORE, 0o600)
    except Exception as exc:
        log.error("Could not write IBKR settings store: %s", exc)


def load_ibkr_settings(user_id: str) -> UserIBKRSettings:
    """Return stored IB Gateway settings, or safe defaults if not configured."""
    data  = _load_store()
    entry = data.get(user_id)
    if not isinstance(entry, dict):
        return UserIBKRSettings()
    return UserIBKRSettings(
        host       = str(entry.get("host",       "127.0.0.1")),
        port       = int(entry.get("port",       _DEFAULT_PAPER_PORT)),
        client_id  = int(entry.get("client_id",  1)),
        account_id = str(entry.get("account_id", "")),
        paper_mode = bool(entry.get("paper_mode", True)),
        configured = True,
    )


def save_ibkr_settings(
    user_id:    str,
    host:       str,
    port:       int,
    client_id:  int,
    account_id: str,
    paper_mode: bool,
) -> None:
    data = _load_store()
    data[user_id] = {
        "host":       host,
        "port":       port,
        "client_id":  client_id,
        "account_id": account_id,
        "paper_mode": paper_mode,
    }
    _write_store(data)
    log.info("IBKR settings saved for user %s — %s:%d (paper=%s)", user_id[:8], host, port, paper_mode)


def delete_ibkr_settings(user_id: str) -> bool:
    data = _load_store()
    if user_id not in data:
        return False
    del data[user_id]
    _write_store(data)
    return True
