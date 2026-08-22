"""Demo account snapshot store.

Saves a point-in-time snapshot of the owner's live data so that a demo user
(DEMO_USER_ID) sees realistic-looking charts and data without any live broker
connection.  The owner triggers a snapshot via POST /demo/snapshot; that
endpoint writes here.  Every demo-aware endpoint reads from here.

Schema of the stored JSON file:
    {
        "captured_at": "<ISO-8601>",
        "portfolio":   { ... }          # /portfolio response shape
        "history": {
            "1D": [ ... ],              # /portfolio/history?period=1D
            "1W": [ ... ],
            "1M": [ ... ],
            "3M": [ ... ],
            "1Y": [ ... ],
            "ALL": [ ... ]
        },
        "signals":  [ ... ],            # /signals/cached response (list)
        "orders":   { "orders": [...] } # /orders response
    }

Security: demo snapshots contain no live credentials — they are pre-serialised
response payloads only.  Values are never re-used for broker calls.
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
            probe = os.path.join(p, ".demo_probe")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
            _STORE_PATH = os.path.join(p, "demo_snapshot.json")
            return _STORE_PATH
        except Exception:
            continue
    _STORE_PATH = "/tmp/demo_snapshot.json"
    return _STORE_PATH


def save_demo_snapshot(data: dict) -> str:
    """Write the snapshot atomically and return the file path."""
    path = _store_path()
    tmp = path + ".tmp"
    with _STORE_LOCK:
        try:
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, path)
            os.chmod(path, 0o600)
        except Exception as exc:
            log.error("Could not write demo snapshot: %s", exc)
            raise
    log.info("Demo snapshot saved to %s", path)
    return path


def load_demo_snapshot() -> dict | None:
    """Return the snapshot dict, or None if no snapshot has been taken."""
    path = _store_path()
    with _STORE_LOCK:
        try:
            with open(path) as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except Exception as exc:
            log.warning("Could not read demo snapshot: %s", exc)
            return None


def demo_snapshot_info() -> dict:
    """Return metadata about the stored snapshot (no PII or account data)."""
    snap = load_demo_snapshot()
    if snap is None:
        return {"available": False, "captured_at": None}
    return {
        "available":    True,
        "captured_at":  snap.get("captured_at"),
        "signal_count": len(snap.get("signals", [])),
        "order_count":  len(snap.get("orders", {}).get("orders", [])),
    }
