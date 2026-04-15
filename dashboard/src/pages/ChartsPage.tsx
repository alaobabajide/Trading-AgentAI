import { useMemo, useState } from "react";
import { Search, X } from "lucide-react";
import clsx from "clsx";
import { TradingViewChart } from "../components/TradingViewChart";
import { TradingViewTicker } from "../components/TradingViewTicker";
import { TradingViewMiniChart } from "../components/TradingViewMiniChart";
import { TV_SYMBOLS, TvGroup, TvSymbol } from "../lib/tradingview";

const INTERVALS: { label: string; value: string }[] = [
  { label: "1m",  value: "1"   },
  { label: "5m",  value: "5"   },
  { label: "15m", value: "15"  },
  { label: "1h",  value: "60"  },
  { label: "4h",  value: "240" },
  { label: "1D",  value: "D"   },
  { label: "1W",  value: "W"   },
];

const GROUPS: TvGroup[] = ["Stocks", "ETFs", "Crypto", "Forex", "NGX"];

const GROUP_COLORS: Record<TvGroup, string> = {
  Stocks: "text-blue-400 bg-blue-500/10 border-blue-500/20",
  ETFs:   "text-violet-400 bg-violet-500/10 border-violet-500/20",
  Crypto: "text-orange-400 bg-orange-500/10 border-orange-500/20",
  Forex:  "text-sky-400 bg-sky-500/10 border-sky-500/20",
  NGX:    "text-green-400 bg-green-500/10 border-green-500/20",
};

const GROUP_BADGE: Partial<Record<TvGroup, string>> = {
  Forex: "FX",
  NGX:   "NGX",
};

