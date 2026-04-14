/**
 * Mock data — used in dev when the Brain API is not running.
 * Replace with real API calls in production.
 */
import { PortfolioSnapshot, Signal, EquityPoint } from "./types";

export const mockPortfolio: PortfolioSnapshot = {
  timestamp: new Date().toISOString(),
  equity: 174_620.8,
  cash: 29_850.0,
  buying_power: 59_700.0,
  daily_pnl: 2_314.5,
  daily_pnl_pct: 1.34,
  crypto_allocation_pct: 0.154,
  positions: [
    { symbol: "AAPL",    asset_class: "stock",  qty: 50,  avg_entry_price: 183.2,  current_price: 191.5,  market_value:  9_575,  unrealized_pnl:   415,  unrealized_pnl_pct:  4.53 },
    { symbol: "NVDA",    asset_class: "stock",  qty: 20,  avg_entry_price: 490.0,  current_price: 512.8,  market_value: 10_256,  unrealized_pnl:   456,  unrealized_pnl_pct:  4.65 },
    { symbol: "MSFT",    asset_class: "stock",  qty: 30,  avg_entry_price: 415.0,  current_price: 408.2,  market_value: 12_246,  unrealized_pnl:  -204,  unrealized_pnl_pct: -1.64 },
    { symbol: "SPY",     asset_class: "stock",  qty: 40,  avg_entry_price: 542.3,  current_price: 579.4,  market_value: 23_176,  unrealized_pnl: 1_484,  unrealized_pnl_pct:  6.84 },
    { symbol: "QQQ",     asset_class: "stock",  qty: 25,  avg_entry_price: 451.6,  current_price: 484.2,  market_value: 12_105,  unrealized_pnl:   815,  unrealized_pnl_pct:  7.22 },
    { symbol: "GLD",     asset_class: "stock",  qty: 60,  avg_entry_price: 198.4,  current_price: 235.8,  market_value: 14_148,  unrealized_pnl: 2_244,  unrealized_pnl_pct: 18.85 },
    { symbol: "TLT",     asset_class: "stock",  qty: 150, avg_entry_price:  98.1,  current_price:  91.4,  market_value: 13_710,  unrealized_pnl:-1_005,  unrealized_pnl_pct: -6.83 },
    { symbol: "XLK",     asset_class: "stock",  qty: 80,  avg_entry_price: 204.2,  current_price: 227.3,  market_value: 18_184,  unrealized_pnl: 1_848,  unrealized_pnl_pct: 11.31 },
    { symbol: "BTCUSDT", asset_class: "crypto", qty: 0.4, avg_entry_price: 62_000, current_price: 67_200, market_value: 26_880,  unrealized_pnl: 2_080,  unrealized_pnl_pct:  8.39 },
  ],
};

