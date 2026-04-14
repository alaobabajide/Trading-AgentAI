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
  // ── US Stocks ────────────────────────────────────────────────────────────────
  AAPL:  { base: 191.5, vol: 0.012 }, MSFT:  { base: 408.2, vol: 0.010 },
  NVDA:  { base: 512.8, vol: 0.022 }, TSLA:  { base: 248.4, vol: 0.030 },
  AMZN:  { base: 182.0, vol: 0.016 }, GOOGL: { base: 175.0, vol: 0.014 },
  META:  { base: 520.0, vol: 0.018 }, JPM:   { base: 200.0, vol: 0.012 },
  BAC:   { base:  38.0, vol: 0.014 }, V:     { base: 275.0, vol: 0.010 },
  UNH:   { base: 510.0, vol: 0.011 }, LLY:   { base: 800.0, vol: 0.018 },
  AVGO:  { base: 175.0, vol: 0.020 }, XOM:   { base: 115.0, vol: 0.013 },
  MA:    { base: 465.0, vol: 0.011 }, HD:    { base: 360.0, vol: 0.011 },
  PG:    { base: 165.0, vol: 0.008 }, COST:  { base: 830.0, vol: 0.012 },
  JNJ:   { base: 147.0, vol: 0.009 }, MRK:   { base: 128.0, vol: 0.010 },
  CVX:   { base: 155.0, vol: 0.013 }, ABBV:  { base: 178.0, vol: 0.012 },
  KO:    { base:  62.0, vol: 0.007 }, PEP:   { base: 175.0, vol: 0.008 },
  NFLX:  { base: 630.0, vol: 0.020 }, TMO:   { base: 555.0, vol: 0.012 },
  ORCL:  { base: 125.0, vol: 0.014 }, AMD:   { base: 165.0, vol: 0.025 },
  CRM:   { base: 295.0, vol: 0.016 }, CSCO:  { base:  48.0, vol: 0.011 },
  ACN:   { base: 320.0, vol: 0.011 }, MCD:   { base: 280.0, vol: 0.009 },
  LIN:   { base: 460.0, vol: 0.010 }, ADBE:  { base: 450.0, vol: 0.016 },
  INTC:  { base:  26.0, vol: 0.020 }, WMT:   { base:  88.0, vol: 0.009 },
  DHR:   { base: 230.0, vol: 0.012 }, TXN:   { base: 185.0, vol: 0.012 },
  IBM:   { base: 185.0, vol: 0.010 }, INTU:  { base: 660.0, vol: 0.015 },
  BKNG:  { base:3800.0, vol: 0.016 }, ISRG:  { base: 500.0, vol: 0.014 },
  SPGI:  { base: 460.0, vol: 0.010 }, NOW:   { base: 800.0, vol: 0.018 },
  PANW:  { base: 320.0, vol: 0.020 }, SNOW:  { base: 155.0, vol: 0.030 },
  PLTR:  { base:  25.0, vol: 0.035 }, UBER:  { base:  72.0, vol: 0.020 },
  COIN:  { base: 180.0, vol: 0.040 }, SHOP:  { base:  70.0, vol: 0.025 },
  SQ:    { base:  70.0, vol: 0.028 }, PYPL:  { base:  65.0, vol: 0.020 },
  SNAP:  { base:  12.0, vol: 0.040 }, RBLX:  { base:  40.0, vol: 0.035 },
  ABNB:  { base: 140.0, vol: 0.022 }, DKNG:  { base:  38.0, vol: 0.030 },
  HOOD:  { base:  18.0, vol: 0.035 }, ARM:   { base: 130.0, vol: 0.030 },
  SMCI:  { base: 800.0, vol: 0.050 }, BABA:  { base:  78.0, vol: 0.025 },
  GS:    { base: 480.0, vol: 0.014 }, MS:    { base: 100.0, vol: 0.014 },
  BLK:   { base: 860.0, vol: 0.012 }, AXP:   { base: 225.0, vol: 0.013 },
  C:     { base:  62.0, vol: 0.015 }, DE:    { base: 380.0, vol: 0.013 },
  CAT:   { base: 355.0, vol: 0.014 }, HON:   { base: 205.0, vol: 0.011 },
  RTX:   { base: 100.0, vol: 0.012 }, GE:    { base: 155.0, vol: 0.018 },
  ETN:   { base: 290.0, vol: 0.013 }, LMT:   { base: 460.0, vol: 0.010 },
  BA:    { base: 175.0, vol: 0.018 }, NEE:   { base:  75.0, vol: 0.012 },
  T:     { base:  18.0, vol: 0.010 }, AMGN:  { base: 290.0, vol: 0.011 },
  GILD:  { base:  85.0, vol: 0.012 }, SBUX:  { base:  90.0, vol: 0.013 },
  BX:    { base: 130.0, vol: 0.016 }, DIS:   { base: 100.0, vol: 0.015 },
  PLD:   { base: 115.0, vol: 0.012 }, PM:    { base: 100.0, vol: 0.010 },
  ABT:   { base: 108.0, vol: 0.011 }, MDLZ:  { base:  68.0, vol: 0.009 },
  MO:    { base:  43.0, vol: 0.009 }, ADI:   { base: 220.0, vol: 0.015 },
  // ── ETFs ─────────────────────────────────────────────────────────────────────
  SPY:   { base: 579.4, vol: 0.008 }, QQQ:   { base: 484.2, vol: 0.011 },
  IWM:   { base: 215.6, vol: 0.013 }, GLD:   { base: 235.8, vol: 0.007 },
  TLT:   { base:  91.4, vol: 0.009 }, XLK:   { base: 227.3, vol: 0.012 },
  EEM:   { base:  43.9, vol: 0.014 }, VTI:   { base: 245.0, vol: 0.008 },
  IVV:   { base: 578.0, vol: 0.008 }, DIA:   { base: 385.0, vol: 0.009 },
  RSP:   { base: 162.0, vol: 0.009 }, SCHB:  { base: 248.0, vol: 0.008 },
  VEA:   { base:  48.0, vol: 0.009 }, ARKK:  { base:  45.0, vol: 0.025 },
  XLV:   { base: 145.0, vol: 0.009 }, XLU:   { base:  68.0, vol: 0.009 },
  XLRE:  { base:  40.0, vol: 0.011 }, SOXX:  { base: 210.0, vol: 0.018 },
  IBIT:  { base:  38.0, vol: 0.028 }, BITX:  { base:  55.0, vol: 0.040 },
  CIBR:  { base:  56.0, vol: 0.015 }, BOTZ:  { base:  25.0, vol: 0.018 },
  ROBO:  { base:  55.0, vol: 0.018 }, HACK:  { base:  62.0, vol: 0.015 },
  AIQ:   { base:  42.0, vol: 0.018 }, UFO:   { base:  16.0, vol: 0.018 },
  SCHD:  { base:  78.0, vol: 0.008 }, VNQ:   { base:  86.0, vol: 0.011 },
  XLF:   { base:  42.0, vol: 0.012 }, XLE:   { base:  88.0, vol: 0.013 },
  XLB:   { base:  88.0, vol: 0.011 }, XLI:   { base: 120.0, vol: 0.010 },
  XLC:   { base:  80.0, vol: 0.012 }, XLP:   { base:  78.0, vol: 0.008 },
  SPDW:  { base:  36.0, vol: 0.010 }, SPEM:  { base:  38.0, vol: 0.013 },
  VTIP:  { base:  49.0, vol: 0.005 }, HYG:   { base:  78.0, vol: 0.008 },
  LQD:   { base: 108.0, vol: 0.008 }, SLV:   { base:  27.0, vol: 0.020 },
  AGG:   { base:  97.0, vol: 0.005 }, BND:   { base:  73.0, vol: 0.005 },
  IEF:   { base:  96.0, vol: 0.007 }, SHY:   { base:  83.0, vol: 0.003 },
  TIP:   { base: 108.0, vol: 0.006 },
  // ── Crypto ───────────────────────────────────────────────────────────────────
  BTCUSDT:  { base: 67200,  vol: 0.028 }, ETHUSDT:  { base:  3480, vol: 0.025 },
  SOLUSDT:  { base:   150,  vol: 0.035 }, BNBUSDT:  { base:   580, vol: 0.025 },
  XRPUSDT:  { base:  0.52,  vol: 0.040 }, ADAUSDT:  { base:  0.44, vol: 0.040 },
  DOGEUSDT: { base:  0.14,  vol: 0.045 }, AVAXUSDT: { base:    35, vol: 0.040 },
  LINKUSDT: { base:    18,  vol: 0.035 }, DOTUSDT:  { base:   7.5, vol: 0.035 },
  MATICUSDT:{ base:  0.85,  vol: 0.040 }, LTCUSDT:  { base:    82, vol: 0.030 },
  UNIUSDT:  { base:    10,  vol: 0.040 }, AAVEUSDT: { base:   120, vol: 0.035 },
  ATOMUSDT: { base:     9,  vol: 0.035 }, NEARUSDT: { base:   5.5, vol: 0.040 },
  APTUSDT:  { base:    10,  vol: 0.040 }, SUIUSDT:  { base:   1.5, vol: 0.045 },
  // ── Forex (quoted in majors; pips vol) ───────────────────────────────────────
  EURUSD: { base: 1.085,  vol: 0.004 }, GBPUSD: { base: 1.265,  vol: 0.005 },
  USDJPY: { base: 148.5,  vol: 0.004 }, AUDUSD: { base: 0.658,  vol: 0.006 },
  USDCHF: { base: 0.895,  vol: 0.004 }, USDCAD: { base: 1.355,  vol: 0.004 },
  NZDUSD: { base: 0.612,  vol: 0.006 }, EURGBP: { base: 0.858,  vol: 0.003 },
  EURJPY: { base: 161.2,  vol: 0.005 }, GBPJPY: { base: 188.0,  vol: 0.006 },
  AUDJPY: { base:  97.8,  vol: 0.006 }, EURCHF: { base: 0.970,  vol: 0.004 },
  GBPCHF: { base:  1.130, vol: 0.005 }, EURCAD: { base: 1.469,  vol: 0.005 },
  CADJPY: { base: 109.5,  vol: 0.005 }, AUDNZD: { base: 1.075,  vol: 0.004 },
  NZDJPY: { base:  91.0,  vol: 0.006 }, XAUUSD: { base: 2350.0, vol: 0.010 },
  XAGUSD: { base:  27.5,  vol: 0.018 }, XAUEUR: { base: 2167.0, vol: 0.010 },
  XPTUSD: { base: 980.0,  vol: 0.015 },
  // ── NGX — prices in NGN ──────────────────────────────────────────────────────
  DANGCEM:   { base: 825.0,  vol: 0.018 }, AIRTELAFRI: { base:1800.0, vol: 0.020 },
  MTNN:      { base: 225.0,  vol: 0.016 }, BUAFOODS:   { base: 370.0, vol: 0.018 },
  SEPLAT:    { base:4200.0,  vol: 0.022 }, BUACEMENT:  { base: 116.0, vol: 0.018 },
  GTCO:      { base:  55.0,  vol: 0.020 }, ZENITHBANK: { base:  42.0, vol: 0.020 },
  ACCESSCORP:{ base:  24.0,  vol: 0.022 }, UBA:        { base:  24.5, vol: 0.022 },
  STANBIC:   { base:  73.0,  vol: 0.016 }, FBNH:       { base:  23.0, vol: 0.022 },
  FIDELITYBK:{ base:  12.0,  vol: 0.022 }, FCMB:       { base:   8.5, vol: 0.025 },
  STERLING:  { base:   4.5,  vol: 0.030 }, WEMABANK:   { base:   7.5, vol: 0.025 },
  JAIZBANK:  { base:   3.2,  vol: 0.030 }, UNIONBANK:  { base:   7.8, vol: 0.025 },
  TRANSCORP: { base:  18.0,  vol: 0.025 }, NB:         { base:  26.0, vol: 0.018 },
  NESTLE:    { base:1000.0,  vol: 0.016 }, PRESCO:     { base: 455.0, vol: 0.018 },
  OKOMUOIL:  { base: 350.0,  vol: 0.018 }, FLOURMILL:  { base:  28.0, vol: 0.020 },
  DANGSUGAR: { base:  27.0,  vol: 0.022 }, CADBURY:    { base:  25.0, vol: 0.020 },
  UNILEVER:  { base:  23.0,  vol: 0.020 }, GUINNESS:   { base:  80.0, vol: 0.020 },
  INTBREW:   { base:   4.5,  vol: 0.030 }, NASCON:     { base:  60.0, vol: 0.022 },
  CONOIL:    { base:  98.0,  vol: 0.022 }, TOTALENERGIES:{ base:330.0,vol: 0.018 },
  OANDO:     { base:  32.0,  vol: 0.025 }, GEREGU:     { base: 850.0, vol: 0.022 },
  TRANSCOHOT:{ base: 230.0,  vol: 0.020 }, BERGER:     { base:  14.0, vol: 0.025 },
  FIDSON:    { base:  15.0,  vol: 0.025 }, MAYBAKER:   { base:   8.0, vol: 0.025 },
  PZ:        { base:  38.0,  vol: 0.022 }, WAPCO:      { base:  42.0, vol: 0.020 },
  CUSTODIAN: { base:  12.0,  vol: 0.025 }, LINKASSURE: { base:   1.5, vol: 0.030 },
  JBERGER:   { base: 122.0,  vol: 0.022 }, CCNN:       { base:  32.0, vol: 0.025 },
  LIVESTOCK: { base:   3.5,  vol: 0.030 }, NEIMETH:    { base:   3.5, vol: 0.030 },
  CHAMS:     { base:   1.8,  vol: 0.035 }, HONYFLOUR:  { base:   6.0, vol: 0.025 },
  CAPHOTEL:  { base:   5.5,  vol: 0.025 }, CILEASING:  { base:   5.0, vol: 0.025 },
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

