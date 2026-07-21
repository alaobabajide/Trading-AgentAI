import { useState, useEffect } from "react";
import { BookOpen, RefreshCw, AlertCircle } from "lucide-react";
import clsx from "clsx";
import { SymbolSelector } from "../components/SymbolSelector";
import { EarningsChart } from "../components/EarningsChart";
import { AnalystBar } from "../components/AnalystBar";
import { EtfHoldingsChart, SectorDonut } from "../components/EtfHoldingsChart";
import {
  getEtfData,
  ETF_LIST,
  type QuarterlyEarnings,
  type EtfMetrics,
} from "../lib/marketMock";
import { apiHeaders } from "../lib/api";
import { LineChart, Line, YAxis, ResponsiveContainer } from "recharts";

// ── Real fundamentals shape (mirrors /api/fundamentals response) ──────────────

interface RealFundamentals {
  symbol: string;
  asset_class: string;
  name: string;
  market_cap: string;
  pe: number;
  forward_pe: number;
  eps: number;
  revenue_growth_yoy: number;
  gross_margin: number;
  debt_to_equity: number;
  roe: number;
  beta: number;
  week52_high: number;
  week52_low: number;
  current_price: number;
  analyst_target: number;
  analyst_rating: "Strong Buy" | "Buy" | "Hold" | "Sell" | "N/A";
  buy_count: number;
  hold_count: number;
  sell_count: number;
  earnings: {
    quarter: string;
    eps_est: number;
    eps_actual: number;
    revenue_est: number;
    revenue_actual: number;
  }[];
}

function useFundamentals(symbol: string, assetClass: string) {
  const [data, setData]       = useState<RealFundamentals | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setData(null);
    setError(null);

    fetch(`/api/fundamentals/${encodeURIComponent(symbol)}?asset_class=${assetClass}`, {
      headers: apiHeaders(),
      signal: AbortSignal.timeout(25000),
    })
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<RealFundamentals>;
      })
      .then((d) => { if (!cancelled) { setData(d); setLoading(false); } })
      .catch((e) => { if (!cancelled) { setError((e as Error).message); setLoading(false); } });

    return () => { cancelled = true; };
  }, [symbol, assetClass]);

  return { data, loading, error };
}

function mapEarnings(raw: RealFundamentals["earnings"]): QuarterlyEarnings[] {
  return raw.map((e) => ({
    quarter:       e.quarter,
    epsEst:        e.eps_est,
    epsActual:     e.eps_actual,
    revenueEst:    e.revenue_est,
    revenueActual: e.revenue_actual,
  }));
}

// ── Shared sub-components ─────────────────────────────────────────────────────

