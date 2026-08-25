"""
Trading Agent Diagnostic Script
================================
Run this on Railway via the shell console, or locally if you export:
  export ALPACA_API_KEY=...
  export ALPACA_SECRET_KEY=...
  export ALPACA_BASE_URL=https://paper-api.alpaca.markets   (or live URL)

Output: complete factual state of the account — positions, recent orders,
P&L, and how many times each symbol was entered/stopped-out.
"""
import os
import sys
from datetime import datetime, timezone, timedelta
from collections import defaultdict

# ── Load credentials ──────────────────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

API_KEY    = os.environ.get("ALPACA_API_KEY", "")
SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY", "")
BASE_URL   = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

if not API_KEY or not SECRET_KEY:
    print("ERROR: ALPACA_API_KEY and ALPACA_SECRET_KEY must be set as environment variables.")
    sys.exit(1)

IS_PAPER = "paper" in BASE_URL.lower()
print(f"\n{'='*60}")
print(f"  TRADING AGENT DIAGNOSTIC — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
print(f"  Account type: {'PAPER' if IS_PAPER else 'LIVE'}")
print(f"{'='*60}\n")

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOrdersRequest
from alpaca.trading.enums import QueryOrderStatus, OrderSide, OrderType

client = TradingClient(API_KEY, SECRET_KEY, paper=IS_PAPER)

# ── 1. Account summary ────────────────────────────────────────────────────────
print("── ACCOUNT ──────────────────────────────────────────────────")
acct = client.get_account()
equity      = float(acct.equity or 0)
cash        = float(acct.cash or 0)
last_equity = float(acct.last_equity or equity)
buying_power = float(acct.buying_power or 0)
day_pl      = float(acct.equity) - float(acct.last_equity) if acct.last_equity else 0
total_pl    = float(acct.equity) - float(acct.initial_capital or acct.equity)

print(f"  Equity:           ${equity:,.2f}")
print(f"  Cash:             ${cash:,.2f}")
print(f"  Buying power:     ${buying_power:,.2f}")
print(f"  Today's P&L:      ${day_pl:+,.2f}  ({day_pl/max(last_equity,1)*100:+.2f}%)")
try:
    initial = float(acct.initial_capital)
    print(f"  Initial capital:  ${initial:,.2f}")
    print(f"  Total P&L:        ${equity - initial:+,.2f}  ({(equity-initial)/max(initial,1)*100:+.2f}%)")
except Exception:
    pass
print()

# ── 2. Current open positions ─────────────────────────────────────────────────
print("── OPEN POSITIONS ───────────────────────────────────────────")
positions = client.get_all_positions()
if not positions:
    print("  No open positions.")
else:
    total_unrealized = 0.0
    for pos in sorted(positions, key=lambda p: float(p.unrealized_pl or 0)):
        sym      = pos.symbol
        qty      = float(pos.qty or 0)
        avg_entry = float(pos.avg_entry_price or 0)
        cur_price = float(pos.current_price or 0)
        unreal_pl = float(pos.unrealized_pl or 0)
        unreal_pct = float(pos.unrealized_plpc or 0) * 100
        mkt_val   = float(pos.market_value or 0)
        total_unrealized += unreal_pl
        flag = "  ⚠️ " if unreal_pct <= -2.0 else "  ✅ " if unreal_pct >= 2.0 else "     "
        print(f"{flag}{sym:8s}  qty={qty:.2f}  entry=${avg_entry:.2f}  now=${cur_price:.2f}"
              f"  P&L=${unreal_pl:+.2f} ({unreal_pct:+.1f}%)  val=${mkt_val:.2f}")
    print(f"\n  Total unrealized P&L: ${total_unrealized:+,.2f}")
print()

# ── 3. Orders from the last 7 days ────────────────────────────────────────────
print("── ORDERS (last 7 days, all statuses) ───────────────────────")
since = datetime.now(timezone.utc) - timedelta(days=7)

try:
    all_orders = client.get_orders(
        filter=GetOrdersRequest(status=QueryOrderStatus.ALL, limit=500, after=since)
    )
except Exception as e:
    print(f"  Could not fetch orders: {e}")
    all_orders = []

# Categorise
buys      = [o for o in all_orders if o.side == OrderSide.BUY   and o.status.value == "filled"]
sells     = [o for o in all_orders if o.side == OrderSide.SELL  and o.status.value == "filled"]
stops     = [o for o in all_orders if o.order_type in (OrderType.STOP, OrderType.STOP_LIMIT) and o.status.value == "filled"]
cancelled = [o for o in all_orders if o.status.value in ("canceled", "expired")]

print(f"  Total orders last 7d:  {len(all_orders)}")
print(f"  Filled BUY entries:    {len(buys)}")
print(f"  Filled SELL exits:     {len(sells)}")
print(f"  Stop-loss fills:       {len(stops)}")
print(f"  Cancelled / expired:   {len(cancelled)}")
print()

# Per-symbol entry count (re-entries = re-buying same symbol)
entry_count: dict[str, int] = defaultdict(int)
stop_count:  dict[str, int] = defaultdict(int)
realized_pl: dict[str, float] = defaultdict(float)

for o in buys:
    entry_count[o.symbol] += 1

for o in stops:
    stop_count[o.symbol] += 1
    if o.filled_avg_price and o.qty:
        # Approximation: stop fill price × qty (negative because it's a loss exit)
        realized_pl[o.symbol] -= float(o.filled_avg_price) * float(o.qty)

print("── RE-ENTRY ANALYSIS (symbols entered more than once) ───────")
repeated = {sym: cnt for sym, cnt in entry_count.items() if cnt > 1}
if not repeated:
    print("  No symbol was entered more than once in the last 7 days.")
else:
    for sym, cnt in sorted(repeated.items(), key=lambda x: -x[1]):
        stops_for = stop_count.get(sym, 0)
        print(f"  {sym:8s}  entered {cnt}x  stop-outs {stops_for}x"
              + (f"  ← REPEATEDLY STOPPED OUT" if stops_for >= 2 else ""))
print()

# ── 4. Stop-loss fills detail ─────────────────────────────────────────────────
print("── STOP-LOSS FILLS DETAIL ───────────────────────────────────")
if not stops:
    print("  No stop-loss fills in the last 7 days.")
else:
    for o in sorted(stops, key=lambda x: x.filled_at or datetime.min.replace(tzinfo=timezone.utc)):
        ts   = o.filled_at.strftime("%m/%d %H:%M") if o.filled_at else "unknown"
        prc  = f"${float(o.filled_avg_price):.2f}" if o.filled_avg_price else "n/a"
        qty  = float(o.qty or 0)
        print(f"  {ts}  {o.symbol:8s}  stop-fill @ {prc}  qty={qty:.2f}")
print()

# ── 5. All filled BUYs in last 7 days ────────────────────────────────────────
print("── ALL FILLED BUY ENTRIES (last 7 days) ─────────────────────")
if not buys:
    print("  No filled buy entries.")
else:
    for o in sorted(buys, key=lambda x: x.filled_at or datetime.min.replace(tzinfo=timezone.utc)):
        ts  = o.filled_at.strftime("%m/%d %H:%M") if o.filled_at else "unknown"
        prc = f"${float(o.filled_avg_price):.2f}" if o.filled_avg_price else "n/a"
        qty = float(o.qty or 0)
        typ = str(o.order_class) if hasattr(o, "order_class") else str(o.order_type)
        print(f"  {ts}  {o.symbol:8s}  entry @ {prc}  qty={qty:.2f}  class={typ}")
print()

# ── 6. Summary verdict ────────────────────────────────────────────────────────
print("── SUMMARY ──────────────────────────────────────────────────")
if repeated:
    max_re  = max(repeated.values())
    worst   = max(repeated, key=lambda s: repeated[s])
    print(f"  Highest re-entry:  {worst} entered {max_re}x in 7 days")
if stops:
    print(f"  Total stop-outs:   {len(stops)} fills")
    worst_stop = max(stop_count, key=lambda s: stop_count[s]) if stop_count else None
    if worst_stop:
        print(f"  Most stopped-out:  {worst_stop} ({stop_count[worst_stop]}x)")
unrealized_total = sum(float(p.unrealized_pl or 0) for p in positions)
print(f"  Current unrealized P&L on open positions: ${unrealized_total:+,.2f}")
print()
print("  Paste this full output and share it for a real diagnosis.")
print(f"{'='*60}\n")
