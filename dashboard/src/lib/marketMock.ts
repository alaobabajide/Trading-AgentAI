/** Realistic mock market data for Technical & Fundamental pages. */
import { subDays, subHours, format } from "date-fns";

export type Candle = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type IndicatorPoint = {
  time: string;
  rsi: number;
  macd: number;
  signal: number;
  hist: number;
  bbUpper: number;
  bbMid: number;
  bbLower: number;
  atr: number;
  close: number;
};

const SEED: Record<string, { base: number; vol: number }> = {
  // Stocks
  AAPL:    { base: 191.5,  vol: 0.012 },
  MSFT:    { base: 408.2,  vol: 0.010 },
  NVDA:    { base: 512.8,  vol: 0.022 },
  TSLA:    { base: 248.4,  vol: 0.030 },
  // ETFs
  SPY:     { base: 579.4,  vol: 0.008 },
  QQQ:     { base: 484.2,  vol: 0.011 },
  IWM:     { base: 215.6,  vol: 0.013 },
  GLD:     { base: 235.8,  vol: 0.007 },
  TLT:     { base: 91.4,   vol: 0.009 },
  XLK:     { base: 227.3,  vol: 0.012 },
  EEM:     { base: 43.9,   vol: 0.014 },
  // Crypto
  BTCUSDT: { base: 67200,  vol: 0.028 },
  ETHUSDT: { base: 3480,   vol: 0.025 },
};

function rng(seed: number) {
  // Deterministic-ish pseudo-random for consistent renders
  const x = Math.sin(seed + 1) * 10000;
  return x - Math.floor(x);
}

/** Generate N daily OHLCV candles for a symbol. */
export function generateCandles(symbol: string, n = 60, jitter = 0): Candle[] {
  const cfg = SEED[symbol] ?? { base: 100, vol: 0.015 };
  const candles: Candle[] = [];
  let price = cfg.base * (1 + (rng(jitter) - 0.5) * 0.02);

  for (let i = n; i >= 0; i--) {
    const s = i * 13 + symbol.charCodeAt(0) + jitter;
    const drift  = (rng(s) - 0.48) * cfg.vol;
    const body   = Math.abs(rng(s + 1) - 0.5) * cfg.vol * price;
    const wick   = (rng(s + 2) * 0.5 + 0.5) * body;

    const open  = price;
    const close = price * (1 + drift);
    const high  = Math.max(open, close) + wick;
    const low   = Math.min(open, close) - wick * 0.7;
    const vol   = Math.round(cfg.base * 1e5 * (0.5 + rng(s + 3)));

    candles.push({
      time: format(subDays(new Date(), i), "MMM d"),
      open:  round(open),
      high:  round(high),
      low:   round(low),
      close: round(close),
      volume: vol,
    });
    price = close;
  }
  return candles;
}

/** Generate intraday 30-min candles for the last 2 days. */
export function generateIntradayCandles(symbol: string, jitter = 0): Candle[] {
  const cfg = SEED[symbol] ?? { base: 100, vol: 0.008 };
  const candles: Candle[] = [];
  let price = cfg.base;
  const intervals = 96; // 48 h × 2

  for (let i = intervals; i >= 0; i--) {
    const s = i * 7 + symbol.charCodeAt(1) + jitter;
    const drift  = (rng(s) - 0.49) * cfg.vol * 0.4;
    const body   = Math.abs(rng(s + 1) - 0.5) * cfg.vol * price * 0.5;
    const wick   = rng(s + 2) * body;

    const open  = price;
    const close = price * (1 + drift);
    const high  = Math.max(open, close) + wick;
    const low   = Math.min(open, close) - wick * 0.6;
    const vol   = Math.round(cfg.base * 2e4 * (0.3 + rng(s + 3)));

    candles.push({
      time: format(subHours(new Date(), i * 0.5), "HH:mm"),
      open:  round(open),
      high:  round(high),
      low:   round(low),
      close: round(close),
      volume: vol,
    });
    price = close;
  }
  return candles;
}

