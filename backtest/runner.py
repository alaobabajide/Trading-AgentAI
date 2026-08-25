"""Paper-mode backtesting harness — Asymmetric Exit Framework.

Replays historical OHLCV data through the same rule-based signal engine used
in production paper mode.  Does NOT call the LLM — uses deterministic rules
so the result is reproducible and fast (no API cost).

Usage:
    python -m backtest.runner --symbols AAPL MSFT NVDA --years 3 --equity 100000
    python -m backtest.runner --symbols all_stocks all_etfs --years 5

Exit strategy — Asymmetric Exit Framework:
  HOT signal + TRENDING_UP  → Layer 1 at +8% (sell 40%) · Layer 2 trailing 12%
  HOT signal + RANGING      → Layer 1 at +6% (sell 50%) · Layer 2 trailing 8%
  WARM signal + TRENDING_UP → Layer 1 at +6% (sell 50%) · Layer 2 trailing 10%
  WARM signal + RANGING/HV  → Bracket only (100% at +5%, hard SL)
  All signals               → Hard stop-loss at ATR-based distance (full position)
  Post-Layer 1              → Break-even floor replaces hard stop; trailing ratchets up

Portfolio controls:
  Market regime gate     — no new longs when SPY < 200-day SMA
  Portfolio exposure cap — max 50% of equity deployed at once
  Max concurrent pos     — hard cap (default 15 open positions)
  Drawdown position scale — sizes reduce 20% when equity drops >8% from peak
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Literal

import pandas as pd
import yfinance as yf

import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from watchlist import STOCK_WATCHLIST, ETF_WATCHLIST, CRYPTO_WATCHLIST

log = logging.getLogger(__name__)


# ── Trade record ──────────────────────────────────────────────────────────────

@dataclass
class Trade:
    symbol: str
    asset_class: Literal["stock", "crypto"]
    action: Literal["BUY", "SELL"]
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    qty: float
    pnl: float
    pnl_pct: float
    exit_reason: Literal["take_profit", "partial_profit", "stop_loss",
                          "signal_sell", "end_of_period"]
    stop_price: float
    take_profit_price: float
    tier: str = "WARM"
    partial_exit_pct: float = 0.0    # fraction exited at Layer 1 (0 = bracket-only)
    runner_trail_pct: float = 0.0    # trailing % for the remaining runner
    layer1_fired: bool = False        # True after Layer 1 has executed


# ── Backtest result ───────────────────────────────────────────────────────────

@dataclass
class BacktestResult:
    start_date: str
    end_date: str
    initial_equity: float
    final_equity: float
    total_return_pct: float
    annualised_return_pct: float
    benchmark_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    win_rate_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    partial_profit_exits: int
    runner_exits: int
    bracket_tp_exits: int
    stop_loss_exits: int
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float
    max_concurrent_positions: int
    max_exposure_pct: float
    market_regime_filter: bool
    symbols_traded: list[str]
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)


# ── Indicator computation ─────────────────────────────────────────────────────

def _precompute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Vectorized indicator computation over a symbol's full OHLCV DataFrame.

    Called once per symbol before the simulation loop, replacing the old
    per-bar rolling-window approach which was O(n_bars) pandas operations per
    symbol. This is O(1) pandas operations per symbol — a 100-250x speedup on
    Railway's constrained CPU.
    """
    import ta
    c = df["Close"]
    h = df["High"]
    l = df["Low"]
    v = df["Volume"]

    out = pd.DataFrame(index=df.index)
    out["price"]   = c
    out["sma_20"]  = c.rolling(20).mean()
    out["sma_50"]  = c.rolling(50).mean()
    out["sma_200"] = c.rolling(200).mean()

    out["rsi_14"] = ta.momentum.RSIIndicator(c, window=14).rsi()

    _macd = ta.trend.MACD(c)
    out["macd"]        = _macd.macd()
    out["macd_signal"] = _macd.macd_signal()

    out["atr_14"] = ta.volatility.AverageTrueRange(h, l, c, window=14).average_true_range()

    _bb = ta.volatility.BollingerBands(c, window=20)
    out["bb_upper"] = _bb.bollinger_hband()
    out["bb_lower"] = _bb.bollinger_lband()
    out["bb_width"] = (out["bb_upper"] - out["bb_lower"]) / c.clip(lower=1e-9)

    vol_avg = v.rolling(20).mean().clip(lower=1)
    out["volume_ratio"] = v / vol_avg

    out["roc_5"]  = c.pct_change(5)  * 100
    out["roc_10"] = c.pct_change(10) * 100
    out["roc_20"] = c.pct_change(20) * 100
    out["roc_60"] = c.pct_change(60) * 100

    high_52w = h.rolling(252, min_periods=1).max()
    low_52w  = l.rolling(252, min_periods=1).min()
    out["high_proximity"] = (c / high_52w.clip(lower=1e-9)) - 1
    out["low_proximity"]  = (c / low_52w.clip(lower=1e-9))  - 1

    out["stoch_k"] = 50.0
    out["stoch_d"] = 50.0

    return out