function agentViews(
  direction: "BULLISH" | "BEARISH" | "NEUTRAL",
  reasoning: string,
  regime: "TRENDING_UP" | "TRENDING_DOWN" | "RANGING" | "HIGH_VOLATILITY",
): Signal["agent_views"] {
  const regimeDir = regime === "TRENDING_UP" ? "BULLISH" : regime === "TRENDING_DOWN" ? "BEARISH" : "NEUTRAL";
  const bull = direction === "BULLISH";
  const bear = direction === "BEARISH";

  // Investor personas — each expresses their own philosophy-filtered view.
  // Buffett/Munger lean neutral unless trend is overwhelmingly clear.
  // Cohen mirrors the direction (momentum trader).
  // Bogle almost always stays neutral.
  const buffettDir  = bull ? "BULLISH"  : bear ? "NEUTRAL"  : "NEUTRAL";
  const mungerDir   = bull ? "NEUTRAL"  : bear ? "NEUTRAL"  : "NEUTRAL";
  const lynchDir    = direction;
  const ackmanDir   = bull ? "BULLISH"  : bear ? "BEARISH"  : "NEUTRAL";
  const cohenDir    = direction;
  const dalioDir    = bull ? "BULLISH"  : bear ? "BEARISH"  : "NEUTRAL";
  const woodDir     = bull ? "BULLISH"  : bear ? "BEARISH"  : "NEUTRAL";
  const bogleDir    = "NEUTRAL";

  return {
    // Panel A — analysts
    fundamental:  `DIRECTION: ${direction}\nREASONING: ${reasoning}`,
    technical:    `DIRECTION: ${direction}\nREASONING: Technical momentum ${direction.toLowerCase()} — RSI and MACD aligned.`,
    sentiment:    `DIRECTION: ${direction}\nREASONING: Market sentiment broadly ${direction.toLowerCase()} on recent catalysts.`,
    macro:        `DIRECTION: ${direction}\nREASONING: Macro backdrop supports ${direction.toLowerCase()} thesis.`,
    quant:        `DIRECTION: ${direction}\nREASONING: Quantitative signals ${direction.toLowerCase()} — momentum factor trending.`,
    options_flow: `DIRECTION: ${direction}\nREASONING: Options flow ${direction.toLowerCase()} — institutional positioning confirms.`,
    regime:       `DIRECTION: ${regimeDir}\nREGIME: ${regime}\nREASONING: ${regime.replace(/_/g, " ")} regime detected.`,
    strategy:     `FIT: ALIGNED\nADJUSTMENT: None needed.\nCOACHING: Signal fits current profile and time horizon.`,
    risk:         JSON.stringify({ action: direction === "BULLISH" ? "BUY" : direction === "BEARISH" ? "SELL" : "HOLD", confidence: 0.75, suggested_position_pct: 0.04, stop_loss_pct: 0.02, take_profit_pct: 0.06, devil_advocate_score: 20, devil_advocate_case: "Counter-thesis: unexpected macro reversal could invalidate this setup.", rationale: reasoning }),
    // Panel B — investor personas
    buffett:  `DIRECTION: ${buffettDir}\nREASONING: Paper mode [Buffett/quality] — ${bull ? "secular trend and quarterly momentum support a high-quality long-term position." : "insufficient certainty to deploy capital; Buffett waits for overwhelming evidence."}`,
    munger:   `DIRECTION: ${mungerDir}\nREASONING: Paper mode [Munger/ultra-selective] — ${bull ? "trend is positive but Munger requires stronger conviction before committing; default NEUTRAL." : "Munger: inaction is preferable to a bad trade; standing aside."}`,
    lynch:    `DIRECTION: ${lynchDir}\nREASONING: Paper mode [Lynch/GARP] — ${bull ? "multi-timeframe momentum intact; earnings-cycle growth story confirmed by volume." : bear ? "growth story showing signs of deterioration; Lynch would reduce exposure." : "mixed signals across timeframes; GARP criteria not clearly met."}`,
    ackman:   `DIRECTION: ${ackmanDir}\nREASONING: Paper mode [Ackman/concentrated] — ${bull ? "structural thesis confirmed across timeframes with catalyst volume; Ackman builds position." : bear ? "structural damage detected; Ackman exits concentrated position." : "insufficient conviction for Ackman's concentrated approach."}`,
    cohen:    `DIRECTION: ${cohenDir}\nREASONING: Paper mode [Cohen/momentum] — ${bull ? "RSI, MACD, short-term ROC all accelerating; flow signals confirm institutional buying." : bear ? "momentum reversing; Cohen cuts position on flow deterioration." : "momentum neutral; Cohen stays flat."}`,
    dalio:    `DIRECTION: ${dalioDir}\nREASONING: Paper mode [Dalio/all-weather] — ${bull ? "macro regime supportive; balanced risk exposure warranted." : bear ? "risk assets under pressure in current macro regime; reduce exposure." : "balanced regime signals; Dalio holds all-weather allocation."}`,
    wood:     `DIRECTION: ${woodDir}\nREASONING: Paper mode [Wood/innovation] — ${bull ? "secular innovation trend intact; strong ROC with volume confirms institutional accumulation." : bear ? "secular growth narrative challenged; Wood reassesses conviction." : "transition zone; Wood maintains position but watches growth catalysts."}`,
    bogle:    `DIRECTION: ${bogleDir}\nREASONING: Paper mode [Bogle/passive] — no extreme structural signals detected; Bogle: own the index, not the individual stock.`,
  };
}

