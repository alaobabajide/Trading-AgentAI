"""Per-user broker type preference store.

Stores which broker a user wants to use. Credentials live in broker-specific
modules (alpaca_creds.py; future tastytrade_creds.py, schwab_creds.py, etc.).

File: {DATA_DIR}/user_broker_settings.json (chmod 0o600)
Schema: { "<user_id>": { "broker_type": "alpaca" } }
"""
from __future__ import annotations

import json
import logging
import os

log = logging.getLogger(__name__)

# ── Broker catalog (single source of truth for UI) ────────────────────────────
BROKER_CATALOG: list[dict] = [
    {
        "id":            "alpaca",
        "name":          "Alpaca",
        "tagline":       "US stocks, ETFs & crypto — paper and live trading",
        "supports_paper": True,
        "status":        "live",
    },
    {
        "id":            "tastytrade",
        "name":          "tastytrade",
        "tagline":       "Stocks, options, futures & crypto — active traders",
        "supports_paper": True,
        "status":        "live",
    },
    {
        "id":            "ibkr",
        "name":          "Interactive Brokers",
        "tagline":       "Global markets — stocks, options, futures, forex, bonds — self-hosted IB Gateway",
        "supports_paper": True,
        "status":        "live",
    },
    {
        "id":            "schwab",
        "name":          "Charles Schwab",
        "tagline":       "Stocks, ETFs & options — OAuth-connected, live trading only",
        "supports_paper": False,
        "status":        "live",
    },
    {
        "id":            "kraken",
        "name":          "Kraken",
        "tagline":       "Crypto spot trading — BTC, ETH, SOL and 200+ pairs, live only",
        "supports_paper": False,
        "status":        "live",
    },
    {
        "id":            "coinbase",
        "name":          "Coinbase Advanced Trade",
        "tagline":       "Crypto — US-regulated exchange, CDP API key authentication",
        "supports_paper": False,
        "status":        "live",
    },
    {
        "id":            "tradestation",
        "name":          "TradeStation",
        "tagline":       "US stocks, ETFs & futures — OAuth-connected, SIM paper trading supported",
        "supports_paper": True,
        "status":        "live",
    },
    {
        "id":            "meritrade",
        "name":          "Meritrade",
        "tagline":       "Nigerian Exchange (NGX) stocks & equities via Meristem Stockbrokers",
        "supports_paper": False,
        "status":        "coming_soon",
    },
    {
        "id":            "cowrywise",
        "name":          "Cowrywise",
        "tagline":       "NGX stocks, mutual funds & fixed income — digital investment platform",
        "supports_paper": False,
        "status":        "coming_soon",
    },
    {
        "id":            "stanbic",
        "name":          "Stanbic IBTC Stockbrokers",
        "tagline":       "NGX stocks, bonds & ETFs — institutional-grade stockbroking",
        "supports_paper": False,
        "status":        "coming_soon",
    },
]

LIVE_BROKERS: set[str] = {"alpaca", "tastytrade", "schwab", "ibkr", "kraken", "coinbase", "tradestation"}
DEFAULT_BROKER = "alpaca"

# ── Asset-class tab availability per broker ───────────────────────────────────
# Keys mirror the frontend BrokerTabs interface in useBrokerAssets.ts.

BROKER_ASSET_TABS: dict[str, dict[str, bool]] = {
    "alpaca":       {"stocks": True,  "etfs": True,  "crypto": True,  "forex": False, "ngx": False, "options": False, "futures": False, "bonds": False},
    "tastytrade":   {"stocks": True,  "etfs": True,  "crypto": True,  "forex": False, "ngx": False, "options": True,  "futures": True,  "bonds": False},
    "ibkr":         {"stocks": True,  "etfs": True,  "crypto": True,  "forex": True,  "ngx": False, "options": True,  "futures": True,  "bonds": True},
    "schwab":       {"stocks": True,  "etfs": True,  "crypto": False, "forex": False, "ngx": False, "options": True,  "futures": False, "bonds": False},
    "kraken":       {"stocks": False, "etfs": False, "crypto": True,  "forex": False, "ngx": False, "options": False, "futures": False, "bonds": False},
    "coinbase":     {"stocks": False, "etfs": False, "crypto": True,  "forex": False, "ngx": False, "options": False, "futures": False, "bonds": False},
    "tradestation": {"stocks": True,  "etfs": True,  "crypto": True,  "forex": True,  "ngx": False, "options": True,  "futures": True,  "bonds": False},
    "meritrade":    {"stocks": True,  "etfs": True,  "crypto": False, "forex": False, "ngx": True,  "options": False, "futures": False, "bonds": False},
    "cowrywise":    {"stocks": True,  "etfs": True,  "crypto": False, "forex": False, "ngx": True,  "options": False, "futures": False, "bonds": True},
    "stanbic":      {"stocks": True,  "etfs": True,  "crypto": False, "forex": False, "ngx": True,  "options": False, "futures": False, "bonds": True},
}

_DEFAULT_ASSET_TABS: dict[str, bool] = {
    "stocks": True, "etfs": True, "crypto": True,
    "forex": False, "ngx": False, "options": False, "futures": False, "bonds": False,
}


def get_broker_asset_tabs(broker_type: str | None) -> dict[str, bool]:
    """Return the asset-class tab visibility map for a given broker type."""
    return BROKER_ASSET_TABS.get(broker_type or DEFAULT_BROKER, _DEFAULT_ASSET_TABS)

# ── File path ────────────────────────────────────────────────────────────────

def _store_path() -> str:
    candidates = [
        os.environ.get("DATA_DIR", ""),
        "/data",
        os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")),
        "/tmp",
    ]
    for p in (c for c in candidates if c):
        try:
            os.makedirs(p, exist_ok=True)
            probe = os.path.join(p, ".write_probe")
            with open(probe, "w") as f:
                f.write("ok")
            os.remove(probe)
            return os.path.join(p, "user_broker_settings.json")
        except Exception:
            continue
    return "/tmp/user_broker_settings.json"


_STORE_PATH = _store_path()


# ── Low-level store helpers ───────────────────────────────────────────────────

def _load_store() -> dict:
    try:
        with open(_STORE_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.warning("Could not read broker settings store: %s", exc)
        return {}


def _write_store(data: dict) -> None:
    tmp = _STORE_PATH + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, _STORE_PATH)
        os.chmod(_STORE_PATH, 0o600)
    except Exception as exc:
        log.error("Could not write broker settings store: %s", exc)


# ── Public API ────────────────────────────────────────────────────────────────

def load_user_broker_type(user_id: str) -> str | None:
    """Return the user's stored broker_type, or None if not explicitly set."""
    store = _load_store()
    entry = store.get(user_id)
    if isinstance(entry, dict):
        return entry.get("broker_type") or None
    return None


def save_user_broker_type(user_id: str, broker_type: str) -> None:
    """Persist the user's broker selection."""
    store = _load_store()
    store[user_id] = {"broker_type": broker_type}
    _write_store(store)
    log.info("Broker type saved for user %s: %s", user_id[:8], broker_type)


def delete_user_broker_type(user_id: str) -> bool:
    """Remove the user's broker selection (reverts to system default).

    Returns True if an entry existed, False otherwise.
    """
    store = _load_store()
    existed = user_id in store
    if existed:
        del store[user_id]
        _write_store(store)
        log.info("Broker preference removed for user %s", user_id[:8])
    return existed
