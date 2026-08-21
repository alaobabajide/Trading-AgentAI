"""Per-user risk configuration overrides.

Each browser user can store their own values for any of the 23 risk fields.
Values are persisted to /data/user_risk_config.json — a flat JSON dict keyed
by Supabase user_id.

Merge order (highest priority wins):
  1. Per-user overrides (this module)
  2. Global dynamic overrides (_dynamic_config in api.py, from ta_dynamic_config.json)
  3. Environment-variable defaults (cfg.*)

Orchestrator safety:
  The orchestrator sends X-Api-Key (user_id = None).
  get_effective_risk_for_user(None, base) returns base unchanged — always
  the global config, never a browser user's per-user overrides.
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
        os.path.normpath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
        ),
        "/tmp",
    ]
    for p in (c for c in candidates if c):
        try:
            os.makedirs(p, exist_ok=True)
            probe = os.path.join(p, ".risk_probe")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
            _STORE_PATH = os.path.join(p, "user_risk_config.json")
            return _STORE_PATH
        except Exception:
            continue
    _STORE_PATH = "/tmp/user_risk_config.json"
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
        log.warning("Could not read risk config store %s: %s", path, exc)
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
        log.warning("Could not write risk config store %s: %s", path, exc)


def load_user_risk_config(user_id: str) -> dict:
    """Return the stored per-user risk overrides. Returns empty dict if none set."""
    with _STORE_LOCK:
        store = _read_store()
    return dict(store.get(user_id, {}))


def save_user_risk_config(user_id: str, validated_fields: dict) -> None:
    """Merge validated_fields into the user's stored overrides.

    Callers (api.py) are responsible for validating and clipping values to
    _CONFIG_BOUNDS / _CONFIG_INT_BOUNDS before calling this function.
    """
    with _STORE_LOCK:
        store = _read_store()
        row = dict(store.get(user_id, {}))
        row.update(validated_fields)
        store[user_id] = row
        _write_store(store)


def delete_user_risk_config(user_id: str) -> None:
    """Remove all per-user risk overrides (reverts user to global config)."""
    with _STORE_LOCK:
        store = _read_store()
        if user_id in store:
            del store[user_id]
            _write_store(store)


def get_effective_risk_for_user(user_id: str | None, base_effective: dict) -> dict:
    """Return effective risk config for a request.

    user_id = None → return base_effective unchanged (orchestrator always gets global).
    user_id = str  → apply per-user overrides on top of base_effective.
    """
    if not user_id:
        return base_effective
    try:
        user_overrides = load_user_risk_config(user_id)
        if not user_overrides:
            return base_effective
        merged = dict(base_effective)
        merged.update(user_overrides)
        return merged
    except Exception as exc:
        log.warning("Could not load per-user risk config for %s: %s", user_id, exc)
        return base_effective
