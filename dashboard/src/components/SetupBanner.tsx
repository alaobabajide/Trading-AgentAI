import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import { useConfigStatus } from "../lib/api";

function Row({ label, ok, note }: { label: string; ok: boolean; note?: string }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      {ok
        ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
        : <XCircle      className="w-3.5 h-3.5 text-red-400    shrink-0" />}
      <span className={ok ? "text-slate-300" : "text-red-300"}>{label}</span>
      {note && <span className="text-slate-500 font-mono">{note}</span>}
    </div>
  );
}

/**
 * Shown at the top of the app when the Brain API is online but some env vars
 * are missing. Hidden once everything is configured.
 * All labels and variable names come from /api/config-status — nothing is hardcoded here.
 */
export function SetupBanner() {
  const cfg = useConfigStatus();

  if (!cfg) return null;
  const allGood = cfg.llm_provider && cfg.alpaca;
  if (allGood) return null;

  const llmNote   = cfg.llm_provider ? undefined : `→ get from ${cfg.llm_provider_url ?? "openrouter.ai"}`;
  const envVarRow = [
    cfg.llm_env_var ?? "OPENROUTER_API_KEY",
    "ALPACA_API_KEY",
    "ALPACA_SECRET_KEY",
    "ALPACA_BASE_URL",
    "BINANCE_API_KEY",
    "BINANCE_SECRET_KEY",
  ].join(" · ");

  return (
    <div className="mx-8 mt-4 glass rounded-2xl border border-amber-500/30 p-4">
      <div className="flex items-start gap-3">
        <AlertTriangle className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
        <div className="flex-1 space-y-2">
          <p className="text-sm font-semibold text-amber-300">Setup required — some API keys are missing</p>
          <p className="text-xs text-slate-400">
            Add the missing keys to your Railway service under{" "}
            <span className="font-mono text-slate-200">Settings → Variables</span>, then redeploy.
          </p>
          <div className="space-y-1 pt-1">
            <Row
              label={`${cfg.llm_provider_name ?? "LLM"} API key (required for signals)`}
              ok={cfg.llm_provider}
              note={llmNote}
            />
            <Row label="Alpaca credentials (required for portfolio + trading)" ok={cfg.alpaca}
                 note={cfg.alpaca ? undefined : "→ get from alpaca.markets → Paper Trading"} />
            <Row label="Binance credentials (optional, crypto trading)" ok={cfg.binance}
                 note={cfg.binance ? undefined : "→ get from testnet.binance.vision"} />
            <Row label="Telegram bot (optional, mobile alerts)" ok={cfg.telegram}
                 note={cfg.telegram ? undefined : "→ message @BotFather on Telegram"} />
          </div>
          <div className="text-[11px] text-slate-500 font-mono pt-1">
            Variable names: {envVarRow}
          </div>
        </div>
      </div>
    </div>
  );
}
