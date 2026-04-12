import { BarChart2 } from "lucide-react";
import { PositionsTable } from "../components/PositionsTable";
import { usePortfolio } from "../lib/api";

export function PositionsPage() {
  const { portfolio, apiState } = usePortfolio();

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
            : "bg-amber-500/10 text-amber-400 border-amber-500/20"
        }`}>
          {apiState === "live" ? "Live — Alpaca paper" : apiState === "loading" ? "Connecting…" : "Mock data"}
        </span>
      </div>

      <div className="glass rounded-2xl p-5">
        <PositionsTable positions={portfolio.positions} />
      </div>

      {/* Portfolio summary */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: "Equity",        value: `$${portfolio.equity.toLocaleString("en-US", { minimumFractionDigits: 2 })}` },
          { label: "Cash",          value: `$${portfolio.cash.toLocaleString("en-US", { minimumFractionDigits: 2 })}` },
          { label: "Daily P&L",     value: `${portfolio.daily_pnl >= 0 ? "+" : ""}$${portfolio.daily_pnl.toLocaleString("en-US", { minimumFractionDigits: 2 })}` },
          { label: "Crypto alloc.", value: `${(portfolio.crypto_allocation_pct * 100).toFixed(1)}%` },
        ].map(({ label, value }) => (
          <div key={label} className="glass rounded-xl p-3 text-center">
            <div className="text-[10px] text-slate-500 uppercase tracking-wider">{label}</div>
            <div className="text-sm font-mono font-semibold mt-1">{value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
