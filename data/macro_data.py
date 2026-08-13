"""FRED macro data fetcher — free CSV endpoint, no API key required.

Fetched series:
  FEDFUNDS  — effective federal funds rate (%)
  T10Y2Y    — 10-year minus 2-year Treasury spread (bps) — yield-curve health
  CPIAUCSL  — CPI all-items, used to compute trailing 12-month inflation
  DTWEXBGS  — broad USD index (trade-weighted)

Data is cached at module level with a 1-hour TTL so parallel symbol
workers share one set of HTTP requests per cycle.
"""
from __future__ import annotations

import logging
import time
from io import StringIO

import httpx
import pandas as pd

log = logging.getLogger(__name__)

_FRED_BASE = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"

# Module-level cache: (fetch_time_monotonic, value)
_CACHE: dict[str, tuple[float, float | None]] = {}
_CACHE_TTL = 3600  # 1 hour — FRED data is daily/weekly, no need to re-fetch more often

# Single shared cache for the full macro context dict
_CTX_CACHE: tuple[float, dict] | None = None
_CTX_CACHE_TTL = 3600


def _fetch_fred(series: str) -> float | None:
    """Return the most-recent numeric value for a FRED series, or None on failure."""
    cached = _CACHE.get(series)
    if cached and (time.monotonic() - cached[0]) < _CACHE_TTL:
        return cached[1]

    url = _FRED_BASE.format(series=series)
    try:
        resp = httpx.get(url, timeout=12, follow_redirects=True)
        resp.raise_for_status()
        df = pd.read_csv(StringIO(resp.text))
        # FRED CSVs have two columns: DATE and value; missing data is "."
        val_col = df.columns[1]
        df = df[df[val_col] != "."].dropna(subset=[val_col])
        if df.empty:
            _CACHE[series] = (time.monotonic(), None)
            return None
        value = float(df.iloc[-1][val_col])
        _CACHE[series] = (time.monotonic(), value)
        log.debug("FRED %s = %.4f", series, value)
        return value
    except Exception as exc:
        log.debug("FRED fetch failed for %s: %s", series, exc)
        _CACHE[series] = (time.monotonic(), None)
        return None


def _fetch_cpi_yoy() -> float | None:
    """Compute trailing 12-month CPI inflation from CPIAUCSL monthly series."""
    cached = _CACHE.get("CPI_YOY")
    if cached and (time.monotonic() - cached[0]) < _CACHE_TTL:
        return cached[1]

    url = _FRED_BASE.format(series="CPIAUCSL")
    try:
        resp = httpx.get(url, timeout=12, follow_redirects=True)
        resp.raise_for_status()
        df = pd.read_csv(StringIO(resp.text))
        val_col = df.columns[1]
        df = df[df[val_col] != "."].dropna(subset=[val_col])
        df[val_col] = df[val_col].astype(float)
        if len(df) < 13:
            _CACHE["CPI_YOY"] = (time.monotonic(), None)
            return None
        latest = df.iloc[-1][val_col]
        year_ago = df.iloc[-13][val_col]
        yoy = round((latest / year_ago - 1) * 100, 2)
        _CACHE["CPI_YOY"] = (time.monotonic(), yoy)
        log.debug("CPI YoY = %.2f%%", yoy)
        return yoy
    except Exception as exc:
        log.debug("CPI YoY computation failed: %s", exc)
        _CACHE["CPI_YOY"] = (time.monotonic(), None)
        return None


def fetch_macro_context() -> dict:
    """Return a dict of macro indicators suitable for injecting into the macro agent context.

    All values are floats or None.  None means the fetch failed — the agent
    prompt should treat None as "data unavailable".
    """
    global _CTX_CACHE
    if _CTX_CACHE and (time.monotonic() - _CTX_CACHE[0]) < _CTX_CACHE_TTL:
        return _CTX_CACHE[1]

    fed_funds   = _fetch_fred("FEDFUNDS")       # e.g. 5.33 (%)
    yield_curve = _fetch_fred("T10Y2Y")         # e.g. -0.42 (pp; negative = inverted)
    cpi_yoy     = _fetch_cpi_yoy()              # e.g. 3.2 (%)
    dxy         = _fetch_fred("DTWEXBGS")       # e.g. 106.5 (index)

    # Derived macro regime signal (deterministic, not LLM)
    macro_regime = "NEUTRAL"
    if yield_curve is not None and yield_curve < -0.25:
        macro_regime = "RECESSION_RISK"          # deeply inverted curve
    elif fed_funds is not None and fed_funds > 5.0 and cpi_yoy is not None and cpi_yoy > 4.0:
        macro_regime = "RESTRICTIVE"             # tight monetary policy + high inflation
    elif fed_funds is not None and fed_funds < 2.0:
        macro_regime = "ACCOMMODATIVE"           # easy monetary conditions

    ctx = {
        "fed_funds_rate_pct":   fed_funds,
        "yield_curve_10y2y_pp": yield_curve,
        "cpi_yoy_pct":          cpi_yoy,
        "usd_index":            dxy,
        "macro_regime":         macro_regime,
        "macro_data_available": any(v is not None for v in [fed_funds, yield_curve, cpi_yoy, dxy]),
    }

    _CTX_CACHE = (time.monotonic(), ctx)
    log.info(
        "Macro context: fed=%.2f%% curve=%.2fpp cpi=%.2f%% dxy=%.1f regime=%s",
        fed_funds or 0, yield_curve or 0, cpi_yoy or 0, dxy or 0, macro_regime,
    )
    return ctx
