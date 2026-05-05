import { useMemo, useState } from "react";
import { Loader2, RefreshCw, Search, Send, X, Zap } from "lucide-react";
import clsx from "clsx";
import { SignalCard } from "../components/SignalCard";
import { useSignals, apiHeaders } from "../lib/api";
import {
  STOCK_LIST, ETF_LIST, CRYPTO_LIST, FOREX_LIST, NGX_LIST,
} from "../lib/marketMock";
import type { Signal, SignalAction, SignalTier } from "../lib/types";

// ── Quick Generate data ───────────────────────────────────────────────────────

type AssetClass = "stock" | "crypto" | "forex" | "ngx";

interface QTab {
  id:         AssetClass;
  label:      string;
  symbols:    string[];
  badge?:     string;
  color:      string;
  pending?:   boolean; // not yet live — show tooltip instead of running
  note?:      string;
}

// Combine all US stocks + ETFs under their own tabs, sorted A-Z within each
const SORTED_STOCKS = [...STOCK_LIST].sort();
const SORTED_ETFS   = [...ETF_LIST].sort();
const SORTED_CRYPTO = [...CRYPTO_LIST].sort();
const SORTED_FOREX  = [...FOREX_LIST].sort();
const SORTED_NGX    = [...NGX_LIST].sort();

const Q_TABS: QTab[] = [
  { id: "stock",  label: "US Stocks", symbols: SORTED_STOCKS, color: "text-blue-400 border-blue-500/30 bg-blue-500/10" },
  { id: "stock",  label: "ETFs",      symbols: SORTED_ETFS,   color: "text-violet-400 border-violet-500/30 bg-violet-500/10" },
  { id: "crypto", label: "Crypto",    symbols: SORTED_CRYPTO, color: "text-orange-400 border-orange-500/30 bg-orange-500/10" },
  { id: "forex",  label: "Forex",     symbols: SORTED_FOREX,  badge: "FX",  color: "text-sky-400 border-sky-500/30 bg-sky-500/10",   pending: true, note: "Forex data provider coming soon" },
  { id: "ngx",    label: "NGX",       symbols: SORTED_NGX,    badge: "NGX", color: "text-green-400 border-green-500/30 bg-green-500/10", pending: true, note: "Requires NGX data provider" },
];

const TOTAL_SYMBOLS = [...STOCK_LIST, ...ETF_LIST, ...CRYPTO_LIST, ...FOREX_LIST, ...NGX_LIST].length;

/** All unique leading letters present in a sorted symbol list */
function uniqueLetters(symbols: string[]): string[] {
  return [...new Set(symbols.map((s) => s[0].toUpperCase()))].sort();
}

// ── Quick Generate Panel ──────────────────────────────────────────────────────

interface QuickRunProps { onGenerated: () => void }

