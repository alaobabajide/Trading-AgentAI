import { useState } from "react";
import { AlertCircle, ExternalLink, RefreshCw, Search } from "lucide-react";
import clsx from "clsx";
import { TradingViewFinancials } from "../components/TradingViewFinancials";
import { useFmpData } from "../lib/api";
import { tvSymbol } from "../lib/tradingview";
import { useBrokerAssets } from "../hooks/useBrokerAssets";
import { SymbolSelector } from "../components/SymbolSelector";

// ── Types ─────────────────────────────────────────────────────────────────────

interface FmpProfile {
  symbol:        string;
  companyName:   string;
  description:   string;
  sector:        string;
  industry:      string;
  ceo:           string;
  website:       string;
  image:         string;
  mktCap:        number;
  price:         number;
  changes:       number;
  exchange:      string;
  currency:      string;
}

interface FmpMetrics {
  date:                string;
  peRatio:             number | null;
  evToEbitda:          number | null;
  returnOnEquity:      number | null;
  returnOnAssets:      number | null;
  debtToEquity:        number | null;
  grossProfitMargin:   number | null;
  netProfitMargin:     number | null;
  freeCashFlowYield:   number | null;
  priceToBook:         number | null;
  revenuePerShare:     number | null;
}

interface FmpRecommendation {
  symbol:       string;
  date:         string;
  strongBuy:    number;
  buy:          number;
  hold:         number;
  sell:         number;
  strongSell:   number;
}

