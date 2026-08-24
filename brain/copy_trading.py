"""Public Disclosure Tracker — SQLite store for 13F institutional filings
and STOCK Act congressional trade disclosures.

Three tables:
  disclosure_investors      — pre-seeded investor metadata (13F filers)
  disclosure_13f_holdings   — holdings per investor per filing period
  disclosure_congress_trades — STOCK Act periodic transaction reports

Data is populated by brain/sec_fetcher.py (13F) and
brain/congress_fetcher.py (STOCK Act), called on schedule by the orchestrator.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

log = logging.getLogger(__name__)

_DB: Path | None = None

# ── Pre-seeded investors (≥80 % confidence, verified multi-source) ─────────────
TRACKED_INVESTORS: list[dict] = [
    {
        "id":              "ackman",
        "name":            "Bill Ackman",
        "fund":            "Pershing Square Capital Management",
        "cik":             "0001336528",
        "confidence_pct":  92,
        "est_alpha_pct":   10.0,
        "disclosure_type": "13F",
        "note":            "Also discloses monthly via PSH on Euronext — fastest institutional lag",
    },
    {
        "id":              "berkshire",
        "name":            "Warren Buffett / Greg Abel",
        "fund":            "Berkshire Hathaway",
        "cik":             "0001067983",
        "confidence_pct":  91,
        "est_alpha_pct":   9.5,
        "disclosure_type": "13F",
        "note":            "BRK.A/BRK.B stock is a real-time proxy; 13F filed quarterly",
    },
    {
        "id":              "baron",
        "name":            "Ron Baron",
        "fund":            "Baron Capital Group",
        "cik":             "0000811156",
        "confidence_pct":  87,
        "est_alpha_pct":   12.0,
        "disclosure_type": "13F",
        "note":            "Baron Partners Fund (BPTRX) accessible as daily-NAV mutual fund",
    },
    {
        "id":              "einhorn",
        "name":            "David Einhorn",
        "fund":            "Greenlight Capital",
        "cik":             "0001079114",
        "confidence_pct":  80,
        "est_alpha_pct":   2.5,
        "disclosure_type": "13F",
        "note":            "Long-term alpha confirmed; recent years mixed vs S&P 500",
    },
]

TRACKED_CONGRESS: list[dict] = [
    {
        "name":            "Nancy Pelosi",
        "party":           "D",
        "chamber":         "House",
        "state":           "CA",
        "confidence_pct":  82,
        "note":            "4-year confirmed outperformance; trades via spouse Paul Pelosi",
    },
]


# ── DB path ────────────────────────────────────────────────────────────────────

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
            _DB = Path(c) / "ta_disclosures.db"
            return _DB
        except Exception:
            continue
    _DB = Path("/tmp/ta_disclosures.db")
    return _DB


@contextmanager
def _conn() -> Generator[sqlite3.Connection, None, None]:
    con = sqlite3.connect(str(_db_path()), timeout=15, check_same_thread=False)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


# ── Schema ─────────────────────────────────────────────────────────────────────

_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS disclosure_investors (
    id               TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    fund             TEXT NOT NULL,
    cik              TEXT,
    confidence_pct   INTEGER,
    est_alpha_pct    REAL,
    disclosure_type  TEXT DEFAULT '13F',
    note             TEXT,
    is_active        INTEGER DEFAULT 1,
    last_fetched_at  TEXT,
    created_at       TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS disclosure_13f_holdings (
    id               TEXT PRIMARY KEY,
    investor_id      TEXT NOT NULL REFERENCES disclosure_investors(id),
    symbol           TEXT,
    cusip            TEXT,
    company_name     TEXT NOT NULL,
    shares           REAL,
    value_usd        REAL,
    pct_portfolio    REAL,
    period_of_report TEXT NOT NULL,
    filed_at         TEXT,
    created_at       TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS disclosure_congress_trades (
    id               TEXT PRIMARY KEY,
    member_name      TEXT NOT NULL,
    party            TEXT,
    chamber          TEXT,
    state            TEXT,
    symbol           TEXT,
    company_name     TEXT,
    trade_type       TEXT,
    amount_range     TEXT,
    transaction_date TEXT,
    disclosure_date  TEXT,
    comment          TEXT,
    source           TEXT,
    created_at       TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_13f_investor_period
    ON disclosure_13f_holdings(investor_id, period_of_report DESC);
CREATE INDEX IF NOT EXISTS idx_13f_symbol
    ON disclosure_13f_holdings(symbol, period_of_report DESC);
CREATE INDEX IF NOT EXISTS idx_congress_member
    ON disclosure_congress_trades(member_name, transaction_date DESC);
CREATE INDEX IF NOT EXISTS idx_congress_symbol
    ON disclosure_congress_trades(symbol, transaction_date DESC);
CREATE INDEX IF NOT EXISTS idx_congress_date
    ON disclosure_congress_trades(transaction_date DESC);
"""


