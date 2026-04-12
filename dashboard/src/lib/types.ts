export type AssetClass  = "stock" | "etf" | "crypto";
export type SignalAction = "BUY" | "SELL" | "HOLD";
export type SignalTier   = "HOT" | "WARM" | "COLD";
export type StrategyFit  = "ALIGNED" | "MISALIGNED" | "PARTIAL";

export interface VoteTally {
  bullish: number;
  bearish: number;
  neutral: number;
}

export interface Signal {
  symbol: string;
  asset_class: AssetClass;
  action: SignalAction;
  confidence: number;   // retained for display; NOT used for execution gating
  rationale: string;
  generated_at: string;
  suggested_position_pct: number;
  stop_loss_pct: number;
  take_profit_pct: number;

  // Vote-based fields (new)
  vote_tally?: VoteTally;
  votes_for_action?: number;
  regime_label?: string;

  // HITL fields
  tier:                 SignalTier;
  devil_advocate_score: number;   // display only — not an execution gate
  devil_advocate_case:  string;
  strategy_fit:         StrategyFit;

  agent_views: {
    fundamental:  string;
    technical:    string;
    sentiment:    string;
    macro:        string;
    quant:        string;
    options_flow: string;
    regime:       string;
    strategy:     string;
    risk:         string;
  };
  passed_confidence_gate: boolean;
}

export interface Position {
  symbol: string;
  asset_class: AssetClass;
  qty: number;
  avg_entry_price: number;
  current_price: number;
  market_value: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
}

export interface PortfolioSnapshot {
  timestamp: string;
  equity: number;
  cash: number;
  positions: Position[];
  daily_pnl: number;
  daily_pnl_pct: number;
  crypto_allocation_pct: number;
}

export interface EquityPoint {
  time: string;
  equity: number;
  pnl: number;
}
