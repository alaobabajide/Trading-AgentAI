import { useMemo, useState } from "react";
import { Loader2, RefreshCw, Search, Send, Zap } from "lucide-react";
import clsx from "clsx";
import { SignalCard } from "../components/SignalCard";
import { useSignals } from "../lib/api";
import type { Signal, SignalAction, SignalTier } from "../lib/types";

// ── Quick-generate watchlist ──────────────────────────────────────────────────

const WATCHLIST_STOCKS  = [
  "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "BAC", "V",
  "NFLX", "AMD",  "INTC", "CRM",  "UBER",  "DIS",  "PG",   "KO",  "XOM", "CVX",
  "PYPL", "COIN", "SNAP", "BABA", "ORCL",
];
const WATCHLIST_ETFS    = [
  "SPY", "QQQ", "IWM", "GLD", "TLT", "XLF", "XLE", "XLK", "VTI", "DIA",
  "ARKK", "XLV", "XLU", "XLRE", "SOXX", "IBIT", "SCHD", "VNQ", "IVV", "EEM",
];
const WATCHLIST_CRYPTO  = [
  "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT",  "XRPUSDT",  "ADAUSDT",
  "DOGEUSDT","AVAXUSDT","LINKUSDT","DOTUSDT",   "MATICUSDT","LTCUSDT",
];

interface QuickRunProps {
  onGenerated: () => void;
}

