import { useEffect, useRef } from "react";
import { TvSymbol } from "../lib/tradingview";

const TV_SCRIPT_URL =
  "https://s3.tradingview.com/external-embedding/embed-widget-mini-symbol-overview.js";

interface Props {
  sym: TvSymbol;
}

export function TradingViewMiniChart({ sym }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    el.innerHTML = "";

    const widgetDiv = document.createElement("div");
    widgetDiv.className = "tradingview-widget-container__widget";
    el.appendChild(widgetDiv);

    const script = document.createElement("script");
    script.type = "text/javascript";
    script.src = TV_SCRIPT_URL;
    script.async = true;
    script.innerHTML = JSON.stringify({
      symbol: sym.tv,
      width: "100%",
      height: "100%",
      locale: "en",
      dateRange: "1M",
      colorTheme: "dark",
      isTransparent: true,
      autosize: true,
      largeChartUrl: "",
    });
    el.appendChild(script);

    return () => { el.innerHTML = ""; };
  }, [sym.tv]);

  return (
    <div
      ref={containerRef}
      className="tradingview-widget-container w-full h-full"
    />
  );
}
