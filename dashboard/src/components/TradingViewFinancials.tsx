import { useEffect, useRef } from "react";

const TV_SCRIPT_URL =
  "https://s3.tradingview.com/external-embedding/embed-widget-financials.js";

interface Props {
  tvSymbol: string;  // e.g. "NASDAQ:AAPL"
  height?: number;
}

export function TradingViewFinancials({ tvSymbol, height = 550 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    el.innerHTML = "";

    const widgetDiv = document.createElement("div");
    widgetDiv.className = "tradingview-widget-container__widget";
    el.appendChild(widgetDiv);

    const script = document.createElement("script");
    script.type  = "text/javascript";
    script.src   = TV_SCRIPT_URL;
    script.async = true;
    script.innerHTML = JSON.stringify({
      isTransparent: true,
      displayMode:   "regular",
      width:         "100%",
      height,
      colorTheme:    "dark",
      symbol:        tvSymbol,
      locale:        "en",
    });
    el.appendChild(script);

    return () => { el.innerHTML = ""; };
  }, [tvSymbol, height]);

  return (
    <div
      ref={containerRef}
      className="tradingview-widget-container w-full"
      style={{ minHeight: height }}
    />
  );
}