export const STOCK_LIST: string[] = [
  // Mega Cap
  "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","JPM","V","UNH",
  "LLY","AVGO","XOM","MA","HD","PG","COST","JNJ","MRK","CVX",
  // Large Cap
  "ABBV","BAC","KO","PEP","NFLX","TMO","ORCL","AMD","CRM","CSCO",
  "ACN","MCD","LIN","ADBE","INTC","WMT","DHR","TXN","IBM","INTU",
  // Growth / Tech
  "BKNG","ISRG","SPGI","NOW","PANW","SNOW","PLTR","UBER","COIN","SHOP",
  "SQ","PYPL","SNAP","RBLX","ABNB","DKNG","HOOD","ARM","SMCI","BABA",
  // Financials / Industrials
  "GS","MS","BLK","AXP","C","DE","CAT","HON","RTX","GE",
  "ETN","LMT","BA","NEE","T","AMGN","GILD","SBUX","BX","DIS",
  // Additional
  "PLD","PM","ABT","MDLZ","MO","ADI",
];

export const ETF_LIST: string[] = [
  // Broad Market
  "SPY","QQQ","IWM","VTI","IVV","DIA","RSP","SCHB","VEA","EEM",
  // Sector / Thematic
  "XLK","XLF","XLE","XLV","XLU","XLI","XLRE","XLB","XLC","XLP",
  "SOXX","ARKK","IBIT","BITX","CIBR","BOTZ","ROBO","HACK","AIQ","UFO",
  // Fixed Income / Commodities
  "TLT","IEF","SHY","AGG","LQD","HYG","TIP","BND","GLD","SLV",
  // International
  "SPDW","SPEM","SCHD","VNQ","VTIP",
];

