import { useState } from "react";
import clsx from "clsx";
import { TradingViewChart } from "../components/TradingViewChart";
import { TradingViewTicker } from "../components/TradingViewTicker";
import { TradingViewMiniChart } from "../components/TradingViewMiniChart";
import { TV_SYMBOLS, TvSymbol } from "../lib/tradingview";

const INTERVALS: { label: string; value: string }[] = [
  { label: "1m",  value: "1"   },
  { label: "5m",  value: "5"   },
  { label: "15m", value: "15"  },
  { label: "1h",  value: "60"  },
  { label: "4h",  value: "240" },
  { label: "1D",  value: "D"   },
  { label: "1W",  value: "W"   },
];

const GROUPS: Array<TvSymbol["group"]> = ["Stocks", "ETFs", "Crypto"];

const GROUP_COLORS: Record<TvSymbol["group"], string> = {
  Stocks: "text-blue-400 bg-blue-500/10",
  ETFs:   "text-violet-400 bg-violet-500/10",
  Crypto: "text-orange-400 bg-orange-500/10",
};

export function ChartsPage() {
  const [active, setActive]   = useState<TvSymbol>(TV_SYMBOLS[0]);
  const [interval, setInterval] = useState("D");
  const [tab, setTab]         = useState<TvSymbol["group"]>("Stocks");
  const [showGrid, setShowGrid] = useState(false);

  const tabSymbols = TV_SYMBOLS.filter((s) => s.group === tab);

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Ticker tape */}
      <div className="shrink-0 border-b border-white/5 bg-surface-800/60">
        <TradingViewTicker />
      </div>

      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Symbol sidebar */}
        <aside className="w-52 shrink-0 border-r border-white/5 bg-surface-800/40 flex flex-col overflow-y-auto min-h-0">
          {/* Group tabs */}
          <div className="flex border-b border-white/5">
            {GROUPS.map((g) => (
              <button
                key={g}
                onClick={() => setTab(g)}
                className={clsx(
                  "flex-1 py-2 text-[10px] font-semibold uppercase tracking-wider transition-colors",
                  tab === g
                    ? "text-brand-400 border-b-2 border-brand-500"
                    : "text-slate-500 hover:text-slate-300",
                )}
              >
                {g}
              </button>
            ))}
          </div>

          {/* Symbol list */}
          <div className="flex-1 py-1">
            {tabSymbols.map((s) => (
              <button
                key={s.tv}
                onClick={() => setActive(s)}
                className={clsx(
                  "w-full text-left px-4 py-3 transition-all",
                  active.tv === s.tv
                    ? "bg-brand-500/15 border-l-2 border-brand-500"
                    : "border-l-2 border-transparent hover:bg-white/[0.03]",
                )}
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono font-semibold text-sm">{s.label}</span>
                  <span className={clsx("text-[9px] px-1.5 py-0.5 rounded font-medium uppercase", GROUP_COLORS[s.group])}>
                    {s.group === "Crypto" ? "crypto" : s.group.slice(0, -1)}
                  </span>
                </div>
                <div className="text-[11px] text-slate-500 mt-0.5 leading-tight truncate">{s.description}</div>
              </button>
            ))}
          </div>
        </aside>

        {/* Main content */}
        <div className="flex-1 flex flex-col min-w-0 overflow-y-auto">
          {/* Chart controls */}
          <div className="flex items-center justify-between px-6 py-3 border-b border-white/5 bg-surface-800/30">
            <div className="flex items-center gap-3">
              <h2 className="font-mono font-bold text-base">{active.label}</h2>
              <span className={clsx("text-[10px] px-2 py-0.5 rounded-full font-medium uppercase", GROUP_COLORS[active.group])}>
                {active.group}
              </span>
              <span className="text-xs text-slate-500">{active.description}</span>
            </div>
            <div className="flex items-center gap-3">
              {/* Interval picker */}
              <div className="flex items-center gap-0.5 bg-surface-700 rounded-lg p-0.5 border border-white/5">
                {INTERVALS.map((iv) => (
                  <button
                    key={iv.value}
                    onClick={() => setInterval(iv.value)}
                    className={clsx(
                      "px-2.5 py-1 rounded-md text-[11px] font-mono font-medium transition-all",
                      interval === iv.value
                        ? "bg-brand-500/30 text-brand-300"
                        : "text-slate-400 hover:text-slate-200",
                    )}
                  >
                    {iv.label}
                  </button>
                ))}
              </div>
              {/* Grid toggle */}
              <button
                onClick={() => setShowGrid((v) => !v)}
                className={clsx(
                  "px-3 py-1.5 rounded-lg text-[11px] font-medium border transition-all",
                  showGrid
                    ? "bg-brand-500/20 border-brand-500/40 text-brand-300"
                    : "border-white/10 text-slate-400 hover:text-slate-200 hover:border-white/20",
                )}
              >
                {showGrid ? "Single view" : "Grid view"}
              </button>
            </div>
          </div>

          {showGrid ? (
            /* Mini chart grid */
            <div className="p-6 grid grid-cols-2 xl:grid-cols-3 gap-4 flex-1">
              {TV_SYMBOLS.map((s) => (
                <div
                  key={s.tv}
                  onClick={() => { setActive(s); setShowGrid(false); }}
                  className={clsx(
                    "glass rounded-2xl overflow-hidden cursor-pointer transition-all hover:ring-1 hover:ring-brand-500/40",
                    active.tv === s.tv && "ring-1 ring-brand-500/60",
                  )}
                  style={{ height: 200 }}
                >
                  <div className="px-4 pt-3 pb-1 flex items-center justify-between">
                    <span className="font-mono font-semibold text-sm">{s.label}</span>
                    <span className={clsx("text-[9px] px-1.5 py-0.5 rounded uppercase font-medium", GROUP_COLORS[s.group])}>
                      {s.group}
                    </span>
                  </div>
                  <div style={{ height: 155 }}>
                    <TradingViewMiniChart sym={s} />
                  </div>
                </div>
              ))}
            </div>
          ) : (
            /* Full advanced chart */
            <div className="flex-1 min-h-0 p-6 flex flex-col">
              <div className="glass rounded-2xl overflow-hidden flex-1 min-h-0" style={{ minHeight: 480 }}>
                <TradingViewChart
                  symbol={active.tv}
                  interval={interval}
                />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
