/**
 * Mock data — used in dev when the Brain API is not running.
 * Replace with real API calls in production.
 */
import { PortfolioSnapshot, Signal, EquityPoint } from "./types";

export const mockPortfolio: PortfolioSnapshot = {
  timestamp: new Date().toISOString(),
  equity: 174_620.8,
  cash: 29_850.0,
  daily_pnl: 2_314.5,
  daily_pnl_pct: 1.34,
  crypto_allocation_pct: 0.154,
  positions: [
    // Stocks
    { symbol: "AAPL",    asset_class: "stock",  qty: 50,  avg_entry_price: 183.2,   current_price: 191.5,  market_value:  9_575,   unrealized_pnl:   415,  unrealized_pnl_pct:  4.53 },
    { symbol: "NVDA",    asset_class: "stock",  qty: 20,  avg_entry_price: 490.0,   current_price: 512.8,  market_value: 10_256,   unrealized_pnl:   456,  unrealized_pnl_pct:  4.65 },
    { symbol: "MSFT",    asset_class: "stock",  qty: 30,  avg_entry_price: 415.0,   current_price: 408.2,  market_value: 12_246,   unrealized_pnl:  -204,  unrealized_pnl_pct: -1.64 },
    // ETFs
    { symbol: "SPY",     asset_class: "stock",  qty: 40,  avg_entry_price: 542.3,   current_price: 579.4,  market_value: 23_176,   unrealized_pnl: 1_484,  unrealized_pnl_pct:  6.84 },
    { symbol: "QQQ",     asset_class: "stock",  qty: 25,  avg_entry_price: 451.6,   current_price: 484.2,  market_value: 12_105,   unrealized_pnl:   815,  unrealized_pnl_pct:  7.22 },
    { symbol: "GLD",     asset_class: "stock",  qty: 60,  avg_entry_price: 198.4,   current_price: 235.8,  market_value: 14_148,   unrealized_pnl: 2_244,  unrealized_pnl_pct: 18.85 },
    { symbol: "TLT",     asset_class: "stock",  qty: 150, avg_entry_price:  98.1,   current_price:  91.4,  market_value: 13_710,   unrealized_pnl: -1_005, unrealized_pnl_pct: -6.83 },
    { symbol: "XLK",     asset_class: "stock",  qty: 80,  avg_entry_price: 204.2,   current_price: 227.3,  market_value: 18_184,   unrealized_pnl: 1_848,  unrealized_pnl_pct: 11.31 },
    // Crypto
    { symbol: "BTCUSDT", asset_class: "crypto", qty: 0.4, avg_entry_price: 62_000,  current_price: 67_200, market_value: 26_880,   unrealized_pnl: 2_080,  unrealized_pnl_pct:  8.39 },
  ],
};