function QuickRunPanel({ onGenerated }: QuickRunProps) {
  const [open, setOpen]       = useState(false);
  const [running, setRunning] = useState<string | null>(null);
  const [done, setDone]       = useState<string[]>([]);
  const [errors, setErrors]   = useState<Record<string, string>>({});

  async function runSymbol(symbol: string, assetClass: "stock" | "crypto") {
    setRunning(symbol);
    try {
      const resp = await fetch("/api/signal", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ symbol, asset_class: assetClass, paper_mode: true }),
      });
      if (!resp.ok) {
        const d = await resp.json().catch(() => ({}));
        throw new Error((d as { detail?: string }).detail ?? `HTTP ${resp.status}`);
      }
      setDone((p) => [...p, symbol]);
      onGenerated();
    } catch (e) {
      setErrors((p) => ({ ...p, [symbol]: (e as Error).message }));
    } finally {
      setRunning(null);
    }
  }

  function SymbolButton({ symbol, assetClass }: { symbol: string; assetClass: "stock" | "crypto" }) {
    const isDone  = done.includes(symbol);
    const isErr   = !!errors[symbol];
    const loading = running === symbol;
    return (
      <button
        onClick={() => runSymbol(symbol, assetClass)}
        disabled={!!running}
        title={isErr ? errors[symbol] : undefined}
        className={clsx(
          "flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-mono font-medium border transition-all",
          isDone   ? "bg-emerald-500/15 border-emerald-500/30 text-emerald-300" :
          isErr    ? "bg-red-500/15 border-red-500/30 text-red-300" :
          loading  ? "bg-brand-500/15 border-brand-500/30 text-brand-300 animate-pulse" :
                     "border-white/10 text-slate-400 hover:text-slate-200 hover:border-white/20",
          running && running !== symbol && "opacity-40 cursor-not-allowed",
        )}
      >
        {loading && <Loader2 className="w-3 h-3 animate-spin" />}
        {symbol}
      </button>
    );
  }

  return (
    <div className="glass rounded-2xl overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-white/[0.02] transition-colors"
      >
        <div className="flex items-center gap-2">
          <Send className="w-4 h-4 text-brand-400" />
          <span className="text-sm font-semibold">Quick Generate</span>
          <span className="text-[11px] text-slate-500 font-mono">Run paper-mode signals for any symbol</span>
        </div>
        <span className="text-xs text-slate-500">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="border-t border-white/5 px-5 py-4 space-y-4">
          <div className="space-y-2">
            <div className="text-[10px] text-slate-500 uppercase tracking-widest font-semibold">Stocks</div>
            <div className="flex flex-wrap gap-2">
              {WATCHLIST_STOCKS.map((s) => <SymbolButton key={s} symbol={s} assetClass="stock" />)}
            </div>
          </div>
          <div className="space-y-2">
            <div className="text-[10px] text-slate-500 uppercase tracking-widest font-semibold">ETFs</div>
            <div className="flex flex-wrap gap-2">
              {WATCHLIST_ETFS.map((s) => <SymbolButton key={s} symbol={s} assetClass="stock" />)}
            </div>
          </div>
          <div className="space-y-2">
            <div className="text-[10px] text-slate-500 uppercase tracking-widest font-semibold">Crypto</div>
            <div className="flex flex-wrap gap-2">
              {WATCHLIST_CRYPTO.map((s) => <SymbolButton key={s} symbol={s} assetClass="crypto" />)}
            </div>
          </div>
          {done.length > 0 && (
            <p className="text-[11px] text-emerald-400 font-mono">
              ✓ {done.length} signal{done.length !== 1 ? "s" : ""} generated — refreshing feed…
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Filter bar ────────────────────────────────────────────────────────────────

type AssetFilter  = "all" | "stock" | "crypto";
type ActionFilter = "all" | SignalAction;
type TierFilter   = "all" | SignalTier;
type SortOrder    = "newest" | "oldest" | "action" | "tier";

function FilterBar({
  search, setSearch,
  asset, setAsset,
  action, setAction,
  tier, setTier,
  sort, setSort,
  total, shown,
}: {
  search: string; setSearch: (v: string) => void;
  asset:  AssetFilter;  setAsset:  (v: AssetFilter)  => void;
  action: ActionFilter; setAction: (v: ActionFilter) => void;
  tier:   TierFilter;   setTier:   (v: TierFilter)   => void;
  sort:   SortOrder;    setSort:   (v: SortOrder)    => void;
  total: number; shown: number;
}) {
  function Chip<T extends string>({ label, value, current, onSelect, color }: { label: string; value: T; current: T; onSelect: (v: T) => void; color?: string }) {
    const active = value === current;
    return (
      <button
        onClick={() => onSelect(value)}
        className={clsx(
          "px-2.5 py-1 rounded-lg text-[11px] font-medium border transition-all",
          active
            ? (color ?? "bg-brand-500/20 border-brand-500/40 text-brand-300")
            : "border-white/10 text-slate-500 hover:text-slate-300 hover:border-white/20",
        )}
      >
        {label}
      </button>
    );
  }

  return (
    <div className="glass rounded-2xl p-4 space-y-3">
      {/* Search */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value.toUpperCase())}
          placeholder="Search symbol…"
          className="w-full bg-surface-700 rounded-xl pl-9 pr-4 py-2 text-sm font-mono outline-none focus:ring-1 focus:ring-brand-500 placeholder:text-slate-600"
        />
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-2 items-center">
        {/* Asset class */}
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-slate-600 uppercase tracking-wider">Asset</span>
          <div className="flex gap-1">
            <Chip label="All"    value="all"    current={asset} onSelect={setAsset} />
            <Chip label="Stocks" value="stock"  current={asset} onSelect={setAsset} />
            <Chip label="Crypto" value="crypto" current={asset} onSelect={setAsset} />
          </div>
        </div>

        {/* Action */}
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-slate-600 uppercase tracking-wider">Action</span>
          <div className="flex gap-1">
            <Chip label="All"  value="all"  current={action} onSelect={setAction} />
            <Chip label="BUY"  value="BUY"  current={action} onSelect={setAction} color="bg-emerald-500/20 border-emerald-500/40 text-emerald-300" />
            <Chip label="SELL" value="SELL" current={action} onSelect={setAction} color="bg-red-500/20 border-red-500/40 text-red-300" />
            <Chip label="HOLD" value="HOLD" current={action} onSelect={setAction} color="bg-slate-500/20 border-slate-500/40 text-slate-300" />
          </div>
        </div>

        {/* Tier */}
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-slate-600 uppercase tracking-wider">Tier</span>
          <div className="flex gap-1">
            <Chip label="All"  value="all"  current={tier} onSelect={setTier} />
            <Chip label="HOT"  value="HOT"  current={tier} onSelect={setTier} color="bg-emerald-500/20 border-emerald-500/40 text-emerald-300" />
            <Chip label="WARM" value="WARM" current={tier} onSelect={setTier} color="bg-amber-500/20 border-amber-500/40 text-amber-300" />
            <Chip label="COLD" value="COLD" current={tier} onSelect={setTier} color="bg-slate-500/20 border-slate-500/40 text-slate-300" />
          </div>
        </div>

        {/* Sort */}
        <div className="flex items-center gap-1.5 ml-auto">
          <span className="text-[10px] text-slate-600 uppercase tracking-wider">Sort</span>
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as SortOrder)}
            className="bg-surface-700 border border-white/10 rounded-lg px-2 py-1 text-[11px] font-mono text-slate-300 outline-none"
          >
            <option value="newest">Newest first</option>
            <option value="oldest">Oldest first</option>
            <option value="action">By action</option>
            <option value="tier">By tier</option>
          </select>
        </div>
      </div>

      <div className="text-[10px] text-slate-600 font-mono">
        Showing {shown} of {total} signals
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

const ACTION_ORDER: Record<string, number> = { BUY: 0, SELL: 1, HOLD: 2 };
const TIER_ORDER:   Record<string, number> = { HOT: 0, WARM: 1, COLD: 2 };

export function SignalsPage() {
  const { signals, apiState } = useSignals();
  const [refreshKey, setRefreshKey] = useState(0);

  const [search, setSearch]   = useState("");
  const [asset,  setAsset]    = useState<AssetFilter>("all");
  const [action, setAction]   = useState<ActionFilter>("all");
  const [tier,   setTier]     = useState<TierFilter>("all");
  const [sort,   setSort]     = useState<SortOrder>("newest");

  const filtered = useMemo(() => {
    let list: Signal[] = [...signals];

    if (search)          list = list.filter((s) => s.symbol.includes(search));
    if (asset  !== "all") list = list.filter((s) => s.asset_class === asset);
    if (action !== "all") list = list.filter((s) => s.action === action);
    if (tier   !== "all") list = list.filter((s) => (s.tier ?? "COLD") === tier);

    list.sort((a, b) => {
      switch (sort) {
        case "oldest":  return new Date(a.generated_at).getTime() - new Date(b.generated_at).getTime();
        case "action":  return (ACTION_ORDER[a.action] ?? 9) - (ACTION_ORDER[b.action] ?? 9);
        case "tier":    return (TIER_ORDER[a.tier ?? "COLD"] ?? 9) - (TIER_ORDER[b.tier ?? "COLD"] ?? 9);
        default:        return new Date(b.generated_at).getTime() - new Date(a.generated_at).getTime();
      }
    });

    return list;
  }, [signals, search, asset, action, tier, sort]);

  const buys  = signals.filter((s) => s.action === "BUY").length;
  const sells = signals.filter((s) => s.action === "SELL").length;
  const holds = signals.filter((s) => s.action === "HOLD").length;

  return (
    <div className="space-y-5 max-w-3xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold flex items-center gap-2">
            <Zap className="w-5 h-5 text-brand-400" />
            Signal Feed
          </h1>
          <div className="flex items-center gap-3 mt-1 text-xs font-mono">
            <span className="text-emerald-400">{buys} BUY</span>
            <span className="text-slate-600">·</span>
            <span className="text-red-400">{sells} SELL</span>
            <span className="text-slate-600">·</span>
            <span className="text-slate-400">{holds} HOLD</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setRefreshKey((k) => k + 1)}
            className="p-2 rounded-lg border border-white/10 text-slate-400 hover:text-slate-200 hover:border-white/20 transition-colors"
            title="Refresh"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
          <span className={clsx(
            "text-[10px] font-mono px-2 py-1 rounded border",
            apiState === "live"    ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" :
            apiState === "loading" ? "bg-slate-500/10 text-slate-400 border-slate-600/20" :
                                     "bg-amber-500/10 text-amber-400 border-amber-500/20",
          )}>
            {apiState === "live" ? "Live cache" : apiState === "loading" ? "Loading…" : "Mock data"}
          </span>
        </div>
      </div>

      {/* Quick generate */}
      <QuickRunPanel key={refreshKey} onGenerated={() => setRefreshKey((k) => k + 1)} />

      {/* Filters */}
      <FilterBar
        search={search} setSearch={setSearch}
        asset={asset}   setAsset={setAsset}
        action={action} setAction={setAction}
        tier={tier}     setTier={setTier}
        sort={sort}     setSort={setSort}
        total={signals.length}
        shown={filtered.length}
      />

      {/* Empty states */}
      {apiState === "live" && signals.length === 0 && (
        <div className="glass rounded-2xl p-8 text-center text-slate-500 text-sm">
          No signals in cache yet — use Quick Generate above or the Brain Console.
        </div>
      )}
      {signals.length > 0 && filtered.length === 0 && (
        <div className="glass rounded-2xl p-6 text-center text-slate-500 text-sm">
          No signals match your filters. Try clearing some filters above.
        </div>
      )}

      {/* Signal cards */}
      <div className="space-y-3">
        {filtered.map((s) => (
          <SignalCard key={`${s.symbol}-${s.generated_at}`} signal={s} />
        ))}
      </div>
    </div>
  );
}
