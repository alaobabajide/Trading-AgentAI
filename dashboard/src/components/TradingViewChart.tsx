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
        save_image: false,
        enable_publishing: false,
        allow_symbol_change: false,
        studies: [
          "MASimple@tv-basicstudies",
          "RSI@tv-basicstudies",
          "MACD@tv-basicstudies",
          "BB@tv-basicstudies",
        ],
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
