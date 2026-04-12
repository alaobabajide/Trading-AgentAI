/** TradingView symbol mapping and widget helpers. */

export type TvSymbol = {
  tv: string;          // exchange:symbol used by TradingView
  label: string;       // display name
  group: "Stocks" | "ETFs" | "Crypto";
  description: string;
};

export const TV_SYMBOLS: TvSymbol[] = [
  // Stocks
  { tv: "NASDAQ:AAPL",  label: "AAPL",    group: "Stocks", description: "Apple Inc." },
  { tv: "NASDAQ:MSFT",  label: "MSFT",    group: "Stocks", description: "Microsoft Corp." },
  { tv: "NASDAQ:NVDA",  label: "NVDA",    group: "Stocks", description: "NVIDIA Corp." },
  { tv: "NASDAQ:TSLA",  label: "TSLA",    group: "Stocks", description: "Tesla Inc." },
  // ETFs
  { tv: "AMEX:SPY",     label: "SPY",     group: "ETFs",   description: "SPDR S&P 500 ETF" },
  { tv: "NASDAQ:QQQ",   label: "QQQ",     group: "ETFs",   description: "Invesco QQQ Trust" },
  { tv: "AMEX:IWM",     label: "IWM",     group: "ETFs",   description: "iShares Russell 2000" },
  { tv: "AMEX:GLD",     label: "GLD",     group: "ETFs",   description: "SPDR Gold Shares" },
  { tv: "NASDAQ:TLT",   label: "TLT",     group: "ETFs",   description: "iShares 20+ Yr Treasury" },
  { tv: "AMEX:XLK",     label: "XLK",     group: "ETFs",   description: "Technology Select SPDR" },
  { tv: "AMEX:EEM",     label: "EEM",     group: "ETFs",   description: "iShares MSCI EM ETF" },
  // Crypto
  { tv: "BINANCE:BTCUSDT", label: "BTC/USDT", group: "Crypto", description: "Bitcoin / Tether" },
  { tv: "BINANCE:ETHUSDT", label: "ETH/USDT", group: "Crypto", description: "Ethereum / Tether" },
];

/** Symbol lookup by short label (e.g. "AAPL" → "NASDAQ:AAPL") */
export function tvSymbol(label: string): string {
  return TV_SYMBOLS.find((s) => s.label === label || s.label === label.replace("USDT", "/USDT"))?.tv
    ?? `NASDAQ:${label}`;
}

/** Ticker tape symbols for the scrolling strip */
export const TICKER_TAPE_SYMBOLS = TV_SYMBOLS.map((s) => ({
  proName: s.tv,
  title: s.label,
}));

/** Base dark theme config shared across all widgets */
export const TV_THEME = {
  colorTheme: "dark",
  locale: "en",
} as const;
