-- ─────────────────────────────────────────────────────────────────────────────
-- Track Record Infrastructure Migration
-- Run this once in your Supabase SQL editor (Database → SQL Editor → New query)
-- ─────────────────────────────────────────────────────────────────────────────

-- Enable UUID extension (usually already enabled on Supabase)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ─────────────────────────────────────────────────────────────────────────────
-- 1. signal_snapshots — single source of truth for every signal
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS signal_snapshots (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- Signal identity
  symbol          TEXT NOT NULL,
  asset_class     TEXT NOT NULL,        -- 'stock', 'etf', 'crypto'
  source          TEXT NOT NULL,        -- 'live_llm', 'live_rule', 'backtest_rule', 'hybrid_llm'

  -- Signal output
  action          TEXT NOT NULL,        -- 'BUY', 'SELL', 'HOLD'
  tier            TEXT NOT NULL,        -- 'HOT', 'WARM', 'COLD'
  regime          TEXT,                 -- 'TRENDING_UP', 'TRENDING_DOWN', 'HIGH_VOLATILITY', 'RANGING'
  confidence      NUMERIC(8,4),         -- votes_for_action (weighted)
  max_score       NUMERIC(8,4),         -- total possible weight (e.g. 24.6 for stocks)
  bullish_votes   NUMERIC(8,4),
  bearish_votes   NUMERIC(8,4),
  neutral_votes   NUMERIC(8,4),
  reasoning       TEXT,                 -- AI-generated rationale

  -- Agent-level detail (Approach 3)
  agent_votes     JSONB,                -- full per-agent breakdown including all 27 views
  model_used      TEXT,                 -- e.g. 'google/gemini-2.5-flash-lite'
  provider        TEXT,                 -- e.g. 'openrouter'

  -- Input data snapshot at signal time
  entry_price     NUMERIC(12,4),
  rsi_14          NUMERIC(6,2),
  macd            NUMERIC(10,4),
  macd_signal     NUMERIC(10,4),
  atr_14          NUMERIC(10,4),
  sma_20          NUMERIC(12,4),
  sma_50          NUMERIC(12,4),
  sma_200         NUMERIC(12,4),
  bb_upper        NUMERIC(12,4),
  bb_lower        NUMERIC(12,4),
  bb_position     NUMERIC(6,2),         -- % position within Bollinger Bands (0-100)
  volume_ratio    NUMERIC(8,4),         -- volume vs 20-day average
  stoch_k         NUMERIC(6,2),
  roc_20          NUMERIC(8,4),

  -- Outcome tracking (filled asynchronously by outcome tracker)
  price_1h        NUMERIC(12,4),
  price_4h        NUMERIC(12,4),
  price_24h       NUMERIC(12,4),
  price_72h       NUMERIC(12,4),
  price_7d        NUMERIC(12,4),
  price_final     NUMERIC(12,4),        -- at position close or 30d max

  return_1h       NUMERIC(8,4),         -- % return at checkpoint
  return_4h       NUMERIC(8,4),
  return_24h      NUMERIC(8,4),
  return_72h      NUMERIC(8,4),
  return_7d       NUMERIC(8,4),
  return_final    NUMERIC(8,4),

  outcome         TEXT DEFAULT 'PENDING', -- 'WIN', 'LOSS', 'NEUTRAL', 'PENDING', 'EXPIRED'
  outcome_at      TIMESTAMPTZ,

  -- Execution tracking
  was_executed    BOOLEAN DEFAULT false,
  execution_id    TEXT,                 -- broker order ID if executed
  exit_price      NUMERIC(12,4),
  realized_pnl    NUMERIC(12,4),

  -- Backtest metadata (NULL for live signals)
  backtest_id     UUID,
  sim_date        DATE                  -- the simulated market date (for backtests only)
);

