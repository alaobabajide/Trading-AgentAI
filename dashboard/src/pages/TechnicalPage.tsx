import { useState, useEffect } from "react";
import { Activity, RefreshCw, AlertCircle } from "lucide-react";
import clsx from "clsx";
import { SymbolSelector } from "../components/SymbolSelector";
import { CandlestickChart } from "../components/CandlestickChart";
import { PriceChart } from "../components/PriceChart";
import { RsiChart } from "../components/RsiChart";
import { MacdChart } from "../components/MacdChart";
import { VolumeChart } from "../components/VolumeChart";
import { apiHeaders } from "../lib/api";
import type { Candle } from "../components/CandlestickChart";
import type { IndicatorPoint } from "../components/PriceChart";

type Timeframe = "1W" | "1M" | "3M";

const TF_DAYS: Record<Timeframe, number> = { "1W": 7, "1M": 30, "3M": 90 };

interface BarData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  rsi?: number | null;
  macd?: number | null;
  macd_signal?: number | null;
  macd_hist?: number | null;
  bb_upper?: number | null;
  bb_mid?: number | null;
  bb_lower?: number | null;
  atr?: number | null;
}

function useBars(symbol: string, days: number, assetClass: string) {
  const [bars, setBars]       = useState<BarData[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState<string | null>(null);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    async function load() {
      try {
        const res = await fetch(
          `/api/bars/${encodeURIComponent(symbol)}?days=${days}&asset_class=${assetClass}`,
          { headers: apiHeaders(), signal: AbortSignal.timeout(20000) },
        );
        if (!res.ok) {
          const d = await res.json().catch(() => ({}));
          throw new Error((d as { detail?: string }).detail ?? `HTTP ${res.status}`);
        }
        const data = await res.json() as { bars: BarData[] };
        if (!cancelled) {
          setBars(data.bars ?? []);
          setUpdatedAt(new Date());
          setError(null);
        }
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    load();
    const id = setInterval(load, 60_000);
    return () => { cancelled = true; clearInterval(id); };
  }, [symbol, days, assetClass]);

  return { bars, loading, error, updatedAt };
}

function toCandles(bars: BarData[]): Candle[] {
  return bars.map((b) => ({
    time: b.time,
    open: b.open,
    high: b.high,
    low: b.low,
    close: b.close,
    volume: b.volume,
  }));
}

function toIndicators(bars: BarData[]): IndicatorPoint[] {
  return bars.map((b) => ({
    time:     b.time,
    rsi:      b.rsi     ?? 50,
    macd:     b.macd    ?? 0,
    signal:   b.macd_signal ?? 0,
    hist:     b.macd_hist   ?? 0,
    bbUpper:  b.bb_upper ?? b.close * 1.02,
    bbMid:    b.bb_mid   ?? b.close,
    bbLower:  b.bb_lower ?? b.close * 0.98,
    atr:      b.atr ?? 0,
    close:    b.close,
  }));
}

export function TechnicalPage() {
  const [symbol, setSymbol] = useState("AAPL");
  const [tf, setTf]         = useState<Timeframe>("1M");
  const assetClass = symbol.endsWith("USDT") ? "crypto" : "stock";

  const { bars, loading, error, updatedAt } = useBars(symbol, TF_DAYS[tf], assetClass);

  const candles    = toCandles(bars);
  const indicators = toIndicators(bars);
  const latest     = bars[bars.length - 1];
  const prev       = bars[bars.length - 2];
  const change     = latest && prev ? latest.close - prev.close : 0;
  const changePct  = prev?.close ? (change / prev.close) * 100 : 0;
  const bullish    = change >= 0;

  const metrics = latest
    ? [
        { label: "RSI 14",  value: latest.rsi?.toFixed(1) ?? "—",
          color: (latest.rsi ?? 50) >= 70 ? "text-red-400" : (latest.rsi ?? 50) <= 30 ? "text-emerald-400" : "text-slate-200" },
        { label: "MACD",    value: latest.macd?.toFixed(3) ?? "—",
          color: (latest.macd ?? 0) >= 0 ? "text-emerald-400" : "text-red-400" },
        { label: "Signal",  value: latest.macd_signal?.toFixed(3) ?? "—", color: "text-orange-400" },
        { label: "ATR 14",  value: latest.atr?.toFixed(2) ?? "—",         color: "text-slate-200" },
        { label: "BB Pos",  value: (() => {
            const range = (latest.bb_upper ?? 0) - (latest.bb_lower ?? 0);
            if (!range) return "—";
            return `${(((latest.close - (latest.bb_lower ?? 0)) / range) * 100).toFixed(0)}%`;
          })(), color: "text-violet-400" },
        { label: "Close",   value: `$${latest.close.toLocaleString()}`,
          color: bullish ? "text-emerald-400" : "text-red-400" },
      ]
    : [];

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <h1 className="text-lg font-semibold flex items-center gap-2">
          <Activity className="w-5 h-5 text-brand-400" />
          Technical Analysis
        </h1>
        <div className="flex items-center gap-2 text-xs font-mono text-slate-500">
          {loading && <RefreshCw className="w-3 h-3 animate-spin" />}
          {updatedAt && !loading && (
            <span>Updated {updatedAt.toLocaleTimeString()}</span>
          )}
          {!loading && !error && (
            <span className="flex items-center gap-1">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
              </span>
              Live data · Alpaca
            </span>
          )}
        </div>
      </div>

      <SymbolSelector value={symbol} onChange={setSymbol} />

      {/* Timeframe tabs — removed 1D since intraday requires separate handling */}
      <div className="flex gap-1">
        {(["1W", "1M", "3M"] as Timeframe[]).map((t) => (
          <button
            key={t}
            onClick={() => setTf(t)}
            className={clsx(
              "px-3 py-1.5 rounded-lg text-xs font-mono font-medium border transition-all",
              tf === t
                ? "bg-brand-500/20 border-brand-500/40 text-brand-300"
                : "border-white/10 text-slate-500 hover:text-slate-300 hover:border-white/20",
            )}
          >
            {t}
          </button>
        ))}
      </div>

      {/* Error state */}
      {error && (
        <div className="glass rounded-2xl p-6 flex items-center gap-3 text-amber-400">
          <AlertCircle className="w-5 h-5 shrink-0" />
          <div>
            <div className="text-sm font-semibold">Market data unavailable</div>
            <div className="text-xs text-slate-400 mt-0.5">{error}</div>
          </div>
        </div>
      )}

      {/* Loading skeleton */}
      {loading && bars.length === 0 && (
        <div className="glass rounded-2xl p-8 text-center text-slate-500 text-sm">
          <RefreshCw className="w-5 h-5 animate-spin mx-auto mb-2" />
          Fetching real market data from Alpaca…
        </div>
      )}

      {/* Price hero */}
      {latest && (
        <div className="glass rounded-2xl p-5 flex flex-wrap items-center gap-6">
          <div>
            <div className="text-3xl font-semibold font-mono">
              ${latest.close.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
            </div>
            <div className={clsx("text-sm font-mono mt-1", bullish ? "text-emerald-400" : "text-red-400")}>
              {bullish ? "▲" : "▼"} {Math.abs(changePct).toFixed(2)}%
              <span className="text-slate-500 ml-2">vs prev close</span>
            </div>
          </div>
          <div className="flex flex-wrap gap-2 ml-auto">
            {metrics.map((m) => (
              <div key={m.label} className="bg-surface-700 rounded-xl px-3 py-2 text-center min-w-[80px]">
                <div className="text-[9px] text-slate-500 uppercase tracking-wider">{m.label}</div>
                <div className={clsx("text-sm font-mono font-semibold mt-0.5", m.color)}>{m.value}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Charts */}
      {candles.length > 0 && (
        <>
          <div className="glass rounded-2xl p-5">
            <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-4">
              {symbol} · {tf} · Candlestick
            </h2>
            <CandlestickChart candles={candles} height={300} />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="glass rounded-2xl p-5">
              <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-4">Volume</h2>
              <VolumeChart candles={candles} height={140} />
            </div>
            <div className="glass rounded-2xl p-5">
              <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-4">RSI (14)</h2>
              <RsiChart data={indicators} height={140} />
            </div>
          </div>

          <div className="glass rounded-2xl p-5">
            <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-4">
              MACD + Bollinger Bands
            </h2>
            <PriceChart data={indicators} height={200} />
            <div className="mt-4 border-t border-white/5 pt-4">
              <MacdChart data={indicators} height={120} />
            </div>
          </div>
        </>
      )}
    </div>
  );
}
