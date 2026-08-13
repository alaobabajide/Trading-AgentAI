"""Paper-mode backtesting harness.

Replays historical OHLCV data through the same rule-based signal engine used
in production paper mode.  Does NOT call the LLM — uses deterministic rules
so the result is reproducible and fast (no API cost).

Usage:
    python -m backtest.runner --symbols AAPL MSFT NVDA --years 3 --equity 100000
    python -m backtest.runner --symbols all_stocks --years 3

Output: JSON summary + optional CSV trade log.

Algorithm:
  1. Download daily OHLCV for each symbol via yfinance (adjusted for splits/divs).
  2. Replay bar-by-bar, computing indicators on a 60-bar rolling window.
  3. Call the same rule-based signal functions used in paper mode (imported from debate.py).
  4. Simulate bracket execution: entry at next-bar open, stop-loss and take-profit
     child orders active until hit or next signal.
  5. Track portfolio equity, drawdown, win rate, and per-symbol P&L.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
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
    max_drawdown_pct: float
    sharpe_ratio: float
    win_rate_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float
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

    price = closes[-1]
    sma20 = float(c.rolling(20).mean().iloc[-1]) if len(closes) >= 20 else price
    sma50 = float(c.rolling(50).mean().iloc[-1]) if len(closes) >= 50 else price
    sma200 = float(c.rolling(200).mean().iloc[-1]) if len(closes) >= 200 else price

    rsi = ta.momentum.RSIIndicator(c, window=14).rsi()
    rsi14 = float(rsi.iloc[-1]) if not rsi.empty else 50.0

    macd_ind = ta.trend.MACD(c)
    macd_val = float(macd_ind.macd().iloc[-1]) if not macd_ind.macd().empty else 0.0
    macd_sig = float(macd_ind.macd_signal().iloc[-1]) if not macd_ind.macd_signal().empty else 0.0

    atr_series = ta.volatility.AverageTrueRange(h, l, c, window=14).average_true_range()
    atr14 = float(atr_series.iloc[-1]) if not atr_series.empty else 0.0

    bb = ta.volatility.BollingerBands(c, window=20)
    bb_upper = float(bb.bollinger_hband().iloc[-1])
    bb_lower = float(bb.bollinger_lband().iloc[-1])

    vol_avg = float(v.rolling(20).mean().iloc[-1]) if len(closes) >= 20 else float(v.mean())
    vol_ratio = float(v.iloc[-1]) / max(vol_avg, 1)

    roc5   = (closes[-1] / closes[-6]  - 1) * 100 if len(closes) > 5  else 0.0
    roc10  = (closes[-1] / closes[-11] - 1) * 100 if len(closes) > 10 else 0.0
    roc20  = (closes[-1] / closes[-21] - 1) * 100 if len(closes) > 20 else 0.0
    roc60  = (closes[-1] / closes[-61] - 1) * 100 if len(closes) > 60 else 0.0

    high52w = max(highs[-252:]) if len(highs) >= 252 else max(highs)
    low52w  = min(lows[-252:])  if len(lows)  >= 252 else min(lows)
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
        "stoch_k": 50.0, "stoch_d": 50.0,  # simplified — stoch needs highs/lows window
    }


# ── Signal generation (paper-mode rules, no LLM) ─────────────────────────────

def _paper_signal(indicators: dict, asset_class: str) -> tuple[str, str, float, float, float]:
    """Return (action, tier, position_pct, stop_loss_pct, take_profit_pct)."""
    # Import paper-mode rule functions from debate.py
    from brain.debate import (
        _paper_technical, _paper_quant, _paper_regime,
        _paper_fundamental, _paper_sentiment, _paper_options_flow,
        _paper_investor_buffett, _paper_investor_munger, _paper_investor_lynch,
        _paper_investor_ackman, _paper_investor_cohen, _paper_investor_dalio,
        _paper_investor_wood, _paper_investor_bogle,
        _paper_investor_soros, _paper_investor_druckenmiller,
        _paper_investor_simons, _paper_investor_templeton,
        _paper_breakout, _paper_trend_strength, _paper_sector_rotation,
        _paper_earnings_event, _paper_momentum_scorer, _paper_supply_demand,
        _paper_volume_analyst, _paper_risk_reward,
        _parse_direction, _compute_panel_tallies, _action_from_votes,
        _compute_tier, _parse_regime_label, HOT_MIN_VOTES, WARM_MIN_VOTES,
    )

    views: dict[str, str] = {}
    # Panel A
    views["technical"]      = _paper_technical(indicators)
    views["quant"]          = _paper_quant(indicators)
    views["fundamental"]    = _paper_fundamental(indicators, asset_class)
    views["sentiment"]      = _paper_sentiment(indicators)
    views["options_flow"]   = _paper_options_flow(indicators)
    views["breakout"]       = _paper_breakout(indicators)
    views["trend_strength"] = _paper_trend_strength(indicators)
    views["sector_rotation"]= _paper_sector_rotation(indicators)
    views["earnings_event"] = _paper_earnings_event(indicators)
    views["momentum_scorer"]= _paper_momentum_scorer(indicators)
    views["supply_demand"]  = _paper_supply_demand(indicators)
    views["volume_analyst"] = _paper_volume_analyst(indicators)
    views["risk_reward"]    = _paper_risk_reward(indicators)

    regime_view = _paper_regime(indicators)
    views["regime"] = regime_view
    regime_label = _parse_regime_label(regime_view)

    # Panel B
    inv_views: dict[str, str] = {
        "buffett": _paper_investor_buffett(indicators),
        "munger":  _paper_investor_munger(indicators),
        "lynch":   _paper_investor_lynch(indicators),
        "ackman":  _paper_investor_ackman(indicators),
        "cohen":   _paper_investor_cohen(indicators),
        "dalio":   _paper_investor_dalio(indicators),
        "wood":    _paper_investor_wood(indicators),
        "bogle":   _paper_investor_bogle(indicators),
        "soros":          _paper_investor_soros(indicators),
        "druckenmiller":  _paper_investor_druckenmiller(indicators),
        "simons":         _paper_investor_simons(indicators),
        "templeton":      _paper_investor_templeton(indicators),
    }

    a_tally, b_tally, combined, conflict, conflict_note, b_abstaining = _compute_panel_tallies(
        views, inv_views, asset_class,
    )

    action = _action_from_votes(combined, conflict)
    tier   = _compute_tier(combined, action, regime_label, indicators,
                           panels_conflict=conflict, b_abstaining=b_abstaining)

    # Simple risk params derived from ATR
    price    = indicators.get("price", 1.0)
    atr14    = indicators.get("atr_14", 0.0)
    atr_pct  = atr14 / max(price, 1e-9)
    stop_pct = max(0.005, min(0.04, 1.5 * atr_pct))
    tp_pct   = 0.05
    if "TRENDING_UP" in regime_label:
        tp_pct = 0.08
    elif "RANGING" in regime_label:
        tp_pct = 0.03
    pos_pct  = 0.05

    return action, tier, pos_pct, stop_pct, tp_pct


# ── Portfolio simulation ──────────────────────────────────────────────────────

class PortfolioSimulator:
    def __init__(self, initial_equity: float = 100_000.0, max_position_pct: float = 0.05) -> None:
        self.equity           = initial_equity
        self._initial_equity  = initial_equity
        self._max_pos         = max_position_pct
        self._open: dict[str, Trade] = {}   # symbol → open trade
        self._closed: list[Trade]    = []
        self._equity_curve: list[dict] = []
        self._peak_equity = initial_equity

    def mark_equity(self, date_str: str, prices: dict[str, float]) -> None:
        """Revalue open positions at end of bar."""
        for sym, trade in self._open.items():
            if sym in prices:
                new_price = prices[sym]
                trade.exit_price = new_price  # live mid
        open_val = sum(
            t.qty * prices.get(t.symbol, t.entry_price) for t in self._open.values()
        )
        cash = self.equity - sum(t.qty * t.entry_price for t in self._open.values())
        total = cash + open_val
        self._equity_curve.append({"date": date_str, "equity": round(total, 2)})
        if total > self._peak_equity:
            self._peak_equity = total

    def try_open(self, symbol: str, asset_class: str, price: float,
                 pos_pct: float, stop_pct: float, tp_pct: float,
                 entry_date: str, tier: str) -> bool:
        if symbol in self._open:
            return False  # already open
        notional = self.equity * min(pos_pct, self._max_pos)
        if notional < 10 or notional > self.equity * 0.99:
            return False
        qty          = notional / price
        stop_price   = price * (1 - stop_pct)
        tp_price     = price * (1 + tp_pct)
        self._open[symbol] = Trade(
            symbol=symbol, asset_class=asset_class, action="BUY",
            entry_date=entry_date, entry_price=price,
            exit_date="", exit_price=0.0,
            qty=qty, pnl=0.0, pnl_pct=0.0,
            exit_reason="end_of_period",
            stop_price=stop_price, take_profit_price=tp_price, tier=tier,
        )
        self.equity -= notional   # reserve the cash
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

    def _close(self, symbol: str, exit_price: float, date_str: str,
               reason: str) -> Trade:
        trade = self._open.pop(symbol)
        trade.exit_date    = date_str
        trade.exit_price   = exit_price
        pnl                = (exit_price - trade.entry_price) * trade.qty
        pnl_pct            = (exit_price / trade.entry_price - 1) * 100
        trade.pnl          = round(pnl, 2)
        trade.pnl_pct      = round(pnl_pct, 2)
        trade.exit_reason  = reason  # type: ignore[assignment]
        self.equity       += trade.qty * exit_price   # return cash at exit price
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
    min_bars: int = 60,        # minimum bars before first signal
) -> BacktestResult:
    end_dt   = date.today()
    start_dt = date(end_dt.year - years, end_dt.month, end_dt.day)

    log.info("Downloading %d symbols from %s to %s …", len(symbols), start_dt, end_dt)
    raw = yf.download(
        symbols, start=str(start_dt), end=str(end_dt),
        progress=False, auto_adjust=True, threads=True,
    )

    # Handle single-symbol vs multi-symbol DataFrame structure
    if len(symbols) == 1:
        sym = symbols[0]
        ohlcv = {sym: raw}
    else:
        ohlcv: dict[str, pd.DataFrame] = {}
        for sym in symbols:
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

    # Align to common index
    closes_union = pd.concat(
        {s: df["Close"] for s, df in ohlcv.items()}, axis=1
    ).ffill()
    dates = closes_union.index.tolist()

    sim = PortfolioSimulator(initial_equity, max_position_pct)

    for i, bar_date in enumerate(dates):
        date_str = str(bar_date.date() if hasattr(bar_date, "date") else bar_date)
        bar_prices: dict[str, float] = {}

        for sym, df in ohlcv.items():
            if bar_date not in df.index:
                continue
            row   = df.loc[bar_date]
            close = float(row["Close"])
            high  = float(row["High"])
            low   = float(row["Low"])
            bar_prices[sym] = close

            # Check bracket exits on today's high/low
            closed_trade = sim.check_exits(sym, high, low, date_str)
            if closed_trade:
                log.debug(
                    "  %s %s → exit=%s pnl=%.2f (%.1f%%)",
                    date_str, sym, closed_trade.exit_reason,
                    closed_trade.pnl, closed_trade.pnl_pct,
                )

            # Skip early bars (insufficient history for indicators)
            if i < min_bars:
                continue

            # Build rolling 60-bar slices
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
                # Use next-bar open price for entry (more realistic)
                next_idx = i + 1
                if next_idx < len(dates):
                    next_date = dates[next_idx]
                    if next_date in df.index:
                        entry_price = float(df.loc[next_date, "Open"])
                    else:
                        entry_price = close
                else:
                    entry_price = close
                sim.try_open(sym, asset_class, entry_price, pos_pct, stop_pct, tp_pct,
                             date_str, tier)

            elif action == "SELL" and sym in sim._open:
                sim.close_on_signal(sym, close, date_str)

        sim.mark_equity(date_str, bar_prices)

    # Close any remaining open positions at last bar price
    last_prices = {
        sym: float(df.iloc[-1]["Close"]) for sym, df in ohlcv.items() if not df.empty
    }
    sim.close_all(last_prices, date_str)

    # ── Performance metrics ───────────────────────────────────────────────────
    all_trades = sim._closed
    total = len(all_trades)
    wins  = [t for t in all_trades if t.pnl > 0]
    losses= [t for t in all_trades if t.pnl <= 0]

    final_equity   = sim.equity
    total_ret_pct  = (final_equity / initial_equity - 1) * 100
    trading_years  = years
    ann_ret_pct    = ((final_equity / initial_equity) ** (1 / max(trading_years, 1)) - 1) * 100

    avg_win   = sum(t.pnl_pct for t in wins)   / max(len(wins),   1)
    avg_loss  = sum(t.pnl_pct for t in losses) / max(len(losses), 1)
    gross_profit = sum(t.pnl for t in wins)
    gross_loss   = abs(sum(t.pnl for t in losses))
    profit_factor = gross_profit / max(gross_loss, 0.01)

    # Sharpe (daily equity curve)
    if len(sim._equity_curve) > 1:
        eq_series = pd.Series([e["equity"] for e in sim._equity_curve])
        daily_rets = eq_series.pct_change().dropna()
        sharpe = float(daily_rets.mean() / daily_rets.std() * (252 ** 0.5)) if daily_rets.std() > 0 else 0.0
    else:
        sharpe = 0.0

    return BacktestResult(
        start_date=str(start_dt),
        end_date=str(end_dt),
        initial_equity=initial_equity,
        final_equity=round(final_equity, 2),
        total_return_pct=round(total_ret_pct, 2),
        annualised_return_pct=round(ann_ret_pct, 2),
        max_drawdown_pct=sim.max_drawdown(),
        sharpe_ratio=round(sharpe, 3),
        win_rate_pct=round(len(wins) / max(total, 1) * 100, 1),
        total_trades=total,
        winning_trades=len(wins),
        losing_trades=len(losses),
        avg_win_pct=round(avg_win, 2),
        avg_loss_pct=round(avg_loss, 2),
        profit_factor=round(profit_factor, 2),
        symbols_traded=list({t.symbol for t in all_trades}),
        trades=all_trades,
        equity_curve=sim._equity_curve,
    )


# ── CLI entry point ───────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Trading-Agent backtesting harness")
    p.add_argument("--symbols", nargs="+", default=["all_stocks"],
                   help="Symbols to backtest, or 'all_stocks', 'all_etfs', 'all_crypto'")
    p.add_argument("--years",   type=int,   default=3,         help="Look-back period in years")
    p.add_argument("--equity",  type=float, default=100_000.0, help="Starting paper equity")
    p.add_argument("--max-pos", type=float, default=0.05,      help="Max position size (fraction)")
    p.add_argument("--out",     type=str,   default="",        help="Output JSON file path")
    p.add_argument("--trades",  type=str,   default="",        help="Output trades CSV path")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s — %(message)s",
    )

    # Expand shorthand symbol lists
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

    asset_class = "crypto" if all(s.endswith("USD") for s in symbols) else "stock"

    log.info("Running %d-year backtest on %d symbols (asset_class=%s)",
             args.years, len(symbols), asset_class)

    result = run_backtest(
        symbols=symbols,
        asset_class=asset_class,
        years=args.years,
        initial_equity=args.equity,
        max_position_pct=args.max_pos,
    )

    # Print summary
    print("\n" + "=" * 60)
    print("BACKTEST SUMMARY")
    print("=" * 60)
    print(f"Period         : {result.start_date} → {result.end_date} ({args.years}y)")
    print(f"Initial equity : ${result.initial_equity:,.2f}")
    print(f"Final equity   : ${result.final_equity:,.2f}")
    print(f"Total return   : {result.total_return_pct:+.2f}%")
    print(f"Ann. return    : {result.annualised_return_pct:+.2f}%  (vs S&P 500 avg ~10%/yr)")
    print(f"Max drawdown   : {result.max_drawdown_pct:.2f}%")
    print(f"Sharpe ratio   : {result.sharpe_ratio:.3f}")
    print(f"Win rate       : {result.win_rate_pct:.1f}%  ({result.winning_trades}W / {result.losing_trades}L)")
    print(f"Avg win        : {result.avg_win_pct:+.2f}%")
    print(f"Avg loss       : {result.avg_loss_pct:+.2f}%")
    print(f"Profit factor  : {result.profit_factor:.2f}")
    print(f"Total trades   : {result.total_trades}")
    print("=" * 60)

    if args.out:
        result_dict = asdict(result)
        result_dict.pop("trades", None)           # trades go in separate CSV
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
