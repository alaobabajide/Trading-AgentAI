"""Engine version profiles for the rule-based backtest harness.

V1 — current production behavior (ATR stops, Layer 1/2 exits, no passive allocation).
V2 — same signal/exit logic as V1 plus passive SPY allocation when cash > 25% NAV.

Profiles are passed to runner.run_backtest() at call-time; the runner reads
stop/allocation behaviour from the profile dict rather than hardcoded constants.
Adding a future V3 is just another entry here — no engine code changes needed.
"""
from __future__ import annotations

ENGINE_PROFILES: dict[str, dict] = {

    "v1": {
        "id":          "v1",
        "name":        "V1 — Asymmetric Exit Framework",
        "description": (
            "Current production rule engine. ATR-based stops, Layer 1/2 partial-exit "
            "framework, trailing runner stops. No passive index allocation."
        ),
        "label_color": "#8892A8",

        # Passive allocation (all disabled for V1)
        "passive_enabled":     False,
        "passive_symbol":      None,
        "cash_threshold_pct":  None,   # buy SPY when cash exceeds this fraction of NAV
        "passive_max_pct":     None,   # cap passive position at this fraction of NAV
        "rebalance_band_pct":  None,   # only rebalance when drift > this fraction
    },

    "v2": {
        "id":          "v2",
        "name":        "V2 — AEF + Passive SPY",
        "description": (
            "Identical signal and exit logic as V1 (ATR stops, Layer 1/2, trailing). "
            "Adds passive SPY allocation: idle cash above 25% NAV is deployed into "
            "SPY (capped at 40% NAV, rebalanced when drift > 5%)."
        ),
        "label_color": "#22D68A",

        # Passive allocation
        "passive_enabled":     True,
        "passive_symbol":      "SPY",
        "cash_threshold_pct":  0.25,   # keep at least 25% NAV as dry powder
        "passive_max_pct":     0.40,   # SPY passive never exceeds 40% NAV
        "rebalance_band_pct":  0.05,   # rebalance band to avoid churn
    },
}

DEFAULT_PROFILE: dict = ENGINE_PROFILES["v1"]


def get_profile(engine_version: str) -> dict:
    """Return the profile dict for the given version string, falling back to V1."""
    return ENGINE_PROFILES.get(engine_version, DEFAULT_PROFILE)
