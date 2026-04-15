import { useEffect, useRef } from "react";
import { TV_THEME } from "../lib/tradingview";

declare global {
  interface Window {
    TradingView: {
      widget: new (config: Record<string, unknown>) => { remove?: () => void };
    };
  }
}

interface Props {
  symbol: string;      // e.g. "NASDAQ:AAPL"
  interval?: string;   // "D" | "W" | "60" | "15" etc.
  height?: number;     // omit for 100% fill
}

const TV_SCRIPT_URL = "https://s3.tradingview.com/tv.js";

function loadTvScript(): Promise<void> {
  if (document.getElementById("tv-js")) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.id = "tv-js";
    s.src = TV_SCRIPT_URL;
    s.async = true;
    s.onload = () => resolve();
    s.onerror = reject;
    document.head.appendChild(s);
  });
}

export function TradingViewChart({ symbol, interval = "D", height = 520 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const widgetRef = useRef<{ remove?: () => void } | null>(null);

  useEffect(() => {
    const containerId = `tv-chart-${Math.random().toString(36).slice(2)}`;
    if (containerRef.current) containerRef.current.id = containerId;

    loadTvScript().then(() => {
      if (!containerRef.current || !window.TradingView) return;
      widgetRef.current = new window.TradingView.widget({
        autosize: true,
        symbol,
        interval,
        container_id: containerId,
        ...TV_THEME,
        theme: "dark",
        style: "1",           // candlestick
        toolbar_bg: "#0d0f1e",
        hide_top_toolbar: false,
        hide_legend: false,
        hide_side_toolbar: false,   // shows drawing toolbar (Fibonacci, trendlines, etc.)
        save_image: false,
        enable_publishing: false,
        allow_symbol_change: false,
        drawings_access: { type: "all", tools: [{ name: "Regression Trend" }] },
        studies: [
          // ── Trend & Volatility (main pane) ──────────────────────────────
          "MASimple@tv-basicstudies",          // 9-period SMA (fast trend)
          "BB@tv-basicstudies",                // Bollinger Bands (volatility envelope)
          // ── Support / Resistance (main pane) ────────────────────────────
          "PivotPointsHighLow@tv-basicstudies",// Auto S/R levels (swing pivots)
          // ── Momentum oscillators (sub-panes) ────────────────────────────
          "RSI@tv-basicstudies",               // RSI (14)
          "MACD@tv-basicstudies",              // MACD
        ],
        studies_overrides: {
          // Bollinger Bands — bright cyan so they stand out from candles
          "Bollinger Bands.upper.color": "#22d3ee",
          "Bollinger Bands.lower.color": "#22d3ee",
          "Bollinger Bands.median.color": "#0ea5e9",
          "Bollinger Bands.upper.linewidth": 1,
          "Bollinger Bands.lower.linewidth": 1,
          "Bollinger Bands.background.color": "rgba(34,211,238,0.04)",
          // Pivot Points — bright amber for S/R levels
          "Pivot Points High Low.High.color": "#f59e0b",
          "Pivot Points High Low.Low.color":  "#f59e0b",
          "Pivot Points High Low.High.linewidth": 2,
          "Pivot Points High Low.Low.linewidth":  2,
          // SMA — purple so it doesn't clash with BB
          "Moving Average.plot.color": "#a78bfa",
          "Moving Average.plot.linewidth": 2,
        },
        overrides: {
          "paneProperties.background": "#0d0f1e",
          "paneProperties.backgroundType": "solid",
          "paneProperties.vertGridProperties.color": "rgba(255,255,255,0.03)",
          "paneProperties.horzGridProperties.color": "rgba(255,255,255,0.03)",
          "scalesProperties.textColor": "#64748b",
          "scalesProperties.lineColor": "rgba(255,255,255,0.05)",
        },
        loading_screen: { backgroundColor: "#0d0f1e", foregroundColor: "#6366f1" },
      });
    });

    return () => {
      if (widgetRef.current?.remove) {
        try { widgetRef.current.remove(); } catch (_) {}
      }
      widgetRef.current = null;
    };
  }, [symbol, interval]);

  return (
    <div
      ref={containerRef}
      style={{ height: height ?? "100%", width: "100%" }}
      className="rounded-xl overflow-hidden"
    />
  );
}
