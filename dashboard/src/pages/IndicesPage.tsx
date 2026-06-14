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

// TradingView MiniChart widget cannot embed pure index/futures symbols (TVC:, CBOE:, NYMEX:, NSE:).
// All tv_symbol values use embeddable ETF exchange:ticker that tracks the underlying index.
const INDEX_GROUPS: IndexGroup[] = [
  {
    id: "us_broad",
    label: "US Broad Market",
    color: "text-brand-400 bg-brand-500/10 border-brand-500/20",
    entries: [
      { name: "S&P 500",            tv_symbol: "AMEX:SPY",     etf_proxy: "SPY",   description: "500 largest US companies by market cap" },
      { name: "NASDAQ 100",         tv_symbol: "NASDAQ:QQQ",   etf_proxy: "QQQ",   description: "100 largest non-financial NASDAQ companies" },
      { name: "Dow Jones",          tv_symbol: "AMEX:DIA",     etf_proxy: "DIA",   description: "30 blue-chip US industrial companies" },
      { name: "Russell 2000",       tv_symbol: "AMEX:IWM",     etf_proxy: "IWM",   description: "2000 small-cap US companies" },
      { name: "Total US Market",    tv_symbol: "AMEX:VTI",     etf_proxy: "VTI",   description: "Entire US stock market (~4000 companies)" },
      { name: "S&P Equal Weight",   tv_symbol: "AMEX:RSP",     etf_proxy: "RSP",   description: "Equal-weighted S&P 500 — reduces mega-cap bias" },
      { name: "S&P 500 Growth",     tv_symbol: "AMEX:IVW",     etf_proxy: "IVW",   description: "iShares S&P 500 Growth — high P/E, high momentum" },
      { name: "S&P 500 Value",      tv_symbol: "AMEX:IVE",     etf_proxy: "IVE",   description: "iShares S&P 500 Value — low P/B, low P/E stocks" },
      { name: "S&P MidCap 400",     tv_symbol: "AMEX:MDY",     etf_proxy: "MDY",   description: "Mid-cap US companies ($2B–$10B market cap)" },
      { name: "S&P SmallCap 600",   tv_symbol: "AMEX:IJR",     etf_proxy: "IJR",   description: "Small-cap US companies with quality screen" },
      { name: "Total World",        tv_symbol: "AMEX:VT",      etf_proxy: "VT",    description: "Vanguard Total World — US + international equities" },
      { name: "Extended Market",    tv_symbol: "AMEX:VXF",     etf_proxy: "VXF",   description: "Mid + small + micro cap ex-S&P 500" },
    ],
  },
  {
    id: "us_sectors",
    label: "US Sectors",
    color: "text-violet-400 bg-violet-500/10 border-violet-500/20",
    entries: [
      { name: "Technology",         tv_symbol: "AMEX:XLK",     etf_proxy: "XLK",   description: "S&P 500 Technology sector" },
      { name: "Financials",         tv_symbol: "AMEX:XLF",     etf_proxy: "XLF",   description: "S&P 500 Financials sector" },
      { name: "Healthcare",         tv_symbol: "AMEX:XLV",     etf_proxy: "XLV",   description: "S&P 500 Healthcare sector" },
      { name: "Energy",             tv_symbol: "AMEX:XLE",     etf_proxy: "XLE",   description: "S&P 500 Energy sector" },
      { name: "Industrials",        tv_symbol: "AMEX:XLI",     etf_proxy: "XLI",   description: "S&P 500 Industrials sector" },
      { name: "Consumer Discr.",    tv_symbol: "AMEX:XLY",     etf_proxy: "XLY",   description: "S&P 500 Consumer Discretionary sector" },
      { name: "Consumer Staples",   tv_symbol: "AMEX:XLP",     etf_proxy: "XLP",   description: "S&P 500 Consumer Staples sector" },
      { name: "Utilities",          tv_symbol: "AMEX:XLU",     etf_proxy: "XLU",   description: "S&P 500 Utilities sector" },
      { name: "Real Estate",        tv_symbol: "AMEX:XLRE",    etf_proxy: "XLRE",  description: "S&P 500 Real Estate sector (REITs)" },
      { name: "Materials",          tv_symbol: "AMEX:XLB",     etf_proxy: "XLB",   description: "S&P 500 Materials sector" },
      { name: "Comm Services",      tv_symbol: "AMEX:XLC",     etf_proxy: "XLC",   description: "S&P 500 Communication Services sector" },
      { name: "Semiconductors",     tv_symbol: "NASDAQ:SOXX",  etf_proxy: "SOXX",  description: "Philadelphia Semiconductor Index (iShares)" },
    ],
  },
  {
    id: "us_subsectors",
    label: "US Sub-Sectors",
    color: "text-purple-400 bg-purple-500/10 border-purple-500/20",
    entries: [
      { name: "Biotech",            tv_symbol: "AMEX:XBI",     etf_proxy: "XBI",   description: "SPDR S&P Biotech — equal-weight biotech" },
      { name: "Pharma/Biotech",     tv_symbol: "AMEX:IBB",     etf_proxy: "IBB",   description: "iShares Nasdaq Biotechnology Index" },
      { name: "Pharmaceuticals",    tv_symbol: "AMEX:PJP",     etf_proxy: "PJP",   description: "Invesco Dynamic Pharmaceuticals ETF" },
      { name: "Software",           tv_symbol: "NASDAQ:IGV",   etf_proxy: "IGV",   description: "iShares Expanded Tech-Software Sector" },
      { name: "Cloud Computing",    tv_symbol: "NASDAQ:WCLD",  etf_proxy: "WCLD",  description: "WisdomTree Cloud Computing — SaaS companies" },
      { name: "Cybersecurity",      tv_symbol: "NASDAQ:CIBR",  etf_proxy: "CIBR",  description: "First Trust Nasdaq Cybersecurity ETF" },
      { name: "Robotics & AI",      tv_symbol: "NASDAQ:BOTZ",  etf_proxy: "BOTZ",  description: "Global X Robotics & Artificial Intelligence" },
      { name: "Oil & Gas E&P",      tv_symbol: "AMEX:XOP",     etf_proxy: "XOP",   description: "SPDR S&P Oil & Gas Exploration & Production" },
      { name: "Aerospace/Defense",  tv_symbol: "AMEX:ITA",     etf_proxy: "ITA",   description: "iShares US Aerospace & Defense ETF" },
      { name: "Regional Banks",     tv_symbol: "AMEX:KRE",     etf_proxy: "KRE",   description: "SPDR S&P Regional Banking ETF" },
      { name: "Homebuilders",       tv_symbol: "AMEX:ITB",     etf_proxy: "ITB",   description: "iShares U.S. Home Construction ETF" },
      { name: "Airlines",           tv_symbol: "AMEX:JETS",    etf_proxy: "JETS",  description: "US Global Jets ETF — airline industry" },
    ],
  },
  {
    id: "volatility",
    label: "Volatility",
    color: "text-red-400 bg-red-500/10 border-red-500/20",
    entries: [
      { name: "Long VIX (UVXY)",    tv_symbol: "AMEX:UVXY",    etf_proxy: "UVXY",  description: "ProShares Ultra VIX — 1.5× short-term VIX futures" },
      { name: "VIX Short-Term",     tv_symbol: "AMEX:VIXY",    etf_proxy: "VIXY",  description: "ProShares VIX Short-Term Futures ETF" },
      { name: "VIX Med-Term",       tv_symbol: "AMEX:VIXM",    etf_proxy: "VIXM",  description: "ProShares VIX Mid-Term Futures ETF" },
      { name: "VIX Futures (VXX)",  tv_symbol: "AMEX:VXX",     etf_proxy: "VXX",   description: "iPath Series B S&P 500 VIX Short-Term Futures" },
      { name: "Inverse VIX",        tv_symbol: "AMEX:SVXY",    etf_proxy: "SVXY",  description: "Short VIX — profits when markets are calm" },
      { name: "3× S&P (leveraged)", tv_symbol: "AMEX:SPXL",    etf_proxy: "SPXL",  description: "Direxion 3× S&P 500 Bull — high-beta volatility" },
    ],
  },
  {
    id: "fixed_income",
    label: "Fixed Income",
    color: "text-sky-400 bg-sky-500/10 border-sky-500/20",
    entries: [
      { name: "20+ Yr Treasury",    tv_symbol: "NASDAQ:TLT",   etf_proxy: "TLT",   description: "iShares 20+ Year Treasury Bond ETF" },
      { name: "7–10 Yr Treasury",   tv_symbol: "NASDAQ:IEF",   etf_proxy: "IEF",   description: "iShares 7–10 Year Treasury Bond ETF" },
      { name: "1–3 Yr Treasury",    tv_symbol: "NASDAQ:SHY",   etf_proxy: "SHY",   description: "iShares 1–3 Year Treasury Bond ETF" },
      { name: "Ultra Long Bond",    tv_symbol: "AMEX:EDV",     etf_proxy: "EDV",   description: "Vanguard Extended Duration Treasury (25+ yr)" },
      { name: "US Agg Bond",        tv_symbol: "NASDAQ:AGG",   etf_proxy: "AGG",   description: "iShares Core US Aggregate Bond Market" },
      { name: "Total Bond Market",  tv_symbol: "NASDAQ:BND",   etf_proxy: "BND",   description: "Vanguard Total Bond Market ETF" },
      { name: "Inv-Grade Corp",     tv_symbol: "NASDAQ:LQD",   etf_proxy: "LQD",   description: "iShares iBoxx Investment Grade Corporate Bond" },
      { name: "High Yield Corp",    tv_symbol: "NASDAQ:HYG",   etf_proxy: "HYG",   description: "iShares iBoxx High Yield Corporate Bond" },
      { name: "TIPS (Inflation)",   tv_symbol: "NASDAQ:TIP",   etf_proxy: "TIP",   description: "iShares TIPS Bond — inflation-protected Treasuries" },
      { name: "EM Bonds",           tv_symbol: "NASDAQ:EMB",   etf_proxy: "EMB",   description: "iShares J.P. Morgan USD Emerging Markets Bond" },
      { name: "Muni Bonds",         tv_symbol: "NASDAQ:MUB",   etf_proxy: "MUB",   description: "iShares National Muni Bond ETF" },
      { name: "Bank Loans (BKLN)",  tv_symbol: "AMEX:BKLN",   etf_proxy: "BKLN",  description: "Invesco Senior Loan ETF — floating rate loans" },
    ],
  },
  {
    id: "macro",
    label: "Macro & FX",
    color: "text-cyan-400 bg-cyan-500/10 border-cyan-500/20",
    entries: [
      { name: "US Dollar (UUP)",    tv_symbol: "AMEX:UUP",     etf_proxy: "UUP",   description: "Invesco DB US Dollar Index Bullish — DXY proxy" },
      { name: "Euro (FXE)",         tv_symbol: "AMEX:FXE",     etf_proxy: "FXE",   description: "Invesco CurrencyShares Euro ETF" },
      { name: "Japanese Yen (FXY)", tv_symbol: "AMEX:FXY",     etf_proxy: "FXY",   description: "Invesco CurrencyShares Japanese Yen ETF" },
      { name: "British Pound (FXB)",tv_symbol: "AMEX:FXB",     etf_proxy: "FXB",   description: "Invesco CurrencyShares British Pound ETF" },
      { name: "Swiss Franc (FXF)",  tv_symbol: "AMEX:FXF",     etf_proxy: "FXF",   description: "Invesco CurrencyShares Swiss Franc ETF" },
      { name: "Australian $ (FXA)", tv_symbol: "AMEX:FXA",     etf_proxy: "FXA",   description: "Invesco CurrencyShares Australian Dollar ETF" },
      { name: "Gold (GLD)",         tv_symbol: "AMEX:GLD",     etf_proxy: "GLD",   description: "SPDR Gold Shares — gold spot price proxy" },
      { name: "Silver (SLV)",       tv_symbol: "AMEX:SLV",     etf_proxy: "SLV",   description: "iShares Silver Trust — silver spot proxy" },
    ],
  },
  {
    id: "factor",
    label: "Factor & Dividend",
    color: "text-teal-400 bg-teal-500/10 border-teal-500/20",
    entries: [
      { name: "Dividend Growth",    tv_symbol: "NASDAQ:VIG",   etf_proxy: "VIG",   description: "Vanguard Dividend Appreciation ETF" },
      { name: "High Dividend",      tv_symbol: "AMEX:VYM",     etf_proxy: "VYM",   description: "Vanguard High Dividend Yield ETF" },
      { name: "Schwab Dividend",    tv_symbol: "AMEX:SCHD",    etf_proxy: "SCHD",  description: "Schwab US Dividend Equity — quality screen" },
      { name: "Dividend Aristocrats",tv_symbol: "AMEX:NOBL",   etf_proxy: "NOBL",  description: "ProShares S&P 500 Dividend Aristocrats (25+ yr growers)" },
      { name: "Quality Factor",     tv_symbol: "AMEX:QUAL",    etf_proxy: "QUAL",  description: "iShares MSCI USA Quality Factor ETF" },
      { name: "Momentum Factor",    tv_symbol: "AMEX:MTUM",    etf_proxy: "MTUM",  description: "iShares MSCI USA Momentum Factor ETF" },
      { name: "Low Volatility",     tv_symbol: "AMEX:USMV",    etf_proxy: "USMV",  description: "iShares MSCI USA Min Vol Factor ETF" },
      { name: "Value Factor",       tv_symbol: "AMEX:RPV",     etf_proxy: "RPV",   description: "Invesco S&P 500 Pure Value ETF" },
      { name: "High Beta",          tv_symbol: "AMEX:SPHB",    etf_proxy: "SPHB",  description: "Invesco S&P 500 High Beta ETF" },
      { name: "Div + Buybacks",     tv_symbol: "AMEX:COWZ",    etf_proxy: "COWZ",  description: "Pacer US Cash Cows 100 — high free cash flow" },
    ],
  },
  {
    id: "thematic",
    label: "Thematic & Innovation",
    color: "text-fuchsia-400 bg-fuchsia-500/10 border-fuchsia-500/20",
    entries: [
      { name: "ARK Innovation",     tv_symbol: "AMEX:ARKK",    etf_proxy: "ARKK",  description: "ARK Innovation ETF — disruptive tech companies" },
      { name: "ARK Genomics",       tv_symbol: "AMEX:ARKG",    etf_proxy: "ARKG",  description: "ARK Genomic Revolution — biotech & gene editing" },
      { name: "ARK Autonomous",     tv_symbol: "AMEX:ARKQ",    etf_proxy: "ARKQ",  description: "ARK Autonomous Technology & Robotics ETF" },
      { name: "ARK FinTech",        tv_symbol: "AMEX:ARKF",    etf_proxy: "ARKF",  description: "ARK Fintech Innovation ETF" },
      { name: "Bitcoin ETF (IBIT)", tv_symbol: "NASDAQ:IBIT",  etf_proxy: "IBIT",  description: "iShares Bitcoin Trust — spot Bitcoin ETF" },
      { name: "Clean Energy",       tv_symbol: "NASDAQ:ICLN",  etf_proxy: "ICLN",  description: "iShares Global Clean Energy ETF" },
      { name: "EV & Future Moblty", tv_symbol: "AMEX:DRIV",    etf_proxy: "DRIV",  description: "Global X Autonomous & Electric Vehicles ETF" },
      { name: "Lithium & Battery",  tv_symbol: "AMEX:LIT",     etf_proxy: "LIT",   description: "Global X Lithium & Battery Tech ETF" },
      { name: "Blockchain",         tv_symbol: "NASDAQ:BLOK",  etf_proxy: "BLOK",  description: "Amplify Transformational Data Sharing ETF" },
      { name: "Metaverse",          tv_symbol: "AMEX:METV",    etf_proxy: "METV",  description: "Roundhill Ball Metaverse ETF" },
      { name: "Infrastructure",     tv_symbol: "AMEX:PAVE",    etf_proxy: "PAVE",  description: "Global X US Infrastructure Development ETF" },
      { name: "Space Exploration",  tv_symbol: "AMEX:UFO",     etf_proxy: "UFO",   description: "Procure Space ETF — satellite & space industry" },
    ],
  },
  {
    id: "international",
    label: "International",
    color: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
    entries: [
      { name: "Dev. Mkts ex-US",    tv_symbol: "NASDAQ:VEA",   etf_proxy: "VEA",   description: "Vanguard FTSE Developed ex-US Markets" },
      { name: "All-World ex-US",    tv_symbol: "AMEX:VEU",     etf_proxy: "VEU",   description: "Vanguard FTSE All-World ex-US ETF" },
      { name: "Emerging Markets",   tv_symbol: "AMEX:EEM",     etf_proxy: "EEM",   description: "iShares MSCI Emerging Markets" },
      { name: "FTSE 100 (UK)",      tv_symbol: "AMEX:EWU",     etf_proxy: "EWU",   description: "iShares MSCI United Kingdom — FTSE 100 proxy" },
      { name: "DAX 40 (Germany)",   tv_symbol: "AMEX:EWG",     etf_proxy: "EWG",   description: "iShares MSCI Germany — DAX 40 proxy" },
      { name: "Nikkei 225 (Japan)", tv_symbol: "AMEX:EWJ",     etf_proxy: "EWJ",   description: "iShares MSCI Japan — Nikkei 225 proxy" },
      { name: "Euro Stoxx 50",      tv_symbol: "AMEX:FEZ",     etf_proxy: "FEZ",   description: "SPDR Euro Stoxx 50 — top Eurozone blue-chips" },
      { name: "CAC 40 (France)",    tv_symbol: "AMEX:EWQ",     etf_proxy: "EWQ",   description: "iShares MSCI France — CAC 40 proxy" },
      { name: "Hang Seng (HK)",     tv_symbol: "AMEX:EWH",     etf_proxy: "EWH",   description: "iShares MSCI Hong Kong — Hang Seng proxy" },
      { name: "China Large Cap",    tv_symbol: "AMEX:MCHI",    etf_proxy: "MCHI",  description: "iShares MSCI China ETF" },
      { name: "China A-Shares",     tv_symbol: "AMEX:ASHR",    etf_proxy: "ASHR",  description: "Xtrackers Harvest CSI 300 China A-Shares" },
      { name: "India (Nifty 50)",   tv_symbol: "AMEX:INDA",    etf_proxy: "INDA",  description: "iShares MSCI India — Nifty 50 proxy" },
      { name: "Taiwan",             tv_symbol: "AMEX:EWT",     etf_proxy: "EWT",   description: "iShares MSCI Taiwan — weighted toward TSM" },
      { name: "South Korea",        tv_symbol: "AMEX:EWY",     etf_proxy: "EWY",   description: "iShares MSCI South Korea — KOSPI proxy" },
      { name: "Brazil",             tv_symbol: "AMEX:EWZ",     etf_proxy: "EWZ",   description: "iShares MSCI Brazil ETF — Bovespa proxy" },
      { name: "Canada",             tv_symbol: "AMEX:EWC",     etf_proxy: "EWC",   description: "iShares MSCI Canada ETF — TSX proxy" },
    ],
  },
  {
    id: "commodities",
    label: "Commodities",
    color: "text-orange-400 bg-orange-500/10 border-orange-500/20",
    entries: [
      { name: "Gold",               tv_symbol: "AMEX:GLD",     etf_proxy: "GLD",   description: "SPDR Gold Shares — gold spot price proxy" },
      { name: "Silver",             tv_symbol: "AMEX:SLV",     etf_proxy: "SLV",   description: "iShares Silver Trust — silver spot proxy" },
      { name: "Gold Miners",        tv_symbol: "AMEX:GDX",     etf_proxy: "GDX",   description: "VanEck Gold Miners ETF — senior gold producers" },
      { name: "Junior Gold Miners", tv_symbol: "AMEX:GDXJ",    etf_proxy: "GDXJ",  description: "VanEck Junior Gold Miners — higher-risk exposure" },
      { name: "Silver Miners",      tv_symbol: "AMEX:SIL",     etf_proxy: "SIL",   description: "Global X Silver Miners ETF" },
      { name: "Crude Oil (WTI)",    tv_symbol: "AMEX:USO",     etf_proxy: "USO",   description: "United States Oil Fund — WTI crude proxy" },
      { name: "Natural Gas",        tv_symbol: "AMEX:UNG",     etf_proxy: "UNG",   description: "United States Natural Gas Fund" },
      { name: "Uranium",            tv_symbol: "AMEX:URA",     etf_proxy: "URA",   description: "Global X Uranium ETF — nuclear fuel cycle" },
      { name: "Copper",             tv_symbol: "AMEX:CPER",    etf_proxy: "CPER",  description: "United States Copper Index Fund" },
      { name: "Agriculture",        tv_symbol: "AMEX:DBA",     etf_proxy: "DBA",   description: "Invesco DB Agriculture Fund — grains & softs" },
      { name: "Agribusiness",       tv_symbol: "AMEX:MOO",     etf_proxy: "MOO",   description: "VanEck Agribusiness ETF — food supply chain" },
      { name: "Broad Commodities",  tv_symbol: "AMEX:PDBC",    etf_proxy: "PDBC",  description: "Invesco Optimum Yield Diversified Commodity" },
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
