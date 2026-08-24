"""Signal Snapshots — Supabase-backed track record writer (Approaches 1, 3).

Writes every signal the debate engine produces to the `signal_snapshots` table
in Supabase along with the full 27-agent JSONB payload, all indicator values
captured at signal time, and then fills in price/outcome checkpoints hourly.

Design decisions:
- This module is non-fatal: every public function catches all exceptions so
  that a Supabase outage never blocks the signal pipeline.
- Works alongside the existing SQLite signal_history.py — both run in parallel.
  SQLite serves the dashboard live views; Supabase is the immutable track record.
- The Supabase client is lazily initialised once and reused (thread-safe via lock).
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

log = logging.getLogger(__name__)

_sb_lock = threading.Lock()
_sb_client = None

# Outcome thresholds (match spec: +5% WIN, -2% LOSS)
WIN_THRESHOLD_PCT  =  5.0
LOSS_THRESHOLD_PCT = -2.0

# Checkpoint hours
CHECKPOINTS_H = (1, 4, 24, 72, 168)   # 168 h = 7 days


# ── Supabase client (lazy, cached) ────────────────────────────────────────────

def _get_sb():
    global _sb_client
    if _sb_client is not None:
        return _sb_client
    with _sb_lock:
        if _sb_client is not None:
            return _sb_client
        try:
            from config import get_settings
            cfg = get_settings()
            if cfg.supabase_url and cfg.supabase_service_role_key:
                from supabase import create_client
                _sb_client = create_client(cfg.supabase_url, cfg.supabase_service_role_key)
                log.info("signal_snapshots: Supabase client initialised (%s)", cfg.supabase_url[:40])
            else:
                log.warning("signal_snapshots: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY not set — snapshots disabled")
        except Exception as exc:
            log.warning("signal_snapshots: Supabase init failed: %s", exc)
    return _sb_client


# ── Agent votes JSONB serialiser ──────────────────────────────────────────────

def _build_agent_votes(signal_dict: dict, paper_mode: bool, model: str, provider: str) -> dict:
    """Serialise the full 27-agent debate payload for the agent_votes JSONB column."""
    av = signal_dict.get("agent_views", {})
    panel_a = signal_dict.get("panel_a_votes", {})
    panel_b = signal_dict.get("panel_b_votes", {})
    tally   = signal_dict.get("vote_tally", {})

    # Annotate each agent with panel membership for future analytics
    panel_a_agents = {
        "fundamental", "technical", "sentiment", "macro", "quant",
        "options_flow", "regime", "strategy", "risk",
        "breakout", "trend_strength", "sector_rotation", "earnings_event",
        "momentum_scorer", "supply_demand", "volume_analyst", "risk_reward",
    }

    agents = []
    for agent_id, view in av.items():
        if not isinstance(view, str):
            continue
        panel = "A" if agent_id in panel_a_agents else "B"
        # Infer vote direction from view text heuristics (best-effort)
        view_lower = view.lower()
        if "agent error" in view_lower:
            vote = "ERROR"
        elif any(w in view_lower for w in ("buy", "bullish", "long", "upside", "positive")):
            vote = "BUY"
        elif any(w in view_lower for w in ("sell", "bearish", "short", "downside", "negative")):
            vote = "SELL"
        else:
            vote = "HOLD"
        agents.append({
            "agent_id":   agent_id,
            "panel":      panel,
            "vote":       vote,
            "reasoning":  view[:500],          # cap at 500 chars to keep JSONB lean
        })

    return {
        "mode":         "paper_rule" if paper_mode else "llm_debate",
        "model":        model,
        "provider":     provider,
        "total_agents": len(agents),
        "agents":       agents,
        "panel_a": {
            "bullish": panel_a.get("bullish", 0),
            "bearish": panel_a.get("bearish", 0),
            "neutral": panel_a.get("neutral", 0),
        },
        "panel_b": {
            "bullish": panel_b.get("bullish", 0),
            "bearish": panel_b.get("bearish", 0),
            "neutral": panel_b.get("neutral", 0),
        },
        "synthesis": {
            "combined_bullish": tally.get("bullish", 0),
            "combined_bearish": tally.get("bearish", 0),
            "combined_neutral": tally.get("neutral", 0),
            "action":           signal_dict.get("action", "HOLD"),
            "tier":             signal_dict.get("tier", "COLD"),
            "regime":           signal_dict.get("regime_label", "UNKNOWN"),
            "panels_conflict":  signal_dict.get("panels_conflict", False),
            "conflict_note":    signal_dict.get("conflict_note", ""),
        },
    }


# ── bb_position helper ────────────────────────────────────────────────────────

def _bb_position(indicators: dict) -> float | None:
    bb_u = indicators.get("bb_upper")
    bb_l = indicators.get("bb_lower")
    price = indicators.get("price")
    if bb_u and bb_l and price and (bb_u - bb_l) > 0:
        return round((price - bb_l) / (bb_u - bb_l) * 100, 2)
    return None


# ── max_score helper ──────────────────────────────────────────────────────────

def _max_score(asset_class: str) -> float:
    """Total weighted vote pool for this asset class (Panel A=15 + weighted Panel B)."""
    try:
        from brain.debate import _total_system_weight
        return _total_system_weight(asset_class)
    except Exception:
        return 27.0


# ── Public write API ──────────────────────────────────────────────────────────

def record_snapshot(
    signal_dict: dict,
    indicators:  dict,
    *,
    source:      str  = "live_rule",
    paper_mode:  bool = True,
    model_used:  str  = "",
    provider:    str  = "",
    backtest_id: str | None = None,
    sim_date:    str | None = None,
) -> str | None:
    """Write one signal to Supabase signal_snapshots.

    Returns the new UUID on success, None on failure.
    All errors are caught and logged — never raises.
    """
    sb = _get_sb()
    if sb is None:
        return None
    try:
        asset_class = signal_dict.get("asset_class", "stock")
        price       = indicators.get("price") or signal_dict.get("current_price")
        bb_pos      = _bb_position(indicators)
        tally       = signal_dict.get("vote_tally", {})

        row = {
            "symbol":       signal_dict.get("symbol", ""),
            "asset_class":  asset_class,
            "source":       source,
            "action":       signal_dict.get("action", "HOLD"),
            "tier":         signal_dict.get("tier", "COLD"),
            "regime":       signal_dict.get("regime_label") or None,
            "confidence":   signal_dict.get("votes_for_action"),
            "max_score":    _max_score(asset_class),
            "bullish_votes": tally.get("bullish"),
            "bearish_votes": tally.get("bearish"),
            "neutral_votes": tally.get("neutral"),
            "reasoning":    signal_dict.get("rationale", "")[:2000],

            # Agent payload (Approach 3)
            "agent_votes":  _build_agent_votes(signal_dict, paper_mode, model_used, provider),
            "model_used":   model_used or None,
            "provider":     provider or None,

            # Indicator snapshot
            "entry_price":   price,
            "rsi_14":        indicators.get("rsi_14"),
            "macd":          indicators.get("macd"),
            "macd_signal":   indicators.get("macd_signal"),
            "atr_14":        indicators.get("atr_14"),
            "sma_20":        indicators.get("sma_20"),
            "sma_50":        indicators.get("sma_50"),
            "sma_200":       indicators.get("sma_200"),
            "bb_upper":      indicators.get("bb_upper"),
            "bb_lower":      indicators.get("bb_lower"),
            "bb_position":   bb_pos,
            "volume_ratio":  indicators.get("volume_ratio"),
            "stoch_k":       indicators.get("stoch_k"),
            "roc_20":        indicators.get("roc_20"),

            # Outcome starts pending
            "outcome":       "PENDING",
        }

        if backtest_id:
            row["backtest_id"] = backtest_id
        if sim_date:
            row["sim_date"] = sim_date

        resp = sb.table("signal_snapshots").insert(row).execute()
        data = resp.data
        if data:
            row_id = data[0].get("id")
            log.debug("signal_snapshots: recorded %s %s %s id=%s",
                      row["action"], row["symbol"], row["tier"], row_id)
            return row_id
    except Exception as exc:
        log.warning("signal_snapshots: record failed for %s: %s",
                    signal_dict.get("symbol"), exc)
    return None


# ── Outcome resolution ─────────────────────────────────────────────────────────

def _pct_return(action: str, entry: float, now_price: float) -> float:
    pct = (now_price - entry) / entry * 100
    if action == "SELL":
        pct = -pct   # price drop = gain for short
    return round(pct, 4)


def _classify_return(pct: float) -> str:
    if pct >= WIN_THRESHOLD_PCT:
        return "WIN"
    if pct <= LOSS_THRESHOLD_PCT:
        return "LOSS"
    return "NEUTRAL"


def resolve_pending_outcomes(fetch_price_fn) -> int:
    """Fill in price checkpoints and classify outcomes for pending signals.

    fetch_price_fn(symbol, asset_class) -> float | None
    Returns number of rows updated.
    """
    sb = _get_sb()
    if sb is None:
        return 0
    updated = 0
    try:
        resp = (
            sb.table("signal_snapshots")
            .select("id,created_at,symbol,asset_class,action,entry_price,"
                    "price_1h,price_4h,price_24h,price_72h,price_7d,outcome")
            .eq("outcome", "PENDING")
            .execute()
        )
        rows = resp.data or []
    except Exception as exc:
        log.warning("signal_snapshots: outcome fetch failed: %s", exc)
        return 0

    now = datetime.now(timezone.utc)

    for row in rows:
        try:
            created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
        except Exception:
            continue

        elapsed_h = (now - created).total_seconds() / 3600
        action    = row.get("action", "HOLD")
        entry     = float(row.get("entry_price") or 0)
        symbol    = row["symbol"]
        ac        = row.get("asset_class", "stock")

        if entry <= 0 or action == "HOLD":
            try:
                sb.table("signal_snapshots").update(
                    {"outcome": "NEUTRAL", "outcome_at": now.isoformat()}
                ).eq("id", row["id"]).execute()
                updated += 1
            except Exception:
                pass
            continue

        changes: dict[str, Any] = {}
        checkpoint_map = [
            (1,   "price_1h",  "return_1h"),
            (4,   "price_4h",  "return_4h"),
            (24,  "price_24h", "return_24h"),
            (72,  "price_72h", "return_72h"),
            (168, "price_7d",  "return_7d"),
        ]

        for cp_h, price_col, return_col in checkpoint_map:
            if row.get(price_col) is not None:
                continue   # already filled
            if elapsed_h < cp_h:
                continue   # not due yet

            # Grace period: if 24h past the checkpoint and still no price, mark EXPIRED
            if elapsed_h > cp_h + 24:
                changes[price_col]  = None
                changes[return_col] = None
                continue

            price_now = fetch_price_fn(symbol, ac)
            if price_now and float(price_now) > 0:
                pct = _pct_return(action, entry, float(price_now))
                changes[price_col]  = price_now
                changes[return_col] = pct

        if not changes:
            continue

        # Determine final outcome when 7-day checkpoint is resolved
        # Merge changes into current state
        merged = {**row, **changes}
        seven_day_return = merged.get("return_7d")
        if seven_day_return is not None:
            outcome = _classify_return(float(seven_day_return))
            # Early WIN/LOSS: check if any earlier checkpoint already crossed threshold
            for col in ("return_1h", "return_4h", "return_24h", "return_72h"):
                v = merged.get(col)
                if v is not None:
                    early = _classify_return(float(v))
                    if early in ("WIN", "LOSS"):
                        outcome = early
                        break
            changes["outcome"]     = outcome
            changes["outcome_at"]  = now.isoformat()
            changes["price_final"] = merged.get("price_7d")
            changes["return_final"] = float(seven_day_return)

        # Force EXPIRED if way past all checkpoints and still PENDING
        if elapsed_h > 168 + 24 and merged.get("outcome") == "PENDING":
            changes["outcome"]    = "EXPIRED"
            changes["outcome_at"] = now.isoformat()

        try:
            sb.table("signal_snapshots").update(changes).eq("id", row["id"]).execute()
            updated += 1
        except Exception as exc:
            log.warning("signal_snapshots: update failed for %s: %s", row["id"], exc)

    if updated:
        log.info("signal_snapshots: resolved outcomes for %d rows", updated)
    return updated


# ── Read API (for dashboard endpoints) ────────────────────────────────────────

def get_stats(source_filter: list[str] | None = None) -> dict:
    """Return 7d and 30d signal stats from Supabase."""
    sb = _get_sb()
    if sb is None:
        return {"7d": None, "30d": None}
    try:
        now = datetime.now(timezone.utc)
        sources = source_filter or ["live_llm", "live_rule"]

        def _window(days: int) -> dict:
            cutoff = (now - timedelta(days=days)).isoformat()
            resp = (
                sb.table("signal_snapshots")
                .select("action,tier,outcome")
                .in_("source", sources)
                .neq("action", "HOLD")
                .gte("created_at", cutoff)
                .execute()
            )
            rows = resp.data or []
            total     = len(rows)
            wins      = sum(1 for r in rows if r["outcome"] == "WIN")
            losses    = sum(1 for r in rows if r["outcome"] == "LOSS")
            neutral   = sum(1 for r in rows if r["outcome"] == "NEUTRAL")
            pending   = sum(1 for r in rows if r["outcome"] == "PENDING")
            hot       = sum(1 for r in rows if r["tier"] == "HOT")
            warm      = sum(1 for r in rows if r["tier"] == "WARM")
            resolved  = wins + losses
            win_rate  = round(wins / resolved * 100, 1) if resolved else None
            return {
                "total": total, "wins": wins, "losses": losses,
                "neutral": neutral, "pending": pending,
                "hot": hot, "warm": warm,
                "win_rate": win_rate,
            }

        return {"7d": _window(7), "30d": _window(30)}
    except Exception as exc:
        log.warning("signal_snapshots.get_stats failed: %s", exc)
        return {"7d": None, "30d": None}


def get_leaderboard(group_by: str = "tier") -> list[dict]:
    """Aggregate win/loss/neutral grouped by tier, asset_class, or regime."""
    sb = _get_sb()
    if sb is None:
        return []
    if group_by not in ("tier", "asset_class", "regime"):
        group_by = "tier"
    try:
        resp = (
            sb.table("signal_snapshots")
            .select(f"{group_by},action,outcome,confidence")
            .in_("source", ["live_llm", "live_rule"])
            .neq("action", "HOLD")
            .execute()
        )
        rows = resp.data or []
        groups: dict[str, dict] = {}
        for r in rows:
            key = r.get(group_by) or "UNKNOWN"
            if key not in groups:
                groups[key] = {"wins": 0, "losses": 0, "neutral": 0,
                               "pending": 0, "total": 0, "conf_sum": 0.0}
            groups[key]["total"] += 1
            groups[key]["conf_sum"] += float(r.get("confidence") or 0)
            o = r.get("outcome")
            if o == "WIN":    groups[key]["wins"]    += 1
            elif o == "LOSS": groups[key]["losses"]  += 1
            elif o == "NEUTRAL": groups[key]["neutral"] += 1
            else:             groups[key]["pending"] += 1

        result = []
        for key, g in groups.items():
            resolved = g["wins"] + g["losses"]
            result.append({
                "group_key":    key,
                "total":        g["total"],
                "wins":         g["wins"],
                "losses":       g["losses"],
                "neutral":      g["neutral"],
                "pending":      g["pending"],
                "win_rate":     round(g["wins"] / resolved * 100, 1) if resolved else None,
                "avg_confidence": round(g["conf_sum"] / g["total"], 2) if g["total"] else None,
            })
        return sorted(result, key=lambda x: x["wins"], reverse=True)
    except Exception as exc:
        log.warning("signal_snapshots.get_leaderboard failed: %s", exc)
        return []