CREATE INDEX IF NOT EXISTS idx_ss_symbol    ON signal_snapshots(symbol);
CREATE INDEX IF NOT EXISTS idx_ss_source    ON signal_snapshots(source);
CREATE INDEX IF NOT EXISTS idx_ss_created   ON signal_snapshots(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ss_outcome   ON signal_snapshots(outcome);
CREATE INDEX IF NOT EXISTS idx_ss_tier      ON signal_snapshots(tier);
CREATE INDEX IF NOT EXISTS idx_ss_asset     ON signal_snapshots(asset_class);
CREATE INDEX IF NOT EXISTS idx_ss_backtest  ON signal_snapshots(backtest_id) WHERE backtest_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ss_pending   ON signal_snapshots(created_at) WHERE outcome = 'PENDING';


-- ─────────────────────────────────────────────────────────────────────────────
-- 2. backtest_runs — one row per backtest execution
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS backtest_runs (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  name                TEXT NOT NULL,
  engine              TEXT NOT NULL,        -- 'rule_based', 'hybrid_llm'
  start_date          DATE NOT NULL,
  end_date            DATE NOT NULL,
  symbol_universe     TEXT[] NOT NULL,
  initial_nav         NUMERIC(14,2) NOT NULL DEFAULT 100000,

  -- Configuration snapshot (frozen at backtest time)
  config              JSONB NOT NULL DEFAULT '{}',

  -- Aggregate results (computed after run)
  final_nav           NUMERIC(14,2),
  total_return        NUMERIC(8,4),
  annualized_return   NUMERIC(8,4),
  sharpe_ratio        NUMERIC(6,3),
  sortino_ratio       NUMERIC(6,3),
  max_drawdown        NUMERIC(8,4),
  max_dd_duration     INTEGER,
  win_rate            NUMERIC(5,2),
  profit_factor       NUMERIC(8,3),
  total_trades        INTEGER,
  avg_hold_days       NUMERIC(6,2),

  -- Benchmark comparison
  spy_return          NUMERIC(8,4),
  btc_return          NUMERIC(8,4),

  status              TEXT DEFAULT 'running',  -- 'running', 'completed', 'failed'
  error_message       TEXT
);

CREATE INDEX IF NOT EXISTS idx_bt_status    ON backtest_runs(status);
CREATE INDEX IF NOT EXISTS idx_bt_created   ON backtest_runs(created_at DESC);


-- ─────────────────────────────────────────────────────────────────────────────
-- 3. portfolio_snapshots — daily NAV for equity curve
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS portfolio_snapshots (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  snapshot_date       DATE NOT NULL,
  source              TEXT NOT NULL,        -- 'paper_live', 'backtest'
  backtest_id         UUID REFERENCES backtest_runs(id) ON DELETE CASCADE,

  nav                 NUMERIC(14,2) NOT NULL,
  cash                NUMERIC(14,2),
  invested            NUMERIC(14,2),
  daily_pnl           NUMERIC(12,4),
  daily_return        NUMERIC(8,4),
  cumulative_return   NUMERIC(8,4),
  drawdown            NUMERIC(8,4),

  positions_count     INTEGER,
  open_signals        INTEGER,

  -- Benchmark values on same date
  spy_close           NUMERIC(10,2),
  btc_close           NUMERIC(12,2),

  UNIQUE(snapshot_date, source, backtest_id)
);

CREATE INDEX IF NOT EXISTS idx_ps_date      ON portfolio_snapshots(snapshot_date DESC);
CREATE INDEX IF NOT EXISTS idx_ps_source    ON portfolio_snapshots(source);
CREATE INDEX IF NOT EXISTS idx_ps_backtest  ON portfolio_snapshots(backtest_id) WHERE backtest_id IS NOT NULL;


-- ─────────────────────────────────────────────────────────────────────────────
-- 4. historical_bars — daily OHLCV + pre-computed indicators for backtest engine
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS historical_bars (
  symbol          TEXT NOT NULL,
  bar_date        DATE NOT NULL,
  open            NUMERIC(12,4),
  high            NUMERIC(12,4),
  low             NUMERIC(12,4),
  close           NUMERIC(12,4),
  volume          BIGINT,

  -- Pre-computed indicators (filled by fetch script)
  rsi_14          NUMERIC(6,2),
  macd            NUMERIC(10,4),
  macd_signal     NUMERIC(10,4),
  atr_14          NUMERIC(10,4),
  sma_20          NUMERIC(12,4),
  sma_50          NUMERIC(12,4),
  sma_200         NUMERIC(12,4),
  bb_upper        NUMERIC(12,4),
  bb_lower        NUMERIC(12,4),
  bb_position     NUMERIC(6,2),
  volume_ratio    NUMERIC(8,4),
  stoch_k         NUMERIC(6,2),
  roc_5           NUMERIC(8,4),
  roc_20          NUMERIC(8,4),
  roc_60          NUMERIC(8,4),

  PRIMARY KEY (symbol, bar_date)
);

CREATE INDEX IF NOT EXISTS idx_hb_date      ON historical_bars(bar_date DESC);
CREATE INDEX IF NOT EXISTS idx_hb_symbol    ON historical_bars(symbol);


-- ─────────────────────────────────────────────────────────────────────────────
-- 5. track_record_config — frozen configuration record
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS track_record_config (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  version         TEXT NOT NULL,         -- e.g. 'v1'
  started_at      TIMESTAMPTZ NOT NULL,
  initial_nav     NUMERIC(14,2) NOT NULL DEFAULT 100000,
  config          JSONB NOT NULL,         -- frozen risk/tier params
  locked          BOOLEAN NOT NULL DEFAULT true,
  change_log      JSONB NOT NULL DEFAULT '[]'
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Row-Level Security: allow service role full access, anon read on snapshots
-- (adjust these policies to match your Supabase project's auth requirements)
-- ─────────────────────────────────────────────────────────────────────────────

ALTER TABLE signal_snapshots   ENABLE ROW LEVEL SECURITY;
ALTER TABLE backtest_runs      ENABLE ROW LEVEL SECURITY;
ALTER TABLE portfolio_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE historical_bars    ENABLE ROW LEVEL SECURITY;
ALTER TABLE track_record_config ENABLE ROW LEVEL SECURITY;

-- Service role bypasses RLS entirely (used by the brain API)
-- These policies allow authenticated users to read (for the dashboard)
CREATE POLICY "service_role_all_signal_snapshots"
  ON signal_snapshots FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "authenticated_read_signal_snapshots"
  ON signal_snapshots FOR SELECT TO authenticated USING (true);

CREATE POLICY "service_role_all_backtest_runs"
  ON backtest_runs FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "authenticated_read_backtest_runs"
  ON backtest_runs FOR SELECT TO authenticated USING (true);

CREATE POLICY "service_role_all_portfolio_snapshots"
  ON portfolio_snapshots FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "authenticated_read_portfolio_snapshots"
  ON portfolio_snapshots FOR SELECT TO authenticated USING (true);

CREATE POLICY "service_role_all_historical_bars"
  ON historical_bars FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "authenticated_read_historical_bars"
  ON historical_bars FOR SELECT TO authenticated USING (true);

CREATE POLICY "service_role_all_track_record_config"
  ON track_record_config FOR ALL TO service_role USING (true) WITH CHECK (true);

CREATE POLICY "authenticated_read_track_record_config"
  ON track_record_config FOR SELECT TO authenticated USING (true);
