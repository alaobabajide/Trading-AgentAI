import { useMemo, useState } from "react";
import { Search, X } from "lucide-react";
import clsx from "clsx";
import { STOCK_LIST, ETF_LIST, CRYPTO_LIST, FOREX_LIST, NGX_LIST } from "../lib/marketMock";

type Tab = "Stocks" | "ETFs" | "Crypto" | "Forex" | "NGX";

const GROUPS: { label: Tab; symbols: string[]; color: string; badge?: string }[] = [
  { label: "Stocks", symbols: STOCK_LIST,  color: "text-blue-400 bg-blue-500/15 border-blue-500/30"    },
  { label: "ETFs",   symbols: ETF_LIST,    color: "text-violet-400 bg-violet-500/15 border-violet-500/30" },
  { label: "Crypto", symbols: CRYPTO_LIST, color: "text-orange-400 bg-orange-500/15 border-orange-500/30" },
  { label: "Forex",  symbols: FOREX_LIST,  color: "text-sky-400 bg-sky-500/15 border-sky-500/30",  badge: "FX"  },
  { label: "NGX",    symbols: NGX_LIST,    color: "text-green-400 bg-green-500/15 border-green-500/30", badge: "NGX" },
];

interface Props {
  value:    string;
  onChange: (s: string) => void;
}

function getDefaultTab(value: string): Tab {
  if (ETF_LIST.includes(value))    return "ETFs";
  if (CRYPTO_LIST.includes(value)) return "Crypto";
  if (FOREX_LIST.includes(value))  return "Forex";
  if (NGX_LIST.includes(value))    return "NGX";
  return "Stocks";
}

/** All unique leading letters present in a symbol list */
function letters(symbols: string[]): string[] {
  return [...new Set(symbols.map((s) => s[0].toUpperCase()))].sort();
}

export function SymbolSelector({ value, onChange }: Props) {
  const [tab, setTab]       = useState<Tab>(() => getDefaultTab(value));
  const [search, setSearch] = useState("");
  const [letter, setLetter] = useState<string | null>(null);

  const group = GROUPS.find((g) => g.label === tab)!;

  const handleTab = (t: Tab) => {
    setTab(t);
    setSearch("");
    setLetter(null);
    const g = GROUPS.find((g) => g.label === t)!;
    if (!g.symbols.includes(value)) onChange(g.symbols[0]);
  };

  const availableLetters = useMemo(() => letters(group.symbols), [group]);

  const visible = useMemo(() => {
    let list = group.symbols;
    const q = search.trim().toUpperCase();
    if (q)      list = list.filter((s) => s.includes(q));
    else if (letter) list = list.filter((s) => s.startsWith(letter));
    return list;
  }, [group, search, letter]);

  return (
    <div className="space-y-2">
      {/* ── Tab row ──────────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-1">
        {GROUPS.map(({ label, symbols, badge }) => (
          <button
            key={label}
            onClick={() => handleTab(label)}
            className={clsx(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all",
              tab === label
                ? GROUPS.find((g) => g.label === label)!.color
                : "border-white/5 text-slate-500 hover:text-slate-300 hover:border-white/10",
            )}
          >
            {label}
            {badge && (
              <span className="text-[9px] font-bold px-1 rounded border border-current opacity-70">{badge}</span>
            )}
            <span className={clsx(
              "text-[10px] px-1.5 py-0.5 rounded-full font-mono",
              tab === label ? "bg-white/10" : "bg-surface-700 text-slate-600",
            )}>
              {symbols.length}
            </span>
          </button>
        ))}
      </div>

      {/* ── Search + A-Z filter ──────────────────────────────────────────────── */}
      <div className="flex items-center gap-2">
        {/* Search */}
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3 h-3 text-slate-500" />
          <input
            value={search}
            onChange={(e) => { setSearch(e.target.value.toUpperCase()); setLetter(null); }}
            placeholder={`Search ${tab}…`}
            className="w-full bg-surface-700 border border-white/5 rounded-lg pl-7 pr-8 py-1.5 text-xs font-mono outline-none focus:ring-1 focus:ring-brand-500 placeholder:text-slate-600"
          />
          {search && (
            <button onClick={() => setSearch("")} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300">
              <X className="w-3 h-3" />
            </button>
          )}
        </div>

        {/* A-Z chips — only when not searching */}
        {!search && availableLetters.length > 1 && (
          <div className="flex flex-wrap gap-0.5 flex-1">
            <button
              onClick={() => setLetter(null)}
              className={clsx(
                "px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold border transition-all",
                !letter ? "bg-brand-500/20 border-brand-500/40 text-brand-400" : "border-white/5 text-slate-500 hover:text-slate-300",
              )}
            >
              All
            </button>
            {availableLetters.map((l) => (
              <button
                key={l}
                onClick={() => setLetter(letter === l ? null : l)}
                className={clsx(
                  "px-1.5 py-0.5 rounded text-[10px] font-mono font-semibold border transition-all",
                  letter === l
                    ? "bg-brand-500/20 border-brand-500/40 text-brand-400"
                    : "border-white/5 text-slate-500 hover:text-slate-300",
                )}
              >
                {l}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* ── Symbol buttons ───────────────────────────────────────────────────── */}
      <div className="flex flex-wrap gap-1.5 max-h-36 overflow-y-auto pr-1">
        {visible.length === 0 ? (
          <span className="text-xs text-slate-600 font-mono py-1">No matches</span>
        ) : (
          visible.map((sym) => (
            <button
              key={sym}
              onClick={() => onChange(sym)}
              className={clsx(
                "font-mono text-xs px-2.5 py-1.5 rounded-lg border transition-all shrink-0",
                value === sym
                  ? clsx(group.color, "font-semibold")
                  : "bg-surface-700 border-white/5 text-slate-400 hover:text-slate-200 hover:border-white/10",
              )}
            >
              {sym}
            </button>
          ))
        )}
      </div>

      {/* Count */}
      <div className="text-[10px] text-slate-600 font-mono">
        {visible.length} of {group.symbols.length} {tab} symbols
        {letter && !search ? ` starting with ${letter}` : search ? ` matching "${search}"` : ""}
      </div>
    </div>
  );
}