export const mockSignals: Signal[] = [
  // ── Mega-cap stocks ──────────────────────────────────────────────────────────
  {
    symbol: "NVDA", asset_class: "stock", action: "BUY", confidence: 0.84,
    rationale: "Strong momentum following AI chip demand surge; RSI at 58 with room to run.",
    generated_at: new Date(Date.now() - 3 * 60_000).toISOString(),
    suggested_position_pct: 0.04, stop_loss_pct: 0.025, take_profit_pct: 0.07,
    passed_confidence_gate: true, tier: "WARM",
    vote_tally: { bullish: 6, bearish: 0, neutral: 1 }, votes_for_action: 6, regime_label: "TRENDING_UP",
    devil_advocate_score: 28, devil_advocate_case: "Valuation at 35× forward earnings leaves no room for execution misses.",
    strategy_fit: "ALIGNED",
    agent_views: agentViews("BULLISH", "Strong earnings, data-center revenue beat. AI capex supercycle.", "TRENDING_UP"),
  },
  {
    symbol: "AAPL", asset_class: "stock", action: "SELL", confidence: 0.75,
    rationale: "Overbought on RSI, negative earnings revision. Reduce position.",
    generated_at: new Date(Date.now() - 22 * 60_000).toISOString(),
    suggested_position_pct: 0.02, stop_loss_pct: 0.02, take_profit_pct: 0.04,
    passed_confidence_gate: true, tier: "WARM",
    vote_tally: { bullish: 1, bearish: 5, neutral: 1 }, votes_for_action: 5, regime_label: "TRENDING_DOWN",
    devil_advocate_score: 41, devil_advocate_case: "Apple services beat could force sharp short-covering above $195.",
    strategy_fit: "PARTIAL",
    agent_views: agentViews("BEARISH", "Services growth decelerating; RSI divergence and double-top pattern forming.", "TRENDING_DOWN"),
  },
  {
    symbol: "MSFT", asset_class: "stock", action: "BUY", confidence: 0.79,
    rationale: "Azure cloud re-acceleration and Copilot monetisation driving earnings upside.",
    generated_at: new Date(Date.now() - 14 * 60_000).toISOString(),
    suggested_position_pct: 0.04, stop_loss_pct: 0.02, take_profit_pct: 0.06,
    passed_confidence_gate: true, tier: "WARM",
    vote_tally: { bullish: 5, bearish: 1, neutral: 1 }, votes_for_action: 5, regime_label: "TRENDING_UP",
    devil_advocate_score: 24, devil_advocate_case: "AI integration costs could compress margins before revenue materialises.",
    strategy_fit: "ALIGNED",
    agent_views: agentViews("BULLISH", "Azure cloud growth re-accelerating. Copilot AI integration driving enterprise upsell.", "TRENDING_UP"),
  },
  {
    symbol: "AMZN", asset_class: "stock", action: "BUY", confidence: 0.82,
    rationale: "AWS margin expansion and retail efficiency gains making this a compounding machine.",
    generated_at: new Date(Date.now() - 40 * 60_000).toISOString(),
    suggested_position_pct: 0.03, stop_loss_pct: 0.02, take_profit_pct: 0.07,
    passed_confidence_gate: true, tier: "WARM",
    vote_tally: { bullish: 5, bearish: 0, neutral: 2 }, votes_for_action: 5, regime_label: "TRENDING_UP",
    devil_advocate_score: 19, devil_advocate_case: "AWS pricing pressure from Google and Azure could slow growth rate in H2.",
    strategy_fit: "ALIGNED",
    agent_views: agentViews("BULLISH", "AWS operating margins expanded 500bps YoY. Retail segment EBIT turning sustainably positive.", "TRENDING_UP"),
  },
  {
    symbol: "GOOGL", asset_class: "stock", action: "HOLD", confidence: 0.63,
    rationale: "AI search disruption risk balances strong advertising fundamentals.",
    generated_at: new Date(Date.now() - 55 * 60_000).toISOString(),
    suggested_position_pct: 0.0, stop_loss_pct: 0.025, take_profit_pct: 0.06,
    passed_confidence_gate: false, tier: "COLD",
    vote_tally: { bullish: 3, bearish: 2, neutral: 2 }, votes_for_action: 0, regime_label: "RANGING",
    devil_advocate_score: 49, devil_advocate_case: "ChatGPT search integration threatens 15–20% of Google's search revenue within 3 years.",
    strategy_fit: "ALIGNED",
    agent_views: agentViews("NEUTRAL", "Ad revenue strong but AI disruption creates binary outcome risk. No conviction either way.", "RANGING"),
  },
  {
    symbol: "META", asset_class: "stock", action: "BUY", confidence: 0.86,
    rationale: "Advertising recovery and AI-driven ad targeting delivering outsized ROI.",
    generated_at: new Date(Date.now() - 70 * 60_000).toISOString(),
    suggested_position_pct: 0.04, stop_loss_pct: 0.025, take_profit_pct: 0.08,
    passed_confidence_gate: true, tier: "HOT",
    vote_tally: { bullish: 6, bearish: 0, neutral: 1 }, votes_for_action: 6, regime_label: "TRENDING_UP",
    devil_advocate_score: 21, devil_advocate_case: "EU regulatory crackdown on targeted advertising could hit 20% of European revenue.",
    strategy_fit: "ALIGNED",
    agent_views: agentViews("BULLISH", "Ad revenue +27% YoY. Threads and Reels monetisation exceeding projections. AI spend delivering measurable ROI.", "TRENDING_UP"),
  },
  // ── ETFs ──────────────────────────────────────────────────────────────────────
  {
    symbol: "SPY", asset_class: "stock", action: "BUY", confidence: 0.72,
    rationale: "Broad market resilience with S&P earnings revisions trending upward.",
    generated_at: new Date(Date.now() - 90 * 60_000).toISOString(),
    suggested_position_pct: 0.05, stop_loss_pct: 0.02, take_profit_pct: 0.05,
    passed_confidence_gate: true, tier: "WARM",
    vote_tally: { bullish: 4, bearish: 1, neutral: 2 }, votes_for_action: 4, regime_label: "TRENDING_UP",
    devil_advocate_score: 30, devil_advocate_case: "S&P at 21× forward earnings with potential Fed overtightening is historically expensive.",
    strategy_fit: "ALIGNED",
    agent_views: agentViews("BULLISH", "S&P 500 earnings revisions breadth positive. Soft-landing narrative intact.", "TRENDING_UP"),
  },
  {
    symbol: "QQQ", asset_class: "stock", action: "BUY", confidence: 0.77,
    rationale: "Nasdaq-100 momentum intact. AI earnings supercycle driving index earnings revisions higher.",
    generated_at: new Date(Date.now() - 61 * 60_000).toISOString(),
    suggested_position_pct: 0.03, stop_loss_pct: 0.025, take_profit_pct: 0.07,
    passed_confidence_gate: true, tier: "WARM",
    vote_tally: { bullish: 5, bearish: 0, neutral: 2 }, votes_for_action: 5, regime_label: "TRENDING_UP",
    devil_advocate_score: 33, devil_advocate_case: "Index concentration risk — top 7 stocks are 45% of QQQ.",
    strategy_fit: "ALIGNED",
    agent_views: agentViews("BULLISH", "Top-10 holdings beat estimates 3 consecutive quarters. RSI 61 — room to run.", "TRENDING_UP"),
  },
  {
    symbol: "GLD", asset_class: "stock", action: "BUY", confidence: 0.81,
    rationale: "Gold breaking higher on central bank demand and dollar softness.",
    generated_at: new Date(Date.now() - 35 * 60_000).toISOString(),
    suggested_position_pct: 0.04, stop_loss_pct: 0.02, take_profit_pct: 0.06,
    passed_confidence_gate: true, tier: "WARM",
    vote_tally: { bullish: 5, bearish: 0, neutral: 2 }, votes_for_action: 5, regime_label: "TRENDING_UP",
    devil_advocate_score: 22, devil_advocate_case: "Hawkish Fed surprise or USD rally could cap gold at $2,350.",
    strategy_fit: "ALIGNED",
    agent_views: agentViews("BULLISH", "Central banks accumulated 1,037t gold in 2024. De-dollarisation trend intact.", "TRENDING_UP"),
  },
  {
    symbol: "TLT", asset_class: "stock", action: "HOLD", confidence: 0.58,
    rationale: "Rate path uncertainty keeps duration risk elevated. Yield attractive but timing uncertain.",
    generated_at: new Date(Date.now() - 48 * 60_000).toISOString(),
    suggested_position_pct: 0.0, stop_loss_pct: 0.025, take_profit_pct: 0.05,
    passed_confidence_gate: false, tier: "COLD",
    vote_tally: { bullish: 2, bearish: 2, neutral: 3 }, votes_for_action: 0, regime_label: "RANGING",
    devil_advocate_score: 55, devil_advocate_case: "Sub-3% CPI could trigger 8% gap-up — being flat misses that convex move.",
    strategy_fit: "ALIGNED",
    agent_views: agentViews("NEUTRAL", "Yield 4.2% attractive but Fed dot-plot hawkish. Duration risk remains elevated.", "RANGING"),
  },
  {
    symbol: "XLF", asset_class: "stock", action: "SELL", confidence: 0.71,
    rationale: "Regional bank stress and NIM compression headwinds outweigh cheap valuation.",
    generated_at: new Date(Date.now() - 105 * 60_000).toISOString(),
    suggested_position_pct: 0.03, stop_loss_pct: 0.02, take_profit_pct: 0.05,
    passed_confidence_gate: true, tier: "WARM",
    vote_tally: { bullish: 1, bearish: 4, neutral: 2 }, votes_for_action: 4, regime_label: "TRENDING_DOWN",
    devil_advocate_score: 37, devil_advocate_case: "Rate cuts materialising earlier than expected would sharply re-rate financials.",
    strategy_fit: "ALIGNED",
    agent_views: agentViews("BEARISH", "Regional bank NIM compression ongoing. CRE loan losses mounting. Sector underperforms in rate-cut environments.", "TRENDING_DOWN"),
  },
  {
    symbol: "XLE", asset_class: "stock", action: "BUY", confidence: 0.74,
    rationale: "Energy sector rerating as OPEC+ supply cuts support $85+ oil.",
    generated_at: new Date(Date.now() - 120 * 60_000).toISOString(),
    suggested_position_pct: 0.03, stop_loss_pct: 0.025, take_profit_pct: 0.07,
    passed_confidence_gate: true, tier: "WARM",
    vote_tally: { bullish: 4, bearish: 1, neutral: 2 }, votes_for_action: 4, regime_label: "TRENDING_UP",
    devil_advocate_score: 32, devil_advocate_case: "Demand destruction from slowdown could unwind OPEC+ discipline.",
    strategy_fit: "ALIGNED",
    agent_views: agentViews("BULLISH", "OPEC+ supply discipline intact. XLE free cash flow yield 8% — highest since 2014.", "TRENDING_UP"),
  },
  // ── Crypto ────────────────────────────────────────────────────────────────────
  {
    symbol: "BTCUSDT", asset_class: "crypto", action: "HOLD", confidence: 0.61,
    rationale: "Mixed signals — on-chain inflows neutral, sentiment slightly bearish.",
    generated_at: new Date(Date.now() - 8 * 60_000).toISOString(),
    suggested_position_pct: 0.0, stop_loss_pct: 0.03, take_profit_pct: 0.08,
    passed_confidence_gate: false, tier: "COLD",
    vote_tally: { bullish: 1, bearish: 2, neutral: 4 }, votes_for_action: 0, regime_label: "HIGH_VOLATILITY",
    devil_advocate_score: 62, devil_advocate_case: "BTC death cross on 4H and DXY strength historically precede 15–25% corrections.",
    strategy_fit: "ALIGNED",
    agent_views: agentViews("NEUTRAL", "BTC dominance stable at 52%. ETF inflows positive but DXY strength creates headwinds.", "HIGH_VOLATILITY"),
  },
  {
    symbol: "ETHUSDT", asset_class: "crypto", action: "BUY", confidence: 0.73,
    rationale: "ETH staking yield + EIP-4844 blob fee reduction making L2 economics viable.",
    generated_at: new Date(Date.now() - 30 * 60_000).toISOString(),
    suggested_position_pct: 0.03, stop_loss_pct: 0.035, take_profit_pct: 0.10,
    passed_confidence_gate: true, tier: "WARM",
    vote_tally: { bullish: 4, bearish: 1, neutral: 2 }, votes_for_action: 4, regime_label: "TRENDING_UP",
    devil_advocate_score: 38, devil_advocate_case: "L2 proliferation cannibalises ETH gas fees, reducing deflationary burn pressure.",
    strategy_fit: "ALIGNED",
    agent_views: agentViews("BULLISH", "Dencun upgrade reduced L2 fees 90%. Staking APY 4.2%. Institutional spot ETH ETF inflows accelerating.", "TRENDING_UP"),
  },
  {
    symbol: "SOLUSDT", asset_class: "crypto", action: "BUY", confidence: 0.78,
    rationale: "Solana DeFi TVL recovering sharply; memecoin activity driving fee revenue.",
    generated_at: new Date(Date.now() - 45 * 60_000).toISOString(),
    suggested_position_pct: 0.02, stop_loss_pct: 0.04, take_profit_pct: 0.12,
    passed_confidence_gate: true, tier: "WARM",
    vote_tally: { bullish: 5, bearish: 1, neutral: 1 }, votes_for_action: 5, regime_label: "TRENDING_UP",
    devil_advocate_score: 44, devil_advocate_case: "Network reliability concerns — history of outages could deter institutional adoption.",
    strategy_fit: "PARTIAL",
    agent_views: agentViews("BULLISH", "SOL DeFi TVL +180% QoQ. Fee revenue approaching ETH levels. Firedancer client improves reliability.", "TRENDING_UP"),
  },
  {
    symbol: "BNBUSDT", asset_class: "crypto", action: "HOLD", confidence: 0.55,
    rationale: "BNB chain activity declining; regulatory overhang from CZ sentencing limits upside.",
    generated_at: new Date(Date.now() - 80 * 60_000).toISOString(),
    suggested_position_pct: 0.0, stop_loss_pct: 0.03, take_profit_pct: 0.07,
    passed_confidence_gate: false, tier: "COLD",
    vote_tally: { bullish: 2, bearish: 2, neutral: 3 }, votes_for_action: 0, regime_label: "RANGING",
    devil_advocate_score: 58, devil_advocate_case: "DOJ compliance requirements could restrict BNB utility across multiple jurisdictions.",
    strategy_fit: "ALIGNED",
    agent_views: agentViews("NEUTRAL", "BNB Chain TVL flat. CZ sentencing regulatory overhang ongoing. On-chain metrics mixed.", "RANGING"),
  },
  // ── Individual stocks ─────────────────────────────────────────────────────────
  {
    symbol: "TSLA", asset_class: "stock", action: "SELL", confidence: 0.69,
    rationale: "EV price war intensifying; margins under pressure and full-self-driving timeline slipping.",
    generated_at: new Date(Date.now() - 130 * 60_000).toISOString(),
    suggested_position_pct: 0.02, stop_loss_pct: 0.03, take_profit_pct: 0.06,
    passed_confidence_gate: true, tier: "WARM",
    vote_tally: { bullish: 1, bearish: 4, neutral: 2 }, votes_for_action: 4, regime_label: "TRENDING_DOWN",
    devil_advocate_score: 52, devil_advocate_case: "Robotaxi launch or FSD breakthrough could re-rate TSLA as a tech company, not just automaker.",
    strategy_fit: "ALIGNED",
    agent_views: agentViews("BEARISH", "Gross margins compressed to 17.4% from 25.1% YoY. China EV competition intensifying. FSD revenue timeline uncertain.", "TRENDING_DOWN"),
  },
  {
    symbol: "JPM", asset_class: "stock", action: "BUY", confidence: 0.76,
    rationale: "JPMorgan outperforming peers on investment banking recovery and fortress balance sheet.",
    generated_at: new Date(Date.now() - 95 * 60_000).toISOString(),
    suggested_position_pct: 0.03, stop_loss_pct: 0.02, take_profit_pct: 0.05,
    passed_confidence_gate: true, tier: "WARM",
    vote_tally: { bullish: 5, bearish: 1, neutral: 1 }, votes_for_action: 5, regime_label: "TRENDING_UP",
    devil_advocate_score: 25, devil_advocate_case: "Any credit cycle turn would disproportionately hit even the best-positioned banks.",
    strategy_fit: "ALIGNED",
    agent_views: agentViews("BULLISH", "JPM IB fees +46% YoY. NIM holding at 2.7%. CET1 ratio 15.2% provides significant buyback capacity.", "TRENDING_UP"),
  },
  {
    symbol: "BAC", asset_class: "stock", action: "HOLD", confidence: 0.59,
    rationale: "NIM headwinds from rate sensitivity offset by improving loan loss reserves and trading revenue.",
    generated_at: new Date(Date.now() - 110 * 60_000).toISOString(),
    suggested_position_pct: 0.0, stop_loss_pct: 0.02, take_profit_pct: 0.05,
    passed_confidence_gate: false, tier: "COLD",
    vote_tally: { bullish: 2, bearish: 2, neutral: 3 }, votes_for_action: 0, regime_label: "RANGING",
    devil_advocate_score: 47, devil_advocate_case: "Rate cut cycle could sharply re-rate deposit-heavy banks like BAC above peers.",
    strategy_fit: "ALIGNED",
    agent_views: agentViews("NEUTRAL", "BAC net interest income declining as rates peak. Loan loss provisioning still elevated. Balance sheet derisked vs 2023.", "RANGING"),
  },
  {
    symbol: "V", asset_class: "stock", action: "BUY", confidence: 0.80,
    rationale: "Visa cross-border volumes accelerating; travel recovery and digital payments secular tailwind.",
    generated_at: new Date(Date.now() - 75 * 60_000).toISOString(),
    suggested_position_pct: 0.04, stop_loss_pct: 0.02, take_profit_pct: 0.06,
    passed_confidence_gate: true, tier: "WARM",
    vote_tally: { bullish: 5, bearish: 0, neutral: 2 }, votes_for_action: 5, regime_label: "TRENDING_UP",
    devil_advocate_score: 20, devil_advocate_case: "Central bank digital currencies could disintermediate card rails over a 5–10 year horizon.",
    strategy_fit: "ALIGNED",
    agent_views: agentViews("BULLISH", "Cross-border volume +13% YoY. Tap-to-pay penetration 73% globally. 97%+ gross margins structurally protected.", "TRENDING_UP"),
  },
  {
    symbol: "XRPUSDT", asset_class: "crypto", action: "BUY", confidence: 0.71,
    rationale: "SEC lawsuit resolution removing legal overhang; RLUSD stablecoin launch expands Ripple utility.",
    generated_at: new Date(Date.now() - 52 * 60_000).toISOString(),
    suggested_position_pct: 0.02, stop_loss_pct: 0.04, take_profit_pct: 0.12,
    passed_confidence_gate: true, tier: "WARM",
    vote_tally: { bullish: 4, bearish: 1, neutral: 2 }, votes_for_action: 4, regime_label: "TRENDING_UP",
    devil_advocate_score: 46, devil_advocate_case: "XRP utility for payments still unproven at scale; SWIFT upgrades reduce switching incentive.",
    strategy_fit: "PARTIAL",
    agent_views: agentViews("BULLISH", "SEC partial win removes key overhang. ODL corridors growing in Asia-Pacific. RLUSD stablecoin adds ecosystem depth.", "TRENDING_UP"),
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
