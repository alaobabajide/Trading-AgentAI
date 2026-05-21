import { useState } from "react";
import { BarChart3, Brain, ChevronRight, Loader2, Send } from "lucide-react";
import clsx from "clsx";
import { TradingViewMiniChart } from "../components/TradingViewMiniChart";
import { SignalCard } from "../components/SignalCard";
import { apiHeaders } from "../lib/api";
import type { Signal } from "../lib/types";
import type { TvSymbol } from "../lib/tradingview";

// ── Index catalogue ────────────────────────────────────────────────────────────

interface IndexEntry {
  name: string;
  tv_symbol: string;
  etf_proxy: string;
  description: string;
}

interface IndexGroup {
  id: string;
  label: string;
  color: string;
  entries: IndexEntry[];
}

const INDEX_GROUPS: IndexGroup[] = [
  {
    id: "us_broad",
    label: "US Broad Market",
    color: "text-brand-400 bg-brand-500/10 border-brand-500/20",
    entries: [
      { name: "S&P 500",           tv_symbol: "TVC:SPX",    etf_proxy: "SPY",  description: "500 largest US companies by market cap" },
      { name: "NASDAQ 100",        tv_symbol: "TVC:NDX",    etf_proxy: "QQQ",  description: "100 largest non-financial NASDAQ companies" },
      { name: "Dow Jones",         tv_symbol: "TVC:DJI",    etf_proxy: "DIA",  description: "30 blue-chip US industrial companies" },
      { name: "Russell 2000",      tv_symbol: "TVC:RUT",    etf_proxy: "IWM",  description: "2000 small-cap US companies" },
      { name: "S&P Equal Weight",  tv_symbol: "TVC:SPX",    etf_proxy: "RSP",  description: "Equal-weighted S&P 500 — less mega-cap bias" },
      { name: "Total US Market",   tv_symbol: "TVC:WILLR",  etf_proxy: "VTI",  description: "Entire US stock market (~4000 companies)" },
      { name: "S&P MidCap 400",    tv_symbol: "TVC:SPX",    etf_proxy: "MDY",  description: "Mid-cap US companies ($2B–$10B market cap)" },
      { name: "S&P SmallCap 600",  tv_symbol: "TVC:RUT",    etf_proxy: "IJR",  description: "Small-cap US companies with quality screen" },
    ],
  },
  {
    id: "volatility",
    label: "Volatility & Fear",
    color: "text-red-400 bg-red-500/10 border-red-500/20",
    entries: [
      { name: "VIX (Fear Index)",  tv_symbol: "CBOE:VIX",   etf_proxy: "UVXY", description: "CBOE Volatility Index — 30-day S&P 500 implied vol" },
      { name: "VIX Short-Term",    tv_symbol: "CBOE:VIX",   etf_proxy: "VIXY", description: "Short-term VIX futures — pure volatility exposure" },
      { name: "NASDAQ Volatility", tv_symbol: "CBOE:VXN",   etf_proxy: "QQQ",  description: "NASDAQ 100 implied volatility index" },
      { name: "Inverse VIX",       tv_symbol: "CBOE:VIX",   etf_proxy: "SVXY", description: "Short VIX — profits when markets are calm" },
    ],
  },
  {
    id: "macro",
    label: "Macro & Rates",
    color: "text-sky-400 bg-sky-500/10 border-sky-500/20",
    entries: [
      { name: "US 10-Year Yield",  tv_symbol: "TVC:US10Y",  etf_proxy: "TLT",  description: "10-yr US Treasury yield — long bond benchmark" },
      { name: "US 2-Year Yield",   tv_symbol: "TVC:US02Y",  etf_proxy: "SHY",  description: "2-yr US Treasury yield — Fed policy sensitive" },
      { name: "US 7-10 Year",      tv_symbol: "TVC:US10Y",  etf_proxy: "IEF",  description: "Intermediate Treasury ETF — yield curve proxy" },
      { name: "US Dollar Index",   tv_symbol: "TVC:DXY",    etf_proxy: "UUP",  description: "USD strength vs EUR, JPY, GBP, CAD, SEK, CHF" },
      { name: "Agg Bond Market",   tv_symbol: "TVC:US10Y",  etf_proxy: "AGG",  description: "US investment-grade bond market aggregate" },
      { name: "High Yield Bonds",  tv_symbol: "TVC:US10Y",  etf_proxy: "HYG",  description: "High-yield bonds — credit risk barometer" },
      { name: "TIPS (Inflation)",  tv_symbol: "TVC:US10Y",  etf_proxy: "TIP",  description: "Treasury inflation-protected securities" },
    ],
  },
  {
    id: "us_sector",
    label: "US Sectors",
    color: "text-violet-400 bg-violet-500/10 border-violet-500/20",
    entries: [
      { name: "Technology",        tv_symbol: "AMEX:XLK",   etf_proxy: "XLK",  description: "S&P 500 Technology sector" },
      { name: "Financials",        tv_symbol: "AMEX:XLF",   etf_proxy: "XLF",  description: "S&P 500 Financials sector" },
      { name: "Healthcare",        tv_symbol: "AMEX:XLV",   etf_proxy: "XLV",  description: "S&P 500 Healthcare sector" },
      { name: "Energy",            tv_symbol: "AMEX:XLE",   etf_proxy: "XLE",  description: "S&P 500 Energy sector" },
      { name: "Industrials",       tv_symbol: "AMEX:XLI",   etf_proxy: "XLI",  description: "S&P 500 Industrials sector" },
      { name: "Consumer Discr.",   tv_symbol: "AMEX:XLY",   etf_proxy: "XLY",  description: "S&P 500 Consumer Discretionary sector" },
      { name: "Consumer Staples",  tv_symbol: "AMEX:XLP",   etf_proxy: "XLP",  description: "S&P 500 Consumer Staples sector" },
      { name: "Utilities",         tv_symbol: "AMEX:XLU",   etf_proxy: "XLU",  description: "S&P 500 Utilities sector" },
      { name: "Real Estate",       tv_symbol: "AMEX:XLRE",  etf_proxy: "XLRE", description: "S&P 500 Real Estate sector (REITs)" },
      { name: "Materials",         tv_symbol: "AMEX:XLB",   etf_proxy: "XLB",  description: "S&P 500 Materials sector" },
      { name: "Comm Services",     tv_symbol: "AMEX:XLC",   etf_proxy: "XLC",  description: "S&P 500 Communication Services sector" },
      { name: "Semiconductors",    tv_symbol: "NASDAQ:SOXX",etf_proxy: "SOXX", description: "Philadelphia Semiconductor Index (iShares)" },
    ],
  },
  {
    id: "international",
    label: "International",
    color: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
    entries: [
      { name: "FTSE 100",          tv_symbol: "TVC:UKX",    etf_proxy: "EWU",  description: "UK top 100 large-cap companies" },
      { name: "DAX 40",            tv_symbol: "TVC:DAX",    etf_proxy: "EWG",  description: "German top 40 companies" },
      { name: "Nikkei 225",        tv_symbol: "TVC:NI225",  etf_proxy: "EWJ",  description: "Japan top 225 blue-chip companies" },
      { name: "Hang Seng",         tv_symbol: "TVC:HSI",    etf_proxy: "EWH",  description: "Hong Kong Hang Seng Index" },
      { name: "CAC 40",            tv_symbol: "TVC:CAC40",  etf_proxy: "EWQ",  description: "French top 40 companies" },
      { name: "Euro Stoxx 50",     tv_symbol: "TVC:SX5E",   etf_proxy: "FEZ",  description: "50 largest Eurozone blue-chips" },
      { name: "Dev. Mkts ex-US",   tv_symbol: "NASDAQ:VEA", etf_proxy: "VEA",  description: "Developed markets — Europe, Asia-Pacific, Canada" },
      { name: "Emerging Markets",  tv_symbol: "AMEX:EEM",   etf_proxy: "EEM",  description: "Emerging markets — China, India, Brazil, etc." },
      { name: "China Large Cap",   tv_symbol: "AMEX:MCHI",  etf_proxy: "MCHI", description: "iShares MSCI China ETF" },
      { name: "India (Nifty 50)",  tv_symbol: "NSE:NIFTY",  etf_proxy: "INDA", description: "iShares MSCI India ETF" },
    ],
  },
  {
    id: "commodities",
    label: "Commodities",
    color: "text-orange-400 bg-orange-500/10 border-orange-500/20",
    entries: [
      { name: "Gold",              tv_symbol: "TVC:GOLD",   etf_proxy: "GLD",  description: "Gold spot price (SPDR Gold Shares)" },
      { name: "Silver",            tv_symbol: "TVC:SILVER", etf_proxy: "SLV",  description: "Silver spot price (iShares Silver Trust)" },
      { name: "Crude Oil (WTI)",   tv_symbol: "NYMEX:CL1!", etf_proxy: "USO",  description: "WTI crude oil front-month futures proxy" },
      { name: "Natural Gas",       tv_symbol: "NYMEX:NG1!", etf_proxy: "UNG",  description: "Henry Hub natural gas front-month futures proxy" },
      { name: "Broad Commodities", tv_symbol: "TVC:BCOM",   etf_proxy: "PDBC", description: "Bloomberg Commodity Index — diversified basket" },
      { name: "Copper",            tv_symbol: "COMEX:HG1!", etf_proxy: "CPER", description: "Copper — leading economic cycle indicator" },
    ],
  },
];