def init_db() -> None:
    with _conn() as con:
        con.executescript(_DDL)
        # Seed investors if not present
        for inv in TRACKED_INVESTORS:
            con.execute(
                """
                INSERT OR IGNORE INTO disclosure_investors
                    (id, name, fund, cik, confidence_pct, est_alpha_pct, disclosure_type, note)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (inv["id"], inv["name"], inv["fund"], inv.get("cik"),
                 inv["confidence_pct"], inv["est_alpha_pct"],
                 inv["disclosure_type"], inv.get("note", "")),
            )
    log.info("disclosure DB initialised at %s", _db_path())


# ── 13F writes ─────────────────────────────────────────────────────────────────

def upsert_13f_holdings(investor_id: str, period: str, holdings: list[dict], filed_at: str = "") -> int:
    """Replace all holdings for (investor_id, period) with the new list."""
    init_db()
    with _conn() as con:
        con.execute(
            "DELETE FROM disclosure_13f_holdings WHERE investor_id=? AND period_of_report=?",
            (investor_id, period),
        )
        total_value = sum(h.get("value_usd", 0) for h in holdings)
        rows = 0
        for h in holdings:
            pct = (h.get("value_usd", 0) / total_value * 100) if total_value else None
            con.execute(
                """
                INSERT INTO disclosure_13f_holdings
                    (id, investor_id, symbol, cusip, company_name, shares,
                     value_usd, pct_portfolio, period_of_report, filed_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (str(uuid.uuid4()), investor_id,
                 h.get("symbol"), h.get("cusip"), h.get("company_name", ""),
                 h.get("shares"), h.get("value_usd"), pct, period, filed_at),
            )
            rows += 1
        con.execute(
            "UPDATE disclosure_investors SET last_fetched_at=datetime('now') WHERE id=?",
            (investor_id,),
        )
    log.info("13F upsert: %d holdings for %s %s", rows, investor_id, period)
    return rows


# ── Congress writes ────────────────────────────────────────────────────────────

def upsert_congress_trades(trades: list[dict]) -> int:
    """Insert new congressional trades; ignore duplicates by (member, symbol, transaction_date, trade_type)."""
    init_db()
    inserted = 0
    with _conn() as con:
        for t in trades:
            existing = con.execute(
                """SELECT id FROM disclosure_congress_trades
                   WHERE member_name=? AND symbol=? AND transaction_date=? AND trade_type=?""",
                (t["member_name"], t.get("symbol", ""), t.get("transaction_date", ""), t.get("trade_type", "")),
            ).fetchone()
            if existing:
                continue
            con.execute(
                """
                INSERT INTO disclosure_congress_trades
                    (id, member_name, party, chamber, state, symbol,
                     company_name, trade_type, amount_range,
                     transaction_date, disclosure_date, comment, source)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (str(uuid.uuid4()), t["member_name"],
                 t.get("party"), t.get("chamber"), t.get("state"),
                 t.get("symbol"), t.get("company_name"),
                 t.get("trade_type"), t.get("amount_range"),
                 t.get("transaction_date"), t.get("disclosure_date"),
                 t.get("comment"), t.get("source", "housestockwatcher")),
            )
            inserted += 1
    if inserted:
        log.info("Congress trades: inserted %d new rows", inserted)
    return inserted


# ── Reads ──────────────────────────────────────────────────────────────────────

def get_investors() -> list[dict]:
    init_db()
    with _conn() as con:
        rows = con.execute(
            "SELECT * FROM disclosure_investors WHERE is_active=1 ORDER BY confidence_pct DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def get_holdings(investor_id: str, period: str | None = None) -> list[dict]:
    """Return holdings for an investor. If period is None, return the latest period."""
    init_db()
    with _conn() as con:
        if period is None:
            row = con.execute(
                "SELECT period_of_report FROM disclosure_13f_holdings WHERE investor_id=? ORDER BY period_of_report DESC LIMIT 1",
                (investor_id,),
            ).fetchone()
            if not row:
                return []
            period = row["period_of_report"]
        rows = con.execute(
            """SELECT * FROM disclosure_13f_holdings
               WHERE investor_id=? AND period_of_report=?
               ORDER BY value_usd DESC""",
            (investor_id, period),
        ).fetchall()
    return [dict(r) for r in rows]


def get_holdings_periods(investor_id: str) -> list[str]:
    init_db()
    with _conn() as con:
        rows = con.execute(
            "SELECT DISTINCT period_of_report FROM disclosure_13f_holdings WHERE investor_id=? ORDER BY period_of_report DESC",
            (investor_id,),
        ).fetchall()
    return [r["period_of_report"] for r in rows]


def get_congress_feed(limit: int = 100, member: str | None = None, symbol: str | None = None) -> list[dict]:
    init_db()
    query = "SELECT * FROM disclosure_congress_trades WHERE 1=1"
    params: list = []
    if member:
        query += " AND member_name LIKE ?"
        params.append(f"%{member}%")
    if symbol:
        query += " AND symbol=?"
        params.append(symbol.upper())
    query += " ORDER BY transaction_date DESC, disclosure_date DESC LIMIT ?"
    params.append(limit)
    with _conn() as con:
        rows = con.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_congress_members() -> list[dict]:
    """Return distinct members who have trades in the DB, with trade counts."""
    init_db()
    with _conn() as con:
        rows = con.execute(
            """SELECT member_name, party, chamber, state, COUNT(*) as trade_count,
                      MAX(transaction_date) as latest_trade
               FROM disclosure_congress_trades
               GROUP BY member_name
               ORDER BY trade_count DESC"""
        ).fetchall()
    return [dict(r) for r in rows]
