import { useState } from "react";
import { BookOpen } from "lucide-react";
import clsx from "clsx";
import { SymbolSelector } from "../components/SymbolSelector";
import { EarningsChart } from "../components/EarningsChart";
import { AnalystBar } from "../components/AnalystBar";
import { EtfHoldingsChart, SectorDonut } from "../components/EtfHoldingsChart";
import { useLiveData } from "../hooks/useLiveTick";
import {
  getFundamentals, getEarnings, getEtfData,
  generateCandles, ETF_LIST,
  type FundamentalMetrics, type EtfMetrics,
} from "../lib/marketMock";
import { LineChart, Line, YAxis, ResponsiveContainer } from "recharts";

// ── Agent views ───────────────────────────────────────────────────────────────

const AGENT_VIEWS: Record<string, { direction: string; reasoning: string }> = {
  AAPL:    { direction: "BEARISH",  reasoning: "Services growth decelerating YoY. iPhone unit sales miss consensus. RSI divergence suggests near-term correction risk. Recommend trimming exposure." },
  MSFT:    { direction: "BULLISH",  reasoning: "Azure revenue growth re-accelerating at 33% YoY driven by AI workloads. Copilot monetisation ahead of schedule. Strong FCF generation supports valuation premium." },
  NVDA:    { direction: "BULLISH",  reasoning: "Data-center GPU demand structurally elevated. Blackwell ramp beats expectations. Gross margins expanding to 75%+. NIM platform creates software moat." },
  TSLA:    { direction: "NEUTRAL",  reasoning: "EV price war compressing margins. FSD v12 shows promise but regulatory timeline uncertain. Energy storage segment offsetting auto weakness." },
  BTCUSDT: { direction: "BULLISH",  reasoning: "Post-halving supply shock historically precedes 6-18 month bull run. ETF net inflows consistently positive. BTC dominance rising." },
  ETHUSDT: { direction: "BULLISH",  reasoning: "Spot ETH ETF approval expected to unlock institutional demand. Staking yield ~4% creates natural floor demand. Layer-2 ecosystem expanding." },
  SPY:     { direction: "NEUTRAL",  reasoning: "S&P 500 at stretched valuations (P/E 24×) but earnings growth holding. Fed pivot narrative supportive near-term. Concentration risk in top-10 names elevated. Expect choppy sideways trading." },
  QQQ:     { direction: "BULLISH",  reasoning: "Nasdaq-100 driven by AI capex supercycle. Mega-cap tech earnings revisions trending higher. Momentum strong but RSI approaching overbought. Scale in on pullbacks." },
  IWM:     { direction: "BEARISH",  reasoning: "Small-caps face disproportionate headwind from higher-for-longer rates (float-rate debt exposure ~40%). Earnings revision breadth deteriorating. Prefer large-cap in this cycle." },
  GLD:     { direction: "BULLISH",  reasoning: "Gold breaking out above $2,300 on central bank accumulation and de-dollarisation trend. Real rates declining. Tactical hedge against geopolitical tail risk and dollar weakness." },
  TLT:     { direction: "NEUTRAL",  reasoning: "Long-duration Treasuries caught between sticky inflation and eventual Fed easing. Duration risk elevated. Current yield 4.2% attractive for risk-off portfolios; position sizing cautious." },
  XLK:     { direction: "BULLISH",  reasoning: "Tech sector earnings growth outpacing index. AI infrastructure spend concentrating in XLK top holdings (AAPL, MSFT, NVDA ~65% weight). Expense ratio advantage vs active funds." },
  EEM:     { direction: "NEUTRAL",  reasoning: "EM valuations cheap at 14× P/E but dollar strength and China structural headwinds offset. India and Mexico bright spots. High expense ratio (0.70%) a drag vs alternatives." },
};

// ── Shared sub-components ─────────────────────────────────────────────────────