/** Compute RSI/MACD/BB from candle series. */
export function computeIndicators(candles: Candle[]): IndicatorPoint[] {
  const closes = candles.map((c) => c.close);
  const n = closes.length;
  const out: IndicatorPoint[] = [];

  for (let i = 0; i < n; i++) {
    // RSI(14)
    let gains = 0, losses = 0;
    for (let k = Math.max(1, i - 13); k <= i; k++) {
      const d = closes[k] - closes[k - 1];
      if (d > 0) gains += d; else losses -= d;
    }
    const rs = losses === 0 ? 100 : gains / losses;
    const rsi = round(100 - 100 / (1 + rs));

    // MACD(12,26,9)
    const ema = (arr: number[], p: number, idx: number) => {
      const k = 2 / (p + 1);
      let e = arr[0];
      for (let j = 1; j <= idx; j++) e = arr[j] * k + e * (1 - k);
      return e;
    };
    const macdLine  = round(ema(closes, 12, i) - ema(closes, 26, i));
    const signalLine = (() => {
      const macdVals = closes.map((_, j) =>
        ema(closes, 12, j) - ema(closes, 26, j)
      );
      return round(ema(macdVals, 9, i));
    })();
    const hist = round(macdLine - signalLine);

    // Bollinger Bands(20)
    const slice = closes.slice(Math.max(0, i - 19), i + 1);
    const mean  = slice.reduce((a, b) => a + b, 0) / slice.length;
    const std   = Math.sqrt(slice.reduce((a, b) => a + (b - mean) ** 2, 0) / slice.length);
    const bbMid   = round(mean);
    const bbUpper = round(mean + 2 * std);
    const bbLower = round(mean - 2 * std);

    // ATR(14)
    let atrSum = 0;
    for (let k = Math.max(1, i - 13); k <= i; k++) {
      const tr = Math.max(
        candles[k].high - candles[k].low,
        Math.abs(candles[k].high - (candles[k - 1]?.close ?? candles[k].close)),
        Math.abs(candles[k].low  - (candles[k - 1]?.close ?? candles[k].close)),
      );
      atrSum += tr;
    }
    const atr = round(atrSum / Math.min(14, i + 1));

    out.push({
      time:    candles[i].time,
      rsi,
      macd:    macdLine,
      signal:  signalLine,
      hist,
      bbUpper,
      bbMid,
      bbLower,
      atr,
      close:   closes[i],
    });
  }
  return out;
}

function round(n: number) {
  return Math.round(n * 100) / 100;
}

// ── Fundamental mock data ─────────────────────────────────────────────────────

export type QuarterlyEarnings = {
  quarter: string;
  epsEst: number;
  epsActual: number;
  revenueEst: number;   // $ billions
  revenueActual: number;
};

export type FundamentalMetrics = {
  marketCap: string;
  pe: number;
  forwardPe: number;
  eps: number;
  revenueGrowthYoy: number;
  grossMargin: number;
  debtToEquity: number;
  roe: number;
  beta: number;
  week52High: number;
  week52Low: number;
  currentPrice: number;
  analystTarget: number;
  analystUpside: number;
  analystRating: "Strong Buy" | "Buy" | "Hold" | "Sell";
  buyCount: number;
  holdCount: number;
  sellCount: number;
};

