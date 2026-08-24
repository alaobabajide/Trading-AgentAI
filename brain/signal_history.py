"""Signal history — append-only SQLite log with outcome tracking.

Every signal produced by POST /signal is recorded here (except signals
where the majority of agents errored). Outcome columns are filled in
by resolve_pending_outcomes(), which is called hourly by the orchestrator.

Outcome classification (per checkpoint):
    WIN      price moved > OUTCOME_THRESHOLD_PCT in the signal direction
    LOSS     price moved > OUTCOME_THRESHOLD_PCT against signal direction
    NEUTRAL  price moved <= OUTCOME_THRESHOLD_PCT either way
    EXPIRED  7-day checkpoint elapsed and price still unavailable

outcome_final = the earliest non-NEUTRAL result across checkpoints,
falling back to the 7-day result, falling back to EXPIRED.

Retention: rows older than RETENTION_DAYS are pruned on each write.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Generator

log = logging.getLogger(__name__)

RETENTION_DAYS        = 90
OUTCOME_THRESHOLD_PCT = 1.0   # ±1 % to classify WIN / LOSS
CHECKPOINTS_H         = (1, 4, 24, 72, 168)  # hours; 168 = 7 days

_DB: Path | None = None


# ── Path resolution ───────────────────────────────────────────────────────────

def _db_path() -> Path:
    global _DB
    if _DB:
        return _DB
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
            _DB = Path(c) / "ta_signal_history.db"
            return _DB
        except Exception:
            continue
    _DB = Path("/tmp/ta_signal_history.db")
    return _DB


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    con = sqlite3.connect(str(_db_path()), timeout=10, check_same_thread=False)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


# ── Schema ────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS signal_history (
    id               TEXT PRIMARY KEY,
    user_id          TEXT NOT NULL,
    symbol           TEXT NOT NULL,
    asset_class      TEXT NOT NULL,
    action           TEXT NOT NULL,
    tier             TEXT NOT NULL,
    regime           TEXT NOT NULL DEFAULT 'UNKNOWN',
    confidence       REAL NOT NULL DEFAULT 0,
    votes_for        REAL NOT NULL DEFAULT 0,
    price_at_signal  REAL,
    generated_at     TEXT NOT NULL,
    panels_conflict  INTEGER NOT NULL DEFAULT 0,
    strategy_fit     TEXT NOT NULL DEFAULT 'ALIGNED',
    -- outcome checkpoints
    price_1h         REAL,
    price_4h         REAL,
    price_24h        REAL,
    price_72h        REAL,
    price_7d         REAL,
    outcome_1h       TEXT,
    outcome_4h       TEXT,
    outcome_24h      TEXT,
    outcome_72h      TEXT,
    outcome_7d       TEXT,
    outcome_final    TEXT
);
CREATE INDEX IF NOT EXISTS idx_sh_user_ts   ON signal_history(user_id, generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_sh_symbol    ON signal_history(symbol, generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_sh_pending   ON signal_history(generated_at) WHERE outcome_final IS NULL;
"""


def _init_db() -> None:
    with _conn() as con:
        con.execute("PRAGMA journal_mode=WAL")   # concurrent reads don't block writers
        con.execute("PRAGMA synchronous=NORMAL")  # safe with WAL; faster than FULL
        con.executescript(_DDL)


# ── Write ─────────────────────────────────────────────────────────────────────

