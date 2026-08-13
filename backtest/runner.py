"""Paper-mode backtesting harness.

Replays historical OHLCV data through the same rule-based signal engine used
in production paper mode.  Does NOT call the LLM — uses deterministic rules
so the result is reproducible and fast (no API cost).

Usage:
    python -m backtest.runner --symbols AAPL MSFT NVDA --years 3 --equity 100000
    python -m backtest.runner --symbols all_stocks --years 3
    python -m backtest.runner --symbols all_stocks all_etfs --years 3 --hot-only

Output: JSON summary + optional CSV trade log.

Algorithm:
  1. Download daily OHLCV for each symbol via yfinance (adjusted for splits/divs).
  2. Download SPY separately to build a market-regime filter (price vs 200-day SMA).
  3. Replay bar-by-bar, computing indicators on a 250-bar rolling window.
  4. Call the same rule-based signal functions used in paper mode (imported from debate.py).
  5. Gate each BUY signal through:
       a. Market regime filter: SPY must be above its 200-day SMA.
       b. Portfolio exposure cap: total deployed ≤ max_exposure_pct of equity.
       c. Max concurrent positions: hard cap on simultaneous open trades.
  6. Simulate bracket execution: entry at next-bar open, stop-loss and take-profit
     child orders active until hit or next signal.
  7. Track portfolio equity (cash + mark-to-market), drawdown, win rate, P&L.
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

# Add project root to path so we can import brain/watchlist
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
    exit_reason: Literal["take_profit", "stop_loss", "signal_sell", "end_of_period"]
    stop_price: float
    take_profit_price: float
    tier: str = "WARM"


@dataclass
class BacktestResult:
    start_date: str
    end_date: str
    initial_equity: float
    final_equity: float
    total_return_pct: float
    annualised_return_pct: float
    benchmark_return_pct: float          # SPY buy-and-hold over same period
    max_drawdown_pct: float
    sharpe_ratio: float
    win_rate_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float
    max_concurrent_positions: int
    max_exposure_pct: float
    market_regime_filter: bool
    hot_only: bool
    symbols_traded: list[str]
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)


# ── Indicator computation (mirrors debate.py paper-mode logic) ────────────────

def _compute_indicators(closes: list[float], highs: list[float], lows: list[float],
                        volumes: list[float]) -> dict:
    """Compute the same indicator set used in paper-mode debate.py."""
    import ta
    if len(closes) < 20:
        return {}

    c = pd.Series(closes)
    h = pd.Series(highs)
    l = pd.Series(lows)
    v = pd.Series(volumes)

    price  = closes[-1]
    sma20  = float(c.rolling(20).mean().iloc[-1]) if len(closes) >= 20  else price
    sma50  = float(c.rolling(50).mean().iloc[-1]) if len(closes) >= 50  else price
    sma200 = float(c.rolling(200).mean().iloc[-1]) if len(closes) >= 200 else price

    rsi    = ta.momentum.RSIIndicator(c, window=14).rsi()
    rsi14  = float(rsi.iloc[-1]) if not rsi.empty else 50.0

    macd_ind = ta.trend.MACD(c)
    macd_val = float(macd_ind.macd().iloc[-1]) if not macd_ind.macd().empty else 0.0
    macd_sig = float(macd_ind.macd_signal().iloc[-1]) if not macd_ind.macd_signal().empty else 0.0

    atr_s  = ta.volatility.AverageTrueRange(h, l, c, window=14).average_true_range()
    atr14  = float(atr_s.iloc[-1]) if not atr_s.empty else 0.0

    bb     = ta.volatility.BollingerBands(c, window=20)
    bb_upper = float(bb.bollinger_hband().iloc[-1])
    bb_lower = float(bb.bollinger_lband().iloc[-1])

    vol_avg   = float(v.rolling(20).mean().iloc[-1]) if len(closes) >= 20 else float(v.mean())
    vol_ratio = float(v.iloc[-1]) / max(vol_avg, 1)

    roc5  = (closes[-1] / closes[-6]  - 1) * 100 if len(closes) > 5  else 0.0
    roc10 = (closes[-1] / closes[-11] - 1) * 100 if len(closes) > 10 else 0.0
    roc20 = (closes[-1] / closes[-21] - 1) * 100 if len(closes) > 20 else 0.0
    roc60 = (closes[-1] / closes[-61] - 1) * 100 if len(closes) > 60 else 0.0

    high52w  = max(highs[-252:]) if len(highs) >= 252 else max(highs)
    low52w   = min(lows[-252:])  if len(lows)  >= 252 else min(lows)
    high_prox = (price / max(high52w, 1e-9)) - 1
    low_prox  = (price / max(low52w,  1e-9)) - 1

    return {
        "price": price, "sma_20": sma20, "sma_50": sma50, "sma_200": sma200,
        "rsi_14": rsi14, "macd": macd_val, "macd_signal": macd_sig,
        "atr_14": atr14, "bb_upper": bb_upper, "bb_lower": bb_lower,
        "volume_ratio": vol_ratio, "roc_5": roc5, "roc_10": roc10,
        "roc_20": roc20, "roc_60": roc60,
        "high_proximity": high_prox, "low_proximity": low_prox,
        "bb_width": (bb_upper - bb_lower) / max(price, 1e-9),
        "stoch_k": 50.0, "stoch_d": 50.0,
    }


# ── Signal generation (paper-mode rules, no LLM) ─────────────────────────────

def _paper_signal(indicators: dict, asset_class: str) -> tuple[str, str, float, float, float]:
    """Return (action, tier, position_pct, stop_loss_pct, take_profit_pct)."""
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
        "regime":         regime_view,
        "technical":      _paper_technical(indicators),
        "quant":          _paper_quant(indicators),
        "fundamental":    _paper_fundamental(indicators),
        "sentiment":      _paper_sentiment(indicators),
        "options_flow":   _paper_options_flow(indicators),
        "macro":          _paper_macro(indicators),
        "breakout":       _paper_breakout(indicators),
        "trend_strength": _paper_trend_strength(indicators),
        "sector_rotation":_paper_sector_rotation(indicators),
        "earnings_event": _paper_earnings_event(indicators),
        "momentum_scorer":_paper_momentum_scorer(indicators),
        "supply_demand":  _paper_supply_demand(indicators),
        "volume_analyst": _paper_volume_analyst(indicators),
        "risk_reward":    _paper_risk_reward(indicators),
    }
    inv_views: dict[str, str] = {
        "buffett":       _paper_investor_buffett(indicators),
        "munger":        _paper_investor_munger(indicators),
        "lynch":         _paper_investor_lynch(indicators),
        "ackman":        _paper_investor_ackman(indicators),
        "cohen":         _paper_investor_cohen(indicators),
        "dalio":         _paper_investor_dalio(indicators),
        "wood":          _paper_investor_wood(indicators),
        "bogle":         _paper_investor_bogle(indicators),
        "soros":         _paper_investor_soros(indicators),
        "druckenmiller": _paper_investor_druckenmiller(indicators),
        "simons":        _paper_investor_simons(indicators),
        "templeton":     _paper_investor_templeton(indicators),
    }

    a_tally, b_tally, combined, conflict, conflict_note, b_abstaining = _aggregate_dual_panel(
        views, inv_views, asset_class,
    )
    action = _action_from_votes(combined, conflict, threshold=WARM_MIN_VOTES)
    tier   = _compute_tier(combined, action, regime_label, indicators,
                           panels_conflict=conflict, b_abstaining=b_abstaining)

    # ATR-primary risk params (Phase 1-B sizing)
    price   = float(indicators.get("price", 1.0))
    atr14   = float(indicators.get("atr_14", 0.0))
    atr_pct = atr14 / max(price, 1e-9)
    stop_pct = max(0.005, min(0.04, 1.5 * atr_pct))

    # Regime-adaptive take-profit (Phase 3-B)
    if "TRENDING_UP" in regime_label:
        tp_pct = 0.08
    elif "RANGING" in regime_label:
        tp_pct = 0.03
    else:
        tp_pct = 0.05

    # HOT signals get 8% position, WARM gets 5% — rewards conviction
    pos_pct = 0.08 if tier == "HOT" else 0.05

    return action, tier, pos_pct, stop_pct, tp_pct


# ── Portfolio simulation ──────────────────────────────────────────────────────

class PortfolioSimulator:
    """
    Tracks cash and open positions separately so mark_equity never
    double-counts invested capital (the original single-equity bug caused
    phantom 70%+ drawdowns).
    """
    def __init__(
        self,
        initial_equity: float = 100_000.0,
        max_position_pct: float = 0.05,
        max_concurrent: int = 15,
        max_exposure_pct: float = 0.50,
    ) -> None:
        self._initial        = initial_equity
        self._cash           = initial_equity
        self._max_pos        = max_position_pct
        self._max_concurrent = max_concurrent
        self._max_exposure   = max_exposure_pct
        self._open: dict[str, Trade]   = {}
        self._closed: list[Trade]      = []
        self._equity_curve: list[dict] = []
        self._peak = initial_equity

    @property
    def equity(self) -> float:
        """Cash + open position cost basis (not mark-to-market; use mark_equity for that)."""
        invested = sum(t.qty * t.entry_price for t in self._open.values())
        return self._cash + invested

    def mark_equity(self, date_str: str, prices: dict[str, float]) -> None:
        """Revalue portfolio mark-to-market at end of bar."""
        open_val = sum(
            t.qty * prices.get(t.symbol, t.entry_price) for t in self._open.values()
        )
        total = self._cash + open_val
        self._equity_curve.append({"date": date_str, "equity": round(total, 2)})
        if total > self._peak:
            self._peak = total

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
    ) -> bool:
        if symbol in self._open:
            return False

        # Max concurrent positions gate
        if len(self._open) >= self._max_concurrent:
            return False

        # Portfolio exposure cap gate
        invested = sum(t.qty * t.entry_price for t in self._open.values())
        if invested / max(self._initial, 1) >= self._max_exposure:
            return False

        # Size based on initial equity so positions don't shrink as cash dwindles
        notional = self._initial * min(pos_pct, self._max_pos)
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
            stop_price=stop_price, take_profit_price=tp_price, tier=tier,
        )
        self._cash -= notional
        return True

    def check_exits(self, symbol: str, high: float, low: float,
                    date_str: str) -> Trade | None:
        """Check if stop-loss or take-profit was hit during the bar."""
        trade = self._open.get(symbol)
        if not trade:
            return None
        hit_tp = high >= trade.take_profit_price
        hit_sl = low  <= trade.stop_price
        if hit_tp or hit_sl:
            exit_price  = trade.take_profit_price if hit_tp else trade.stop_price
            exit_reason = "take_profit" if hit_tp else "stop_loss"
            return self._close(symbol, exit_price, date_str, exit_reason)
        return None

    def close_on_signal(self, symbol: str, price: float, date_str: str) -> Trade | None:
        if symbol not in self._open:
            return None
        return self._close(symbol, price, date_str, "signal_sell")

    def _close(self, symbol: str, exit_price: float, date_str: str, reason: str) -> Trade:
        trade = self._open.pop(symbol)
        trade.exit_date  = date_str
        trade.exit_price = exit_price
        pnl     = (exit_price - trade.entry_price) * trade.qty
        pnl_pct = (exit_price / trade.entry_price - 1) * 100
        trade.pnl         = round(pnl, 2)
        trade.pnl_pct     = round(pnl_pct, 2)
        trade.exit_reason = reason  # type: ignore[assignment]
        self._cash += trade.qty * exit_price
        self._closed.append(trade)
        return trade

    def close_all(self, prices: dict[str, float], date_str: str) -> None:
        for sym in list(self._open.keys()):
            price = prices.get(sym, self._open[sym].entry_price)
            self._close(sym, price, date_str, "end_of_period")

    def max_drawdown(self) -> float:
        if not self._equity_curve:
            return 0.0
        equities = [e["equity"] for e in self._equity_curve]
        peak = equities[0]
        max_dd = 0.0
        for e in equities:
            if e > peak:
                peak = e
            dd = (peak - e) / peak * 100
            max_dd = max(max_dd, dd)
        return round(max_dd, 2)


# ── Main backtest loop ────────────────────────────────────────────────────────

def run_backtest(
    symbols: list[str],
    asset_class: str = "stock",
    years: int = 3,
    initial_equity: float = 100_000.0,
    max_position_pct: float = 0.05,
    max_concurrent_positions: int = 15,
    max_portfolio_exposure: float = 0.50,
    market_regime_filter: bool = True,
    hot_only: bool = False,
    min_bars: int = 60,
) -> BacktestResult:
    end_dt   = date.today()
    start_dt = date(end_dt.year - years, end_dt.month, end_dt.day)

    # Always download SPY alongside traded symbols for the market regime gate
    spy_only = "SPY" not in symbols
    download_syms = list(dict.fromkeys(symbols + ["SPY"]))  # deduplicated, SPY last if new

    log.info(
        "Downloading %d symbols (%d traded + SPY regime ref) from %s to %s …",
        len(download_syms), len(symbols), start_dt, end_dt,
    )
    raw = yf.download(
        download_syms, start=str(start_dt), end=str(end_dt),
        progress=False, auto_adjust=True, threads=True,
    )

    # Build per-symbol OHLCV dict
    if len(download_syms) == 1:
        sym = download_syms[0]
        ohlcv: dict[str, pd.DataFrame] = {sym: raw}
    else:
        ohlcv = {}
        for sym in download_syms:
            try:
                df = pd.DataFrame({
                    "Open":   raw["Open"][sym],
                    "High":   raw["High"][sym],
                    "Low":    raw["Low"][sym],
                    "Close":  raw["Close"][sym],
                    "Volume": raw["Volume"][sym],
                }).dropna()
                if not df.empty:
                    ohlcv[sym] = df
            except KeyError:
                log.warning("No data for %s", sym)

    # ── SPY market regime series: True = market is above its 200-day SMA ──────
    spy_up: dict[str, bool] = {}
    spy_return_pct = 0.0
    if "SPY" in ohlcv:
        spy_df     = ohlcv["SPY"]
        spy_closes = spy_df["Close"]
        sma200_s   = spy_closes.rolling(200).mean()
        for dt_idx in spy_closes.index:
            key = str(dt_idx.date() if hasattr(dt_idx, "date") else dt_idx)
            sma = sma200_s.get(dt_idx, float("nan"))
            spy_up[key] = (not pd.isna(sma)) and (float(spy_closes[dt_idx]) > float(sma))
        # SPY buy-and-hold return for benchmark comparison
        spy_first = float(spy_closes.iloc[0])
        spy_last  = float(spy_closes.iloc[-1])
        spy_return_pct = round((spy_last / spy_first - 1) * 100, 2)

    # Common date index across all traded symbols (not SPY-only symbols)
    traded_ohlcv = {s: df for s, df in ohlcv.items() if s in symbols}
    if not traded_ohlcv:
        raise ValueError("No price data downloaded for any traded symbol.")

    closes_union = pd.concat(
        {s: df["Close"] for s, df in traded_ohlcv.items()}, axis=1
    ).ffill()
    dates = closes_union.index.tolist()

    sim = PortfolioSimulator(
        initial_equity=initial_equity,
        max_position_pct=max_position_pct,
        max_concurrent=max_concurrent_positions,
        max_exposure_pct=max_portfolio_exposure,
    )

    for i, bar_date in enumerate(dates):
        date_str   = str(bar_date.date() if hasattr(bar_date, "date") else bar_date)
        bar_prices: dict[str, float] = {}
        market_is_up = spy_up.get(date_str, True)  # default True when SMA not yet valid

        for sym, df in traded_ohlcv.items():
            if bar_date not in df.index:
                continue
            row   = df.loc[bar_date]
            close = float(row["Close"])
            high  = float(row["High"])
            low   = float(row["Low"])
            bar_prices[sym] = close

            # Check bracket exits on today's high/low range
            closed_trade = sim.check_exits(sym, high, low, date_str)
            if closed_trade:
                log.debug(
                    "  %s %s → %s  pnl=%.2f (%.1f%%)",
                    date_str, sym, closed_trade.exit_reason,
                    closed_trade.pnl, closed_trade.pnl_pct,
                )

            if i < min_bars:
                continue

            start_i = max(0, i - 250)
            sym_df  = df.iloc[start_i:i + 1]
            closes  = sym_df["Close"].tolist()
            highs   = sym_df["High"].tolist()
            lows    = sym_df["Low"].tolist()
            volumes = sym_df["Volume"].tolist()

            if len(closes) < 20:
                continue

            indicators = _compute_indicators(closes, highs, lows, volumes)
            if not indicators:
                continue

            try:
                action, tier, pos_pct, stop_pct, tp_pct = _paper_signal(indicators, asset_class)
            except Exception as exc:
                log.debug("Signal error for %s on %s: %s", sym, date_str, exc)
                continue

            if action == "BUY" and tier != "COLD":
                # Gate 1 — market regime: no longs when SPY is below its 200-day SMA
                if market_regime_filter and not market_is_up:
                    continue
                # Gate 2 — hot-only mode: skip WARM signals when flag is set
                if hot_only and tier != "HOT":
                    continue

                # Enter at next-bar open (more realistic than current close)
                next_idx = i + 1
                if next_idx < len(dates):
                    next_date = dates[next_idx]
                    entry_price = (
                        float(df.loc[next_date, "Open"]) if next_date in df.index else close
                    )
                else:
                    entry_price = close

                sim.try_open(sym, asset_class, entry_price, pos_pct, stop_pct, tp_pct,
                             date_str, tier)

            elif action == "SELL" and sym in sim._open:
                sim.close_on_signal(sym, close, date_str)

        sim.mark_equity(date_str, bar_prices)

    # Close remaining open positions at last bar price
    last_prices = {
        sym: float(df.iloc[-1]["Close"]) for sym, df in traded_ohlcv.items() if not df.empty
    }
    sim.close_all(last_prices, str(dates[-1].date() if hasattr(dates[-1], "date") else dates[-1]))

    # ── Performance metrics ───────────────────────────────────────────────────
    all_trades = sim._closed
    total  = len(all_trades)
    wins   = [t for t in all_trades if t.pnl > 0]
    losses = [t for t in all_trades if t.pnl <= 0]

    final_equity  = sim._cash   # all positions closed, cash = total portfolio value
    total_ret_pct = (final_equity / initial_equity - 1) * 100
    ann_ret_pct   = ((final_equity / initial_equity) ** (1 / max(years, 1)) - 1) * 100

    avg_win  = sum(t.pnl_pct for t in wins)   / max(len(wins),   1)
    avg_loss = sum(t.pnl_pct for t in losses) / max(len(losses), 1)
    gross_profit = sum(t.pnl for t in wins)
    gross_loss   = abs(sum(t.pnl for t in losses))
    profit_factor = gross_profit / max(gross_loss, 0.01)

    if len(sim._equity_curve) > 1:
        eq_series  = pd.Series([e["equity"] for e in sim._equity_curve])
        daily_rets = eq_series.pct_change().dropna()
        sharpe = float(
            daily_rets.mean() / daily_rets.std() * (252 ** 0.5)
        ) if daily_rets.std() > 0 else 0.0
    else:
        sharpe = 0.0

    return BacktestResult(
        start_date=str(start_dt),
        end_date=str(end_dt),
        initial_equity=initial_equity,
        final_equity=round(final_equity, 2),
        total_return_pct=round(total_ret_pct, 2),
        annualised_return_pct=round(ann_ret_pct, 2),
        benchmark_return_pct=spy_return_pct,
        max_drawdown_pct=sim.max_drawdown(),
        sharpe_ratio=round(sharpe, 3),
        win_rate_pct=round(len(wins) / max(total, 1) * 100, 1),
        total_trades=total,
        winning_trades=len(wins),
        losing_trades=len(losses),
        avg_win_pct=round(avg_win, 2),
        avg_loss_pct=round(avg_loss, 2),
        profit_factor=round(profit_factor, 2),
        max_concurrent_positions=max_concurrent_positions,
        max_exposure_pct=max_portfolio_exposure,
        market_regime_filter=market_regime_filter,
        hot_only=hot_only,
        symbols_traded=list({t.symbol for t in all_trades}),
        trades=all_trades,
        equity_curve=sim._equity_curve,
    )


# ── CLI entry point ───────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Trading-Agent backtesting harness")
    p.add_argument("--symbols",      nargs="+", default=["all_stocks"],
                   help="Symbols to backtest, or 'all_stocks', 'all_etfs', 'all_crypto'")
    p.add_argument("--years",        type=int,   default=3,         help="Look-back in years")
    p.add_argument("--equity",       type=float, default=100_000.0, help="Starting equity")
    p.add_argument("--max-pos",      type=float, default=0.05,      help="Max position size (fraction)")
    p.add_argument("--max-positions",type=int,   default=15,        help="Max concurrent open positions")
    p.add_argument("--max-exposure", type=float, default=0.50,      help="Max portfolio exposure (fraction)")
    p.add_argument("--no-market-filter", action="store_true",
                   help="Disable the SPY 200-day SMA market regime gate")
    p.add_argument("--hot-only",     action="store_true",
                   help="Only trade HOT tier signals (17+ votes)")
    p.add_argument("--out",          type=str,   default="",        help="Output JSON file path")
    p.add_argument("--trades",       type=str,   default="",        help="Output trades CSV path")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s — %(message)s",
    )

    raw_syms  = args.symbols
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
    symbols = list(dict.fromkeys(symbols))  # dedup preserving order

    asset_class = "crypto" if all(s.endswith("USD") for s in symbols) else "stock"
    use_market_filter = not args.no_market_filter

    log.info(
        "Running %d-year backtest on %d symbols (class=%s, max_pos=%d, exposure=%.0f%%, "
        "market_filter=%s, hot_only=%s)",
        args.years, len(symbols), asset_class, args.max_positions,
        args.max_exposure * 100, use_market_filter, args.hot_only,
    )

    result = run_backtest(
        symbols=symbols,
        asset_class=asset_class,
        years=args.years,
        initial_equity=args.equity,
        max_position_pct=args.max_pos,
        max_concurrent_positions=args.max_positions,
        max_portfolio_exposure=args.max_exposure,
        market_regime_filter=use_market_filter,
        hot_only=args.hot_only,
    )

    alpha = result.annualised_return_pct - (result.benchmark_return_pct / args.years)

    print("\n" + "=" * 65)
    print("BACKTEST SUMMARY")
    print("=" * 65)
    print(f"Period            : {result.start_date} → {result.end_date} ({args.years}y)")
    print(f"Universe          : {len(symbols)} symbols  |  {asset_class}")
    print(f"Controls          : max {result.max_concurrent_positions} positions  |  "
          f"≤{result.max_exposure_pct*100:.0f}% exposure  |  "
          f"market-filter={'ON' if result.market_regime_filter else 'OFF'}  |  "
          f"hot-only={'ON' if result.hot_only else 'OFF'}")
    print("-" * 65)
    print(f"Initial equity    : ${result.initial_equity:,.2f}")
    print(f"Final equity      : ${result.final_equity:,.2f}")
    print(f"Total return      : {result.total_return_pct:+.2f}%")
    print(f"Ann. return       : {result.annualised_return_pct:+.2f}%")
    print(f"SPY benchmark     : {result.benchmark_return_pct:+.2f}%  "
          f"(annualised: {result.benchmark_return_pct/args.years:+.2f}%/yr)")
    print(f"Alpha vs SPY      : {alpha:+.2f}%/yr")
    print(f"Max drawdown      : {result.max_drawdown_pct:.2f}%")
    print(f"Sharpe ratio      : {result.sharpe_ratio:.3f}")
    print(f"Win rate          : {result.win_rate_pct:.1f}%  "
          f"({result.winning_trades}W / {result.losing_trades}L)")
    print(f"Avg win           : {result.avg_win_pct:+.2f}%")
    print(f"Avg loss          : {result.avg_loss_pct:+.2f}%")
    print(f"Profit factor     : {result.profit_factor:.2f}")
    print(f"Total trades      : {result.total_trades}")
    print(f"Symbols traded    : {len(result.symbols_traded)}")
    print("=" * 65)

    if args.out:
        result_dict = asdict(result)
        result_dict.pop("trades", None)
        result_dict.pop("equity_curve", None)
        with open(args.out, "w") as f:
            json.dump(result_dict, f, indent=2)
        log.info("Summary saved to %s", args.out)

    if args.trades and result.trades:
        df = pd.DataFrame([asdict(t) for t in result.trades])
        df.to_csv(args.trades, index=False)
        log.info("Trade log saved to %s (%d rows)", args.trades, len(result.trades))


if __name__ == "__main__":
    main()
