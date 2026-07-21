import { useState } from "react";
import { DollarSign, TrendingDown, TrendingUp, Wallet } from "lucide-react";
import { AllocationDonut } from "../components/AllocationDonut";
import { EquityChart } from "../components/EquityChart";
import { PositionsTable } from "../components/PositionsTable";
import { SignalCard } from "../components/SignalCard";
import { StatCard } from "../components/StatCard";
import { usePortfolio, useSignals, useEquitySeries, useRiskConfig } from "../lib/api";
import type { EquityPoint } from "../lib/types";

function LiveBadge({ live }: { live: boolean }) {
  return (
    <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${
      live
        ? "bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
        : "bg-amber-500/10 text-amber-400 border border-amber-500/20"
    }`}>
      {live ? "Live" : "Mock"}
    </span>
  );
}

type EquityPeriod = "1D" | "1M" | "1Y";

export function Dashboard() {
  const { portfolio: p, apiState } = usePortfolio();
  const { signals, apiState: sigState } = useSignals();
  const { config: riskCfg } = useRiskConfig();
  const [equityPeriod, setEquityPeriod] = useState<EquityPeriod>("1D");
  const { series: liveSeries, isLive: equityLive } = useEquitySeries(equityPeriod);
  const isLive = apiState === "live";

  // Build the equity series — never use random mock data.
  // Priority:
  //   1. Live history from Alpaca (≥2 points)             → use as-is
  //   2. Live portfolio snapshot (real equity known)       → 2-point line
  //   3. Not yet connected                                 → empty (chart shows loading)
  const series: EquityPoint[] = (() => {
    if (liveSeries.length >= 2) return liveSeries;

    if (isLive && (p?.equity ?? 0) > 0) {
      // Portfolio data is live — synthesise a 2-point line so the chart
      // always reflects real current equity even when history is loading.
      const now      = new Date().toISOString();
      const dayStart = new Date(Date.now() - 8 * 3_600_000).toISOString();
      const equity   = p!.equity;
      const daily_pnl = p!.daily_pnl;
      const open     = equity - daily_pnl;
      return [
        { time: dayStart, equity: open > 0 ? open : equity, pnl: 0 },
        { time: now,      equity: equity,                   pnl: daily_pnl },
      ];
    }

    return [];   // nothing real yet — EquityChart handles empty gracefully
  })();

  const pnlUp = (p?.daily_pnl ?? 0) >= 0;

  return (
    <div className="space-y-6">
      {/* Stat row */}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
        <StatCard
          label="Portfolio Equity"
          value={`$${(p?.equity ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2 })}`}
          sub={`Total NAV · ${isLive ? "Live" : "Mock"}`}
          trend="neutral"
          icon={<DollarSign className="w-4 h-4" />}
          accent
        />
        <StatCard
          label="Daily P&L"
          value={`${pnlUp ? "+" : ""}$${(p?.daily_pnl ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2 })}`}
          sub={`${pnlUp ? "+" : ""}${(p?.daily_pnl_pct ?? 0).toFixed(2)}% today`}
          trend={pnlUp ? "up" : "down"}
          icon={pnlUp ? <TrendingUp className="w-4 h-4 text-emerald-500" /> : <TrendingDown className="w-4 h-4 text-red-500" />}
        />
        <StatCard
          label="Cash"
          value={`$${(p?.cash ?? 0).toLocaleString("en-US", { minimumFractionDigits: 2 })}`}
          sub={`Buying power: $${(p?.buying_power ?? p?.cash ?? 0).toLocaleString("en-US", { maximumFractionDigits: 0 })}`}
          trend="neutral"
          icon={<Wallet className="w-4 h-4" />}
        />
        <StatCard
          label="Crypto Allocation"
          value={`${((p?.crypto_allocation_pct ?? 0) * 100).toFixed(1)}%`}
          sub={`Cap: ${((riskCfg?.max_crypto_allocation_pct ?? 0.30) * 100).toFixed(0)}% — ${(((riskCfg?.max_crypto_allocation_pct ?? 0.30) - (p?.crypto_allocation_pct ?? 0)) * 100).toFixed(1)}% headroom`}
          trend={(p?.crypto_allocation_pct ?? 0) > ((riskCfg?.max_crypto_allocation_pct ?? 0.30) * 0.90) ? "down" : "neutral"}
        />
      </div>

      {/* Main content */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        <div className="xl:col-span-2 glass rounded-2xl p-5">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <h2 className="text-sm font-semibold">Equity Curve</h2>
              <LiveBadge live={equityLive} />
            </div>
            <div className="flex items-center gap-3">
              <div className="flex gap-1">
                {(["1D", "1M", "1Y"] as EquityPeriod[]).map((p) => (
                  <button
                    key={p}
                    onClick={() => setEquityPeriod(p)}
                    className={`text-[11px] font-mono px-2 py-0.5 rounded transition-colors ${
                      equityPeriod === p
                        ? "bg-brand-500/20 text-brand-400 border border-brand-500/30"
                        : "text-slate-500 hover:text-slate-300"
                    }`}
                  >
                    {p}
                  </button>
                ))}
              </div>
              <span className="text-xs text-slate-500">
                {equityLive ? "Alpaca" : isLive ? "Connecting…" : "Waiting for data"}
              </span>
            </div>
          </div>
          <EquityChart data={series} period={equityPeriod} />
        </div>

        <div className="space-y-4">
          <div className="glass rounded-2xl p-5">
            <h2 className="text-sm font-semibold mb-4">Allocation</h2>
            <AllocationDonut positions={p?.positions ?? []} equity={p?.equity ?? 0} cash={p?.cash ?? 0} />
          </div>
          <div className="glass rounded-2xl p-5">
            <h2 className="text-sm font-semibold mb-3">Risk Controls</h2>
            <div className="space-y-2 text-xs text-slate-400 font-mono">
              {(riskCfg ? [
                ["Circuit breaker", `${(riskCfg.circuit_breaker_drawdown * 100).toFixed(0)}% drawdown`],
                ["Max position",    `${(riskCfg.max_position_pct * 100).toFixed(0)}% NAV`],
                ["Crypto cap",      `${(riskCfg.max_crypto_allocation_pct * 100).toFixed(0)}%`],
                ["Stop (default)",  `${(riskCfg.stop_loss_pct * 100).toFixed(1)}%`],
                ["Target (default)",`${(riskCfg.take_profit_pct * 100).toFixed(1)}%`],
              ] : [
                ["Circuit breaker", "—"],
                ["Max position",    "—"],
                ["Crypto cap",      "—"],
                ["Stop (default)",  "—"],
                ["Target (default)","—"],
              ]).map(([k, v]) => (
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
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-sm font-semibold">Open Positions</h2>
          <LiveBadge live={isLive} />
        </div>
        <PositionsTable positions={p?.positions ?? []} />
      </div>

      {/* Recent signals */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <h2 className="text-sm font-semibold">Recent Signals</h2>
          <LiveBadge live={sigState === "live"} />
        </div>
        <div className="space-y-3">
          {signals.map((s) => (
            <SignalCard key={`${s.symbol}-${s.generated_at}`} signal={s} />
          ))}
        </div>
      </div>
    </div>
  );
}