export function ChartsPage() {
  const [active, setActive]     = useState<TvSymbol>(TV_SYMBOLS[0]);
  const [interval, setInterval] = useState("D");
  const [tab, setTab]           = useState<TvGroup>("Stocks");
  const [showGrid, setShowGrid] = useState(false);
  const [search, setSearch]     = useState("");

  const tabSymbols = useMemo(() => {
    const all = TV_SYMBOLS.filter((s) => s.group === tab);
    const q = search.trim().toUpperCase();
    if (!q) return all;
    return all.filter((s) => s.label.includes(q) || s.description.toUpperCase().includes(q));
  }, [tab, search]);

  const handleTab = (g: TvGroup) => {
    setTab(g);
    setSearch("");
    const first = TV_SYMBOLS.find((s) => s.group === g);
    if (first && first.group !== active.group) setActive(first);
  };

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Ticker tape */}
      <div className="shrink-0 border-b border-white/5 bg-surface-800/60">
        <TradingViewTicker />
      </div>

      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Symbol sidebar */}
        <aside className="w-56 shrink-0 border-r border-white/5 bg-surface-800/40 flex flex-col min-h-0">
          {/* Group tabs — scrollable row */}
          <div className="shrink-0 border-b border-white/5 overflow-x-auto">
            <div className="flex min-w-max">
              {GROUPS.map((g) => (
                <button
                  key={g}
                  onClick={() => handleTab(g)}
                  className={clsx(
                    "flex items-center gap-1 px-3 py-2.5 text-[10px] font-semibold uppercase tracking-wider transition-colors shrink-0",
                    tab === g
                      ? "text-brand-400 border-b-2 border-brand-500"
                      : "text-slate-500 hover:text-slate-300",
                  )}
                >
                  {g}
                  {GROUP_BADGE[g] && (
                    <span className={clsx(
                      "text-[8px] font-bold px-1 rounded border",
                      tab === g ? "border-brand-500/40 text-brand-400" : "border-white/10 text-slate-600",
                    )}>
                      {GROUP_BADGE[g]}
                    </span>
                  )}
                </button>
              ))}
            </div>
          </div>

          {/* Search */}
          <div className="shrink-0 px-3 py-2 border-b border-white/5">
            <div className="relative">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3 h-3 text-slate-600" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search…"
                className="w-full bg-surface-700 border border-white/5 rounded-lg pl-6 pr-6 py-1 text-xs font-mono outline-none focus:ring-1 focus:ring-brand-500 placeholder:text-slate-700"
              />
              {search && (
                <button onClick={() => setSearch("")} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-600 hover:text-slate-400">
                  <X className="w-3 h-3" />
                </button>
              )}
            </div>
            <div className="text-[9px] text-slate-700 font-mono mt-1">
              {tabSymbols.length} symbols
            </div>
          </div>

          {/* Symbol list */}
          <div className="flex-1 overflow-y-auto py-1 min-h-0">
            {tabSymbols.length === 0 ? (
              <div className="px-4 py-3 text-xs text-slate-600 font-mono">No matches</div>
            ) : (
              tabSymbols.map((s) => (
                <button
                  key={s.tv}
                  onClick={() => setActive(s)}
                  className={clsx(
                    "w-full text-left px-4 py-2.5 transition-all",
                    active.tv === s.tv
                      ? "bg-brand-500/15 border-l-2 border-brand-500"
                      : "border-l-2 border-transparent hover:bg-white/[0.03]",
                  )}
                >
                  <div className="flex items-center justify-between gap-1">
                    <span className="font-mono font-semibold text-xs truncate">{s.label}</span>
                    <span className={clsx(
                      "text-[8px] px-1.5 py-0.5 rounded font-medium uppercase shrink-0 border",
                      GROUP_COLORS[s.group],
                    )}>
                      {GROUP_BADGE[s.group] ?? s.group.slice(0, -1)}
                    </span>
                  </div>
                  <div className="text-[10px] text-slate-500 mt-0.5 leading-tight truncate">{s.description}</div>
                </button>
              ))
            )}
          </div>
        </aside>

        {/* Main content */}
        <div className="flex-1 flex flex-col min-w-0 overflow-y-auto">
          {/* Chart controls */}
          <div className="flex items-center justify-between px-6 py-3 border-b border-white/5 bg-surface-800/30">
            <div className="flex items-center gap-3">
              <h2 className="font-mono font-bold text-base">{active.label}</h2>
              <span className={clsx(
                "text-[10px] px-2 py-0.5 rounded-full font-medium uppercase border",
                GROUP_COLORS[active.group],
              )}>
                {active.group}
              </span>
              <span className="text-xs text-slate-500 hidden sm:block truncate max-w-xs">{active.description}</span>
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
            /* Mini chart grid — filtered to current tab */
            <div className="p-6 grid grid-cols-2 xl:grid-cols-3 gap-4 flex-1">
              {tabSymbols.map((s) => (
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
                    <span className={clsx("text-[9px] px-1.5 py-0.5 rounded uppercase font-medium border", GROUP_COLORS[s.group])}>
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
            <div className="flex-1 min-h-0 p-6 flex flex-col gap-3">
              <div className="glass rounded-2xl overflow-hidden flex-1 min-h-0" style={{ minHeight: 480 }}>
                <TradingViewChart symbol={active.tv} interval={interval} />
              </div>
              {/* Indicator legend */}
              <div className="glass rounded-xl px-4 py-3 flex flex-wrap items-center gap-x-1 gap-y-2">
                <span className="text-slate-500 font-semibold uppercase tracking-widest text-[10px] mr-3">Chart Key</span>

                {/* BB */}
                <span className="flex items-center gap-1.5 bg-[#22d3ee]/10 border border-[#22d3ee]/30 rounded-lg px-2.5 py-1">
                  <span className="inline-block w-3 h-0.5 bg-[#22d3ee]" />
                  <span className="font-bold text-[#22d3ee] text-xs">BB</span>
                  <span className="text-slate-400 text-[11px]">Bollinger Bands</span>
                  <span className="text-slate-600 text-[10px]">— volatility envelope around price</span>
                </span>

                {/* SL / RL */}
                <span className="flex items-center gap-1.5 bg-[#f59e0b]/10 border border-[#f59e0b]/30 rounded-lg px-2.5 py-1">
                  <span className="inline-block w-3 h-0.5 bg-[#f59e0b]" />
                  <span className="font-bold text-[#f59e0b] text-xs">SL&nbsp;/&nbsp;RL</span>
                  <span className="text-slate-400 text-[11px]">Support &amp; Resistance Levels</span>
                  <span className="text-slate-600 text-[10px]">— price floors (SL) &amp; ceilings (RL)</span>
                </span>

                {/* MA */}
                <span className="flex items-center gap-1.5 bg-[#a78bfa]/10 border border-[#a78bfa]/30 rounded-lg px-2.5 py-1">
                  <span className="inline-block w-3 h-0.5 bg-[#a78bfa]" />
                  <span className="font-bold text-[#a78bfa] text-xs">MA</span>
                  <span className="text-slate-400 text-[11px]">Moving Average (9)</span>
                  <span className="text-slate-600 text-[10px]">— short-term trend direction</span>
                </span>

                {/* RSI */}
                <span className="flex items-center gap-1.5 bg-slate-700/40 border border-slate-600/40 rounded-lg px-2.5 py-1">
                  <span className="font-bold text-emerald-400 text-xs">RSI</span>
                  <span className="text-slate-400 text-[11px]">Relative Strength Index</span>
                  <span className="text-slate-600 text-[10px]">— overbought (&gt;70) / oversold (&lt;30)</span>
                </span>

                {/* MACD */}
                <span className="flex items-center gap-1.5 bg-slate-700/40 border border-slate-600/40 rounded-lg px-2.5 py-1">
                  <span className="font-bold text-rose-400 text-xs">MACD</span>
                  <span className="text-slate-400 text-[11px]">Moving Avg Convergence Divergence</span>
                  <span className="text-slate-600 text-[10px]">— momentum &amp; trend shifts</span>
                </span>

                {/* FIB + TL */}
                <span className="flex items-center gap-1.5 bg-slate-700/40 border border-slate-600/40 rounded-lg px-2.5 py-1">
                  <span className="font-bold text-yellow-300 text-xs">FIB</span>
                  <span className="text-slate-400 text-[11px]">Fibonacci Retracement</span>
                  <span className="text-slate-600 text-[10px]">— key pullback levels (23.6%–78.6%)</span>
                </span>
                <span className="flex items-center gap-1.5 bg-slate-700/40 border border-slate-600/40 rounded-lg px-2.5 py-1">
                  <span className="font-bold text-sky-300 text-xs">TL</span>
                  <span className="text-slate-400 text-[11px]">Trendline</span>
                  <span className="text-slate-600 text-[10px]">— connect swing highs or lows</span>
                </span>

                <span className="ml-auto text-slate-600 text-[10px] italic">FIB &amp; TL: draw using the ✎ toolbar on the left of the chart</span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