interface FmpPriceTarget {
  symbol:              string;
  targetHigh:          number | null;
  targetLow:           number | null;
  targetMean:          number | null;
  targetMedian:        number | null;
  lastMonth:           number | null;
  lastQuarter:         number | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmt(n: number | null | undefined, decimals = 2, suffix = ""): string {
  if (n == null || !isFinite(n)) return "—";
  if (Math.abs(n) >= 1e12) return `${(n / 1e12).toFixed(1)}T${suffix}`;
  if (Math.abs(n) >= 1e9)  return `${(n / 1e9).toFixed(1)}B${suffix}`;
  if (Math.abs(n) >= 1e6)  return `${(n / 1e6).toFixed(1)}M${suffix}`;
  return n.toFixed(decimals) + suffix;
}

function pct(n: number | null | undefined): string {
  if (n == null || !isFinite(n)) return "—";
  return `${(n * 100).toFixed(1)}%`;
}

function MetricTile({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="bg-surface-700 rounded-xl p-3 text-center">
      <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">{label}</div>
      <div className={clsx("text-sm font-mono font-semibold", color ?? "text-slate-200")}>{value}</div>
    </div>
  );
}

// ── Sub-panels ────────────────────────────────────────────────────────────────

function ProfilePanel({ symbol }: { symbol: string }) {
  const { data, loading, error } = useFmpData<FmpProfile>("profile", symbol);
  const p = data[0] as FmpProfile | undefined;

  if (loading) return (
    <div className="glass rounded-2xl p-5 flex items-center gap-3 text-slate-500 text-sm">
      <RefreshCw className="w-4 h-4 animate-spin" /> Loading company data…
    </div>
  );
  if (error) return (
    <div className="glass rounded-2xl p-4 flex items-start gap-3 border border-amber-500/20 bg-amber-500/5">
      <AlertCircle className="w-4 h-4 text-amber-400 mt-0.5 shrink-0" />
      <div className="text-xs text-amber-300">{error}</div>
    </div>
  );
  if (!p) return null;

  return (
    <div className="glass rounded-2xl p-5 space-y-4">
      <div className="flex items-start gap-4">
        {p.image && (
          <img
            src={p.image}
            alt={p.companyName}
            className="w-12 h-12 rounded-xl object-contain bg-white/5 p-1 shrink-0"
            onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
          />
        )}
        <div className="min-w-0">
          <div className="text-base font-semibold text-slate-100 truncate">{p.companyName}</div>
          <div className="text-xs text-slate-500 mt-0.5">
            {p.exchange} · {p.sector}{p.industry ? ` · ${p.industry}` : ""}
          </div>
          <div className="flex items-center gap-3 mt-2">
            <span className="text-lg font-mono font-bold text-slate-100">
              {p.currency === "USD" ? "$" : ""}{fmt(p.price)}
            </span>
            <span className={clsx("text-sm font-mono", (p.changes ?? 0) >= 0 ? "text-emerald-400" : "text-red-400")}>
              {(p.changes ?? 0) >= 0 ? "▲" : "▼"} {Math.abs(p.changes ?? 0).toFixed(2)}
            </span>
            <span className="text-xs text-slate-500">Mkt Cap {fmt(p.mktCap)}</span>
          </div>
        </div>
        {p.website && (
          <a
            href={p.website}
            target="_blank"
            rel="noreferrer"
            className="ml-auto shrink-0 text-slate-500 hover:text-brand-400 transition-colors"
            title="Company website"
          >
            <ExternalLink className="w-4 h-4" />
          </a>
        )}
      </div>
      {p.description && (
        <p className="text-xs text-slate-400 leading-relaxed line-clamp-4">{p.description}</p>
      )}
      {p.ceo && (
        <div className="text-xs text-slate-500">CEO: <span className="text-slate-300">{p.ceo}</span></div>
      )}
    </div>
  );
}

function MetricsPanel({ symbol }: { symbol: string }) {
  const { data, loading, error } = useFmpData<FmpMetrics>("key-metrics", symbol, { limit: 1 });
  const m = data[0] as FmpMetrics | undefined;

  const tiles = m ? [
    { label: "P/E Ratio",      value: fmt(m.peRatio, 1),           color: "text-slate-200" },
    { label: "EV/EBITDA",      value: fmt(m.evToEbitda, 1),        color: "text-slate-200" },
    { label: "P/B Ratio",      value: fmt(m.priceToBook, 1),       color: "text-slate-200" },
    { label: "ROE",            value: pct(m.returnOnEquity),       color: (m.returnOnEquity ?? 0) > 0.15 ? "text-emerald-400" : "text-slate-200" },
    { label: "ROA",            value: pct(m.returnOnAssets),       color: (m.returnOnAssets ?? 0) > 0.05 ? "text-emerald-400" : "text-slate-200" },
    { label: "Gross Margin",   value: pct(m.grossProfitMargin),    color: "text-slate-200" },
    { label: "Net Margin",     value: pct(m.netProfitMargin),      color: (m.netProfitMargin ?? 0) > 0.15 ? "text-emerald-400" : "text-slate-200" },
    { label: "Debt/Equity",    value: fmt(m.debtToEquity, 2),      color: (m.debtToEquity ?? 0) > 2 ? "text-red-400" : "text-slate-200" },
    { label: "FCF Yield",      value: pct(m.freeCashFlowYield),    color: (m.freeCashFlowYield ?? 0) > 0.04 ? "text-emerald-400" : "text-slate-200" },
  ] : [];

  return (
    <div className="glass rounded-2xl p-5">
      <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-4">Key Metrics</h2>
      {loading && <div className="text-xs text-slate-500 flex items-center gap-2"><RefreshCw className="w-3 h-3 animate-spin" /> Loading…</div>}
      {error   && <div className="text-xs text-amber-400 flex items-center gap-2"><AlertCircle className="w-3 h-3" />{error}</div>}
      {m && (
        <div className="grid grid-cols-3 gap-2">
          {tiles.map((t) => <MetricTile key={t.label} {...t} />)}
        </div>
      )}
      {!loading && !error && !m && (
        <p className="text-xs text-slate-500">No metrics available for this symbol.</p>
      )}
    </div>
  );
}

function AnalystPanel({ symbol }: { symbol: string }) {
  const rec = useFmpData<FmpRecommendation>("analyst-stock-recommendations", symbol, { limit: 1 });
  const pt  = useFmpData<FmpPriceTarget>("price-target-consensus", symbol);

  const r = rec.data[0] as FmpRecommendation | undefined;
  const p = pt.data[0] as FmpPriceTarget | undefined;

  const total = r ? r.strongBuy + r.buy + r.hold + r.sell + r.strongSell : 0;
  const bullish = r ? r.strongBuy + r.buy : 0;
  const bearish = r ? r.sell + r.strongSell : 0;

  const loading = rec.loading || pt.loading;
  const error   = rec.error   || pt.error;

  return (
    <div className="glass rounded-2xl p-5">
      <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-4">Analyst Consensus</h2>
      {loading && <div className="text-xs text-slate-500 flex items-center gap-2"><RefreshCw className="w-3 h-3 animate-spin" /> Loading…</div>}
      {error   && <div className="text-xs text-amber-400 flex items-center gap-2"><AlertCircle className="w-3 h-3" />{error}</div>}

      {r && total > 0 && (
        <div className="space-y-3">
          {/* Stacked bar */}
          <div className="flex rounded-lg overflow-hidden h-3">
            {[
              { n: r.strongBuy,   color: "bg-emerald-500" },
              { n: r.buy,         color: "bg-emerald-400/70" },
              { n: r.hold,        color: "bg-amber-400/70" },
              { n: r.sell,        color: "bg-red-400/70" },
              { n: r.strongSell,  color: "bg-red-600" },
            ].map(({ n, color }, i) => n > 0 ? (
              <div
                key={i}
                className={color}
                style={{ width: `${(n / total) * 100}%` }}
              />
            ) : null)}
          </div>
          <div className="flex justify-between text-[10px] font-mono">
            <span className="text-emerald-400">{bullish} Buy ({((bullish / total) * 100).toFixed(0)}%)</span>
            <span className="text-amber-400">{r.hold} Hold</span>
            <span className="text-red-400">{bearish} Sell ({((bearish / total) * 100).toFixed(0)}%)</span>
          </div>
          <div className="text-[10px] text-slate-600">{total} analyst{total !== 1 ? "s" : ""} · {r.date}</div>
        </div>
      )}

      {p && (
        <div className="grid grid-cols-2 gap-2 mt-4">
          <MetricTile label="Target Mean"   value={`$${fmt(p.targetMean, 2)}`}   color="text-brand-400" />
          <MetricTile label="Target Median" value={`$${fmt(p.targetMedian, 2)}`} color="text-brand-400" />
          <MetricTile label="Target High"   value={`$${fmt(p.targetHigh, 2)}`}   color="text-emerald-400" />
          <MetricTile label="Target Low"    value={`$${fmt(p.targetLow, 2)}`}    color="text-red-400" />
        </div>
      )}

      {!loading && !error && !r && !p && (
        <p className="text-xs text-slate-500">No analyst data available for this symbol.</p>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function ResearchPage() {
  const [symbol, setSymbol] = useState("AAPL");
  const { tabs: brokerTabs } = useBrokerAssets();
  const tv = tvSymbol(symbol);

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <h1 className="text-lg font-semibold flex items-center gap-2">
          <Search className="w-5 h-5 text-brand-400" />
          Research
        </h1>
        <div className="text-xs text-slate-500 font-mono">
          Powered by Financial Modeling Prep · TradingView
        </div>
      </div>

      <SymbolSelector value={symbol} onChange={setSymbol} enabledTabs={brokerTabs} />

      {/* Top row: profile left, metrics + analyst right */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ProfilePanel symbol={symbol} />
        <div className="space-y-4">
          <MetricsPanel  symbol={symbol} />
          <AnalystPanel  symbol={symbol} />
        </div>
      </div>

      {/* TradingView Financials — income / balance / cash flow */}
      <div className="glass rounded-2xl p-5">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-4">
          Financial Statements · {symbol}
        </h2>
        <TradingViewFinancials tvSymbol={tv} height={550} />
        <p className="text-[10px] text-slate-600 mt-3 text-center">
          Financial statements data via TradingView. Fundamental metrics via{" "}
          <a
            href="https://financialmodelingprep.com"
            target="_blank"
            rel="noreferrer"
            className="underline hover:text-slate-400"
          >
            Financial Modeling Prep
          </a>.
          Add your own FMP key in <span className="text-slate-400">Settings → Research Data</span> for higher limits.
        </p>
      </div>
    </div>
  );
}