# ── Signal generation ─────────────────────────────────────────────────────────

def _paper_signal(
    indicators: dict, asset_class: str
) -> tuple[str, str, float, float, float, float, float]:
    """Return (action, tier, pos_pct, stop_pct, tp_pct, partial_exit_pct, runner_trail_pct)."""
    from brain.debate import (
        _paper_technical, _paper_quant, _paper_fundamental,
        _paper_sentiment, _paper_options_flow, _paper_macro,
        _paper_investor_buffett, _paper_investor_munger, _paper_investor_lynch,
        _paper_investor_ackman, _paper_investor_cohen, _paper_investor_dalio,
        _paper_investor_wood, _paper_investor_bogle,
        _paper_investor_soros, _paper_investor_druckenmiller,
        _paper_investor_simons, _paper_investor_templeton,
        _paper_breakout, _paper_trend_strength, _paper_sector_rotation,
        _paper_earnings_event, _paper_momentum_scorer, _paper_supply_demand,
        _paper_volume_analyst, _paper_risk_reward,
        _aggregate_dual_panel, _action_from_votes, _compute_tier,
        _parse_regime_label, WARM_MIN_VOTES,
    )
    from brain.agents.regime import RegimeDetector

    regime_detector = RegimeDetector()
    regime_view     = regime_detector.analyse({"indicators": indicators})
    regime_label    = _parse_regime_label(regime_view)

    views: dict[str, str] = {
        "regime":          regime_view,
        "technical":       _paper_technical(indicators),
        "quant":           _paper_quant(indicators),
        "fundamental":     _paper_fundamental(indicators),
        "sentiment":       _paper_sentiment(indicators),
        "options_flow":    _paper_options_flow(indicators),
        "macro":           _paper_macro(indicators),
        "breakout":        _paper_breakout(indicators),
        "trend_strength":  _paper_trend_strength(indicators),
        "sector_rotation": _paper_sector_rotation(indicators),
        "earnings_event":  _paper_earnings_event(indicators),
        "momentum_scorer": _paper_momentum_scorer(indicators),
        "supply_demand":   _paper_supply_demand(indicators),
        "volume_analyst":  _paper_volume_analyst(indicators),
        "risk_reward":     _paper_risk_reward(indicators),
    }
    inv_views: dict[str, str] = {
        "buffett":        _paper_investor_buffett(indicators),
        "munger":         _paper_investor_munger(indicators),
        "lynch":          _paper_investor_lynch(indicators),
        "ackman":         _paper_investor_ackman(indicators),
        "cohen":          _paper_investor_cohen(indicators),
        "dalio":          _paper_investor_dalio(indicators),
        "wood":           _paper_investor_wood(indicators),
        "bogle":          _paper_investor_bogle(indicators),
        "soros":          _paper_investor_soros(indicators),
        "druckenmiller":  _paper_investor_druckenmiller(indicators),
        "simons":         _paper_investor_simons(indicators),
        "templeton":      _paper_investor_templeton(indicators),
    }

    _, _, combined, conflict, _, b_abstaining = _aggregate_dual_panel(
        views, inv_views, asset_class,
    )
    action = _action_from_votes(combined, conflict, threshold=WARM_MIN_VOTES)
    tier   = _compute_tier(combined, action, regime_label, indicators,
                           panels_conflict=conflict, b_abstaining=b_abstaining)

    price    = float(indicators.get("price", 1.0))
    atr14    = float(indicators.get("atr_14", 0.0))
    atr_pct  = atr14 / max(price, 1e-9)
    stop_pct = max(0.005, min(0.04, 1.5 * atr_pct))

    # Position size: fixed at 5% for all tiers — measured data showed HOT at 8%
    # had a sub-break-even win rate (33-36%), making the size premium a net negative
    pos_pct = 0.05

    # ── Asymmetric Exit Framework — tier × regime matrix ──────────────────────
    is_trending_up  = "TRENDING_UP"     in regime_label
    is_ranging      = "RANGING"         in regime_label
    is_high_vol     = "HIGH_VOLATILITY" in regime_label

    if tier == "HOT" and is_trending_up:
        partial_exit_pct = 0.40
        runner_trail_pct = 0.12
        tp_pct           = 0.08

    elif tier == "HOT":
        partial_exit_pct = 0.50
        runner_trail_pct = 0.08
        tp_pct           = 0.06

    elif tier == "WARM" and is_trending_up:
        partial_exit_pct = 0.50
        runner_trail_pct = 0.10
        tp_pct           = 0.06

    else:
        # WARM + RANGING / HIGH_VOLATILITY: bracket-only, no runner
        partial_exit_pct = 0.0
        runner_trail_pct = 0.0
        tp_pct           = 0.05

    return action, tier, pos_pct, stop_pct, tp_pct, partial_exit_pct, runner_trail_pct