export const mockSignals: Signal[] = [
  {
    symbol: "NVDA", asset_class: "stock", action: "BUY", confidence: 0.84,
    rationale: "Strong momentum following AI chip demand surge; RSI at 58 with room to run.",
    generated_at: new Date(Date.now() - 3 * 60_000).toISOString(),
    suggested_position_pct: 0.04, stop_loss_pct: 0.025, take_profit_pct: 0.07,
    passed_confidence_gate: true,
    tier: "WARM",
    devil_advocate_score: 28,
    devil_advocate_case: "Valuation at 35× forward earnings leaves no room for execution misses; any guidance cut triggers violent de-rating.",
    strategy_fit: "ALIGNED",
    agent_views: {
      fundamental:  "DIRECTION: BULLISH\nREASONING: Strong earnings, data-center revenue beat.",
      technical:    "DIRECTION: BULLISH\nREASONING: Break above 200-day MA with volume confirmation.",
      sentiment:    "DIRECTION: BULLISH\nREASONING: Positive X buzz post-earnings.",
      macro:        "DIRECTION: BULLISH\nREASONING: Risk-on environment; AI capex supercycle driving tech sector re-rating. Fed pause supports growth equities.",
      quant:        "DIRECTION: BULLISH\nREASONING: Strong momentum factor with Sharpe > 2.0 over 60-day window. Low mean-reversion probability — trending regime favours continuation.",
      options_flow: "DIRECTION: BULLISH\nREASONING: Elevated call volume and narrowing BB width preceding breakout. IV expansion consistent with accumulation.",
      regime:       "DIRECTION: BULLISH\nREASONING: TRENDING_UP regime confirmed — MACD and RSI aligned. Trend-following entry recommended with ATR-based trailing stop.",
      strategy:     "FIT: ALIGNED\nADJUSTMENT: None needed.\nCOACHING: Signal holding period (3–7 days) matches your swing profile. 4% NAV sizing is within your 5% max. ATR stop at 2.5% sits inside your 10% drawdown tolerance.",
      risk:         '{"action":"BUY","confidence":0.84,"suggested_position_pct":0.04,"stop_loss_pct":0.025,"take_profit_pct":0.07,"devil_advocate_score":28,"devil_advocate_case":"Valuation at 35× forward earnings leaves no room for execution misses.","rationale":"High-conviction long — size at 4% NAV."}',
    },
  },
  {
    symbol: "BTCUSDT", asset_class: "crypto", action: "HOLD", confidence: 0.61,
    rationale: "Mixed signals — on-chain inflows neutral, sentiment slightly bearish.",
    generated_at: new Date(Date.now() - 8 * 60_000).toISOString(),
    suggested_position_pct: 0.0, stop_loss_pct: 0.03, take_profit_pct: 0.08,
    passed_confidence_gate: false,
    tier: "COLD",
    devil_advocate_score: 62,
    devil_advocate_case: "BTC death cross on 4H and DXY strength historically precede 15–25% corrections; existing position may need trimming rather than holding.",
    strategy_fit: "ALIGNED",
    agent_views: {
      fundamental:  "DIRECTION: NEUTRAL\nREASONING: BTC dominance stable at 52%.",
      technical:    "DIRECTION: BEARISH\nREASONING: Death cross on 4H chart.",
      sentiment:    "DIRECTION: BULLISH\nREASONING: ETF inflow news positive.",
      macro:        "DIRECTION: NEUTRAL\nREASONING: Global risk appetite mixed; DXY strengthening creates headwinds for crypto. Fed hawkish rhetoric limits upside.",
      quant:        "DIRECTION: BEARISH\nREASONING: Momentum factor decaying — 30-day return Sharpe below 0.5. High ATR signals volatile, non-trending regime.",
      options_flow: "DIRECTION: NEUTRAL\nREASONING: Balanced put/call activity. Wide Bollinger Bands suggest IV already elevated — limited options edge.",
      regime:       "DIRECTION: NEUTRAL\nREASONING: HIGH_VOLATILITY regime — MACD diverging from price. Stand aside; mean-reversion and trend signals conflicting.",
      strategy:     "FIT: ALIGNED\nADJUSTMENT: None needed — HOLD is correct for your profile.\nCOACHING: Signal confidence (0.61) is below threshold and regime is HIGH_VOLATILITY. Your swing profile does not benefit from fighting a choppy market. Hold existing position; no new entry.",
      risk:         '{"action":"HOLD","confidence":0.61,"devil_advocate_score":62,"devil_advocate_case":"BTC death cross and DXY strength historically precede corrections.","rationale":"Analyst disagreement — hold."}',
    },
  },
  {
    symbol: "AAPL", asset_class: "stock", action: "SELL", confidence: 0.75,
    rationale: "Overbought on RSI, negative earnings revision. Reduce position.",
    generated_at: new Date(Date.now() - 22 * 60_000).toISOString(),
    suggested_position_pct: 0.02, stop_loss_pct: 0.02, take_profit_pct: 0.04,
    passed_confidence_gate: true,
    tier: "WARM",
    devil_advocate_score: 41,
    devil_advocate_case: "Apple's services revenue has never missed two consecutive quarters; a single beat would force a sharp short-covering rally above $195.",
    strategy_fit: "PARTIAL",
    agent_views: {
      fundamental:  "DIRECTION: BEARISH\nREASONING: Services growth decelerating.",
      technical:    "DIRECTION: BEARISH\nREASONING: RSI divergence, double-top pattern.",
      sentiment:    "DIRECTION: NEUTRAL\nREASONING: No material news.",
      macro:        "DIRECTION: BEARISH\nREASONING: Rising real yields compress P/E multiples for mega-cap tech. Services spending slowdown aligns with tightening cycle.",
      quant:        "DIRECTION: BEARISH\nREASONING: Negative momentum factor — price below 50-day MA with declining volume. Mean-reversion to support likely.",
      options_flow: "DIRECTION: BEARISH\nREASONING: Elevated put/call ratio near key resistance. IV skew tilted to downside — institutional hedging activity visible.",
      regime:       "DIRECTION: BEARISH\nREASONING: TRENDING_DOWN regime — MACD below signal line with RSI below 50. Trend-following short or reduce-position approach warranted.",
      strategy:     "FIT: PARTIAL\nADJUSTMENT: Reduce target size from 2% to 1% NAV given your 10% max drawdown — a gap-up at earnings would breach your limit at full size.\nCOACHING: The SELL thesis is valid for a swing trader, but earnings are in 9 days. Your time horizon may force you to exit before the thesis fully plays out, crystallising a loss if the stock gaps up on results.",
      risk:         '{"action":"SELL","confidence":0.75,"suggested_position_pct":0.02,"stop_loss_pct":0.02,"take_profit_pct":0.04,"devil_advocate_score":41,"devil_advocate_case":"A single services beat would force sharp short-covering.","rationale":"Trim position on technicals."}',
    },
  },
  // ETF signals
  {
    symbol: "GLD", asset_class: "stock", action: "BUY", confidence: 0.81,
    rationale: "Gold breaking higher on central bank demand and dollar softness. Macro hedge warranted.",
    generated_at: new Date(Date.now() - 35 * 60_000).toISOString(),
    suggested_position_pct: 0.04, stop_loss_pct: 0.02, take_profit_pct: 0.06,
    passed_confidence_gate: true,
    tier: "WARM",
    devil_advocate_score: 22,
    devil_advocate_case: "A hawkish Fed surprise or sudden USD rally could cap gold at $2,350 and trigger a 5% retracement before the next leg higher.",
    strategy_fit: "ALIGNED",
    agent_views: {
      fundamental:  "DIRECTION: BULLISH\nREASONING: Central banks accumulated 1,037t gold in 2024. De-dollarisation trend intact.",
      technical:    "DIRECTION: BULLISH\nREASONING: Clean breakout above $2,300 resistance. ATR-based stop gives 2% risk.",
      sentiment:    "DIRECTION: BULLISH\nREASONING: Geopolitical risk headlines driving safe-haven flows.",
      macro:        "DIRECTION: BULLISH\nREASONING: Real rates declining and USD softening — classic gold bull setup. Central bank diversification away from UST supports structural demand.",
      quant:        "DIRECTION: BULLISH\nREASONING: Gold momentum factor outperforming 90th percentile. Low correlation to equity beta makes it an efficient portfolio hedge.",
      options_flow: "DIRECTION: BULLISH\nREASONING: Call buying dominant with IV at 12-month lows pre-breakout. Gamma squeeze potential above $2,350.",
      regime:       "DIRECTION: BULLISH\nREASONING: TRENDING_UP confirmed — BB width expanding post-consolidation. Trend-following long entry with hard stop below breakout level.",
      strategy:     "FIT: ALIGNED\nADJUSTMENT: None needed.\nCOACHING: GLD is a low-beta macro hedge that fits your swing profile perfectly. The 2% stop aligns with your drawdown tolerance and the 6% target gives a 3:1 risk/reward. Adding here is consistent with your stated strategy.",
      risk:         '{"action":"BUY","confidence":0.81,"suggested_position_pct":0.04,"stop_loss_pct":0.02,"take_profit_pct":0.06,"devil_advocate_score":22,"devil_advocate_case":"Hawkish Fed surprise could cap gold and trigger retracement.","rationale":"Low-beta macro hedge — add on momentum."}',
    },
  },
  {
    symbol: "TLT", asset_class: "stock", action: "HOLD", confidence: 0.58,
    rationale: "Rate path uncertainty keeps duration risk elevated. Yield attractive but timing uncertain.",
    generated_at: new Date(Date.now() - 48 * 60_000).toISOString(),
    suggested_position_pct: 0.0, stop_loss_pct: 0.025, take_profit_pct: 0.05,
    passed_confidence_gate: false,
    tier: "COLD",
    devil_advocate_score: 55,
    devil_advocate_case: "If inflation prints below 3% next month, the market will price 4 cuts and TLT could gap 8% in a single session — being flat misses that convex move.",
    strategy_fit: "ALIGNED",
    agent_views: {
      fundamental:  "DIRECTION: NEUTRAL\nREASONING: Yield 4.2% attractive but Fed dot-plot hawkish.",
      technical:    "DIRECTION: BEARISH\nREASONING: Trading below 200-day MA. No trend reversal signal yet.",
      sentiment:    "DIRECTION: BULLISH\nREASONING: Soft CPI print boosting rate-cut hopes.",
      macro:        "DIRECTION: NEUTRAL\nREASONING: Rate path uncertainty is the dominant driver. Front-end pricing implies 2 cuts; long-end remains volatile. Duration risk elevated.",
      quant:        "DIRECTION: BEARISH\nREASONING: Negative carry adjusted for volatility. TLT Sharpe near zero over 60-day window — not worth additional risk budget.",
      options_flow: "DIRECTION: NEUTRAL\nREASONING: Hedged positioning on both sides. Near-term IV modest — market not pricing a significant move in either direction.",
      regime:       "DIRECTION: NEUTRAL\nREASONING: RANGING regime — price oscillating near support. No clear trend signal; mean-reversion within band more likely than breakout.",
      strategy:     "FIT: ALIGNED\nADJUSTMENT: None needed — below-threshold signal correctly held.\nCOACHING: TLT is a macro timing trade, not a momentum trade. Your swing horizon is too short to absorb the 10–15 day windows between CPI prints. HOLD is correct — wait for a catalyst that resolves the rate path ambiguity.",
      risk:         '{"action":"HOLD","confidence":0.58,"devil_advocate_score":55,"devil_advocate_case":"Sub-3% CPI could trigger 8% gap-up — being flat misses convex move.","rationale":"Disagreement between fundamental and technical — hold existing position."}',
    },
  },
  {
    symbol: "QQQ", asset_class: "stock", action: "BUY", confidence: 0.77,
    rationale: "Nasdaq-100 momentum intact. AI earnings supercycle driving index earnings revisions higher.",
    generated_at: new Date(Date.now() - 61 * 60_000).toISOString(),
    suggested_position_pct: 0.03, stop_loss_pct: 0.025, take_profit_pct: 0.07,
    passed_confidence_gate: true,
    tier: "WARM",
    devil_advocate_score: 33,
    devil_advocate_case: "Index concentration risk is extreme — top 7 stocks are 45% of QQQ; any single mega-cap miss cascades into the whole position.",
    strategy_fit: "ALIGNED",
    agent_views: {
      fundamental:  "DIRECTION: BULLISH\nREASONING: Top-10 holdings beat earnings estimates for 3 consecutive quarters.",
      technical:    "DIRECTION: BULLISH\nREASONING: RSI 61 — room to run. MACD bullish crossover on weekly.",
      sentiment:    "DIRECTION: BULLISH\nREASONING: AI capex announcements driving positive fund flows.",
      macro:        "DIRECTION: BULLISH\nREASONING: Nasdaq-100 benefits from falling real yields and resilient corporate earnings. AI infrastructure buildout creating durable earnings tailwinds.",
      quant:        "DIRECTION: BULLISH\nREASONING: QQQ momentum factor in top decile — 60-day Sharpe 1.8. Trending regime with low mean-reversion probability supports sizing up.",
      options_flow: "DIRECTION: BULLISH\nREASONING: Significant call overwriting activity unwinding — net long delta positioning. IV moderately elevated but justified by earnings catalysts.",
      regime:       "DIRECTION: BULLISH\nREASONING: TRENDING_UP regime — price above all major MAs with confirming volume. Trend-following strategy appropriate; ATR trailing stop recommended.",
      strategy:     "FIT: ALIGNED\nADJUSTMENT: None needed.\nCOACHING: QQQ at 3% NAV is conservative sizing for a swing trade with 7 analysts aligned bullish. The 2.5% stop and 7% target give a 2.8:1 ratio. This is a textbook swing setup within your profile — no adjustments required.",
      risk:         '{"action":"BUY","confidence":0.77,"suggested_position_pct":0.03,"stop_loss_pct":0.025,"take_profit_pct":0.07,"devil_advocate_score":33,"devil_advocate_case":"Index concentration risk — top 7 stocks are 45% of QQQ.","rationale":"Add exposure — strong momentum with healthy risk/reward."}',
    },
  },
];

export function mockEquitySeries(points = 48): EquityPoint[] {
  const series: EquityPoint[] = [];
  let equity = 120_000;
  const now = Date.now();
  for (let i = points; i >= 0; i--) {
    const delta = (Math.random() - 0.47) * 600;
    equity = Math.max(equity + delta, 100_000);
    series.push({
      time:   new Date(now - i * 30 * 60_000).toISOString(),
      equity: Math.round(equity * 100) / 100,
      pnl:    Math.round(delta * 100) / 100,
    });
  }
  return series;
}
