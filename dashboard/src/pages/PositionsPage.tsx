import { useMemo, useState } from "react";
import { BarChart2, AlertCircle, Clock, RefreshCw, Download, FileText } from "lucide-react";
import { format } from "date-fns";
import clsx from "clsx";
import { PositionsTable } from "../components/PositionsTable";
import { usePortfolio, useOrders, useOrderHistory, exportOrderHistory } from "../lib/api";
import type { AlpacaOrder, StoredOrder } from "../lib/api";

function usMarketStatus(): { open: boolean; nextOpen: string } {
  return useMemo(() => {
    const now = new Date();
    // Convert to ET (UTC-4 in summer / UTC-5 in winter)
    const etOffset = isDst(now) ? -4 : -5;
    const etNow = new Date(now.getTime() + etOffset * 60 * 60 * 1000);
    const etDay  = etNow.getUTCDay();   // 0=Sun, 6=Sat
    const etHour = etNow.getUTCHours();
    const etMin  = etNow.getUTCMinutes();
    const etMins = etHour * 60 + etMin; // minutes since midnight ET

    const marketOpen  = 9 * 60 + 30;   // 9:30 AM ET
    const marketClose = 16 * 60;        // 4:00 PM ET

    const isWeekday = etDay >= 1 && etDay <= 5;
    const isInSession = isWeekday && etMins >= marketOpen && etMins < marketClose;

    if (isInSession) return { open: true, nextOpen: "" };

    // Calculate next open
    let daysUntilOpen = 0;
    if (!isWeekday || etMins >= marketClose) {
      // Move to next weekday
      const daysToAdd = etDay === 5 ? 3 : etDay === 6 ? 2 : 1;
      daysUntilOpen = daysToAdd;
    }
    // daysUntilOpen === 0 means later today (before open)
    const nextOpenET = new Date(etNow);
    nextOpenET.setUTCDate(nextOpenET.getUTCDate() + daysUntilOpen);
    nextOpenET.setUTCHours(9, 30, 0, 0);
    const nextOpenUTC = new Date(nextOpenET.getTime() - etOffset * 60 * 60 * 1000);
    const h = nextOpenUTC.getUTCHours().toString().padStart(2, "0");
    const m = nextOpenUTC.getUTCMinutes().toString().padStart(2, "0");
    const day = nextOpenUTC.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });
    return { open: false, nextOpen: `${day} at ${h}:${m} UTC` };
  }, []);
}

function isDst(d: Date): boolean {
  // Approximate US DST: second Sunday in March → first Sunday in November
  const jan = new Date(d.getFullYear(), 0, 1).getTimezoneOffset();
  const jul = new Date(d.getFullYear(), 6, 1).getTimezoneOffset();
  return d.getTimezoneOffset() < Math.max(jan, jul);
}

// ── Order status display helpers ─────────────────────────────────────────────

const STATUS_COLOR: Record<string, string> = {
  new:               "text-amber-400",
  pending_new:       "text-amber-400",
  accepted:          "text-amber-400",
  partially_filled:  "text-cyan-400",
  filled:            "text-emerald-400",
  canceled:          "text-slate-500",
  expired:           "text-slate-500",
  replaced:          "text-slate-500",
  rejected:          "text-red-400",
};

