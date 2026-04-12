import { useState, useMemo } from "react";
import { Activity } from "lucide-react";
import clsx from "clsx";
import { SymbolSelector } from "../components/SymbolSelector";
import { PriceChart } from "../components/PriceChart";
import { RsiChart } from "../components/RsiChart";
import { MacdChart } from "../components/MacdChart";
import { VolumeChart } from "../components/VolumeChart";
import { useLiveData } from "../hooks/useLiveTick";
import { generateCandles, generateIntradayCandles, computeIndicators } from "../lib/marketMock";

type Timeframe = "1D" | "1W" | "1M" | "3M";

const TF_DAYS: Record<Timeframe, number> = { "1D": 0, "1W": 7, "1M": 30, "3M": 90 };

function buildData(symbol: string, tf: Timeframe, tick: number) {
  const candles = tf === "1D"
    ? generateIntradayCandles(symbol, tick)
    : generateCandles(symbol, TF_DAYS[tf], tick);
  const indicators = computeIndicators(candles);
  return { candles, indicators };
}

export function TechnicalPage() {
  const [symbol, setSymbol] = useState("AAPL");
  const [tf, setTf] = useState<Timeframe>("1M");

  // Rebuild on every 3 s tick → simulates live feed
  const { candles, indicators } = useLiveData(
    () => buildData(symbol, tf, Date.now()),
    3000,
  );

  // Reset when symbol / timeframe changes
  const stableData = useMemo(() => buildData(symbol, tf, 0), [symbol, tf]);
  const display = candles.length ? { candles, indicators } : stableData;

  const latest = display.indicators[display.indicators.length - 1];
  const prevClose = display.candles[display.candles.length - 2]?.close ?? latest?.close;
  const change    = latest ? latest.close - prevClose : 0;
  const changePct = prevClose ? (change / prevClose) * 100 : 0;
  const bullish   = change >= 0;

  const metrics = latest
    ? [
        { label: "RSI 14", value: latest.rsi.toFixed(1),
          color: latest.rsi >= 70 ? "text-red-400" : latest.rsi <= 30 ? "text-emerald-400" : "text-slate-200" },
        { label: "MACD",   value: latest.macd.toFixed(3),
          color: latest.macd >= 0 ? "text-emerald-400" : "text-red-400" },
        { label: "Signal", value: latest.signal.toFixed(3), color: "text-orange-400" },
        { label: "ATR 14", value: latest.atr.toFixed(2),    color: "text-slate-200" },
        { label: "BB Pos", value: (() => {
            const range = latest.bbUpper - latest.bbLower;
            if (!range) return "–";
            const pct = ((latest.close - latest.bbLower) / range * 100).toFixed(0);
            return `${pct}%`;
          })(), color: "text-violet-400" },
        { label: "Close",  value: `$${latest.close.toLocaleString()}`,
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
        <div className="flex items-center gap-2">
          {/* Live pulse */}
          <span className="relative flex h-2 w-2 mr-1">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
          </span>
          <span className="text-xs text-slate-500 font-mono mr-3">Live</span>
          {/* Timeframe */}
          {(["1D", "1W", "1M", "3M"] as Timeframe[]).map((t) => (
            <button key={t} onClick={() => setTf(t)}
              className={clsx(
                "px-2.5 py-1 rounded-lg text-xs font-mono transition-all",
                tf === t
                  ? "bg-brand-500/20 text-brand-400"
                  : "text-slate-500 hover:text-slate-200",
              )}>
              {t}
            </button>
          ))}
        </div>
      </div>

      <SymbolSelector value={symbol} onChange={setSymbol} />

      {/* Price header */}
      <div className="flex items-baseline gap-3">
        <span className="text-3xl font-semibold font-mono">
          ${latest?.close.toLocaleString()}
        </span>
        <span className={clsx("text-sm font-mono", bullish ? "text-emerald-400" : "text-red-400")}>
          {bullish ? "▲" : "▼"} {Math.abs(change).toLocaleString(undefined, { maximumFractionDigits: 2 })}
          &nbsp;({bullish ? "+" : ""}{changePct.toFixed(2)}%)
        </span>
        <span className="text-xs text-slate-500 font-mono ml-auto">{tf} · {symbol}</span>
      </div>

      {/* Indicator summary row */}
      <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
        {metrics.map(({ label, value, color }) => (
          <div key={label} className="glass rounded-xl p-3 text-center">
            <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">{label}</div>
            <div className={clsx("text-sm font-mono font-semibold", color)}>{value}</div>
          </div>
        ))}
      </div>

      {/* Charts */}
      <div className="glass rounded-2xl p-5 space-y-1">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs font-semibold">Price · Bollinger Bands (20, 2)</span>
        </div>
        <PriceChart data={display.indicators} height={280} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="glass rounded-2xl p-5">
          <RsiChart data={display.indicators} height={130} />
        </div>
        <div className="glass rounded-2xl p-5">
          <MacdChart data={display.indicators} height={130} />
        </div>
      </div>

      <div className="glass rounded-2xl p-5">
        <VolumeChart candles={display.candles} height={90} />
      </div>
    </div>
  );
}
