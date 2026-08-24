"""Track Record Configuration — immutable parameters for the official v1 track record.

Written to Supabase track_record_config on first startup. Once locked, parameters
are never modified retroactively — only appended to change_log with a timestamp
if something changes (and a new track record series is started).

The started_at date marks when forward signal logging began. Any signal before
this date was not captured and cannot be part of the official track record.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

TRACK_RECORD_VERSION = "v1"
INITIAL_NAV = 100_000.0
STARTED_AT  = "2026-08-24T00:00:00Z"   # date this logging infrastructure went live

V1_CONFIG = {
    "track_record_id":    TRACK_RECORD_VERSION,
    "started_at":         STARTED_AT,
    "initial_nav":        INITIAL_NAV,
    "risk_controls": {
        "circuit_breaker":   0.10,
        "max_position":      0.05,
        "crypto_cap":        0.20,
        "default_stop":      0.02,
        "default_target":    0.05,
    },
    "tier_thresholds": {
        "hot":       17,
        "warm":      13,
        "cold_below": 13,
        "max_votes":  27,
    },
    "outcome_thresholds": {
        "win_pct":  5.0,
        "loss_pct": -2.0,
    },
    "execution_mode":             "auto",
    "orchestrator_interval_minutes": 30,
    "symbol_count":               86,
    "engine":                     "llm_debate",
    "primary_model":              "google/gemini-2.5-flash-lite",
    "locked":                     True,
    "change_log":                 [],
}


def ensure_track_record_config() -> bool:
    """Create the v1 track record config in Supabase if it doesn't exist yet.

    This is idempotent — safe to call on every startup.
    Returns True if config was created or already exists.
    """
    try:
        from config import get_settings
        cfg = get_settings()
        if not cfg.supabase_url or not cfg.supabase_service_role_key:
            log.debug("track_record: Supabase not configured — skipping")
            return False
        from supabase import create_client
        sb = create_client(cfg.supabase_url, cfg.supabase_service_role_key)

        existing = (
            sb.table("track_record_config")
            .select("id,version")
            .eq("version", TRACK_RECORD_VERSION)
            .limit(1)
            .execute()
        )
        if existing.data:
            log.debug("track_record: v1 config already exists (%s)", existing.data[0]["id"])
            return True

        sb.table("track_record_config").insert({
            "version":    TRACK_RECORD_VERSION,
            "started_at": STARTED_AT,
            "initial_nav": INITIAL_NAV,
            "config":     V1_CONFIG,
            "locked":     True,
            "change_log": [],
        }).execute()
        log.info("track_record: v1 config locked and written to Supabase (started_at=%s)", STARTED_AT)
        return True
    except Exception as exc:
        log.warning("track_record: config lock failed (non-fatal): %s", exc)
        return False


def get_config() -> dict:
    """Return the active track record config (from Supabase or hard-coded default)."""
    try:
        from config import get_settings
        cfg = get_settings()
        if not cfg.supabase_url or not cfg.supabase_service_role_key:
            return V1_CONFIG
        from supabase import create_client
        sb = create_client(cfg.supabase_url, cfg.supabase_service_role_key)
        resp = (
            sb.table("track_record_config")
            .select("config,started_at,initial_nav")
            .eq("version", TRACK_RECORD_VERSION)
            .limit(1)
            .execute()
        )
        if resp.data:
            return resp.data[0].get("config", V1_CONFIG)
    except Exception:
        pass
    return V1_CONFIG
