"""Yahoo Finance fallback for Research page data.

Used when no FMP API key is configured. Returns data shaped to match
the FMP API response schemas consumed by the frontend.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)


def _info(symbol: str) -> dict:
    import yfinance as yf
    ticker = yf.Ticker(symbol)
    try:
        info = ticker.info or {}
        if info:
            return info
    except Exception as exc:
        log.debug("yf .info failed for %s (%s), trying fast_info", symbol, exc)
    # fast_info uses a different Yahoo endpoint — more stable under rate-limiting
    try:
        fi = ticker.fast_info
        return {
            "currentPrice":       getattr(fi, "last_price", None),
            "regularMarketPrice": getattr(fi, "last_price", None),
            "marketCap":          getattr(fi, "market_cap", None),
            "fiftyTwoWeekHigh":   getattr(fi, "year_high", None),
            "fiftyTwoWeekLow":    getattr(fi, "year_low", None),
            "trailingPE":         getattr(fi, "p_e_ratio", None),
            "priceToBook":        getattr(fi, "price_to_book", None),
        }
    except Exception as exc2:
        log.warning("yf fast_info also failed for %s: %s", symbol, exc2)
        return {}


def yf_profile(symbol: str) -> list[dict]:
    try:
        info = _info(symbol)
        officers = info.get("companyOfficers") or []
        ceo = next(
            (o.get("name", "") for o in officers if "ceo" in o.get("title", "").lower()),
            officers[0].get("name", "") if officers else "",
        )
        return [{
            "symbol":      symbol.upper(),
            "companyName": info.get("longName") or info.get("shortName") or symbol,
            "description": info.get("longBusinessSummary") or "",
            "sector":      info.get("sector") or "",
            "industry":    info.get("industry") or "",
            "ceo":         ceo,
            "website":     info.get("website") or "",
            "image":       "",
            "mktCap":      info.get("marketCap") or 0,
            "price":       info.get("currentPrice") or info.get("regularMarketPrice") or 0,
            "changes":     info.get("regularMarketChange") or 0,
            "exchange":    info.get("exchange") or "",
            "currency":    info.get("currency") or "USD",
        }]
    except Exception as exc:
        log.warning("yf_profile(%s): %s", symbol, exc)
        return []


def yf_key_metrics(symbol: str, limit: int = 1) -> list[dict]:
    try:
        info = _info(symbol)
        mkt_cap = info.get("marketCap") or None
        fcf     = info.get("freeCashflow") or None
        fcf_yield = (fcf / mkt_cap) if (fcf and mkt_cap) else None
        d_e = info.get("debtToEquity")
        return [{
            "date":              datetime.today().strftime("%Y-%m-%d"),
            "peRatio":           info.get("trailingPE"),
            "evToEbitda":        info.get("enterpriseToEbitda"),
            "returnOnEquity":    info.get("returnOnEquity"),
            "returnOnAssets":    info.get("returnOnAssets"),
            "debtToEquity":      (d_e / 100) if d_e is not None else None,
            "grossProfitMargin": info.get("grossMargins"),
            "netProfitMargin":   info.get("profitMargins"),
            "freeCashFlowYield": fcf_yield,
            "priceToBook":       info.get("priceToBook"),
            "revenuePerShare":   info.get("revenuePerShare"),
        }]
    except Exception as exc:
        log.warning("yf_key_metrics(%s): %s", symbol, exc)
        return []


def yf_analyst_recommendations(symbol: str, limit: int = 1) -> list[dict]:
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        recs = ticker.recommendations
        if recs is None or recs.empty:
            return []
        latest = recs.tail(1).iloc[0]
        return [{
            "symbol":     symbol.upper(),
            "date":       str(recs.index[-1].date()),
            "strongBuy":  int(latest.get("strongBuy",  0)),
            "buy":        int(latest.get("buy",        0)),
            "hold":       int(latest.get("hold",       0)),
            "sell":       int(latest.get("sell",       0)),
            "strongSell": int(latest.get("strongSell", 0)),
        }]
    except Exception as exc:
        log.warning("yf_analyst_recommendations(%s): %s", symbol, exc)
        return []


def yf_price_target_consensus(symbol: str) -> list[dict]:
    try:
        info = _info(symbol)
        return [{
            "symbol":       symbol.upper(),
            "targetHigh":   info.get("targetHighPrice"),
            "targetLow":    info.get("targetLowPrice"),
            "targetMean":   info.get("targetMeanPrice"),
            "targetMedian": info.get("targetMedianPrice"),
            "lastMonth":    None,
            "lastQuarter":  None,
        }]
    except Exception as exc:
        log.warning("yf_price_target_consensus(%s): %s", symbol, exc)
        return []


def yf_fetch(data_type: str, symbol: str, limit: int = 1) -> list[dict] | None:
    """Return YF data shaped like the FMP response, or None if data_type unsupported."""
    mapping: dict[str, Any] = {
        "profile":                      lambda: yf_profile(symbol),
        "key-metrics":                  lambda: yf_key_metrics(symbol, limit),
        "analyst-stock-recommendations": lambda: yf_analyst_recommendations(symbol, limit),
        "price-target-consensus":        lambda: yf_price_target_consensus(symbol),
    }
    fn = mapping.get(data_type)
    return fn() if fn else None