function PriceSparkline({ symbol }: { symbol: string }) {
  const [data, setData] = useState<{ v: number }[]>([]);
  const assetClass = symbol.endsWith("USDT") ? "crypto" : "stock";

  useEffect(() => {
    let cancelled = false;
    fetch(`/api/bars/${encodeURIComponent(symbol)}?days=30&asset_class=${assetClass}`, {
      headers: apiHeaders(),
      signal: AbortSignal.timeout(15000),
    })
      .then((r) => r.json())
      .then((d: { bars?: { close: number }[] }) => {
        if (!cancelled) setData((d.bars ?? []).map((b) => ({ v: b.close })));
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [symbol, assetClass]);

  if (!data.length) return <div className="h-[72px] flex items-center justify-center text-xs text-slate-600">Loading…</div>;
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
  const range = high - low;
  const pct = !range ? 50 : Math.min(100, Math.max(0, ((current - low) / range) * 100));
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

// ── ETF panel ─────────────────────────────────────────────────────────────────

function EtfPanel({ etf, priceLive }: { etf: EtfMetrics; priceLive: number }) {
  const upside = ((etf.nav - priceLive) / priceLive) * 100;
  return (
    <div className="space-y-5">
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
        <div className="grid grid-cols-4 gap-2 pt-1">
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
        <div className="grid grid-cols-2 gap-2">
          <div className="bg-surface-700 rounded-xl p-3 flex items-center justify-between">
            <span className="text-xs text-slate-500">YTD Return</span>
            <span className={clsx("text-sm font-mono font-semibold", etf.ytdReturn >= 0 ? "text-emerald-400" : "text-red-400")}>
              {etf.ytdReturn >= 0 ? "+" : ""}{etf.ytdReturn.toFixed(1)}%
            </span>
          </div>
          <div className="bg-surface-700 rounded-xl p-3 flex items-center justify-between">
            <span className="text-xs text-slate-500">1-Year Return</span>
            <span className={clsx("text-sm font-mono font-semibold", etf.oneYearReturn >= 0 ? "text-emerald-400" : "text-red-400")}>
              {etf.oneYearReturn >= 0 ? "+" : ""}{etf.oneYearReturn.toFixed(1)}%
            </span>
          </div>
        </div>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        <div className="lg:col-span-3 glass rounded-2xl p-5">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-4">Top Holdings by Weight</h2>
          <EtfHoldingsChart holdings={etf.topHoldings} height={etf.topHoldings.length * 32 + 16} />
        </div>
        <div className="lg:col-span-2 glass rounded-2xl p-5">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-4">Sector Allocation</h2>
          <SectorDonut sectors={etf.sectorWeights} />
        </div>
      </div>
    </div>
  );
}

// ── Stock / Crypto panel ───────────────────────────────────────────────────────

interface StockPanelProps {
  isCrypto: boolean;
  fundamentals: RealFundamentals | null;
  earnings: QuarterlyEarnings[];
  loading: boolean;
  error: string | null;
}

function StockPanel({ isCrypto, fundamentals: f, earnings, loading, error }: StockPanelProps) {
  if (loading) {
    return (
      <div className="glass rounded-2xl p-8 text-center text-slate-500 text-sm">
        <RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2" />
        Fetching live fundamental data…
      </div>
    );
  }
  if (error || !f) {
    return (
      <div className="glass rounded-2xl p-6 flex items-center gap-3 text-amber-400">
        <AlertCircle className="w-5 h-5 shrink-0" />
        <div>
          <div className="text-sm font-semibold">Fundamental data unavailable</div>
          <div className="text-xs text-slate-400 mt-0.5">{error ?? "No data returned"}</div>
        </div>
      </div>
    );
  }

  const metrics = [
    { label: "Market Cap",   value: f.market_cap !== "N/A" ? f.market_cap : "N/A" },
    { label: "P/E (TTM)",    value: f.pe > 0 ? f.pe.toFixed(1) : "N/A" },
    { label: "Fwd P/E",      value: f.forward_pe > 0 ? f.forward_pe.toFixed(1) : "N/A" },
    { label: "EPS (TTM)",    value: f.eps !== 0 ? `$${f.eps.toFixed(2)}` : "N/A" },
    { label: "Rev YoY",      value: f.revenue_growth_yoy !== 0 ? `${f.revenue_growth_yoy > 0 ? "+" : ""}${f.revenue_growth_yoy.toFixed(1)}%` : "N/A",
      color: f.revenue_growth_yoy > 0 ? "text-emerald-400" : f.revenue_growth_yoy < 0 ? "text-red-400" : undefined },
    { label: "Gross Margin", value: f.gross_margin > 0 ? `${f.gross_margin.toFixed(1)}%` : "N/A" },
    { label: "D/E",          value: f.debt_to_equity > 0 ? f.debt_to_equity.toFixed(2) : "N/A" },
    { label: "ROE",          value: f.roe !== 0 ? `${f.roe.toFixed(1)}%` : "N/A" },
    { label: "Beta",         value: f.beta !== 0 ? f.beta.toFixed(2) : "N/A" },
  ];

  const ratingColor =
    f.analyst_rating === "Strong Buy" ? "bg-emerald-500/15 text-emerald-400"
    : f.analyst_rating === "Buy"      ? "bg-emerald-500/10 text-emerald-400"
    : f.analyst_rating === "Hold"     ? "bg-yellow-500/10 text-yellow-400"
    : f.analyst_rating === "Sell"     ? "bg-red-500/10 text-red-400"
    : "bg-surface-700 text-slate-400";

  return (
    <div className="space-y-5">
      <div className="glass rounded-2xl p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400">Key Metrics</h2>
          {f.name && f.name !== f.symbol && (
            <span className="text-xs text-slate-500 font-mono">{f.name}</span>
          )}
        </div>
        <div className="grid grid-cols-3 sm:grid-cols-9 gap-2">
          {metrics.map((m) => (
            <MetricCell key={m.label} label={m.label} value={m.value} color={m.color} />
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 glass rounded-2xl p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400">Quarterly Earnings</h2>
            <div className="flex items-center gap-3 text-[10px] font-mono text-slate-500">
              <span><span className="inline-block w-2 h-2 rounded-sm bg-emerald-500 mr-1" />Rev Actual</span>
              <span><span className="inline-block w-3 h-0.5 bg-yellow-400 mr-1 align-middle" />EPS Actual</span>
            </div>
          </div>
          {isCrypto ? (
            <div className="text-center text-slate-500 text-sm py-12">Earnings not applicable for crypto.</div>
          ) : earnings.length === 0 ? (
            <div className="text-center text-slate-500 text-sm py-12">No earnings data available for this symbol.</div>
          ) : (
            <EarningsChart data={earnings} height={210} />
          )}
        </div>

        <div className="glass rounded-2xl p-5 space-y-3">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400">Analyst Consensus</h2>
          <div className={clsx("text-center py-2 rounded-xl text-sm font-semibold", ratingColor)}>
            {f.analyst_rating}
          </div>
          {(f.buy_count + f.hold_count + f.sell_count) > 0 ? (
            <>
              <AnalystBar buy={f.buy_count} hold={f.hold_count} sell={f.sell_count} />
              <div className="text-xs text-slate-500 font-mono text-center">
                {f.buy_count + f.hold_count + f.sell_count} analysts
              </div>
            </>
          ) : (
            <div className="text-xs text-slate-500 text-center py-2">No analyst coverage data</div>
          )}
          {f.analyst_target > 0 && (
            <div className="text-xs text-slate-400 font-mono text-center pt-1">
              Price target <span className="text-slate-200">${f.analyst_target.toLocaleString()}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function FundamentalPage() {
  const [symbol, setSymbol] = useState("AAPL");

  const isEtf      = ETF_LIST.includes(symbol);
  const isCrypto   = symbol.endsWith("USDT");
  const assetClass = isCrypto ? "crypto" : "stock";

  // Static ETF holdings/sector data (only for the 7 ETFs with detail records)
  const etfDetail  = isEtf ? getEtfData(symbol) : null;

  // Real fundamentals from Yahoo Finance (used for stocks + ETFs without detail)
  const { data: fundamentals, loading: fundLoading, error: fundError } =
    useFundamentals(symbol, assetClass);

  // Live price from /api/bars (overrides static current_price)
  const staticPrice = fundamentals?.current_price ?? 0;
  const [priceLive, setPriceLive] = useState(0);

  useEffect(() => {
    setPriceLive(staticPrice);
    let cancelled = false;
    const load = () => {
      fetch(`/api/bars/${encodeURIComponent(symbol)}?days=2&asset_class=${assetClass}`, {
        headers: apiHeaders(),
        signal: AbortSignal.timeout(15000),
      })
        .then((r) => r.json())
        .then((d: { current_price?: number; bars?: { close: number }[] }) => {
          if (!cancelled) {
            const p = d.current_price ?? d.bars?.[d.bars.length - 1]?.close ?? staticPrice;
            setPriceLive(p);
          }
        })
        .catch(() => {});
    };
    load();
    const id = setInterval(load, 60_000);
    return () => { cancelled = true; clearInterval(id); };
  }, [symbol, staticPrice, assetClass]);

  const displayPrice   = priceLive || staticPrice;
  const week52Low      = fundamentals?.week52_low  ?? etfDetail?.week52Low  ?? 0;
  const week52High     = fundamentals?.week52_high ?? etfDetail?.week52High ?? 0;
  const analystTarget  = !isEtf ? (fundamentals?.analyst_target ?? 0) : 0;
  const upside         = analystTarget && displayPrice ? ((analystTarget - displayPrice) / displayPrice) * 100 : null;

  const earnings: QuarterlyEarnings[] = fundamentals ? mapEarnings(fundamentals.earnings) : [];

  return (
    <div className="space-y-5">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <h1 className="text-lg font-semibold flex items-center gap-2">
          <BookOpen className="w-5 h-5 text-brand-400" />
          Fundamental Analysis
        </h1>
      </div>

      <SymbolSelector value={symbol} onChange={setSymbol} />

      {/* Price hero */}
      <div className="glass rounded-2xl p-5 grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="space-y-3">
          <div className="flex items-baseline gap-3 flex-wrap">
            {displayPrice > 0 ? (
              <span className="text-3xl font-semibold font-mono">
                ${displayPrice.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
              </span>
            ) : (
              <span className="text-3xl font-semibold font-mono text-slate-600">—</span>
            )}
            {isEtf && (
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-brand-500/15 text-brand-400 font-mono border border-brand-500/20">
                ETF
              </span>
            )}
            {fundamentals?.name && fundamentals.name !== symbol && (
              <span className="text-xs text-slate-500 font-mono hidden sm:block">{fundamentals.name}</span>
            )}
          </div>
          {(week52Low > 0 || week52High > 0) && (
            <RangeBar low={week52Low} high={week52High} current={displayPrice} />
          )}
          {upside !== null && analystTarget > 0 && (
            <div className="flex items-center gap-4 text-xs text-slate-400 font-mono">
              <span>Target <span className="text-slate-200">${analystTarget.toLocaleString()}</span></span>
              <span className={clsx("font-semibold", upside >= 0 ? "text-emerald-400" : "text-red-400")}>
                {upside >= 0 ? "+" : ""}{upside.toFixed(1)}% upside
              </span>
            </div>
          )}
          {isEtf && etfDetail && (
            <div className="flex items-center gap-4 text-xs text-slate-400 font-mono">
              <span>NAV <span className="text-slate-200">${etfDetail.nav.toFixed(2)}</span></span>
              <span>ER <span className="text-slate-200">{etfDetail.expenseRatio}%</span></span>
              <span>Yield <span className="text-emerald-400">
                {etfDetail.distributionYield > 0 ? `${etfDetail.distributionYield.toFixed(2)}%` : "–"}
              </span></span>
            </div>
          )}
        </div>
        <div>
          <div className="text-[10px] text-slate-500 uppercase tracking-widest mb-1">30-day price</div>
          <PriceSparkline symbol={symbol} />
        </div>
      </div>

      {/* ETF with holdings detail OR stock/crypto panel */}
      {isEtf && etfDetail
        ? <EtfPanel etf={etfDetail} priceLive={displayPrice} />
        : <StockPanel
            isCrypto={isCrypto}
            fundamentals={fundamentals}
            earnings={earnings}
            loading={fundLoading}
            error={fundError}
          />
      }
    </div>
  );
}