const FUNDAMENTALS: Record<string, FundamentalMetrics> = {
  AAPL: {
    marketCap: "2.97T", pe: 31.2, forwardPe: 28.4, eps: 6.14,
    revenueGrowthYoy: 4.9, grossMargin: 46.2, debtToEquity: 1.87,
    roe: 147.3, beta: 1.24, week52High: 199.6, week52Low: 164.1,
    currentPrice: 191.5, analystTarget: 213, analystUpside: 11.2,
    analystRating: "Buy", buyCount: 24, holdCount: 8, sellCount: 2,
  },
  MSFT: {
    marketCap: "3.04T", pe: 37.8, forwardPe: 32.1, eps: 10.79,
    revenueGrowthYoy: 16.4, grossMargin: 69.8, debtToEquity: 0.32,
    roe: 38.5, beta: 0.90, week52High: 468.4, week52Low: 362.9,
    currentPrice: 408.2, analystTarget: 472, analystUpside: 15.6,
    analystRating: "Strong Buy", buyCount: 31, holdCount: 4, sellCount: 0,
  },
  NVDA: {
    marketCap: "1.26T", pe: 54.1, forwardPe: 38.7, eps: 9.47,
    revenueGrowthYoy: 122.4, grossMargin: 74.6, debtToEquity: 0.41,
    roe: 88.4, beta: 1.68, week52High: 553.3, week52Low: 393.7,
    currentPrice: 512.8, analystTarget: 620, analystUpside: 20.9,
    analystRating: "Strong Buy", buyCount: 36, holdCount: 3, sellCount: 0,
  },
  TSLA: {
    marketCap: "793B", pe: 63.4, forwardPe: 55.0, eps: 3.92,
    revenueGrowthYoy: 8.8, grossMargin: 17.9, debtToEquity: 0.18,
    roe: 9.2, beta: 2.31, week52High: 278.9, week52Low: 138.8,
    currentPrice: 248.4, analystTarget: 262, analystUpside: 5.5,
    analystRating: "Hold", buyCount: 12, holdCount: 14, sellCount: 7,
  },
  BTCUSDT: {
    marketCap: "1.32T", pe: 0, forwardPe: 0, eps: 0,
    revenueGrowthYoy: 0, grossMargin: 0, debtToEquity: 0,
    roe: 0, beta: 1.85, week52High: 73_750, week52Low: 38_500,
    currentPrice: 67200, analystTarget: 85000, analystUpside: 26.5,
    analystRating: "Buy", buyCount: 18, holdCount: 7, sellCount: 3,
  },
  ETHUSDT: {
    marketCap: "418B", pe: 0, forwardPe: 0, eps: 0,
    revenueGrowthYoy: 0, grossMargin: 0, debtToEquity: 0,
    roe: 0, beta: 1.92, week52High: 4_090, week52Low: 1_510,
    currentPrice: 3480, analystTarget: 4800, analystUpside: 38.0,
    analystRating: "Strong Buy", buyCount: 15, holdCount: 5, sellCount: 2,
  },
};

const EARNINGS: Record<string, QuarterlyEarnings[]> = {
  AAPL: [
    { quarter: "Q1 '24", epsEst: 2.10, epsActual: 2.18, revenueEst: 117.9, revenueActual: 119.6 },
    { quarter: "Q2 '24", epsEst: 1.50, epsActual: 1.53, revenueEst:  90.3, revenueActual:  90.8 },
    { quarter: "Q3 '24", epsEst: 1.33, epsActual: 1.40, revenueEst:  84.5, revenueActual:  85.8 },
    { quarter: "Q4 '24", epsEst: 1.60, epsActual: 1.64, revenueEst:  94.5, revenueActual:  94.9 },
  ],
  MSFT: [
    { quarter: "Q1 '24", epsEst: 2.82, epsActual: 2.94, revenueEst:  60.9, revenueActual:  61.9 },
    { quarter: "Q2 '24", epsEst: 2.93, epsActual: 3.10, revenueEst:  63.1, revenueActual:  64.7 },
    { quarter: "Q3 '24", epsEst: 2.82, epsActual: 2.95, revenueEst:  64.5, revenueActual:  65.6 },
    { quarter: "Q4 '24", epsEst: 3.10, epsActual: 3.30, revenueEst:  68.7, revenueActual:  69.6 },
  ],
  NVDA: [
    { quarter: "Q1 '24", epsEst: 5.16, epsActual: 6.12, revenueEst:  24.6, revenueActual:  26.0 },
    { quarter: "Q2 '24", epsEst: 6.34, epsActual: 6.80, revenueEst:  28.2, revenueActual:  30.0 },
    { quarter: "Q3 '24", epsEst: 7.42, epsActual: 8.10, revenueEst:  33.1, revenueActual:  35.1 },
    { quarter: "Q4 '24", epsEst: 8.44, epsActual: 0,    revenueEst:  37.5, revenueActual:  0    },
  ],
  TSLA: [
    { quarter: "Q1 '24", epsEst: 0.62, epsActual: 0.45, revenueEst:  22.3, revenueActual:  21.3 },
    { quarter: "Q2 '24", epsEst: 0.60, epsActual: 0.52, revenueEst:  24.5, revenueActual:  25.2 },
    { quarter: "Q3 '24", epsEst: 0.66, epsActual: 0.72, revenueEst:  25.4, revenueActual:  25.2 },
    { quarter: "Q4 '24", epsEst: 0.78, epsActual: 0.73, revenueEst:  27.2, revenueActual:  25.7 },
  ],
  BTCUSDT: [
    { quarter: "Q1 '24", epsEst: 0, epsActual: 0, revenueEst: 0, revenueActual: 0 },
    { quarter: "Q2 '24", epsEst: 0, epsActual: 0, revenueEst: 0, revenueActual: 0 },
    { quarter: "Q3 '24", epsEst: 0, epsActual: 0, revenueEst: 0, revenueActual: 0 },
    { quarter: "Q4 '24", epsEst: 0, epsActual: 0, revenueEst: 0, revenueActual: 0 },
  ],
  ETHUSDT: [
    { quarter: "Q1 '24", epsEst: 0, epsActual: 0, revenueEst: 0, revenueActual: 0 },
    { quarter: "Q2 '24", epsEst: 0, epsActual: 0, revenueEst: 0, revenueActual: 0 },
    { quarter: "Q3 '24", epsEst: 0, epsActual: 0, revenueEst: 0, revenueActual: 0 },
    { quarter: "Q4 '24", epsEst: 0, epsActual: 0, revenueEst: 0, revenueActual: 0 },
  ],
};