export const CRYPTO_LIST: string[] = [
  "BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT","XRPUSDT","ADAUSDT",
  "DOGEUSDT","AVAXUSDT","LINKUSDT","DOTUSDT","MATICUSDT","LTCUSDT",
  "UNIUSDT","AAVEUSDT","ATOMUSDT","NEARUSDT","APTUSDT","SUIUSDT",
];

export const FOREX_LIST: string[] = [
  // Majors
  "EURUSD","GBPUSD","USDJPY","AUDUSD","USDCHF","USDCAD","NZDUSD",
  // Crosses
  "EURGBP","EURJPY","GBPJPY","AUDJPY","EURCHF","GBPCHF","EURCAD",
  "CADJPY","AUDNZD","NZDJPY",
  // Metals
  "XAUUSD","XAGUSD","XAUEUR","XPTUSD",
];

export const NGX_LIST: string[] = [
  // Banking
  "GTCO","ZENITHBANK","ACCESSCORP","UBA","STANBIC","FBNH",
  "FIDELITYBK","FCMB","STERLING","WEMABANK","JAIZBANK","UNIONBANK",
  // Industrial / Energy
  "DANGCEM","BUACEMENT","WAPCO","CCNN","JBERGER","BERGER",
  "TRANSCORP","GEREGU","SEPLAT","OANDO","CONOIL","TOTALENERGIES",
  // Consumer / Telecoms
  "AIRTELAFRI","MTNN","BUAFOODS","NESTLE","DANGSUGAR","FLOURMILL",
  "NB","GUINNESS","INTBREW","CADBURY","UNILEVER","HONYFLOUR",
  // Agriculture / Health / Other
  "PRESCO","OKOMUOIL","LIVESTOCK","FIDSON","MAYBAKER","NEIMETH",
  "PZ","NASCON","CUSTODIAN","CHAMS","CAPHOTEL","LINKASSURE",
  "TRANSCOHOT","CILEASING",
];

export const SYMBOLS = [...STOCK_LIST, ...ETF_LIST, ...CRYPTO_LIST, ...FOREX_LIST, ...NGX_LIST];