# ── Portfolio simulation ──────────────────────────────────────────────────────

class PortfolioSimulator:
    """
    Implements the Asymmetric Exit Framework:
      - Layer 1: partial exit at first TP target
      - Layer 2: remaining qty runs under a trailing stop (no fixed ceiling)
      - Break-even floor applied after Layer 1 so a profitable trade cannot
        return a net loss on its runner
      - Cash and open positions tracked separately (no double-counting bug)
    """

    def __init__(
        self,
        initial_equity: float = 100_000.0,
        max_position_pct: float = 0.05,
        hot_position_pct: float = 0.08,
        max_concurrent: int = 15,
        max_exposure_pct: float = 0.50,
        drawdown_scale_threshold: float = 0.08,
        drawdown_scale_factor: float = 0.80,
    ) -> None:
        self._initial        = initial_equity
        self._cash           = initial_equity
        self._max_pos        = max_position_pct
        self._hot_max_pos    = hot_position_pct
        self._max_concurrent = max_concurrent
        self._max_exposure   = max_exposure_pct
        self._dd_threshold   = drawdown_scale_threshold
        self._dd_factor      = drawdown_scale_factor
        self._open:  dict[str, Trade] = {}
        self._closed: list[Trade]     = []
        self._equity_curve: list[dict] = []
        self._peak           = initial_equity
        self._price_peaks:   dict[str, float] = {}   # runner peak tracking
        self._stop_cooldown: dict[str, int]   = {}   # symbol → bar index when re-entry allowed

    @property
    def equity(self) -> float:
        invested = sum(t.qty * t.entry_price for t in self._open.values())
        return self._cash + invested

    def mark_equity(self, date_str: str, prices: dict[str, float]) -> None:
        open_val = sum(
            t.qty * prices.get(t.symbol, t.entry_price) for t in self._open.values()
        )
        total = self._cash + open_val
        self._equity_curve.append({"date": date_str, "equity": round(total, 2)})
        if total > self._peak:
            self._peak = total

    # ── Position sizing scale factor (drawdown protection) ────────────────────
    def _size_scale(self) -> float:
        """Reduce position sizes when equity has drawn down beyond the configured threshold."""
        current = self._cash + sum(
            t.qty * t.entry_price for t in self._open.values()
        )
        dd = (self._peak - current) / max(self._peak, 1)
        return self._dd_factor if dd > self._dd_threshold else 1.0

    def try_open(
        self,
        symbol: str,
        asset_class: str,
        price: float,
        pos_pct: float,
        stop_pct: float,
        tp_pct: float,
        entry_date: str,
        tier: str,
        partial_exit_pct: float = 0.0,
        runner_trail_pct: float = 0.0,
        bar_idx: int = 0,
    ) -> bool:
        if symbol in self._open:
            return False
        # Block re-entry within 5 bars of a stop-loss on this symbol
        if self._stop_cooldown.get(symbol, 0) > bar_idx:
            return False
        if len(self._open) >= self._max_concurrent:
            return False

        # Portfolio exposure gate
        invested = sum(t.qty * t.entry_price for t in self._open.values())
        if invested / max(self._initial, 1) >= self._max_exposure:
            return False

        # Fix 2: all tiers use the same max position cap (5%)
        notional = self._initial * min(pos_pct, self._max_pos) * self._size_scale()
        if notional < 10 or notional > self._cash:
            return False

        qty         = notional / price
        stop_price  = price * (1 - stop_pct)
        tp_price    = price * (1 + tp_pct)

        self._open[symbol] = Trade(
            symbol=symbol, asset_class=asset_class, action="BUY",
            entry_date=entry_date, entry_price=price,
            exit_date="", exit_price=0.0,
            qty=qty, pnl=0.0, pnl_pct=0.0,
            exit_reason="end_of_period",
            stop_price=stop_price, take_profit_price=tp_price,
            tier=tier,
            partial_exit_pct=partial_exit_pct,
            runner_trail_pct=runner_trail_pct,
            layer1_fired=False,
        )
        self._cash -= notional
        return True

    # ── Layer 1: partial exit, convert remainder to runner ────────────────────
    def _fire_layer1(self, symbol: str, exit_price: float, date_str: str) -> Trade:
        """Execute Layer 1 partial profit-take. Position stays open as runner."""
        trade       = self._open[symbol]        # NOT removed from _open
        partial_qty = trade.qty * trade.partial_exit_pct
        runner_qty  = trade.qty - partial_qty

        pnl     = (exit_price - trade.entry_price) * partial_qty
        pnl_pct = (exit_price / trade.entry_price - 1) * 100

        partial_trade = Trade(
            symbol=symbol, asset_class=trade.asset_class, action="BUY",
            entry_date=trade.entry_date, entry_price=trade.entry_price,
            exit_date=date_str, exit_price=exit_price,
            qty=partial_qty, pnl=round(pnl, 2), pnl_pct=round(pnl_pct, 2),
            exit_reason="partial_profit",
            stop_price=trade.stop_price,
            take_profit_price=exit_price,
            tier=trade.tier,
            partial_exit_pct=trade.partial_exit_pct,
            runner_trail_pct=trade.runner_trail_pct,
            layer1_fired=True,
        )
        self._cash += partial_qty * exit_price
        self._closed.append(partial_trade)

        # Convert remaining portion to runner
        trade.qty               = runner_qty
        trade.stop_price        = trade.entry_price   # break-even floor
        trade.take_profit_price = float("inf")        # no ceiling
        trade.layer1_fired      = True
        self._price_peaks[symbol] = exit_price        # start trailing from Layer 1 price

        return partial_trade

    # ── Full close ────────────────────────────────────────────────────────────
    def _close(self, symbol: str, exit_price: float, date_str: str, reason: str) -> Trade:
        trade = self._open.pop(symbol)
        self._price_peaks.pop(symbol, None)
        trade.exit_date  = date_str
        trade.exit_price = exit_price
        pnl              = (exit_price - trade.entry_price) * trade.qty
        pnl_pct          = (exit_price / trade.entry_price - 1) * 100
        trade.pnl        = round(pnl, 2)
        trade.pnl_pct    = round(pnl_pct, 2)
        trade.exit_reason = reason  # type: ignore[assignment]
        self._cash       += trade.qty * exit_price
        self._closed.append(trade)
        return trade

    # ── Main exit check (called every bar for every open symbol) ──────────────
    def check_exits(self, symbol: str, high: float, low: float,
                    date_str: str, bar_idx: int = 0) -> list[Trade]:
        """
        Returns list of Trade records created this bar (0, 1, or 2 items):
          - 0 items: no exit condition met
          - 1 item:  stop-loss, bracket TP, or Layer 1 partial (runner stays open)
          - 2 items: Layer 1 + runner stop hit on same bar (rare edge case)
        """
        trade = self._open.get(symbol)
        if not trade:
            return []

        results: list[Trade] = []

        if not trade.layer1_fired:
            # ── Pre-Layer 1: bracket mode ─────────────────────────────────────
            hit_sl = low  <= trade.stop_price
            hit_tp = high >= trade.take_profit_price

            if hit_sl:
                # Hard stop fires first (worst-case ordering on gap bars)
                results.append(self._close(symbol, trade.stop_price, date_str, "stop_loss"))
                # Block re-entry for 5 bars so we don't immediately re-enter a falling stock
                self._stop_cooldown[symbol] = bar_idx + 5
                return results

            if hit_tp:
                if trade.partial_exit_pct > 0:
                    # Layer 1 fires: partial exit, runner stays open
                    results.append(self._fire_layer1(symbol, trade.take_profit_price, date_str))
                    # Check if runner also stopped on this same bar (high/low gap)
                    runner = self._open.get(symbol)
                    if runner and low <= runner.stop_price:
                        self._price_peaks.pop(symbol, None)
                        results.append(self._close(symbol, runner.stop_price, date_str, "stop_loss"))
                else:
                    # Bracket-only: full exit at TP
                    results.append(
                        self._close(symbol, trade.take_profit_price, date_str, "take_profit")
                    )
            return results

        else:
            # ── Post-Layer 1: runner / trailing stop mode ─────────────────────
            peak = self._price_peaks.get(symbol, trade.entry_price)
            if high > peak:
                peak = high
                self._price_peaks[symbol] = peak
                # Trail ratchets up; break-even floor is permanent lower bound
                new_stop = max(trade.stop_price, peak * (1 - trade.runner_trail_pct))
                trade.stop_price = new_stop

            if low <= trade.stop_price:
                self._price_peaks.pop(symbol, None)
                results.append(self._close(symbol, trade.stop_price, date_str, "stop_loss"))

            return results

    def close_on_signal(self, symbol: str, price: float, date_str: str) -> Trade | None:
        if symbol not in self._open:
            return None
        return self._close(symbol, price, date_str, "signal_sell")

    def close_all(self, prices: dict[str, float], date_str: str) -> None:
        for sym in list(self._open.keys()):
            price = prices.get(sym, self._open[sym].entry_price)
            self._close(sym, price, date_str, "end_of_period")

    def max_drawdown(self) -> float:
        if not self._equity_curve:
            return 0.0
        equities = [e["equity"] for e in self._equity_curve]
        peak, max_dd = equities[0], 0.0
        for e in equities:
            if e > peak:
                peak = e
            dd = (peak - e) / peak * 100
            if dd > max_dd:
                max_dd = dd
        return round(max_dd, 2)


