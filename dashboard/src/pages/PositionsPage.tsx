import { useState } from "react";
import { BarChart2, AlertCircle, Clock, RefreshCw } from "lucide-react";
import { format } from "date-fns";
import clsx from "clsx";
import { PositionsTable } from "../components/PositionsTable";
import { usePortfolio, useOrders } from "../lib/api";
import type { AlpacaOrder } from "../lib/api";

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

// ── Main page ─────────────────────────────────────────────────────────────────

export function PositionsPage() {
  const { portfolio, apiState } = usePortfolio();
  const [showPendingOnly, setShowPendingOnly] = useState(false);
  const { orders, fetchError: ordersError, loading: ordersLoading } = useOrders(showPendingOnly ? "open" : "all");

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

      {/* Pending orders callout — shown when there are open orders but no filled positions */}
      {hasPendingOrders && (portfolio?.positions ?? []).length === 0 && (
        <div className="glass rounded-2xl p-4 flex items-start gap-3 border border-amber-500/20 bg-amber-500/5">
          <Clock className="w-4 h-4 text-amber-400 mt-0.5 shrink-0" />
          <div>
            <div className="text-sm font-semibold text-amber-400">Orders pending — waiting for fill</div>
            <div className="text-xs text-slate-400 mt-0.5">
              {pendingOrders.length} order(s) submitted to Alpaca are awaiting execution.
              Positions will appear here once the market opens and orders are filled.
            </div>
          </div>
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
    </div>
  );
}