def record(
    user_id: str,
    signal_dict: dict,
    current_price: float | None,
) -> str:
    """Append one signal to history. Returns the generated row id."""
    _init_db()
    row_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    cutoff  = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()

    with _conn() as con:
        con.execute(
            """
            INSERT INTO signal_history
                (id, user_id, symbol, asset_class, action, tier, regime,
                 confidence, votes_for, price_at_signal, generated_at,
                 panels_conflict, strategy_fit)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                row_id,
                user_id or "system",
                signal_dict.get("symbol", ""),
                signal_dict.get("asset_class", "stock"),
                signal_dict.get("action", "HOLD"),
                signal_dict.get("tier", "WARM"),
                signal_dict.get("regime_label", "UNKNOWN"),
                float(signal_dict.get("confidence", 0) or 0),
                float(signal_dict.get("votes_for_action", 0) or 0),
                float(current_price) if current_price else None,
                signal_dict.get("generated_at", now_iso),
                1 if signal_dict.get("panels_conflict") else 0,
                signal_dict.get("strategy_fit", "ALIGNED"),
            ),
        )
        # Prune old rows to keep DB lean (90-day retention)
        con.execute("DELETE FROM signal_history WHERE generated_at < ?", (cutoff,))

    log.debug("signal_history: recorded %s %s %s id=%s",
              signal_dict.get("action"), signal_dict.get("symbol"), signal_dict.get("tier"), row_id)
    return row_id


# ── Outcome resolution ────────────────────────────────────────────────────────

def _classify(action: str, price_at_signal: float, price_now: float) -> str:
    if price_at_signal <= 0:
        return "NEUTRAL"
    pct_change = (price_now - price_at_signal) / price_at_signal * 100
    if action == "BUY":
        if pct_change > OUTCOME_THRESHOLD_PCT:
            return "WIN"
        if pct_change < -OUTCOME_THRESHOLD_PCT:
            return "LOSS"
    elif action == "SELL":
        if pct_change < -OUTCOME_THRESHOLD_PCT:
            return "WIN"
        if pct_change > OUTCOME_THRESHOLD_PCT:
            return "LOSS"
    return "NEUTRAL"


def _derive_final(row: sqlite3.Row) -> str | None:
    """Pick the earliest non-NEUTRAL result, else 7d result, else None."""
    for col in ("outcome_1h", "outcome_4h", "outcome_24h", "outcome_72h", "outcome_7d"):
        val = row[col]
        if val and val not in ("NEUTRAL", "EXPIRED"):
            return val
    # All NEUTRAL or EXPIRED — take 7d as canonical
    return row["outcome_7d"]


def resolve_pending_outcomes(fetch_price_fn) -> int:
    """Check every unresolved row against its elapsed checkpoints.

    fetch_price_fn(symbol, asset_class) -> float | None
        Caller provides this to avoid circular imports with brain/api.py.
        Should return the current mid price, or None on failure.

    Returns the number of rows updated.
    """
    _init_db()
    now = datetime.now(timezone.utc)
    updated = 0

    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM signal_history WHERE outcome_final IS NULL"
        ).fetchall()

    for row in rows:
        try:
            gen = datetime.fromisoformat(row["generated_at"].replace("Z", "+00:00"))
        except Exception:
            continue

        elapsed_h = (now - gen).total_seconds() / 3600
        action    = row["action"]
        base      = row["price_at_signal"]
        symbol    = row["symbol"]
        ac        = row["asset_class"]

        if not base or base <= 0 or action == "HOLD":
            # HOLD signals: mark final immediately — no directional outcome possible
            with _conn() as con:
                con.execute(
                    "UPDATE signal_history SET outcome_final='NEUTRAL' WHERE id=?",
                    (row["id"],)
                )
            updated += 1
            continue

        changes: dict[str, object] = {}

        for cp_h, col_price, col_out in (
            (1,   "price_1h",  "outcome_1h"),
            (4,   "price_4h",  "outcome_4h"),
            (24,  "price_24h", "outcome_24h"),
            (72,  "price_72h", "outcome_72h"),
            (168, "price_7d",  "outcome_7d"),
        ):
            if row[col_out] is not None:
                continue  # already resolved
            if elapsed_h < cp_h:
                continue  # not due yet

            if elapsed_h > cp_h + 24 and row[col_price] is None:
                # Grace period expired without a price — mark EXPIRED
                changes[col_out] = "EXPIRED"
                changes[col_price] = None
            else:
                price_now = fetch_price_fn(symbol, ac)
                if price_now and price_now > 0:
                    changes[col_price] = price_now
                    changes[col_out]   = _classify(action, base, price_now)
                # else: try again next cycle

        if not changes:
            continue

        # Build the final outcome if all 5 checkpoints are now resolved
        # Merge changes into a temporary dict to compute final
        merged = dict(row)
        merged.update(changes)
        all_resolved = all(merged.get(c) is not None for c in (
            "outcome_1h", "outcome_4h", "outcome_24h", "outcome_72h", "outcome_7d"
        ))
        if all_resolved:
            finals = [merged.get(c) for c in (
                "outcome_1h", "outcome_4h", "outcome_24h", "outcome_72h", "outcome_7d"
            )]
            for v in finals:
                if v and v not in ("NEUTRAL", "EXPIRED"):
                    changes["outcome_final"] = v
                    break
            else:
                changes["outcome_final"] = finals[-1] or "EXPIRED"

        # elapsed > 7 days + 24h grace → force EXPIRED on any remaining NULLs
        if elapsed_h > 168 + 24:
            for col_out in ("outcome_1h", "outcome_4h", "outcome_24h", "outcome_72h", "outcome_7d"):
                if merged.get(col_out) is None:
                    changes[col_out] = "EXPIRED"
            if not merged.get("outcome_final"):
                changes["outcome_final"] = "EXPIRED"

        if changes:
            set_clause = ", ".join(f"{k}=?" for k in changes)
            vals = list(changes.values()) + [row["id"]]
            with _conn() as con:
                con.execute(
                    f"UPDATE signal_history SET {set_clause} WHERE id=?", vals
                )
            updated += 1

    if updated:
        log.info("signal_history: resolved outcomes for %d rows", updated)
    return updated


# ── Queries ───────────────────────────────────────────────────────────────────

def list_history(
    user_id: str,
    symbol: str | None = None,
    action: str | None = None,
    tier: str | None = None,
    outcome: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    _init_db()
    clauses = ["user_id = ?"]
    params: list = [user_id]
    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol.upper())
    if action:
        clauses.append("action = ?")
        params.append(action.upper())
    if tier:
        clauses.append("tier = ?")
        params.append(tier.upper())
    if outcome:
        clauses.append("outcome_final = ?")
        params.append(outcome.upper())

    where = " AND ".join(clauses)
    params += [min(limit, 500), max(offset, 0)]

    with _conn() as con:
        rows = con.execute(
            f"""
            SELECT id, symbol, asset_class, action, tier, regime, confidence,
                   votes_for, price_at_signal, generated_at, panels_conflict,
                   strategy_fit, outcome_1h, outcome_4h, outcome_24h, outcome_72h,
                   outcome_7d, outcome_final,
                   price_1h, price_4h, price_24h, price_72h, price_7d
            FROM signal_history
            WHERE {where}
            ORDER BY generated_at DESC
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
        total = con.execute(
            f"SELECT COUNT(*) FROM signal_history WHERE {where}",
            params[:-2],
        ).fetchone()[0]

    return {
        "total": total,
        "rows": [dict(r) for r in rows],
    }


def get_leaderboard(user_id: str, group_by: str = "tier") -> list[dict]:
    """Aggregate win/loss/neutral counts grouped by tier, asset_class, or regime."""
    _init_db()
    allowed = {"tier", "asset_class", "regime"}
    if group_by not in allowed:
        group_by = "tier"

    with _conn() as con:
        rows = con.execute(
            f"""
            SELECT
                {group_by}                                     AS group_key,
                COUNT(*)                                       AS total,
                SUM(CASE WHEN outcome_final='WIN'     THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN outcome_final='LOSS'    THEN 1 ELSE 0 END) AS losses,
                SUM(CASE WHEN outcome_final='NEUTRAL' THEN 1 ELSE 0 END) AS neutrals,
                SUM(CASE WHEN outcome_final='EXPIRED' THEN 1 ELSE 0 END) AS expired,
                SUM(CASE WHEN outcome_final IS NULL   THEN 1 ELSE 0 END) AS pending,
                ROUND(AVG(confidence), 4)                      AS avg_confidence,
                ROUND(AVG(votes_for),  2)                      AS avg_votes
            FROM signal_history
            WHERE user_id = ?
              AND action != 'HOLD'
            GROUP BY {group_by}
            ORDER BY wins DESC
            """,
            (user_id,),
        ).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        resolved = (d["wins"] or 0) + (d["losses"] or 0) + (d["neutrals"] or 0)
        d["win_rate"] = round(d["wins"] / resolved * 100, 1) if resolved else None
        result.append(d)
    return result


def get_stats(user_id: str) -> dict:
    """Rolling 7-day and 30-day summary for the dashboard card."""
    _init_db()
    now = datetime.now(timezone.utc)
    cutoff_7d  = (now - timedelta(days=7)).isoformat()
    cutoff_30d = (now - timedelta(days=30)).isoformat()

    def _window(cutoff: str) -> dict:
        with _conn() as con:
            r = con.execute(
                """
                SELECT
                    COUNT(*)                                              AS total,
                    SUM(CASE WHEN action!='HOLD' THEN 1 ELSE 0 END)      AS actionable,
                    SUM(CASE WHEN outcome_final='WIN'  THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN outcome_final='LOSS' THEN 1 ELSE 0 END) AS losses,
                    SUM(CASE WHEN tier='HOT'  THEN 1 ELSE 0 END)          AS hot,
                    SUM(CASE WHEN tier='WARM' THEN 1 ELSE 0 END)          AS warm,
                    SUM(CASE WHEN tier='COLD' THEN 1 ELSE 0 END)          AS cold
                FROM signal_history
                WHERE user_id = ? AND generated_at >= ?
                """,
                (user_id, cutoff),
            ).fetchone()
        d = dict(r)
        resolved = (d["wins"] or 0) + (d["losses"] or 0)
        d["win_rate"] = round(d["wins"] / resolved * 100, 1) if resolved else None
        return d

    return {
        "7d":  _window(cutoff_7d),
        "30d": _window(cutoff_30d),
    }