export function getFundamentals(symbol: string): FundamentalMetrics {
  return FUNDAMENTALS[symbol] ?? FUNDAMENTALS["AAPL"];
}

export function getEarnings(symbol: string): QuarterlyEarnings[] {
  return EARNINGS[symbol] ?? EARNINGS["AAPL"];
}

// ── ETF data ──────────────────────────────────────────────────────────────────

export type EtfHolding = { name: string; ticker: string; weight: number };

export type EtfMetrics = {
  fullName: string;
  category: string;
  benchmark: string;
  issuer: string;
  inceptionDate: string;
  aum: string;           // e.g. "$570B"
  expenseRatio: number;  // e.g. 0.0945 (%)
  nav: number;
  navDiscount: number;   // % premium/discount to NAV
  distributionYield: number; // %
  peUnderlying: number;
  beta: number;
  week52High: number;
  week52Low: number;
  currentPrice: number;
  avgVolume: string;
  topHoldings: EtfHolding[];
  sectorWeights: { sector: string; weight: number }[];
  ytdReturn: number;     // %
  oneYearReturn: number; // %
};

const ETF_DATA: Record<string, EtfMetrics> = {
  SPY: {
    fullName: "SPDR S&P 500 ETF Trust",
    category: "Large-Cap Blend", benchmark: "S&P 500", issuer: "State Street",
    inceptionDate: "Jan 22, 1993", aum: "$570B", expenseRatio: 0.0945,
    nav: 579.12, navDiscount: 0.05, distributionYield: 1.31, peUnderlying: 24.2,
    beta: 1.00, week52High: 613.2, week52Low: 492.8, currentPrice: 579.4,
    avgVolume: "72.4M",
    topHoldings: [
      { name: "Apple",      ticker: "AAPL", weight: 7.02 },
      { name: "Microsoft",  ticker: "MSFT", weight: 6.41 },
      { name: "NVIDIA",     ticker: "NVDA", weight: 6.18 },
      { name: "Amazon",     ticker: "AMZN", weight: 3.71 },
      { name: "Meta",       ticker: "META", weight: 2.53 },
      { name: "Alphabet A", ticker: "GOOGL",weight: 2.18 },
      { name: "Berkshire",  ticker: "BRK.B",weight: 1.74 },
      { name: "Broadcom",   ticker: "AVGO", weight: 1.71 },
    ],
    sectorWeights: [
      { sector: "Technology",    weight: 31.4 },
      { sector: "Financials",    weight: 13.2 },
      { sector: "Healthcare",    weight: 11.8 },
      { sector: "Consumer Disc", weight: 10.6 },
      { sector: "Industrials",   weight: 8.7  },
      { sector: "Comm Services", weight: 8.5  },
      { sector: "Other",         weight: 15.8 },
    ],
    ytdReturn: 4.8, oneYearReturn: 22.1,
  },
  QQQ: {
    fullName: "Invesco QQQ Trust",
    category: "Large-Cap Growth", benchmark: "Nasdaq-100", issuer: "Invesco",
    inceptionDate: "Mar 10, 1999", aum: "$265B", expenseRatio: 0.20,
    nav: 483.88, navDiscount: 0.07, distributionYield: 0.62, peUnderlying: 31.8,
    beta: 1.18, week52High: 540.8, week52Low: 399.3, currentPrice: 484.2,
    avgVolume: "38.2M",
    topHoldings: [
      { name: "Microsoft",  ticker: "MSFT", weight: 8.92 },
      { name: "Apple",      ticker: "AAPL", weight: 8.44 },
      { name: "NVIDIA",     ticker: "NVDA", weight: 8.21 },
      { name: "Amazon",     ticker: "AMZN", weight: 5.12 },
      { name: "Meta",       ticker: "META", weight: 4.88 },
      { name: "Broadcom",   ticker: "AVGO", weight: 4.61 },
      { name: "Tesla",      ticker: "TSLA", weight: 3.22 },
      { name: "Alphabet A", ticker: "GOOGL",weight: 3.09 },
    ],
    sectorWeights: [
      { sector: "Technology",    weight: 51.2 },
      { sector: "Comm Services", weight: 17.4 },
      { sector: "Consumer Disc", weight: 14.6 },
      { sector: "Healthcare",    weight: 6.3  },
      { sector: "Industrials",   weight: 4.8  },
      { sector: "Other",         weight: 5.7  },
    ],
    ytdReturn: 3.2, oneYearReturn: 26.4,
  },
  IWM: {
    fullName: "iShares Russell 2000 ETF",
    category: "Small-Cap Blend", benchmark: "Russell 2000", issuer: "BlackRock",
    inceptionDate: "May 22, 2000", aum: "$63B", expenseRatio: 0.19,
    nav: 215.31, navDiscount: 0.13, distributionYield: 1.44, peUnderlying: 22.1,
    beta: 1.24, week52High: 244.9, week52Low: 186.4, currentPrice: 215.6,
    avgVolume: "27.6M",
    topHoldings: [
      { name: "FTAI Aviation",   ticker: "FTAI",  weight: 0.52 },
      { name: "Sprouts Farmers", ticker: "SFM",   weight: 0.48 },
      { name: "Fabrinet",        ticker: "FN",    weight: 0.44 },
      { name: "Vericel Corp",    ticker: "VCEL",  weight: 0.41 },
      { name: "Onto Innovation", ticker: "ONTO",  weight: 0.38 },
      { name: "Clearwater Paper",ticker: "CLW",   weight: 0.36 },
      { name: "Kinsale Capital", ticker: "KNSL",  weight: 0.35 },
      { name: "Chord Energy",    ticker: "CHRD",  weight: 0.34 },
    ],
    sectorWeights: [
      { sector: "Financials",    weight: 17.8 },
      { sector: "Industrials",   weight: 17.2 },
      { sector: "Healthcare",    weight: 15.4 },
      { sector: "Technology",    weight: 13.1 },
      { sector: "Consumer Disc", weight: 10.8 },
      { sector: "Energy",        weight: 6.4  },
      { sector: "Other",         weight: 19.3 },
    ],
    ytdReturn: -3.1, oneYearReturn: 8.4,
  },
  GLD: {
    fullName: "SPDR Gold Shares",
    category: "Commodities — Precious Metals", benchmark: "Gold Spot Price", issuer: "State Street",
    inceptionDate: "Nov 18, 2004", aum: "$78B", expenseRatio: 0.40,
    nav: 235.62, navDiscount: 0.08, distributionYield: 0.0, peUnderlying: 0,
    beta: 0.06, week52High: 261.4, week52Low: 182.5, currentPrice: 235.8,
    avgVolume: "8.3M",
    topHoldings: [
      { name: "Physical Gold (LBMA)", ticker: "XAU", weight: 99.60 },
    ],
    sectorWeights: [
      { sector: "Physical Gold", weight: 100 },
    ],
    ytdReturn: 18.2, oneYearReturn: 29.5,
  },
  TLT: {
    fullName: "iShares 20+ Year Treasury Bond ETF",
    category: "Fixed Income — Long-Term Gov't", benchmark: "ICE 20+ Yr US Treasury", issuer: "BlackRock",
    inceptionDate: "Jul 22, 2002", aum: "$55B", expenseRatio: 0.15,
    nav: 91.28, navDiscount: 0.13, distributionYield: 4.24, peUnderlying: 0,
    beta: -0.24, week52High: 100.3, week52Low: 82.4, currentPrice: 91.4,
    avgVolume: "39.8M",
    topHoldings: [
      { name: "US Treasury 4.625% 2054", ticker: "T 4.625 54", weight: 4.12 },
      { name: "US Treasury 4.750% 2053", ticker: "T 4.750 53", weight: 3.98 },
      { name: "US Treasury 4.500% 2039", ticker: "T 4.500 39", weight: 3.81 },
      { name: "US Treasury 3.875% 2043", ticker: "T 3.875 43", weight: 3.64 },
      { name: "US Treasury 3.625% 2053", ticker: "T 3.625 53", weight: 3.51 },
    ],
    sectorWeights: [
      { sector: "US Treasuries", weight: 100 },
    ],
    ytdReturn: -4.8, oneYearReturn: -6.2,
  },
  XLK: {
    fullName: "Technology Select Sector SPDR Fund",
    category: "Sector — Technology", benchmark: "S&P Tech Select Sector", issuer: "State Street",
    inceptionDate: "Dec 16, 1998", aum: "$70B", expenseRatio: 0.09,
    nav: 226.94, navDiscount: 0.16, distributionYield: 0.72, peUnderlying: 32.4,
    beta: 1.22, week52High: 255.7, week52Low: 195.6, currentPrice: 227.3,
    avgVolume: "6.8M",
    topHoldings: [
      { name: "Apple",     ticker: "AAPL", weight: 22.41 },
      { name: "Microsoft", ticker: "MSFT", weight: 22.06 },
      { name: "NVIDIA",    ticker: "NVDA", weight: 20.16 },
      { name: "Broadcom",  ticker: "AVGO", weight: 4.82  },
      { name: "Salesforce",ticker: "CRM",  weight: 2.14  },
      { name: "AMD",       ticker: "AMD",  weight: 2.02  },
      { name: "Oracle",    ticker: "ORCL", weight: 1.96  },
      { name: "Qualcomm",  ticker: "QCOM", weight: 1.88  },
    ],
    sectorWeights: [
      { sector: "Semiconductors",  weight: 34.1 },
      { sector: "Software",        weight: 32.4 },
      { sector: "Hardware",        weight: 28.6 },
      { sector: "IT Services",     weight: 4.9  },
    ],
    ytdReturn: 5.4, oneYearReturn: 28.6,
  },
  EEM: {
    fullName: "iShares MSCI Emerging Markets ETF",
    category: "Diversified Emerging Markets", benchmark: "MSCI Emerging Markets", issuer: "BlackRock",
    inceptionDate: "Apr 7, 2003", aum: "$18B", expenseRatio: 0.70,
    nav: 43.72, navDiscount: 0.41, distributionYield: 2.14, peUnderlying: 14.2,
    beta: 0.94, week52High: 48.2, week52Low: 36.7, currentPrice: 43.9,
    avgVolume: "38.4M",
    topHoldings: [
      { name: "Samsung Electronics", ticker: "005930.KS", weight: 4.82 },
      { name: "Taiwan Semi",         ticker: "TSM",       weight: 4.71 },
      { name: "Alibaba",             ticker: "BABA",      weight: 2.88 },
      { name: "Tencent",             ticker: "0700.HK",   weight: 2.64 },
      { name: "Meituan",             ticker: "3690.HK",   weight: 1.22 },
      { name: "Reliance Ind.",       ticker: "RELIANCE",  weight: 1.18 },
      { name: "Infosys",             ticker: "INFY",      weight: 1.02 },
      { name: "SK Hynix",            ticker: "000660.KS", weight: 0.98 },
    ],
    sectorWeights: [
      { sector: "Financials",    weight: 22.4 },
      { sector: "Technology",    weight: 21.8 },
      { sector: "Consumer Disc", weight: 13.6 },
      { sector: "Comm Services", weight: 9.8  },
      { sector: "Materials",     weight: 7.2  },
      { sector: "Energy",        weight: 5.9  },
      { sector: "Other",         weight: 19.3 },
    ],
    ytdReturn: 2.8, oneYearReturn: 11.3,
  },
};

export function getEtfData(symbol: string): EtfMetrics | null {
  return ETF_DATA[symbol] ?? null;
}

export const ETF_LIST    = ["SPY", "QQQ", "IWM", "GLD", "TLT", "XLK", "EEM"];
export const STOCK_LIST  = ["AAPL", "MSFT", "NVDA", "TSLA"];
export const CRYPTO_LIST = ["BTCUSDT", "ETHUSDT"];
export const SYMBOLS = [...STOCK_LIST, ...ETF_LIST, ...CRYPTO_LIST];
