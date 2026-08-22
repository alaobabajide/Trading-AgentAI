"""Persistent order history — 1-year audit retention.

All orders placed through the system (execute endpoint, TradingView webhook,
passive sync from broker fetch) are recorded here. Records older than 365 days
are pruned automatically on every write.

Storage: {DATA_DIR}/order_audit_history.json — a single JSON list so the
full audit trail is in one place. File is chmod 0o600 on every write.

Schema per record:
    order_id        str     broker order ID
    symbol          str     e.g. "AAPL"
    side            str     "BUY" or "SELL"
    order_type      str     "market", "bracket", "limit", etc.
    qty             float
    filled_qty      float   (0.0 if not yet filled at record time)
    status          str     "submitted", "filled", "cancelled", etc.
    submitted_at    str     ISO-8601 UTC
    filled_at       str|null
    broker          str     "alpaca", "tastytrade", "schwab", "ibkr"
    stop_price      float|null
    take_profit_price float|null
    filled_avg_price float|null
    notional        float|null
    source          str     "manual", "tradingview", "orchestrator"
    user_id         str     JWT user ID or "system" for orchestrator
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_RETENTION_DAYS = 365

def _store_path() -> Path:
    candidates = [
        os.environ.get("DATA_DIR", ""),
        "/data",
        os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")),
        "/tmp",
    ]
    for c in (p for p in candidates if p):
        try:
            os.makedirs(c, exist_ok=True)
            probe = os.path.join(c, ".write_probe")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
            return Path(c) / "order_audit_history.json"
        except Exception:
            continue
    return Path("/tmp/order_audit_history.json")


_STORE: Path = _store_path()
_CUTOFF_SECONDS = _RETENTION_DAYS * 86400


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load() -> list[dict]:
    try:
        return json.loads(_STORE.read_text())
    except FileNotFoundError:
        return []
    except Exception as exc:
        log.warning("Could not read order history: %s", exc)
        return []


def _save(records: list[dict]) -> None:
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(_STORE) + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(records, f)
        os.replace(tmp, str(_STORE))
        os.chmod(str(_STORE), 0o600)
    except Exception as exc:
        log.error("Could not write order history: %s", exc)


def _is_recent(record: dict) -> bool:
    """Return True if this record is within the retention window."""
    ts = record.get("submitted_at")
    if not ts:
        return True  # keep if no timestamp (shouldn't happen)
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        age = time.time() - dt.timestamp()
        return age < _CUTOFF_SECONDS
    except Exception:
        return True


# ── Public API ────────────────────────────────────────────────────────────────

def record_order(record: dict[str, Any]) -> None:
    """Append one order record. Deduplicates by order_id. Prunes stale entries."""
    records = _load()

    order_id = record.get("order_id", "")
    if order_id:
        # Replace existing record with the same order_id (status may have updated)
        records = [r for r in records if r.get("order_id") != order_id]

    records.append(record)

    # Prune records older than retention window
    records = [r for r in records if _is_recent(r)]

    # Keep sorted by submitted_at (newest last, so slicing [:N] gets oldest)
    try:
        records.sort(key=lambda r: r.get("submitted_at") or "")
    except Exception:
        pass

    _save(records)


def get_all_orders(days: int | None = None, user_id: str | None = None) -> list[dict]:
    """Return stored orders, optionally filtered to the last N days and/or a specific user.

    Results are sorted newest-first for display.
    """
    records = _load()
    if user_id is not None:
        records = [r for r in records if r.get("user_id") == user_id]
    if days is not None:
        cutoff = time.time() - days * 86400
        filtered = []
        for r in records:
            ts = r.get("submitted_at")
            try:
                dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                if dt.timestamp() >= cutoff:
                    filtered.append(r)
            except Exception:
                filtered.append(r)
        records = filtered
    # Newest first for display
    return list(reversed(records))


def get_available_years(user_id: str | None = None) -> list[int]:
    """Return sorted (newest-first) list of past complete calendar years that have orders."""
    records = _load()
    if user_id is not None:
        records = [r for r in records if r.get("user_id") == user_id]
    current_year = datetime.now(timezone.utc).year
    years: set[int] = set()
    for r in records:
        ts = r.get("submitted_at")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if dt.year < current_year:
                years.add(dt.year)
        except Exception:
            continue
    return sorted(years, reverse=True)


def get_orders_for_year(year: int, user_id: str | None = None) -> list[dict]:
    """Return all stored orders whose submitted_at falls in the given calendar year, newest-first."""
    records = _load()
    if user_id is not None:
        records = [r for r in records if r.get("user_id") == user_id]
    result = []
    for r in records:
        ts = r.get("submitted_at")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if dt.year == year:
                result.append(r)
        except Exception:
            continue
    return list(reversed(result))


def record_from_broker_result(
    *,
    order_id:          str,
    symbol:            str,
    side:              str,
    order_type:        str = "market",
    qty:               float,
    filled_qty:        float = 0.0,
    status:            str = "submitted",
    submitted_at:      str | None = None,
    filled_at:         str | None = None,
    broker:            str = "unknown",
    stop_price:        float | None = None,
    take_profit_price: float | None = None,
    filled_avg_price:  float | None = None,
    notional:          float | None = None,
    source:            str = "manual",
    user_id:           str = "system",
) -> None:
    """Convenience wrapper to record a BrokerOrderResult or live order."""
    now_iso = datetime.now(timezone.utc).isoformat()
    record_order({
        "order_id":          order_id,
        "symbol":            symbol,
        "side":              side.upper(),
        "order_type":        order_type,
        "qty":               qty,
        "filled_qty":        filled_qty,
        "status":            status,
        "submitted_at":      submitted_at or now_iso,
        "filled_at":         filled_at,
        "broker":            broker,
        "stop_price":        stop_price,
        "take_profit_price": take_profit_price,
        "filled_avg_price":  filled_avg_price,
        "notional":          notional,
        "source":            source,
        "user_id":           user_id,
    })
