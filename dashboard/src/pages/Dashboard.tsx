import { DollarSign, TrendingDown, TrendingUp, Wallet } from "lucide-react";
import { AllocationDonut } from "../components/AllocationDonut";
import { EquityChart } from "../components/EquityChart";
import { PositionsTable } from "../components/PositionsTable";
import { SignalCard } from "../components/SignalCard";
import { StatCard } from "../components/StatCard";
import { mockEquitySeries, mockPortfolio, mockSignals } from "../lib/mock";

const series = mockEquitySeries();

export function Dashboard() {
  const p = mockPortfolio;
  const pnlUp = p.daily_pnl >= 0;
  const cashPct = p.cash / p.equity;

  return (
    <div className="space-y-6">
      {/* Stat row */}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
        <StatCard
          label="Portfolio Equity"
          value={`$${p.equity.toLocaleString("en-US", { minimumFractionDigits: 2 })}`}
          sub="Total NAV"
          trend="neutral"
          icon={<DollarSign className="w-4 h-4" />}
          accent
        />
        <StatCard
          label="Daily P&L"
          value={`${pnlUp ? "+" : ""}$${p.daily_pnl.toLocaleString("en-US", { minimumFractionDigits: 2 })}`}
          sub={`${pnlUp ? "+" : ""}${p.daily_pnl_pct.toFixed(2)}% today`}
          trend={pnlUp ? "up" : "down"}
          icon={pnlUp ? <TrendingUp className="w-4 h-4 text-emerald-500" /> : <TrendingDown className="w-4 h-4 text-red-500" />}
        />
        <StatCard
          label="Cash"
          value={`$${p.cash.toLocaleString("en-US", { minimumFractionDigits: 2 })}`}
          sub={`${(cashPct * 100).toFixed(1)}% of equity`}
          trend="neutral"
          icon={<Wallet className="w-4 h-4" />}
        />
        <StatCard
          label="Crypto Allocation"
          value={`${(p.crypto_allocation_pct * 100).toFixed(1)}%`}
          sub={`Cap: 30% — ${((0.30 - p.crypto_allocation_pct) * 100).toFixed(1)}% headroom`}
          trend={p.crypto_allocation_pct > 0.27 ? "down" : "neutral"}
        />
      </div>

      {/* Main content */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Equity chart */}
        <div className="xl:col-span-2 glass rounded-2xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold">Equity Curve</h2>
            <span className="text-xs text-slate-500">Last 24 h</span>
          </div>
          <EquityChart data={series} />
        </div>

        {/* Allocation + circuit breaker */}
        <div className="space-y-4">
          <div className="glass rounded-2xl p-5">
            <h2 className="text-sm font-semibold mb-4">Allocation</h2>
            <AllocationDonut positions={p.positions} equity={p.equity} cash={p.cash} />
          </div>
          <div className="glass rounded-2xl p-5">
            <h2 className="text-sm font-semibold mb-3">Risk Controls</h2>
            <div className="space-y-2 text-xs text-slate-400 font-mono">
              {[
                ["Circuit breaker", "OK"],
                ["Max position", "5% NAV"],
                ["Crypto cap", "30%"],
                ["Stop (default)", "2%"],
              ].map(([k, v]) => (
                <div key={k} className="flex justify-between">
                  <span>{k}</span>
                  <span className="text-slate-200">{v}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Positions */}
      <div className="glass rounded-2xl p-5">
        <h2 className="text-sm font-semibold mb-4">Open Positions</h2>
        <PositionsTable positions={p.positions} />
      </div>

      {/* Recent signals */}
      <div>
        <h2 className="text-sm font-semibold mb-3">Recent Signals</h2>
        <div className="space-y-3">
          {mockSignals.map((s) => (
            <SignalCard key={`${s.symbol}-${s.generated_at}`} signal={s} />
          ))}
        </div>
      </div>
    </div>
  );
}
