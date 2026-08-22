import { createClient } from "@supabase/supabase-js";

function _runtimeCfg(): Record<string, string> {
  return (
    (window as unknown as { __TA_CONFIG__?: Record<string, string> }).__TA_CONFIG__ ?? {}
  );
}

const cfg = _runtimeCfg();

export const supabase = createClient(
  cfg.supabaseUrl ?? "",
  cfg.supabaseAnonKey ?? "",
);

/** Supabase user ID of the account owner (set via OWNER_USER_ID env var). */
export const OWNER_USER_ID: string = cfg.ownerUserId ?? "";

/** Supabase user ID of the demo account (set via DEMO_USER_ID env var). */
export const DEMO_USER_ID: string = cfg.demoUserId ?? "";
