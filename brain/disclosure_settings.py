"""Disclosure Tracker configuration — file-based per-instance settings.

Stores all configurable parameters for the Public Disclosure Tracker feature:
  - SEC EDGAR User-Agent (required by EDGAR fair-use policy)
  - Congress feed URLs (HouseStockWatcher, SenateStockWatcher)
  - Refresh intervals
  - Minimum confidence filter for display

Settings are written to ta_disclosure_config.json in the same DATA_DIR as
other app data files. Defaults are safe out-of-the-box without any config.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

_LOCK = threading.Lock()
_STORE_PATH: str | None = None


def _store_path() -> str:
    global _STORE_PATH
    if _STORE_PATH:
        return _STORE_PATH
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
            _STORE_PATH = os.path.join(c, "ta_disclosure_config.json")
            return _STORE_PATH
        except Exception:
            continue
    _STORE_PATH = "/tmp/ta_disclosure_config.json"
    return _STORE_PATH


@dataclass
class DisclosureConfig:
    # SEC EDGAR
    edgar_user_agent: str = "TradingAgentAI/1.0 alao.babajide@gmail.com"
    edgar_request_timeout_secs: int = 30
    edgar_rate_limit_sleep_secs: int = 1

    # Congress feed URLs
    house_feed_url: str = "https://housestockwatcher.com/api"
    senate_feed_url: str = "https://senatestockwatcher.com/api"
    congress_request_timeout_secs: int = 20

    # Refresh schedule (hours — read by orchestrator on startup)
    congress_refresh_hours: int = 6
    holdings_refresh_hours: int = 24

    # Display filter
    min_confidence_pct: int = 70

    # Quiver Quantitative API key (free tier at quiverquant.com)
    # Used for congressional STOCK Act trade disclosures
    quiver_api_key: str = ""


def load() -> DisclosureConfig:
    path = _store_path()
    with _LOCK:
        try:
            with open(path) as f:
                data = json.load(f)
            cfg = DisclosureConfig()
            for k, v in data.items():
                if hasattr(cfg, k):
                    setattr(cfg, k, v)
            return cfg
        except FileNotFoundError:
            return DisclosureConfig()
        except Exception as exc:
            log.warning("Could not read disclosure config (%s): %s — using defaults", path, exc)
            return DisclosureConfig()


def save(updates: dict) -> DisclosureConfig:
    path = _store_path()
    with _LOCK:
        cfg = load()
        for k, v in updates.items():
            if hasattr(cfg, k):
                setattr(cfg, k, v)
            else:
                log.warning("Unknown disclosure config key ignored: %s", k)
        try:
            with open(path, "w") as f:
                json.dump(asdict(cfg), f, indent=2)
            try:
                os.chmod(path, 0o600)
            except Exception:
                pass
        except Exception as exc:
            log.error("Could not write disclosure config: %s", exc)
            raise
    return cfg


def as_dict() -> dict:
    return asdict(load())
