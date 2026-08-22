"""Watch rule store and evaluation engine for Category C NLP queries.

Rules are per-user conditions on a ticker's price.  The orchestrator calls
evaluate_rules() after each symbol cycle; triggered alerts land in a JSON
file that the /brain/alerts/stream SSE endpoint tails and delivers.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone

log = logging.getLogger(__name__)

_lock = threading.Lock()

CONDITION_TYPES: frozenset[str] = frozenset({"price_above", "price_below"})

# ── Persistent file locations ─────────────────────────────────────────────────

def _data_dir() -> str:
    candidates = [
        os.environ.get("DATA_DIR", ""),
        "/data",
        os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")),
        "/tmp",
    ]
    for p in (c for c in candidates if c):
        try:
            os.makedirs(p, exist_ok=True)
            probe = os.path.join(p, ".wr_probe")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
            return p
        except Exception:
            continue
    return "/tmp"

_DATA_DIR   = _data_dir()
_RULE_FILE  = os.environ.get("WATCH_RULE_FILE",  os.path.join(_DATA_DIR, "ta_watch_rules.json"))
_ALERT_FILE = os.environ.get("WATCH_ALERT_FILE", os.path.join(_DATA_DIR, "ta_watch_alerts.json"))


# ── File I/O ──────────────────────────────────────────────────────────────────

def _load_rules() -> dict[str, dict]:
    try:
        with open(_RULE_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_rules(rules: dict[str, dict]) -> None:
    with open(_RULE_FILE, "w") as f:
        json.dump(rules, f)


def _load_alerts() -> dict[str, dict]:
    try:
        with open(_ALERT_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_alerts(alerts: dict[str, dict]) -> None:
    with open(_ALERT_FILE, "w") as f:
        json.dump(alerts, f)


# ── Rule management ───────────────────────────────────────────────────────────

def add_rule(
    uid: str,
    symbol: str,
    asset_class: str,
    condition_type: str,
    threshold: float,
    trigger_debate: bool = True,
    max_rules: int = 10,
) -> dict:
    """Register a new watch rule. Raises ValueError on limit/validation errors."""
    if condition_type not in CONDITION_TYPES:
        raise ValueError(
            f"Unsupported condition_type '{condition_type}'. "
            f"Must be one of: {sorted(CONDITION_TYPES)}"
        )
    with _lock:
        rules = _load_rules()
        active = [r for r in rules.values() if r["uid"] == uid and not r.get("triggered")]
        if len(active) >= max_rules:
            raise ValueError(
                f"Rule limit reached ({max_rules} active rules). "
                "Delete an existing rule before adding a new one."
            )
        rule_id = str(uuid.uuid4())
        rule: dict = {
            "rule_id":        rule_id,
            "uid":            uid,
            "symbol":         symbol.upper(),
            "asset_class":    asset_class,
            "condition_type": condition_type,
            "threshold":      float(threshold),
            "trigger_debate": bool(trigger_debate),
            "created_at":     datetime.now(timezone.utc).isoformat(),
            "last_checked":   None,
            "triggered":      False,
        }
        rules[rule_id] = rule
        _save_rules(rules)

    log.info(
        "Watch rule registered: %s %s %.4f uid=%s",
        symbol.upper(), condition_type, threshold, uid,
    )
    return rule


def list_rules(uid: str) -> list[dict]:
    """Return all active (non-triggered) rules for a user, newest first."""
    with _lock:
        rules = _load_rules()
    active = [r for r in rules.values() if r["uid"] == uid and not r.get("triggered")]
    return sorted(active, key=lambda r: r["created_at"], reverse=True)


def delete_rule(uid: str, rule_id: str) -> bool:
    """Delete a rule by ID. Returns True if deleted, False if not found/owned."""
    with _lock:
        rules = _load_rules()
        if rule_id not in rules or rules[rule_id]["uid"] != uid:
            return False
        del rules[rule_id]
        _save_rules(rules)
    return True


# ── Evaluation (called by orchestrator each cycle) ────────────────────────────

def evaluate_rules(symbol: str, price: float) -> list[dict]:
    """
    Check all active rules for symbol against price.
    Marks matching rules as triggered and writes alerts.
    Returns the list of newly created alert dicts.
    Safe to call from multiple threads (guarded by _lock).
    """
    if price <= 0:
        return []

    triggered_alerts: list[dict] = []

    with _lock:
        rules  = _load_rules()
        alerts = _load_alerts()
        changed = False
        now = datetime.now(timezone.utc).isoformat()

        for rule_id, rule in rules.items():
            if rule.get("triggered"):
                continue
            if rule["symbol"] != symbol.upper():
                continue

            ctype  = rule["condition_type"]
            thresh = rule["threshold"]
            fired  = (
                (ctype == "price_above" and price >= thresh) or
                (ctype == "price_below" and price <= thresh)
            )

            rule["last_checked"] = now

            if fired:
                rule["triggered"] = True
                alert_id = str(uuid.uuid4())
                alert: dict = {
                    "alert_id":       alert_id,
                    "rule_id":        rule_id,
                    "uid":            rule["uid"],
                    "symbol":         rule["symbol"],
                    "asset_class":    rule["asset_class"],
                    "condition_type": ctype,
                    "threshold":      thresh,
                    "trigger_price":  round(price, 6),
                    "trigger_debate": rule.get("trigger_debate", True),
                    "triggered_at":   now,
                    "delivered":      False,
                }
                alerts[alert_id] = alert
                triggered_alerts.append(alert)
                log.info(
                    "Watch rule FIRED: %s %s %.4f (price=%.4f uid=%s)",
                    symbol.upper(), ctype, thresh, price, rule["uid"],
                )
                changed = True

        if changed:
            _save_rules(rules)
            _save_alerts(alerts)

    return triggered_alerts


# ── Alert management ──────────────────────────────────────────────────────────

def list_alerts(uid: str, include_delivered: bool = False) -> list[dict]:
    """Return alerts for a user, newest first."""
    with _lock:
        alerts = _load_alerts()
    result = [
        a for a in alerts.values()
        if a["uid"] == uid and (include_delivered or not a.get("delivered"))
    ]
    return sorted(result, key=lambda a: a["triggered_at"], reverse=True)


def mark_delivered(uid: str, alert_ids: list[str]) -> None:
    """Mark the given alerts as delivered so the SSE stream won't re-send them."""
    if not alert_ids:
        return
    with _lock:
        alerts = _load_alerts()
        for aid in alert_ids:
            if aid in alerts and alerts[aid]["uid"] == uid:
                alerts[aid]["delivered"] = True
        _save_alerts(alerts)
