import { useState } from "react";
import clsx from "clsx";
import { STOCK_LIST, ETF_LIST, CRYPTO_LIST } from "../lib/marketMock";

type Tab = "Stocks" | "ETFs" | "Crypto";

const GROUPS: { label: Tab; symbols: string[] }[] = [
  { label: "Stocks", symbols: STOCK_LIST },
  { label: "ETFs",   symbols: ETF_LIST   },
  { label: "Crypto", symbols: CRYPTO_LIST },
];

interface Props {
  value: string;
  onChange: (s: string) => void;
}

export function SymbolSelector({ value, onChange }: Props) {
  // Determine default tab from current value
  const defaultTab = (): Tab => {
    if (ETF_LIST.includes(value))    return "ETFs";
    if (CRYPTO_LIST.includes(value)) return "Crypto";
    return "Stocks";
  };
  const [tab, setTab] = useState<Tab>(defaultTab);

  const handleTab = (t: Tab) => {
    setTab(t);
    // Auto-select first symbol of new group if current symbol isn't in it
    const group = GROUPS.find((g) => g.label === t)!;
    if (!group.symbols.includes(value)) onChange(group.symbols[0]);
  };

  const active = GROUPS.find((g) => g.label === tab)!;

  return (
    <div className="space-y-2">
      {/* Tab row */}
      <div className="flex items-center gap-1 bg-surface-800 rounded-xl p-1 w-fit border border-white/5">
        {GROUPS.map(({ label }) => (
          <button
            key={label}
            onClick={() => handleTab(label)}
            className={clsx(
              "px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all",
              tab === label
                ? "bg-brand-500/25 text-brand-400 shadow-sm"
                : "text-slate-500 hover:text-slate-300",
            )}
          >
            {label}
            <span className={clsx(
              "ml-1.5 text-[10px] px-1.5 py-0.5 rounded-full font-mono",
              tab === label ? "bg-brand-500/20 text-brand-400" : "bg-surface-700 text-slate-600",
            )}>
              {GROUPS.find((g) => g.label === label)!.symbols.length}
            </span>
          </button>
        ))}
      </div>

      {/* Symbol buttons */}
      <div className="flex flex-wrap gap-1.5">
        {active.symbols.map((sym) => (
          <button
            key={sym}
            onClick={() => onChange(sym)}
            className={clsx(
              "font-mono text-xs px-3 py-1.5 rounded-lg border transition-all",
              value === sym
                ? "bg-brand-500/20 border-brand-500/50 text-brand-400 font-semibold"
                : "bg-surface-700 border-white/5 text-slate-400 hover:text-slate-200 hover:border-white/10",
            )}
          >
            {sym}
          </button>
        ))}
      </div>
    </div>
  );
}
