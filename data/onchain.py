"""Layer 1 — On-chain data (crypto only).

Metrics fetched:
  • ETH gas price (Etherscan / Web3)
  • Exchange netflow (Glassnode free tier)
  • BTC dominance (CoinGecko free API — no key required)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

log = logging.getLogger(__name__)

COINGECKO_GLOBAL = "https://api.coingecko.com/api/v3/global"
ETHERSCAN_GAS = "https://api.etherscan.io/api?module=gastracker&action=gasoracle&apikey={key}"


@dataclass
class OnChainSnapshot:
    timestamp: datetime
    btc_dominance_pct: float = 0.0
    eth_gas_gwei: float = 0.0
    total_market_cap_usd: float = 0.0
    market_cap_change_24h_pct: float = 0.0
    extra: dict = field(default_factory=dict)


class OnChainFetcher:
    def __init__(self, etherscan_api_key: str = "", eth_rpc_url: str = "") -> None:
        self._etherscan_key = etherscan_api_key
        self._eth_rpc_url = eth_rpc_url

    def fetch_global(self) -> OnChainSnapshot:
        snap = OnChainSnapshot(timestamp=datetime.now(timezone.utc))
        try:
            resp = httpx.get(COINGECKO_GLOBAL, timeout=10)
            resp.raise_for_status()
            data = resp.json().get("data", {})
            snap.btc_dominance_pct = data.get("market_cap_percentage", {}).get("btc", 0.0)
            snap.total_market_cap_usd = data.get("total_market_cap", {}).get("usd", 0.0)
            snap.market_cap_change_24h_pct = data.get("market_cap_change_percentage_24h_usd", 0.0)
        except Exception as exc:
            log.error("CoinGecko global fetch failed: %s", exc)
        return snap

    def fetch_eth_gas(self) -> float:
        """Returns fast gas price in Gwei, or 0 on failure."""
        if self._etherscan_key:
            url = ETHERSCAN_GAS.format(key=self._etherscan_key)
        elif self._eth_rpc_url:
            return self._gas_via_rpc()
        else:
            return 0.0

        try:
            resp = httpx.get(url, timeout=10)
            resp.raise_for_status()
            result = resp.json().get("result", {})
            return float(result.get("FastGasPrice", 0))
        except Exception as exc:
            log.error("Etherscan gas fetch failed: %s", exc)
            return 0.0

    def _gas_via_rpc(self) -> float:
        try:
            from web3 import Web3
            w3 = Web3(Web3.HTTPProvider(self._eth_rpc_url))
            return w3.eth.gas_price / 1e9   # wei → Gwei
        except Exception as exc:
            log.error("Web3 gas fetch failed: %s", exc)
            return 0.0

    def snapshot(self) -> OnChainSnapshot:
        snap = self.fetch_global()
        snap.eth_gas_gwei = self.fetch_eth_gas()
        return snap