// ── Signal runner ──────────────────────────────────────────────────────────────

interface SignalState {
  symbol: string;
  loading: boolean;
  signal: Signal | null;
  error: string | null;
}

async function runSignal(etfProxy: string, paperMode: boolean): Promise<Signal> {
  const resp = await fetch("/api/signal", {
    method: "POST",
    headers: apiHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ symbol: etfProxy, asset_class: "stock", paper_mode: paperMode }),
    signal: AbortSignal.timeout(120_000),
  });
  const text = await resp.text();
  if (!text) throw new Error(`HTTP ${resp.status}`);
  const data = JSON.parse(text);
  if (!resp.ok) throw new Error(data?.detail ?? `HTTP ${resp.status}`);
  return data as Signal;
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function IndexCard({
  entry,
  signalState,
  onAnalyse,
}: {
  entry: IndexEntry;
  signalState: SignalState | undefined;
  onAnalyse: (entry: IndexEntry) => void;
}) {
  const sym: TvSymbol = {
    tv: entry.tv_symbol,
    label: entry.name,
    group: "Indices",
    description: entry.description,
  };

  const isLoading = signalState?.symbol === entry.etf_proxy && signalState.loading;

  return (
    <div className="glass rounded-2xl overflow-hidden flex flex-col">
      {/* Mini chart */}
      <div style={{ height: 140 }}>
        <TradingViewMiniChart sym={sym} />
      </div>

      {/* Info */}
      <div className="px-4 py-3 flex flex-col gap-2">
        <div>
          <div className="font-mono font-semibold text-sm">{entry.name}</div>
          <div className="text-[10px] text-slate-500 mt-0.5 leading-tight">{entry.description}</div>
        </div>

        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-1.5">
            <span className="text-[9px] text-slate-600 uppercase tracking-wider">ETF proxy</span>
            <span className="font-mono font-bold text-xs text-slate-300 bg-surface-700 px-2 py-0.5 rounded-lg border border-white/5">
              {entry.etf_proxy}
            </span>
          </div>
          <button
            onClick={() => onAnalyse(entry)}
            disabled={isLoading}
            className={clsx(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-[11px] font-medium transition-colors",
              isLoading
                ? "bg-brand-500/10 text-brand-400 cursor-wait"
                : "bg-brand-600/80 hover:bg-brand-500 text-white",
            )}
          >
            {isLoading
              ? <Loader2 className="w-3 h-3 animate-spin" />
              : <Brain className="w-3 h-3" />
            }
            {isLoading ? "Analysing…" : "Analyse"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

interface IndicesPageProps {
  paperMode?: boolean;
}

export function IndicesPage({ paperMode = true }: IndicesPageProps) {
  const [activeGroup, setActiveGroup] = useState<string>("us_broad");
  const [signalStates, setSignalStates] = useState<Record<string, SignalState>>({});
  const [latestResult, setLatestResult] = useState<Signal | null>(null);

  const group = INDEX_GROUPS.find((g) => g.id === activeGroup) ?? INDEX_GROUPS[0];

  async function handleAnalyse(entry: IndexEntry) {
    const sym = entry.etf_proxy;
    setSignalStates((prev) => ({
      ...prev,
      [sym]: { symbol: sym, loading: true, signal: null, error: null },
    }));
    setLatestResult(null);

    try {
      const signal = await runSignal(sym, paperMode);
      setSignalStates((prev) => ({
        ...prev,
        [sym]: { symbol: sym, loading: false, signal, error: null },
      }));
      setLatestResult(signal);
    } catch (err) {
      const msg = (err as Error).message ?? "Network error";
      setSignalStates((prev) => ({
        ...prev,
        [sym]: { symbol: sym, loading: false, signal: null, error: msg },
      }));
    }
  }

  const hasAnyLoading = Object.values(signalStates).some((s) => s.loading);
  const errorState = Object.values(signalStates).find((s) => s.error);

  return (
    <div className="space-y-6 max-w-7xl">
      {/* Header */}
      <div>
        <h1 className="text-lg font-semibold flex items-center gap-2">
          <BarChart3 className="w-5 h-5 text-brand-400" />
          Market Indices
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Live index charts via TradingView. Click <strong className="text-slate-300">Analyse</strong> to run the Brain
          on the ETF proxy — all{" "}
          {paperMode ? "rule-based (paper mode)" : "full LLM (live mode)"}.
        </p>
        <div className={clsx(
          "inline-flex items-center gap-1.5 mt-2 px-2.5 py-1 rounded-lg text-[11px] font-mono font-semibold border",
          paperMode
            ? "bg-sky-500/10 border-sky-500/20 text-sky-400"
            : "bg-red-500/10 border-red-500/20 text-red-400",
        )}>
          <span className={clsx("w-1.5 h-1.5 rounded-full", paperMode ? "bg-sky-400" : "bg-red-400 animate-pulse")} />
          {paperMode ? "Paper mode — rule-based analysis" : "Live mode — full LLM debate"}
        </div>
      </div>

      {/* Category tabs */}
      <div className="flex flex-wrap gap-2">
        {INDEX_GROUPS.map((g) => (
          <button
            key={g.id}
            onClick={() => setActiveGroup(g.id)}
            className={clsx(
              "flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-medium transition-all border",
              activeGroup === g.id
                ? g.color
                : "text-slate-500 border-white/5 hover:text-slate-300 hover:border-white/10",
            )}
          >
            {g.label}
            <span className="text-[10px] opacity-60">{g.entries.length}</span>
          </button>
        ))}
      </div>

      {/* Index grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4 gap-4">
        {group.entries.map((entry) => (
          <IndexCard
            key={entry.etf_proxy + entry.tv_symbol}
            entry={entry}
            signalState={signalStates[entry.etf_proxy]}
            onAnalyse={handleAnalyse}
          />
        ))}
      </div>

      {/* Status / error */}
      {hasAnyLoading && (
        <div className="flex items-center gap-2 text-xs text-brand-400 font-mono bg-brand-500/10 border border-brand-500/20 rounded-xl px-4 py-3">
          <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" />
          Running Brain analysis — this takes 10–30 seconds in paper mode, longer in live mode…
        </div>
      )}

      {errorState && (
        <div className="rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm px-4 py-3 font-mono">
          <span className="font-semibold">Error on {errorState.symbol}:</span> {errorState.error}
        </div>
      )}

      {/* Latest signal result */}
      {latestResult && (
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <ChevronRight className="w-4 h-4 text-brand-400" />
            Latest Signal — {latestResult.symbol}
          </div>
          <SignalCard signal={latestResult} />
        </div>
      )}

      {/* All previous results for the active group */}
      {Object.values(signalStates).filter(
        (s) => s.signal && !s.loading && s.symbol !== latestResult?.symbol
          && group.entries.some((e) => e.etf_proxy === s.symbol),
      ).length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center gap-2 text-xs text-slate-500 font-mono uppercase tracking-wider">
            <Send className="w-3.5 h-3.5" />
            Previous signals (this session)
          </div>
          {Object.values(signalStates)
            .filter(
              (s) => s.signal && !s.loading && s.symbol !== latestResult?.symbol
                && group.entries.some((e) => e.etf_proxy === s.symbol),
            )
            .map((s) => (
              <SignalCard key={s.symbol} signal={s.signal!} />
            ))}
        </div>
      )}
    </div>
  );
}
