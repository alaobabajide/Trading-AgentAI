import { createClient } from "@supabase/supabase-js";

function _runtimeCfg(): Record<string, string> {
  return (
    (window as unknown as { __TA_CONFIG__?: Record<string, string> }).__TA_CONFIG__ ?? {}
  );
}

const cfg = _runtimeCfg();

export const supabase = createClient(
  cfg.supabaseUrl ?? import.meta.env.VITE_SUPABASE_URL ?? "",
  cfg.supabaseAnonKey ?? import.meta.env.VITE_SUPABASE_ANON_KEY ?? "",
);