function QuickRunPanel({ onGenerated }: QuickRunProps) {
  const [open, setOpen]         = useState(false);
  const [activeTab, setActiveTab] = useState(0);
  const [letter, setLetter]     = useState<string | null>(null);
  const [search, setSearch]     = useState("");
  const [running, setRunning]   = useState<string | null>(null);
  const [done, setDone]         = useState<string[]>([]);
  const [errors, setErrors]     = useState<Record<string, string>>({});

  const tab = Q_TABS[activeTab];

  const availLetters = useMemo(() => uniqueLetters(tab.symbols), [tab]);

  const visible = useMemo(() => {
    const q = search.trim().toUpperCase();
    if (q)      return tab.symbols.filter((s) => s.includes(q));
    if (letter) return tab.symbols.filter((s) => s.startsWith(letter));
    return tab.symbols;
  }, [tab, search, letter]);

  function switchTab(i: number) {
    setActiveTab(i);
    setLetter(null);
    setSearch("");
  }

  async function runSymbol(symbol: string) {
    if (tab.pending) {
      setErrors((p) => ({ ...p, [symbol]: tab.note ?? "Not yet available" }));
      return;
    }
    setRunning(symbol);
    try {
      const resp = await fetch("/api/signal", {
        method:  "POST",
        headers: apiHeaders({ "Content-Type": "application/json" }),
        body:    JSON.stringify({ symbol, asset_class: tab.id, paper_mode: true }),
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

  function SymbolBtn({ symbol }: { symbol: string }) {
    const isDone    = done.includes(symbol);
    const isErr     = !!errors[symbol];
    const loading   = running === symbol;
    const isPending = !!tab.pending;
    return (
      <button
        onClick={() => runSymbol(symbol)}
        disabled={!!running && !isPending}
        title={isErr ? errors[symbol] : isPending ? tab.note : undefined}
        className={clsx(
          "flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-mono font-medium border transition-all shrink-0",
          isDone    ? "bg-emerald-500/15 border-emerald-500/30 text-emerald-300" :
          isErr     ? "bg-red-500/15 border-red-500/30 text-red-300" :
          loading   ? "bg-brand-500/15 border-brand-500/30 text-brand-300 animate-pulse" :
          isPending ? "border-white/5 text-slate-600 cursor-help" :
                      "border-white/10 text-slate-400 hover:text-slate-200 hover:border-white/20",
          running && running !== symbol && !isPending && "opacity-40 cursor-not-allowed",
        )}
      >
        {loading && <Loader2 className="w-3 h-3 animate-spin" />}
        {symbol}
      </button>
    );
  }

  return (
    <div className="glass rounded-2xl overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-5 py-3.5 hover:bg-white/[0.02] transition-colors"
      >
        <div className="flex items-center gap-2">
          <Send className="w-4 h-4 text-brand-400" />
          <span className="text-sm font-semibold">Quick Generate</span>
          <span className="text-[11px] text-slate-500 font-mono">
            {TOTAL_SYMBOLS} symbols — US Stocks, ETFs, Crypto, Forex, NGX
          </span>
        </div>
        <span className="text-xs text-slate-500">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="border-t border-white/5 space-y-3">
          {/* ── Category tabs ─────────────────────────────────────────────── */}
          <div className="flex gap-1 px-5 pt-4 flex-wrap">
            {Q_TABS.map((t, i) => (
              <button
                key={`${t.label}-${i}`}
                onClick={() => switchTab(i)}
                className={clsx(
                  "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all",
                  activeTab === i ? t.color : "border-white/5 text-slate-500 hover:text-slate-300 hover:border-white/10",
                )}
              >
                {t.label}
                {t.badge && (
                  <span className="text-[9px] font-bold px-1 rounded border border-current opacity-70">{t.badge}</span>
                )}
                <span className={clsx(
                  "text-[10px] px-1.5 py-0.5 rounded-full font-mono",
                  activeTab === i ? "bg-white/10" : "bg-surface-700 text-slate-600",
                )}>
                  {t.symbols.length}
                </span>
              </button>
            ))}
          </div>

          {/* ── Search + A-Z filter ───────────────────────────────────────── */}
          <div className="px-5 space-y-2">
            {tab.pending && tab.note && (
              <div className="text-[11px] text-amber-400/80 bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2 font-mono">
                {tab.note}
              </div>
            )}

            <div className="flex items-center gap-2">
              <div className="relative max-w-xs">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3 h-3 text-slate-500" />
                <input
                  value={search}
                  onChange={(e) => { setSearch(e.target.value.toUpperCase()); setLetter(null); }}
                  placeholder={`Search ${tab.label}…`}
                  className="w-full bg-surface-700 border border-white/5 rounded-lg pl-7 pr-7 py-1.5 text-xs font-mono outline-none focus:ring-1 focus:ring-brand-500 placeholder:text-slate-600"
                />
                {search && (
                  <button onClick={() => setSearch("")} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300">
                    <X className="w-3 h-3" />
                  </button>
                )}
              </div>
              <span className="text-[10px] text-slate-600 font-mono shrink-0">
                {visible.length}/{tab.symbols.length}
              </span>
            </div>

            {/* A-Z letter chips */}
            {!search && availLetters.length > 1 && (
              <div className="flex flex-wrap gap-0.5">
                <button
                  onClick={() => setLetter(null)}
                  className={clsx(
                    "px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold border transition-all",
                    !letter ? "bg-brand-500/20 border-brand-500/40 text-brand-400" : "border-white/5 text-slate-500 hover:text-slate-300",
                  )}
                >All</button>
                {availLetters.map((l) => (
                  <button
                    key={l}
                    onClick={() => setLetter(letter === l ? null : l)}
                    className={clsx(
                      "px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold border transition-all",
                      letter === l
                        ? "bg-brand-500/20 border-brand-500/40 text-brand-400"
                        : "border-white/5 text-slate-500 hover:text-slate-300",
                    )}
                  >{l}</button>
                ))}
              </div>
            )}
          </div>

          {/* ── Symbol buttons ────────────────────────────────────────────── */}
          <div className="px-5 pb-4">
            <div className="flex flex-wrap gap-1.5 max-h-48 overflow-y-auto pr-1">
              {visible.length === 0
                ? <span className="text-xs text-slate-600 font-mono py-1">No matches</span>
                : visible.map((s) => <SymbolBtn key={s} symbol={s} />)
              }
            </div>

            {done.length > 0 && (
              <p className="text-[11px] text-emerald-400 font-mono mt-3">
                ✓ {done.length} signal{done.length !== 1 ? "s" : ""} generated — refreshing feed…
              </p>
            )}
          </div>
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
  function Chip<T extends string>({ label, value, current, onSelect, color }: {
    label: string; value: T; current: T; onSelect: (v: T) => void; color?: string;
  }) {
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
  const { signals, apiState, refresh, refreshing } = useSignals();

  const [search, setSearch]   = useState("");
  const [asset,  setAsset]    = useState<AssetFilter>("all");
  const [action, setAction]   = useState<ActionFilter>("all");
  const [tier,   setTier]     = useState<TierFilter>("all");
  const [sort,   setSort]     = useState<SortOrder>("newest");

  const filtered = useMemo(() => {
    let list: Signal[] = [...signals];

    if (search)            list = list.filter((s) => s.symbol.includes(search));
    if (asset  !== "all")  list = list.filter((s) => s.asset_class === asset);
    if (action !== "all")  list = list.filter((s) => s.action === action);
    if (tier   !== "all")  list = list.filter((s) => (s.tier ?? "COLD") === tier);

    list.sort((a, b) => {
      switch (sort) {
        case "oldest": return new Date(a.generated_at).getTime() - new Date(b.generated_at).getTime();
        case "action": return (ACTION_ORDER[a.action] ?? 9) - (ACTION_ORDER[b.action] ?? 9);
        case "tier":   return (TIER_ORDER[a.tier ?? "COLD"] ?? 9) - (TIER_ORDER[b.tier ?? "COLD"] ?? 9);
        default:       return new Date(b.generated_at).getTime() - new Date(a.generated_at).getTime();
      }
    });

    return list;
  }, [signals, search, asset, action, tier, sort]);

  const buys  = signals.filter((s) => s.action === "BUY").length;
  const sells = signals.filter((s) => s.action === "SELL").length;
  const holds = signals.filter((s) => s.action === "HOLD").length;

  return (
    <div className="space-y-5">
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
            onClick={refresh}
            disabled={refreshing}
            className="p-2 rounded-lg border border-white/10 text-slate-400 hover:text-slate-200 hover:border-white/20 transition-colors disabled:opacity-50"
            title="Refresh signal feed"
          >
            <RefreshCw className={clsx("w-3.5 h-3.5", refreshing && "animate-spin")} />
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
      <QuickRunPanel onGenerated={refresh} />

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
