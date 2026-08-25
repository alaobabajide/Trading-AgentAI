-- Add engine versioning columns to backtest_runs.
-- engine_version: "v1" (AEF only) or "v2" (AEF + passive SPY).
-- engine_config: full profile dict serialised as JSONB for auditability.
-- Existing rows default to "v1" (current production behaviour).

ALTER TABLE backtest_runs
  ADD COLUMN IF NOT EXISTS engine_version TEXT    DEFAULT 'v1',
  ADD COLUMN IF NOT EXISTS engine_config  JSONB,
  ADD COLUMN IF NOT EXISTS profit_factor  NUMERIC;
