"""Telegram bot — market signals and trade execution.

Commands
--------
/start                           Welcome & status
/help                            Command reference
/signal  SYMBOL stock|crypto     9-agent debate → signal card
/trend   SYMBOL stock|crypto     Alias for /signal
/buy     SYMBOL AMOUNT stock|crypto   Direct buy with confirmation
/sell    SYMBOL AMOUNT stock|crypto   Direct sell with confirmation
/positions                       Open positions + P&L
/health                          System liveness
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from config import get_settings

log = logging.getLogger(__name__)

# Internal FastAPI URL — uvicorn binds here inside the combined container
_BRAIN = "http://127.0.0.1:8000"

_TIER_EMOJI   = {"HOT": "🔥", "WARM": "🌤", "COLD": "🔵"}
_ACTION_EMOJI = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⚪"}
_FIT_EMOJI    = {"ALIGNED": "✅", "PARTIAL": "⚠️", "MISALIGNED": "❌"}
_VIEW_ICON    = {
    "fundamental":  "📈",
    "technical":    "📉",
    "sentiment":    "📰",
    "macro":        "🌍",
    "quant":        "📐",
    "options_flow": "⚡",
    "regime":       "🔄",
    "strategy":     "🎯",
    "risk":         "🛡",
}


# ── Auth ──────────────────────────────────────────────────────────────────────

def _allowed(update: Update) -> bool:
    cfg = get_settings()
    if not cfg.telegram_allowed_ids:
        return True  # open when no whitelist configured
    chat_id = str(update.effective_chat.id)
    return chat_id in [s.strip() for s in cfg.telegram_allowed_ids.split(",")]


# ── Formatters ────────────────────────────────────────────────────────────────

def _fmt_signal(d: dict) -> str:
    action    = d.get("action", "HOLD")
    symbol    = d.get("symbol", "?")
    tier      = d.get("tier", "WARM")
    conf      = d.get("confidence", 0)
    pos_pct   = d.get("suggested_position_pct", 0)
    sl_pct    = d.get("stop_loss_pct", 0)
    tp_pct    = d.get("take_profit_pct", 0)
    rationale = d.get("rationale", "")
    views     = d.get("agent_views", {})
    da_score  = d.get("devil_advocate_score", 0)
    da_case   = d.get("devil_advocate_case", "")
    fit       = d.get("strategy_fit", "ALIGNED")

    lines = [
        f"🧠 <b>TradingAgent — {symbol}</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"{_ACTION_EMOJI.get(action, '⚪')} <b>{action}</b>"
        f"  ·  Confidence: <b>{conf * 100:.0f}%</b>"
        f"  ·  {_TIER_EMOJI.get(tier, '')} <b>{tier}</b>",
        "",
        f"📊 <b>Position:</b> {pos_pct * 100:.1f}% of portfolio",
        f"🛡 <b>Stop loss:</b> -{sl_pct * 100:.1f}%"
        f"   🎯 <b>Take profit:</b> +{tp_pct * 100:.1f}%",
    ]

    if rationale:
        lines += ["", f"<i>{rationale[:280]}</i>"]

    # Agent views — skip risk (verbose) to keep message compact
    view_lines = [
        f"  {_VIEW_ICON.get(k, '•')} <i>{k.replace('_', ' ').title()}:</i> {str(v)[:120]}"
        for k, v in views.items()
        if k != "risk" and v
    ]
    if view_lines:
        lines += ["", "<b>Agent Views:</b>"] + view_lines

    # Devil's Advocate bar
    if da_case:
        bar = "🟢" if da_score < 30 else ("🟡" if da_score < 60 else "🔴")
        lines += [
            "",
            f"{bar} <b>Devil's Advocate ({da_score}/100):</b>",
            f"<i>{da_case[:220]}</i>",
        ]

    fit_e = _FIT_EMOJI.get(fit, "")
    lines += ["", f"{fit_e} <b>Strategy fit:</b> {fit}"]

    return "\n".join(lines)


def _fmt_portfolio(d: dict) -> str:
    equity    = d.get("equity", 0)
    cash      = d.get("cash", 0)
    pnl       = d.get("daily_pnl", 0)
    pnl_pct   = d.get("daily_pnl_pct", 0)
    positions = d.get("positions", [])

    sign = "+" if pnl >= 0 else ""
    pnl_e = "🟢" if pnl >= 0 else "🔴"

    lines = [
        "💼 <b>Portfolio Snapshot</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📊 <b>Equity:</b>   ${equity:,.2f}",
        f"💵 <b>Cash:</b>     ${cash:,.2f}",
        f"{pnl_e} <b>Today P&L:</b> {sign}${pnl:,.2f}  ({sign}{pnl_pct:.2f}%)",
    ]

    if positions:
        lines += ["", "<b>Open Positions:</b>"]
        for p in positions[:12]:
            upnl     = p.get("unrealized_pnl", 0)
            upnl_pct = p.get("unrealized_pnl_pct", 0)
            e   = "🟢" if upnl >= 0 else "🔴"
            sg  = "+" if upnl >= 0 else ""
            lines.append(
                f"  {e} <b>{p['symbol']}</b>  "
                f"{p['qty']:.4f} × ${p['current_price']:,.4f}"
                f"  ({sg}{upnl_pct:.1f}%)"
            )
    else:
        lines.append("\n<i>No open positions.</i>")

    return "\n".join(lines)


def _fmt_order(result) -> str:
    qty = getattr(result, "qty", "?")
    e   = "🟢" if result.action == "BUY" else "🔴"
    return (
        f"{e} <b>Order Submitted</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Symbol:   <b>{result.symbol}</b>\n"
        f"Action:   <b>{result.action}</b>\n"
        f"Qty:      <b>{qty}</b>\n"
        f"Price:    <b>${result.submitted_price:,.4f}</b>\n"
        f"Stop:     <b>${result.stop_price:,.4f}</b>\n"
        f"Target:   <b>${result.take_profit_price:,.4f}</b>\n"
        f"Order ID: <code>{result.order_id}</code>"
    )


# ── Command handlers ──────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        await update.message.reply_text("⛔ Unauthorized.")
        return
    await update.message.reply_html(
        "👋 <b>TradingAgent Bot</b>\n\n"
        "AI-powered market signals and trade execution.\n\n"
        "/help — see all commands\n\n"
        "<i>Paper trading / testnet mode active by default.</i>"
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    await update.message.reply_html(
        "<b>Available Commands</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>Market Analysis</b>\n"
        "/signal <code>SYMBOL stock|crypto</code>\n"
        "  → Run 9-agent debate, get a full signal card\n\n"
        "💰 <b>Trade Execution</b>\n"
        "/buy  <code>SYMBOL AMOUNT_USD stock|crypto</code>\n"
        "/sell <code>SYMBOL AMOUNT_USD stock|crypto</code>\n"
        "  → Places market order after confirmation\n\n"
        "📈 <b>Portfolio</b>\n"
        "/positions — Open positions & today's P&L\n\n"
        "⚙️ <b>System</b>\n"
        "/health — Liveness check\n\n"
        "<i>Examples:</i>\n"
        "<code>/signal AAPL stock</code>\n"
        "<code>/signal BTCUSDT crypto</code>\n"
        "<code>/buy AAPL 500 stock</code>\n"
        "<code>/sell BTCUSDT 200 crypto</code>"
    )


async def cmd_signal(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    args = ctx.args or []
    if len(args) < 2:
        await update.message.reply_html(
            "Usage: /signal <code>SYMBOL stock|crypto</code>\n"
            "Example: /signal AAPL stock"
        )
        return

    symbol      = args[0].upper()
    asset_class = args[1].lower()
    if asset_class not in ("stock", "crypto"):
        await update.message.reply_text("Asset class must be 'stock' or 'crypto'.")
        return

    msg = await update.message.reply_html(
        f"🧠 <b>Analyzing {symbol}…</b>\n"
        "Running 9-agent debate — this takes ~30s."
    )

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            resp = await client.post(
                f"{_BRAIN}/signal",
                json={"symbol": symbol, "asset_class": asset_class},
            )
        if resp.status_code != 200:
            raise ValueError(f"API {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
    except Exception as exc:
        await msg.edit_text(f"❌ Signal failed: {exc}")
        return

    text = _fmt_signal(data)

    # Offer execution button if signal is actionable
    action   = data.get("action", "HOLD")
    keyboard = None
    if action in ("BUY", "SELL"):
        cb = f"exec:{symbol}:{asset_class}:{action}"
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(f"✅ Execute {action}", callback_data=cb),
            InlineKeyboardButton("❌ Dismiss", callback_data="dismiss"),
        ]])

    await msg.edit_text(text, parse_mode="HTML", reply_markup=keyboard)


async def cmd_buy(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _direct_order(update, ctx, "BUY")


async def cmd_sell(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await _direct_order(update, ctx, "SELL")


async def _direct_order(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE, side: str
) -> None:
    if not _allowed(update):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    args = ctx.args or []
    if len(args) < 3:
        await update.message.reply_html(
            f"Usage: /{side.lower()} <code>SYMBOL AMOUNT_USD stock|crypto</code>\n"
            f"Example: /{side.lower()} AAPL 500 stock"
        )
        return

    symbol      = args[0].upper()
    asset_class = args[2].lower() if len(args) > 2 else "stock"
    try:
        amount = float(args[1])
    except ValueError:
        await update.message.reply_text("Amount must be a number (USD notional).")
        return

    e = "🟢" if side == "BUY" else "🔴"
    text = (
        f"{e} <b>Confirm {side}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Symbol:    <b>{symbol}</b>  ({asset_class})\n"
        f"Notional:  <b>${amount:,.2f}</b>\n\n"
        "⚠️ <i>Market order — executes at current price</i>"
    )
    cb = f"direct:{symbol}:{asset_class}:{side}:{amount}"
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"✅ Confirm {side}", callback_data=cb),
        InlineKeyboardButton("❌ Cancel", callback_data="dismiss"),
    ]])
    await update.message.reply_html(text, reply_markup=keyboard)


async def cmd_positions(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        await update.message.reply_text("⛔ Unauthorized.")
        return

    msg = await update.message.reply_text("📊 Fetching portfolio…")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{_BRAIN}/portfolio")
        if resp.status_code != 200:
            raise ValueError(f"HTTP {resp.status_code}")
        text = _fmt_portfolio(resp.json())
    except Exception as exc:
        text = f"❌ Portfolio fetch failed: {exc}"

    await msg.edit_text(text, parse_mode="HTML")


async def cmd_health(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not _allowed(update):
        return
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{_BRAIN}/health")
        d  = resp.json()
        ts = d.get("timestamp", "?")
        await update.message.reply_html(
            f"✅ <b>System healthy</b>\n"
            f"Timestamp: <code>{ts}</code>"
        )
    except Exception as exc:
        await update.message.reply_text(f"❌ Health check failed: {exc}")


# ── Inline keyboard callbacks ─────────────────────────────────────────────────

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data or ""

    if data == "dismiss":
        await query.edit_message_reply_markup(None)
        return

    if data.startswith("exec:"):
        # exec:SYMBOL:asset_class:ACTION  — execute from cached signal
        _, symbol, asset_class, action = data.split(":")
        await query.edit_message_text(
            f"⏳ Executing <b>{action} {symbol}</b>…", parse_mode="HTML"
        )
        text = await asyncio.to_thread(_sync_exec_signal, symbol, asset_class, action)
        await query.edit_message_text(text, parse_mode="HTML")

    elif data.startswith("direct:"):
        # direct:SYMBOL:asset_class:SIDE:amount
        _, symbol, asset_class, side, amount_str = data.split(":")
        amount = float(amount_str)
        await query.edit_message_text(
            f"⏳ Placing <b>{side} {symbol}</b> (${amount:,.2f})…",
            parse_mode="HTML",
        )
        text = await asyncio.to_thread(_sync_exec_direct, symbol, asset_class, side, amount)
        await query.edit_message_text(text, parse_mode="HTML")


# ── Sync execution helpers (run in thread pool) ───────────────────────────────

def _signal_from_cache(symbol: str) -> dict | None:
    """Fetch the last cached signal from the brain API (synchronous)."""
    import urllib.request, json as _json
    try:
        with urllib.request.urlopen(f"{_BRAIN}/signal/{symbol}/latest", timeout=10) as r:
            return _json.loads(r.read())
    except Exception:
        return None


def _build_trading_signal(d: dict):
    """Reconstruct a TradingSignal dataclass from an API response dict."""
    from brain.signal import TradingSignal
    views = d.get("agent_views", {})
    generated_at = d.get("generated_at")
    if isinstance(generated_at, str):
        try:
            from datetime import datetime
            generated_at = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except Exception:
            generated_at = datetime.now(timezone.utc)

    return TradingSignal(
        symbol                = d["symbol"],
        asset_class           = d["asset_class"],
        action                = d["action"],
        confidence            = d["confidence"],
        rationale             = d.get("rationale", ""),
        generated_at          = generated_at,
        tier                  = d.get("tier", "WARM"),
        suggested_position_pct= d.get("suggested_position_pct", 0.05),
        stop_loss_pct         = d.get("stop_loss_pct", 0.02),
        take_profit_pct       = d.get("take_profit_pct", 0.05),
        devil_advocate_score  = d.get("devil_advocate_score", 0),
        devil_advocate_case   = d.get("devil_advocate_case", ""),
        strategy_fit          = d.get("strategy_fit", "ALIGNED"),
        fundamental_view      = views.get("fundamental", ""),
        technical_view        = views.get("technical", ""),
        sentiment_view        = views.get("sentiment", ""),
        macro_view            = views.get("macro", ""),
        quant_view            = views.get("quant", ""),
        options_flow_view     = views.get("options_flow", ""),
        regime_view           = views.get("regime", ""),
        strategy_view         = views.get("strategy", ""),
        risk_view             = views.get("risk", ""),
    )


def _sync_exec_signal(symbol: str, asset_class: str, action: str) -> str:
    """Execute the last cached signal (runs in thread pool)."""
    try:
        cached = _signal_from_cache(symbol)
        if not cached:
            return (
                f"❌ No cached signal for {symbol}.\n"
                "Run /signal first to generate one."
            )

        signal = _build_trading_signal(cached)

        cfg = get_settings()
        if asset_class == "stock":
            from execution.stock.engine import StockExecutionEngine
            from data.market_data import AlpacaMarketData
            # Fetch recent bars for ATR sizing
            bars_closes: list[float] = []
            bars_highs:  list[float] = []
            bars_lows:   list[float] = []
            try:
                md = AlpacaMarketData(cfg.alpaca_api_key, cfg.alpaca_secret_key)
                snap = md.snapshot(symbol, lookback_days=20)
                bars_closes = list(snap.closes)
                bars_highs  = list(snap.highs)
                bars_lows   = list(snap.lows)
            except Exception as e:
                log.warning("Could not fetch bars for sizing: %s", e)

            engine = StockExecutionEngine(
                cfg.alpaca_api_key, cfg.alpaca_secret_key, cfg.alpaca_base_url,
                cfg.max_position_pct, cfg.circuit_breaker_drawdown,
            )
            result = engine.execute(signal, bars_highs, bars_lows, bars_closes)
        else:
            from execution.crypto.engine import CryptoExecutionEngine
            engine = CryptoExecutionEngine(
                cfg.binance_api_key, cfg.binance_secret_key, cfg.binance_testnet,
                cfg.max_position_pct, cfg.max_crypto_allocation_pct,
            )
            result = engine.execute(signal)

        if result is None:
            return "⚠️ Order blocked by risk controls (circuit breaker or position sizing)."

        return _fmt_order(result)

    except Exception as exc:
        log.error("Signal execution failed: %s", exc, exc_info=True)
        return f"❌ Execution failed: {exc}"


def _sync_exec_direct(
    symbol: str, asset_class: str, side: str, amount_usd: float
) -> str:
    """Direct market order for a given USD notional (runs in thread pool)."""
    try:
        cfg = get_settings()

        if asset_class == "stock":
            from alpaca.trading.client import TradingClient
            from alpaca.trading.requests import MarketOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce

            client = TradingClient(cfg.alpaca_api_key, cfg.alpaca_secret_key, paper=True)
            req = MarketOrderRequest(
                symbol=symbol,
                notional=round(amount_usd, 2),
                side=OrderSide.BUY if side == "BUY" else OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
            )
            order = client.submit_order(req)
            # Alpaca notional orders don't have a fixed price until filled
            return (
                f"{'🟢' if side == 'BUY' else '🔴'} <b>Order Submitted</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"Symbol:   <b>{symbol}</b>\n"
                f"Action:   <b>{side}</b>\n"
                f"Notional: <b>${amount_usd:,.2f}</b>\n"
                f"Order ID: <code>{order.id}</code>\n"
                f"Status:   <code>{order.status}</code>"
            )

        else:  # crypto
            from binance.client import Client as BinanceClient
            client = BinanceClient(
                cfg.binance_api_key, cfg.binance_secret_key,
                testnet=cfg.binance_testnet,
            )
            ticker  = client.get_symbol_ticker(symbol=symbol)
            price   = float(ticker["price"])
            qty     = round(amount_usd / price, 6)

            if side == "BUY":
                order = client.order_market_buy(symbol=symbol, quantity=qty)
            else:
                order = client.order_market_sell(symbol=symbol, quantity=qty)

            order_id = str(order.get("orderId", "?"))
            fills    = order.get("fills", [])
            avg_px   = (
                sum(float(f["price"]) * float(f["qty"]) for f in fills)
                / max(sum(float(f["qty"]) for f in fills), 1e-12)
                if fills else price
            )
            return (
                f"{'🟢' if side == 'BUY' else '🔴'} <b>Order Filled</b>\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"Symbol:   <b>{symbol}</b>\n"
                f"Action:   <b>{side}</b>\n"
                f"Qty:      <b>{qty:.6f}</b>\n"
                f"Avg px:   <b>${avg_px:,.4f}</b>\n"
                f"Order ID: <code>{order_id}</code>"
            )

    except Exception as exc:
        log.error("Direct execution failed: %s", exc, exc_info=True)
        return f"❌ Execution failed: {exc}"


# ── Bot entry point ───────────────────────────────────────────────────────────

def run_bot() -> None:
    cfg = get_settings()
    if not cfg.telegram_bot_token:
        log.warning("TELEGRAM_BOT_TOKEN not set — Telegram bot disabled.")
        return

    application = (
        Application.builder()
        .token(cfg.telegram_bot_token)
        .build()
    )

    application.add_handler(CommandHandler("start",     cmd_start))
    application.add_handler(CommandHandler("help",      cmd_help))
    application.add_handler(CommandHandler("signal",    cmd_signal))
    application.add_handler(CommandHandler("trend",     cmd_signal))   # alias
    application.add_handler(CommandHandler("buy",       cmd_buy))
    application.add_handler(CommandHandler("sell",      cmd_sell))
    application.add_handler(CommandHandler("positions", cmd_positions))
    application.add_handler(CommandHandler("health",    cmd_health))
    application.add_handler(CallbackQueryHandler(handle_callback))

    log.info("Telegram bot polling…")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_bot()
