import { useEffect, useRef } from "react";
import { TICKER_TAPE_SYMBOLS } from "../lib/tradingview";

const TV_SCRIPT_URL = "https://s3.tradingview.com/external-embedding/embed-widget-ticker-tape.js";

export function TradingViewTicker() {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    // Clear any previous widget
    el.innerHTML = "";

    const widgetDiv = document.createElement("div");
    widgetDiv.className = "tradingview-widget-container__widget";
    el.appendChild(widgetDiv);

    const script = document.createElement("script");
    script.type = "text/javascript";
    script.src = TV_SCRIPT_URL;
    script.async = true;
    script.innerHTML = JSON.stringify({
      symbols: TICKER_TAPE_SYMBOLS,
      showSymbolLogo: true,
      isTransparent: true,
      displayMode: "adaptive",
      colorTheme: "dark",
      locale: "en",
    });
    el.appendChild(script);

    return () => { el.innerHTML = ""; };
  }, []);

  return (
    <div
      className="tradingview-widget-container overflow-hidden"
      ref={containerRef}
      style={{ height: 46 }}
    />
  );
}