function orderStatusLabel(status: string): string {
  return status.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function OrdersTable({ orders }: { orders: AlpacaOrder[] }) {
  if (orders.length === 0) {
    return (
      <p className="text-sm text-slate-500 text-center py-4">
        No orders found on this Alpaca account yet.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-[10px] uppercase tracking-widest text-slate-500 border-b border-white/5">
            <th className="text-left pb-2 pr-4">Symbol</th>
            <th className="text-left pb-2 pr-4">Side</th>
            <th className="text-left pb-2 pr-4">Type</th>
            <th className="text-right pb-2 pr-4">Qty</th>
            <th className="text-right pb-2 pr-4">Filled</th>
            <th className="text-left pb-2 pr-4">Status</th>
            <th className="text-left pb-2 pr-4">Submitted</th>
            <th className="text-right pb-2">Limit / Stop</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-white/5">
          {orders.map((o) => (
            <tr key={o.order_id} className="font-mono">
              <td className="py-2 pr-4 font-semibold text-slate-200">{o.symbol}</td>
              <td className={clsx("py-2 pr-4 font-semibold",
                o.side === "buy" ? "text-emerald-400" : "text-red-400"
              )}>
                {o.side.toUpperCase()}
              </td>
              <td className="py-2 pr-4 text-slate-400 text-xs">{o.order_type}</td>
              <td className="py-2 pr-4 text-right text-slate-300">{o.qty}</td>
              <td className={clsx("py-2 pr-4 text-right",
                o.filled_qty > 0 ? "text-emerald-400" : "text-slate-500"
              )}>
                {o.filled_qty}
              </td>
              <td className={clsx("py-2 pr-4 text-xs", STATUS_COLOR[o.status] ?? "text-slate-400")}>
                {orderStatusLabel(o.status)}
              </td>
              <td className="py-2 pr-4 text-slate-500 text-xs">
                {o.submitted_at ? format(new Date(o.submitted_at), "MMM d · HH:mm") : "—"}
              </td>
              <td className="py-2 text-right text-slate-400 text-xs">
                {o.limit_price ? `$${o.limit_price.toFixed(2)}` : "—"}
                {o.stop_price  ? ` / $${o.stop_price.toFixed(2)}` : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Audit history table (persistent store — all brokers) ─────────────────────

const AUDIT_STATUS_COLOR: Record<string, string> = {
  filled:           "text-emerald-400",
  submitted:        "text-amber-400",
  canceled:         "text-slate-500",
  cancelled:        "text-slate-500",
  expired:          "text-slate-500",
  rejected:         "text-red-400",
  broker_sync:      "text-slate-400",
};

function AuditTable({ orders }: { orders: StoredOrder[] }) {
  if (orders.length === 0) {
    return (
      <p className="text-sm text-slate-500 text-center py-6">
        No audit records yet — orders placed through the platform appear here.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-[10px] uppercase tracking-widest text-slate-500 border-b border-white/5">
            <th className="text-left pb-2 pr-3">Date</th>
            <th className="text-left pb-2 pr-3">Symbol</th>
            <th className="text-left pb-2 pr-3">Side</th>
            <th className="text-left pb-2 pr-3">Type</th>
            <th className="text-right pb-2 pr-3">Qty</th>
            <th className="text-right pb-2 pr-3">Filled</th>
            <th className="text-left pb-2 pr-3">Status</th>
            <th className="text-left pb-2 pr-3">Broker</th>
            <th className="text-left pb-2 pr-3">Source</th>
            <th className="text-right pb-2 pr-3">Avg $</th>
            <th className="text-right pb-2">Stop / TP</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-white/5">
          {orders.map((o, i) => (
            <tr key={o.order_id || i} className="font-mono text-xs">
              <td className="py-1.5 pr-3 text-slate-500">
                {o.submitted_at ? format(new Date(o.submitted_at), "MMM d · HH:mm") : "—"}
              </td>
              <td className="py-1.5 pr-3 font-semibold text-slate-200">{o.symbol}</td>
              <td className={clsx("py-1.5 pr-3 font-semibold",
                o.side === "BUY" ? "text-emerald-400" : "text-red-400"
              )}>
                {o.side}
              </td>
              <td className="py-1.5 pr-3 text-slate-400">{o.order_type}</td>
              <td className="py-1.5 pr-3 text-right text-slate-300">{o.qty}</td>
              <td className={clsx("py-1.5 pr-3 text-right",
                o.filled_qty > 0 ? "text-emerald-400" : "text-slate-500"
              )}>
                {o.filled_qty}
              </td>
              <td className={clsx("py-1.5 pr-3", AUDIT_STATUS_COLOR[o.status] ?? "text-slate-400")}>
                {o.status.charAt(0).toUpperCase() + o.status.slice(1)}
              </td>
              <td className="py-1.5 pr-3 text-slate-400">{o.broker}</td>
              <td className="py-1.5 pr-3 text-slate-500">{o.source}</td>
              <td className="py-1.5 pr-3 text-right text-slate-300">
                {o.filled_avg_price != null ? `$${o.filled_avg_price.toFixed(2)}` : "—"}
              </td>
              <td className="py-1.5 text-right text-slate-400">
                {o.stop_price != null ? `$${o.stop_price.toFixed(2)}` : "—"}
                {o.take_profit_price != null ? ` / $${o.take_profit_price.toFixed(2)}` : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Export bar ────────────────────────────────────────────────────────────────

function ExportBar({ days }: { days: number }) {
  const [exporting, setExporting] = useState<"csv" | "pdf" | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  async function handleExport(fmt: "csv" | "pdf") {
    setExporting(fmt);
    setExportError(null);
    try {
      await exportOrderHistory(fmt, days);
    } catch (e) {
      setExportError((e as Error).message);
    } finally {
      setExporting(null);
    }
  }

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <button
        onClick={() => handleExport("csv")}
        disabled={exporting !== null}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-white/10 bg-white/5 text-xs font-mono text-slate-300 hover:bg-white/10 hover:text-white transition-colors disabled:opacity-40"
      >
        <Download className="w-3 h-3" />
        {exporting === "csv" ? "Exporting…" : "Export CSV"}
      </button>
      <button
        onClick={() => handleExport("pdf")}
        disabled={exporting !== null}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-white/10 bg-white/5 text-xs font-mono text-slate-300 hover:bg-white/10 hover:text-white transition-colors disabled:opacity-40"
      >
        <FileText className="w-3 h-3" />
        {exporting === "pdf" ? "Exporting…" : "Export PDF"}
      </button>
      {exportError && (
        <span className="text-xs text-red-400 font-mono">{exportError}</span>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function PositionsPage() {
  const { portfolio, apiState } = usePortfolio();
  const [showPendingOnly, setShowPendingOnly] = useState(false);
  const { orders, fetchError: ordersError, loading: ordersLoading } = useOrders(showPendingOnly ? "open" : "all");
  const market = usMarketStatus();
  const [auditDays, setAuditDays] = useState(90);
  const { orders: auditOrders, loading: auditLoading, error: auditError } = useOrderHistory(auditDays);

  const portfolioError = portfolio?.fetch_error ?? null;
  const pendingOrders = orders.filter(
    (o) => ["new", "pending_new", "accepted", "partially_filled"].includes(o.status)
  );
  const hasPendingOrders = pendingOrders.length > 0;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold flex items-center gap-2">
          <BarChart2 className="w-5 h-5 text-brand-400" />
          Open Positions
        </h1>
        <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${
          apiState === "live"
            ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
            : apiState === "loading"
              ? "bg-amber-500/10 text-amber-400 border-amber-500/20"
              : "bg-red-500/10 text-red-400 border-red-500/20"
        }`}>
          {apiState === "live" ? "Live — Alpaca" : apiState === "loading" ? "Connecting…" : "Connection error"}
        </span>
      </div>

      {/* Portfolio error banner */}
      {portfolioError && (
        <div className="glass rounded-2xl p-4 flex items-start gap-3 border border-red-500/20 bg-red-500/5">
          <AlertCircle className="w-4 h-4 text-red-400 mt-0.5 shrink-0" />
          <div>
            <div className="text-sm font-semibold text-red-400">Portfolio fetch error</div>
            <div className="text-xs text-slate-400 mt-0.5">{portfolioError}</div>
            <div className="text-xs text-slate-500 mt-1">
              Check that ALPACA_API_KEY and ALPACA_SECRET_KEY are set correctly in Railway environment variables.
            </div>
          </div>
        </div>
      )}

      {/* Pending orders callout */}
      {hasPendingOrders && (portfolio?.positions ?? []).length === 0 && (
        <div className="glass rounded-2xl p-4 flex items-start gap-3 border border-amber-500/20 bg-amber-500/5">
          <Clock className="w-4 h-4 text-amber-400 mt-0.5 shrink-0" />
          <div className="space-y-1 text-xs">
            <div className="text-sm font-semibold text-amber-400">
              {pendingOrders.length} order{pendingOrders.length > 1 ? "s" : ""} pending — queued at Alpaca
            </div>
            {market.open ? (
              <p className="text-slate-300">
                US market is <span className="text-emerald-400 font-semibold">OPEN</span>.
                Market orders should fill within seconds — refresh to see the latest status.
              </p>
            ) : (
              <p className="text-slate-300">
                US market is <span className="text-amber-400 font-semibold">CLOSED</span>.
                Orders will execute automatically when the market opens:{" "}
                <span className="font-mono text-white">{market.nextOpen}</span>
                {" "}(9:30 AM ET · 2:30 PM Lagos time).
              </p>
            )}
            <p className="text-slate-500">
              Stop-loss and take-profit orders are GTC — they stay active across sessions until triggered or you cancel them.
              Filled positions appear in the table above.
            </p>
          </div>
        </div>
      )}

      {/* Market hours info — shown any time when market is closed and there are no open positions */}
      {!market.open && !hasPendingOrders && (portfolio?.positions ?? []).length === 0 && (
        <div className="glass rounded-2xl p-3 flex items-center gap-3 border border-slate-700/40 bg-slate-800/20">
          <Clock className="w-3.5 h-3.5 text-slate-500 shrink-0" />
          <p className="text-xs text-slate-500">
            US market closed · Next session: <span className="text-slate-400 font-mono">{market.nextOpen}</span>
            {" "}· Orders submitted now will fill at market open.
          </p>
        </div>
      )}

      {/* Filled positions */}
      <div className="glass rounded-2xl p-5">
        <PositionsTable positions={portfolio?.positions ?? []} />
      </div>

      {/* Portfolio summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: "Equity",        value: `$${(portfolio?.equity ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2 })}` },
          { label: "Cash",          value: `$${(portfolio?.cash ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2 })}` },
          { label: "Daily P&L",     value: `${(portfolio?.daily_pnl ?? 0) >= 0 ? "+" : ""}$${(portfolio?.daily_pnl ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2 })}` },
          { label: "Crypto alloc.", value: `${((portfolio?.crypto_allocation_pct ?? 0) * 100).toFixed(1)}%` },
        ].map(({ label, value }) => (
          <div key={label} className="glass rounded-xl p-3 text-center">
            <div className="text-[10px] text-slate-500 uppercase tracking-wider">{label}</div>
            <div className="text-sm font-mono font-semibold mt-1">{value}</div>
          </div>
        ))}
      </div>

      {/* Orders section */}
      <div className="glass rounded-2xl p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 flex items-center gap-2">
            <Clock className="w-3.5 h-3.5" />
            {showPendingOnly ? "Pending Orders" : "Order History (Last 50)"}
            {hasPendingOrders && (
              <span className="px-1.5 py-0.5 rounded-full bg-amber-500/20 text-amber-400 text-[9px] font-bold">
                {pendingOrders.length} PENDING
              </span>
            )}
          </h2>
          <div className="flex items-center gap-2">
            {ordersLoading && (
              <RefreshCw className="w-3 h-3 text-slate-500 animate-spin" />
            )}
            <button
              onClick={() => setShowPendingOnly((v) => !v)}
              className="text-[10px] font-mono text-slate-500 hover:text-slate-300 underline underline-offset-2 transition-colors"
            >
              {showPendingOnly ? "Show full history" : "Show pending only"}
            </button>
          </div>
        </div>

        {ordersError && (
          <div className="flex items-center gap-2 text-xs text-red-400">
            <AlertCircle className="w-3.5 h-3.5 shrink-0" />
            {ordersError}
          </div>
        )}

        <OrdersTable orders={orders} />
      </div>

      {/* Audit history — 1-year persistent store, all brokers */}
      <div className="glass rounded-2xl p-5 space-y-4">
        <div className="flex items-center justify-between flex-wrap gap-3">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 flex items-center gap-2">
            <Clock className="w-3.5 h-3.5" />
            Audit History
            {auditLoading && <RefreshCw className="w-3 h-3 text-slate-500 animate-spin" />}
            <span className="text-slate-600 font-normal normal-case tracking-normal">
              · {auditOrders.length} record{auditOrders.length !== 1 ? "s" : ""}
            </span>
          </h2>
          <div className="flex items-center gap-3 flex-wrap">
            <select
              value={auditDays}
              onChange={(e) => setAuditDays(Number(e.target.value))}
              className="text-[10px] font-mono bg-white/5 border border-white/10 rounded-lg px-2 py-1.5 text-slate-400 focus:outline-none focus:ring-1 focus:ring-brand-500/40"
            >
              <option value={7}>Last 7 days</option>
              <option value={30}>Last 30 days</option>
              <option value={90}>Last 90 days</option>
              <option value={180}>Last 180 days</option>
              <option value={365}>Last 365 days</option>
            </select>
            <ExportBar days={auditDays} />
          </div>
        </div>

        {auditError && (
          <div className="flex items-center gap-2 text-xs text-red-400">
            <AlertCircle className="w-3.5 h-3.5 shrink-0" />
            {auditError}
          </div>
        )}

        <AuditTable orders={auditOrders} />
      </div>
    </div>
  );
}