# ── Main backtest loop ────────────────────────────────────────────────────────

def run_backtest(
    symbols: list[str],
    asset_class: str = "stock",
    years: int = 1,             # ignored when start_date/end_date are provided
    start_date: str | None = None,
    end_date: str | None = None,
    initial_equity: float = 100_000.0,
    max_position_pct: float = 0.05,
    hot_position_pct: float = 0.08,
    max_concurrent_positions: int = 15,
    max_portfolio_exposure: float = 0.50,
    drawdown_scale_threshold: float = 0.08,
    drawdown_scale_factor: float = 0.80,
    market_regime_filter: bool = True,
    min_bars: int = 60,
) -> BacktestResult:
    end_dt   = date.fromisoformat(end_date)   if end_date   else date.today()
    start_dt = date.fromisoformat(start_date) if start_date else date(end_dt.year - years, end_dt.month, end_dt.day)
    years    = max((end_dt - start_dt).days / 365.0, 1/12)  # actual years for annualization

    spy_only = "SPY" not in symbols
    download_syms = list(dict.fromkeys(symbols + ["SPY"]))

    log.info(
        "Downloading %d symbols from %s to %s …",
        len(download_syms), start_dt, end_dt,
    )

    import concurrent.futures as _cf_dl
    import time as _time

    _BATCH_TIMEOUT_S   = 15    # per-batch hard cap — 15 s is plenty for fast networks
    _DOWNLOAD_BUDGET_S = 90    # total download budget — stop batching after 90 s
    _dl_start = _time.monotonic()

    def _download_batch(batch: list[str], timeout: float) -> "pd.DataFrame | None":
        """Download one batch via yf.download with a per-batch hard timeout."""
        _ex = _cf_dl.ThreadPoolExecutor(max_workers=1)
        _f  = _ex.submit(yf.download, batch,
                         start=str(start_dt), end=str(end_dt),
                         progress=False, auto_adjust=True, threads=False)
        try:
            result = _f.result(timeout=timeout)
            _ex.shutdown(wait=False)
            return result
        except _cf_dl.TimeoutError:
            _ex.shutdown(wait=False)
            log.warning("Batch timed out (%.0f s), skipping: %s…", timeout, batch[:3])
            return None

    ohlcv: dict[str, pd.DataFrame] = {}
    BATCH = 10
    for _i in range(0, len(download_syms), BATCH):
        _elapsed  = _time.monotonic() - _dl_start
        _remaining = _DOWNLOAD_BUDGET_S - _elapsed
        if _remaining <= 0:
            log.warning("Download budget exhausted after %.0f s — proceeding with %d/%d symbols",
                        _elapsed, len(ohlcv), len(download_syms))
            break
        _batch   = download_syms[_i:_i + BATCH]
        _timeout = min(_BATCH_TIMEOUT_S, _remaining)
        _raw     = _download_batch(_batch, _timeout)
        if _raw is None:
            continue
        if len(_batch) == 1:
            _df = _raw.dropna()
            if not _df.empty:
                ohlcv[_batch[0]] = _df[["Open", "High", "Low", "Close", "Volume"]]
        else:
            for sym in _batch:
                try:
                    _df = pd.DataFrame({
                        "Open":   _raw["Open"][sym],
                        "High":   _raw["High"][sym],
                        "Low":    _raw["Low"][sym],
                        "Close":  _raw["Close"][sym],
                        "Volume": _raw["Volume"][sym],
                    }).dropna()
                    if not _df.empty:
                        ohlcv[sym] = _df
                except (KeyError, TypeError):
                    pass

    if not ohlcv:
        raise RuntimeError(
            "No price data downloaded — Yahoo Finance may be unreachable from this server."
        )

    # SPY regime series
    spy_up: dict[str, bool] = {}
    spy_return_pct = 0.0
    if "SPY" in ohlcv:
        spy_df     = ohlcv["SPY"]
        spy_closes = spy_df["Close"]
        sma200_s   = spy_closes.rolling(200).mean()
        for dt_idx in spy_closes.index:
            key = str(dt_idx.date() if hasattr(dt_idx, "date") else dt_idx)
            sma = sma200_s.get(dt_idx, float("nan"))
            spy_up[key] = (not pd.isna(sma)) and float(spy_closes[dt_idx]) > float(sma)
        spy_return_pct = round(
            (float(spy_closes.iloc[-1]) / float(spy_closes.iloc[0]) - 1) * 100, 2
        )

    traded_ohlcv = {s: df for s, df in ohlcv.items() if s in symbols}
    if not traded_ohlcv:
        raise ValueError("No price data for any traded symbol.")

    closes_union = pd.concat(
        {s: df["Close"] for s, df in traded_ohlcv.items()}, axis=1
    ).ffill()
    dates = closes_union.index.tolist()

    # Pre-compute all indicators for every symbol in one vectorized pass.
    # This replaces the old per-bar rolling-window approach and cuts runtime
    # from O(n_bars × n_symbols) pandas calls to O(n_symbols) vectorized calls.
    log.info("Pre-computing indicators for %d symbols…", len(traded_ohlcv))
    symbol_ind: dict[str, pd.DataFrame] = {}
    for sym, df in traded_ohlcv.items():
        try:
            symbol_ind[sym] = _precompute_indicators(df)
        except Exception as exc:
            log.warning("Indicator pre-compute skipped for %s: %s", sym, exc)

    sim = PortfolioSimulator(
        initial_equity=initial_equity,
        max_position_pct=max_position_pct,
        hot_position_pct=hot_position_pct,
        max_concurrent=max_concurrent_positions,
        max_exposure_pct=max_portfolio_exposure,
        drawdown_scale_threshold=drawdown_scale_threshold,
        drawdown_scale_factor=drawdown_scale_factor,
    )

    for i, bar_date in enumerate(dates):
        date_str     = str(bar_date.date() if hasattr(bar_date, "date") else bar_date)
        bar_prices:  dict[str, float] = {}
        market_is_up = spy_up.get(date_str, True)

        for sym, df in traded_ohlcv.items():
            if bar_date not in df.index:
                continue
            row   = df.loc[bar_date]
            close = float(row["Close"])
            high  = float(row["High"])
            low   = float(row["Low"])
            bar_prices[sym] = close

            # Check all exit conditions for this bar
            exits = sim.check_exits(sym, high, low, date_str, bar_idx=i)
            for t in exits:
                log.debug("  %s %s → %s qty=%.4f pnl=%.2f (%.1f%%)",
                          date_str, sym, t.exit_reason, t.qty, t.pnl, t.pnl_pct)

            if i < min_bars:
                continue

            # Look up pre-computed indicators for this bar (O(1) dict lookup)
            ind_df = symbol_ind.get(sym)
            if ind_df is None or bar_date not in ind_df.index:
                continue
            ind_row = ind_df.loc[bar_date]
            if ind_row.isna().any():
                continue
            indicators = ind_row.to_dict()

            try:
                (action, tier, pos_pct, stop_pct, tp_pct,
                 partial_exit_pct, runner_trail_pct) = _paper_signal(indicators, asset_class)
            except Exception as exc:
                log.debug("Signal error %s %s: %s", sym, date_str, exc)
                continue

            if action == "BUY" and tier != "COLD":
                if market_regime_filter and not market_is_up:
                    continue

                next_idx = i + 1
                if next_idx < len(dates):
                    next_date = dates[next_idx]
                    entry_price = (
                        float(df.loc[next_date, "Open"]) if next_date in df.index else close
                    )
                else:
                    entry_price = close

                sim.try_open(
                    sym, asset_class, entry_price, pos_pct, stop_pct, tp_pct,
                    date_str, tier,
                    partial_exit_pct=partial_exit_pct,
                    runner_trail_pct=runner_trail_pct,
                    bar_idx=i,
                )

            elif action == "SELL" and sym in sim._open:
                sim.close_on_signal(sym, close, date_str)

        sim.mark_equity(date_str, bar_prices)

    last_date_str = str(dates[-1].date() if hasattr(dates[-1], "date") else dates[-1])
    last_prices   = {s: float(df.iloc[-1]["Close"]) for s, df in traded_ohlcv.items() if not df.empty}
    sim.close_all(last_prices, last_date_str)

    # ── Performance metrics ───────────────────────────────────────────────────
    all_trades = sim._closed
    total      = len(all_trades)
    wins       = [t for t in all_trades if t.pnl > 0]
    losses     = [t for t in all_trades if t.pnl <= 0]

    partial_exits  = [t for t in all_trades if t.exit_reason == "partial_profit"]
    runner_exits   = [t for t in all_trades if t.exit_reason == "stop_loss" and t.layer1_fired]
    bracket_tps    = [t for t in all_trades if t.exit_reason == "take_profit"]
    pre_layer1_sls = [t for t in all_trades if t.exit_reason == "stop_loss" and not t.layer1_fired]

    final_equity   = sim._cash
    total_ret_pct  = (final_equity / initial_equity - 1) * 100
    ann_ret_pct    = ((final_equity / initial_equity) ** (1 / max(years, 1)) - 1) * 100

    avg_win   = sum(t.pnl_pct for t in wins)   / max(len(wins),   1)
    avg_loss  = sum(t.pnl_pct for t in losses) / max(len(losses), 1)
    gross_profit = sum(t.pnl for t in wins)
    gross_loss   = abs(sum(t.pnl for t in losses))
    profit_factor = gross_profit / max(gross_loss, 0.01)

    if len(sim._equity_curve) > 1:
        eq_s       = pd.Series([e["equity"] for e in sim._equity_curve])
        daily_rets = eq_s.pct_change().dropna()
        sharpe     = float(daily_rets.mean() / daily_rets.std() * 252 ** 0.5) if daily_rets.std() > 0 else 0.0
    else:
        sharpe = 0.0

    return BacktestResult(
        start_date=str(start_dt), end_date=str(end_dt),
        initial_equity=initial_equity, final_equity=round(final_equity, 2),
        total_return_pct=round(total_ret_pct, 2),
        annualised_return_pct=round(ann_ret_pct, 2),
        benchmark_return_pct=spy_return_pct,
        max_drawdown_pct=sim.max_drawdown(),
        sharpe_ratio=round(sharpe, 3),
        win_rate_pct=round(len(wins) / max(total, 1) * 100, 1),
        total_trades=total, winning_trades=len(wins), losing_trades=len(losses),
        partial_profit_exits=len(partial_exits),
        runner_exits=len(runner_exits),
        bracket_tp_exits=len(bracket_tps),
        stop_loss_exits=len(pre_layer1_sls),
        avg_win_pct=round(avg_win, 2), avg_loss_pct=round(avg_loss, 2),
        profit_factor=round(profit_factor, 2),
        max_concurrent_positions=max_concurrent_positions,
        max_exposure_pct=max_portfolio_exposure,
        market_regime_filter=market_regime_filter,
        symbols_traded=list({t.symbol for t in all_trades}),
        trades=all_trades, equity_curve=sim._equity_curve,
    )


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Trading-Agent backtesting harness")
    p.add_argument("--symbols",       nargs="+", default=["all_stocks"])
    p.add_argument("--years",         type=int,   default=3)
    p.add_argument("--equity",        type=float, default=100_000.0)
    p.add_argument("--max-pos",       type=float, default=0.05)
    p.add_argument("--max-positions", type=int,   default=15)
    p.add_argument("--max-exposure",  type=float, default=0.50)
    p.add_argument("--no-market-filter", action="store_true")
    p.add_argument("--out",     type=str, default="")
    p.add_argument("--trades",  type=str, default="")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s — %(message)s",
    )

    raw_syms = args.symbols
    symbols: list[str] = []
    for s in raw_syms:
        if s == "all_stocks":
            symbols.extend(STOCK_WATCHLIST)
        elif s == "all_etfs":
            symbols.extend(ETF_WATCHLIST)
        elif s == "all_crypto":
            symbols.extend(CRYPTO_WATCHLIST)
        else:
            symbols.append(s.upper())
    symbols = list(dict.fromkeys(symbols))

    asset_class = "crypto" if all(s.endswith("USD") for s in symbols) else "stock"
    use_mf      = not args.no_market_filter

    log.info("Running %d-year backtest on %d symbols (Asymmetric Exit Framework)",
             args.years, len(symbols))

    r = run_backtest(
        symbols=symbols, asset_class=asset_class, years=args.years,
        initial_equity=args.equity, max_position_pct=args.max_pos,
        max_concurrent_positions=args.max_positions,
        max_portfolio_exposure=args.max_exposure,
        market_regime_filter=use_mf,
    )

    ann_spy = r.benchmark_return_pct / args.years
    alpha   = r.annualised_return_pct - ann_spy

    print("\n" + "=" * 68)
    print("BACKTEST SUMMARY — Asymmetric Exit Framework")
    print("=" * 68)
    print(f"Period            : {r.start_date} → {r.end_date} ({args.years}y)")
    print(f"Universe          : {len(symbols)} symbols")
    print(f"Controls          : max {r.max_concurrent_positions} positions · "
          f"≤{r.max_exposure_pct*100:.0f}% exposure · "
          f"market-filter={'ON' if r.market_regime_filter else 'OFF'}")
    print("-" * 68)
    print(f"Initial equity    : ${r.initial_equity:,.2f}")
    print(f"Final equity      : ${r.final_equity:,.2f}")
    print(f"Total return      : {r.total_return_pct:+.2f}%")
    print(f"Ann. return       : {r.annualised_return_pct:+.2f}%")
    print(f"SPY benchmark     : {r.benchmark_return_pct:+.2f}%  "
          f"(ann: {ann_spy:+.2f}%/yr)")
    print(f"Alpha vs SPY      : {alpha:+.2f}%/yr")
    print(f"Max drawdown      : {r.max_drawdown_pct:.2f}%")
    print(f"Sharpe ratio      : {r.sharpe_ratio:.3f}")
    print(f"Win rate          : {r.win_rate_pct:.1f}%  "
          f"({r.winning_trades}W / {r.losing_trades}L)")
    print(f"Avg win           : {r.avg_win_pct:+.2f}%")
    print(f"Avg loss          : {r.avg_loss_pct:+.2f}%")
    print(f"Profit factor     : {r.profit_factor:.2f}")
    print(f"Total trades      : {r.total_trades}")
    print("-" * 68)
    print(f"Exit breakdown:")
    print(f"  Layer 1 partial profits : {r.partial_profit_exits:4d}  (40–50% at first TP)")
    print(f"  Runner stop exits       : {r.runner_exits:4d}  (trailing stop after Layer 1)")
    print(f"  Bracket TP exits        : {r.bracket_tp_exits:4d}  (bracket-only full exit)")
    print(f"  Stop-loss exits (pre-L1): {r.stop_loss_exits:4d}  (hard stop before TP)")
    print("=" * 68)

    if args.out:
        rd = asdict(r)
        rd.pop("trades", None)
        rd.pop("equity_curve", None)
        with open(args.out, "w") as f:
            json.dump(rd, f, indent=2)
        log.info("Summary → %s", args.out)

    if args.trades and r.trades:
        pd.DataFrame([asdict(t) for t in r.trades]).to_csv(args.trades, index=False)
        log.info("Trades  → %s (%d rows)", args.trades, len(r.trades))


if __name__ == "__main__":
    main()