function PriceSparkline({ symbol }: { symbol: string }) {
  const data = useLiveData(
    () => generateCandles(symbol, 30, Date.now()).map((c) => ({ v: c.close })),
    5000,
  );
  const start = data[0]?.v ?? 0;
  const end   = data[data.length - 1]?.v ?? 0;
  const up    = end >= start;
  const min   = Math.min(...data.map((d) => d.v));
  const max   = Math.max(...data.map((d) => d.v));
  return (
    <ResponsiveContainer width="100%" height={72}>
      <LineChart data={data} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
        <YAxis domain={[min * 0.995, max * 1.005]} hide />
        <Line dataKey="v" stroke={up ? "#10b981" : "#ef4444"} strokeWidth={1.5}
          dot={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

function RangeBar({ low, high, current }: { low: number; high: number; current: number }) {
  const pct = Math.min(100, Math.max(0, ((current - low) / (high - low)) * 100));
  return (
    <div className="space-y-1.5">
      <div className="relative h-2 bg-surface-700 rounded-full overflow-visible">
        <div className="absolute inset-0 rounded-full bg-gradient-to-r from-red-500 via-yellow-500 to-emerald-500 opacity-30" />
        <div className="absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full bg-white border-2 border-brand-500 shadow"
          style={{ left: `calc(${pct}% - 6px)` }} />
      </div>
      <div className="flex justify-between text-[10px] font-mono text-slate-500">
        <span>${low.toLocaleString()}</span>
        <span className="text-slate-400">52W Range</span>
        <span>${high.toLocaleString()}</span>
      </div>
    </div>
  );
}

function MetricCell({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="bg-surface-700 rounded-xl p-3 text-center">
      <div className="text-[9px] text-slate-500 uppercase tracking-wider leading-tight mb-1">{label}</div>
      <div className={clsx("text-sm font-mono font-semibold", color ?? "text-slate-200")}>{value}</div>
    </div>
  );
}

function AgentView({ symbol }: { symbol: string }) {
  const view = AGENT_VIEWS[symbol];
  if (!view) return null;
  return (
    <div className="glass rounded-2xl p-5 space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400">Agent View</h2>
        <span className={clsx(
          "text-[10px] font-mono font-semibold px-2 py-0.5 rounded",
          view.direction === "BULLISH" ? "bg-emerald-500/15 text-emerald-400"
          : view.direction === "BEARISH" ? "bg-red-500/15 text-red-400"
          : "bg-yellow-500/15 text-yellow-400",
        )}>
          {view.direction}
        </span>
      </div>
      <p className="text-xs text-slate-400 leading-relaxed">{view.reasoning}</p>
    </div>
  );
}

// ── ETF panel ─────────────────────────────────────────────────────────────────

function EtfPanel({ etf, priceLive }: { etf: EtfMetrics; priceLive: number }) {
  const upside = ((etf.nav - priceLive) / priceLive) * 100; // premium/discount to NAV

  return (
    <div className="space-y-5">
      {/* ETF identity */}
      <div className="glass rounded-2xl p-5 space-y-3">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h3 className="text-sm font-semibold text-slate-100">{etf.fullName}</h3>
            <p className="text-xs text-slate-500 mt-0.5">{etf.category} · {etf.issuer} · est. {etf.inceptionDate}</p>
          </div>
          <div className="text-right shrink-0">
            <div className="text-xs text-slate-500 font-mono">Benchmark</div>
            <div className="text-xs text-slate-300 font-mono">{etf.benchmark}</div>
          </div>
        </div>

        {/* Key ETF metrics */}
        <div className="grid grid-cols-4 sm:grid-cols-4 gap-2 pt-1">
          <MetricCell label="AUM" value={etf.aum} />
          <MetricCell label="Expense Ratio" value={`${etf.expenseRatio.toFixed(4)}%`}
            color={etf.expenseRatio < 0.2 ? "text-emerald-400" : etf.expenseRatio > 0.5 ? "text-red-400" : "text-yellow-400"} />
          <MetricCell label="Dist. Yield" value={etf.distributionYield > 0 ? `${etf.distributionYield.toFixed(2)}%` : "N/A"}
            color="text-emerald-400" />
          <MetricCell label="Avg Volume" value={etf.avgVolume} />
          <MetricCell label="NAV" value={`$${etf.nav.toFixed(2)}`} />
          <MetricCell label="NAV Discount" value={`${upside >= 0 ? "+" : ""}${upside.toFixed(2)}%`}
            color={Math.abs(upside) < 0.2 ? "text-emerald-400" : "text-yellow-400"} />
          <MetricCell label="P/E (Underlying)" value={etf.peUnderlying > 0 ? etf.peUnderlying.toFixed(1) : "N/A"} />
          <MetricCell label="Beta" value={etf.beta.toFixed(2)}
            color={Math.abs(etf.beta) < 0.3 ? "text-emerald-400" : etf.beta > 1.2 ? "text-red-400" : "text-slate-200"} />
        </div>

        {/* Returns */}
        <div className="grid grid-cols-2 gap-2">
          <div className="bg-surface-700 rounded-xl p-3 flex items-center justify-between">
            <span className="text-xs text-slate-500">YTD Return</span>
            <span className={clsx("text-sm font-mono font-semibold",
              etf.ytdReturn >= 0 ? "text-emerald-400" : "text-red-400")}>
              {etf.ytdReturn >= 0 ? "+" : ""}{etf.ytdReturn.toFixed(1)}%
            </span>
          </div>
          <div className="bg-surface-700 rounded-xl p-3 flex items-center justify-between">
            <span className="text-xs text-slate-500">1-Year Return</span>
            <span className={clsx("text-sm font-mono font-semibold",
              etf.oneYearReturn >= 0 ? "text-emerald-400" : "text-red-400")}>
              {etf.oneYearReturn >= 0 ? "+" : ""}{etf.oneYearReturn.toFixed(1)}%
            </span>
          </div>
        </div>
      </div>

      {/* Holdings + Sectors */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        <div className="lg:col-span-3 glass rounded-2xl p-5">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-4">
            Top Holdings by Weight
          </h2>
          <EtfHoldingsChart holdings={etf.topHoldings} height={etf.topHoldings.length * 32 + 16} />
        </div>

        <div className="lg:col-span-2 glass rounded-2xl p-5">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-4">
            Sector Allocation
          </h2>
          <SectorDonut sectors={etf.sectorWeights} />
        </div>
      </div>
    </div>
  );
}

// ── Stock / Crypto panel ───────────────────────────────────────────────────────

function StockPanel({ symbol, isCrypto }: { symbol: string; isCrypto: boolean }) {
  const metrics  = getFundamentals(symbol);
  const earnings = getEarnings(symbol);

  const METRIC_KEYS: { key: keyof FundamentalMetrics; label: string; fmt: (v: any) => string; color?: string }[] = [
    { key: "marketCap",        label: "Market Cap",   fmt: (v) => `$${v}` },
    { key: "pe",               label: "P/E (TTM)",    fmt: (v) => v > 0 ? v.toFixed(1) : "N/A" },
    { key: "forwardPe",        label: "Fwd P/E",      fmt: (v) => v > 0 ? v.toFixed(1) : "N/A" },
    { key: "eps",              label: "EPS (TTM)",    fmt: (v) => v > 0 ? `$${v.toFixed(2)}` : "N/A" },
    { key: "revenueGrowthYoy", label: "Rev YoY",      fmt: (v) => v > 0 ? `+${v.toFixed(1)}%` : "N/A", color: "text-emerald-400" },
    { key: "grossMargin",      label: "Gross Margin", fmt: (v) => v > 0 ? `${v.toFixed(1)}%` : "N/A" },
    { key: "debtToEquity",     label: "D/E",          fmt: (v) => v > 0 ? v.toFixed(2) : "N/A" },
    { key: "roe",              label: "ROE",          fmt: (v) => v > 0 ? `${v.toFixed(1)}%` : "N/A" },
    { key: "beta",             label: "Beta",         fmt: (v) => v.toFixed(2) },
  ];

  return (
    <div className="space-y-5">
      {/* Metrics grid */}
      <div className="glass rounded-2xl p-5">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-4">Key Metrics</h2>
        <div className="grid grid-cols-3 sm:grid-cols-9 gap-2">
          {METRIC_KEYS.map(({ key, label, fmt, color }) => (
            <MetricCell key={key} label={label} value={fmt(metrics[key])} color={color} />
          ))}
        </div>
      </div>

      {/* Earnings + analyst */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 glass rounded-2xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400">Quarterly Earnings</h2>
            <div className="flex items-center gap-3 text-[10px] font-mono text-slate-500">
              <span><span className="inline-block w-2 h-2 rounded-sm bg-brand-500/40 mr-1" />Rev Est</span>
              <span><span className="inline-block w-2 h-2 rounded-sm bg-emerald-500 mr-1" />Rev Actual</span>
              <span><span className="inline-block w-3 h-0.5 bg-slate-400 mr-1 align-middle" />EPS Est</span>
              <span><span className="inline-block w-3 h-0.5 bg-yellow-400 mr-1 align-middle" />EPS Actual</span>
            </div>
          </div>
          {isCrypto ? (
            <div className="text-center text-slate-500 text-sm py-12">Earnings data not applicable for crypto assets.</div>
          ) : (
            <EarningsChart data={earnings} height={210} />
          )}
        </div>

        <div className="space-y-4">
          <div className="glass rounded-2xl p-5 space-y-3">
            <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400">Analyst Consensus</h2>
            <div className={clsx(
              "text-center py-2 rounded-xl text-sm font-semibold",
              metrics.analystRating === "Strong Buy" ? "bg-emerald-500/15 text-emerald-400"
              : metrics.analystRating === "Buy"      ? "bg-emerald-500/10 text-emerald-400"
              : metrics.analystRating === "Hold"     ? "bg-yellow-500/10 text-yellow-400"
              : "bg-red-500/10 text-red-400",
            )}>
              {metrics.analystRating}
            </div>
            <AnalystBar buy={metrics.buyCount} hold={metrics.holdCount} sell={metrics.sellCount} />
            <div className="text-xs text-slate-500 font-mono text-center">
              {metrics.buyCount + metrics.holdCount + metrics.sellCount} analysts
            </div>
          </div>
          <AgentView symbol={symbol} />
        </div>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function FundamentalPage() {
  const [symbol, setSymbol] = useState("AAPL");

  const isEtf    = ETF_LIST.includes(symbol);
  const isCrypto = symbol.endsWith("USDT");
  const etf      = isEtf ? getEtfData(symbol)! : null;
  const metrics  = !isEtf ? getFundamentals(symbol) : null;

  const basePrice = etf?.currentPrice ?? metrics?.currentPrice ?? 100;

  const priceLive = useLiveData(() => {
    const c = generateCandles(symbol, 2, Date.now());
    return c[c.length - 1]?.close ?? basePrice;
  }, 3000);

  const priceChange    = priceLive - basePrice;
  const priceChangePct = basePrice ? (priceChange / basePrice) * 100 : 0;

  const week52Low  = etf?.week52Low  ?? metrics?.week52Low  ?? 0;
  const week52High = etf?.week52High ?? metrics?.week52High ?? 0;
  const target     = etf ? null : metrics?.analystTarget;
  const upside     = target ? ((target - priceLive) / priceLive) * 100 : null;

  return (
    <div className="space-y-5">
      {/* Page header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <h1 className="text-lg font-semibold flex items-center gap-2">
          <BookOpen className="w-5 h-5 text-brand-400" />
          Fundamental Analysis
        </h1>
        <div className="flex items-center gap-2 text-xs font-mono text-slate-500">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
          </span>
          Live price feed
        </div>
      </div>

      <SymbolSelector value={symbol} onChange={setSymbol} />

      {/* Price hero */}
      <div className="glass rounded-2xl p-5 grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="space-y-3">
          <div className="flex items-baseline gap-3 flex-wrap">
            <span className="text-3xl font-semibold font-mono">
              ${priceLive.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </span>
            <span className={clsx("text-sm font-mono", priceChange >= 0 ? "text-emerald-400" : "text-red-400")}>
              {priceChange >= 0 ? "▲" : "▼"} {Math.abs(priceChangePct).toFixed(2)}%
            </span>
            {isEtf && (
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-brand-500/15 text-brand-400 font-mono border border-brand-500/20">
                ETF
              </span>
            )}
          </div>
          <RangeBar low={week52Low} high={week52High} current={priceLive} />
          {upside !== null && (
            <div className="flex items-center gap-4 text-xs text-slate-400 font-mono">
              <span>Target <span className="text-slate-200">${target?.toLocaleString()}</span></span>
              <span className={clsx("font-semibold", upside >= 0 ? "text-emerald-400" : "text-red-400")}>
                {upside >= 0 ? "+" : ""}{upside.toFixed(1)}% upside
              </span>
            </div>
          )}
          {isEtf && etf && (
            <div className="flex items-center gap-4 text-xs text-slate-400 font-mono">
              <span>NAV <span className="text-slate-200">${etf.nav.toFixed(2)}</span></span>
              <span>ER <span className="text-slate-200">{etf.expenseRatio}%</span></span>
              <span>Yield <span className="text-emerald-400">{etf.distributionYield > 0 ? `${etf.distributionYield.toFixed(2)}%` : "–"}</span></span>
            </div>
          )}
        </div>
        <div>
          <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">30-day price</div>
          <PriceSparkline symbol={symbol} />
        </div>
      </div>

      {/* Conditional panel */}
      {isEtf && etf
        ? <EtfPanel etf={etf} priceLive={priceLive} />
        : <StockPanel symbol={symbol} isCrypto={isCrypto} />
      }

      {/* Agent view always shown for ETFs (it's inside StockPanel for stocks) */}
      {isEtf && <AgentView symbol={symbol} />}
    </div>
  );
}
