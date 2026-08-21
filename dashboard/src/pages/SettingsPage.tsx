import clsx from "clsx";
import { Brain, Clock, Package, RefreshCw, Shield, TrendingUp, Zap } from "lucide-react";
import {
  HITLMode, UserProfile, DEFAULT_PROFILE,
  MODE_CONFIG, loadProfile, saveProfile,
} from "../lib/hitl";
import { useConfigStatus, useRiskConfig, RiskConfigFields, useLlmSettings, LlmSavePayload } from "../lib/api";
import { useState } from "react";

// ── Layout helpers ────────────────────────────────────────────────────────────

function Section({ icon, title, subtitle, children }: {
  icon: React.ReactNode; title: string; subtitle?: string; children: React.ReactNode;
}) {
  return (
    <div className="glass rounded-2xl p-5 space-y-4">
      <div className="flex items-start gap-2.5">
        <div className="w-7 h-7 rounded-lg bg-brand-500/15 flex items-center justify-center text-brand-400 shrink-0 mt-0.5">
          {icon}
        </div>
        <div>
          <h3 className="text-sm font-semibold">{title}</h3>
          {subtitle && <p className="text-[11px] text-slate-500 font-mono mt-0.5">{subtitle}</p>}
        </div>
      </div>
      {children}
    </div>
  );
}

function SectionNote({ children, variant = "info" }: { children: React.ReactNode; variant?: "info" | "warn" }) {
  return (
    <div className={clsx(
      "text-[11px] font-mono rounded-xl px-3 py-2 leading-relaxed",
      variant === "warn"
        ? "text-amber-400/90 bg-amber-500/10 border border-amber-500/20"
        : "text-slate-400 bg-surface-700",
    )}>
      {children}
    </div>
  );
}

function SubSection({ title }: { title: string }) {
  return (
    <div className="flex items-center gap-2 pt-1">
      <div className="h-px flex-1 bg-white/5" />
      <span className="text-[10px] font-mono uppercase tracking-widest text-slate-600">{title}</span>
      <div className="h-px flex-1 bg-white/5" />
    </div>
  );
}

// ── Row components ────────────────────────────────────────────────────────────

function RiskRow({
  label, value, options, onChange, valueColor, unit = "%", formatFn,
}: {
  label: string; value: number; options: number[];
  onChange: (v: number) => void; valueColor: string;
  unit?: string; formatFn?: (v: number) => string;
}) {
  const display = formatFn ? formatFn(value) : `${(value * 100).toFixed(1)}${unit}`;
  const optionDisplay = formatFn
    ? (o: number) => formatFn(o / 100)
    : (o: number) => `${o}${unit}`;
  const optionVal = (o: number) => o / 100;

  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs">
        <span className="text-slate-300 font-medium">{label}</span>
        <span className={clsx("font-mono font-semibold", valueColor)}>{display}</span>
      </div>
      <div className="flex gap-1.5">
        {options.map((o) => (
          <button key={o}
            onClick={() => onChange(optionVal(o))}
            className={clsx(
              "flex-1 py-1.5 rounded-lg text-xs font-mono font-medium transition-all border",
              Math.abs(value - optionVal(o)) < 0.0001
                ? clsx(
                    valueColor === "text-red-400"      ? "bg-red-500/20 border-red-500/40 text-red-300"         :
                    valueColor === "text-emerald-400"  ? "bg-emerald-500/20 border-emerald-500/40 text-emerald-300" :
                    valueColor === "text-amber-400"    ? "bg-amber-500/20 border-amber-500/40 text-amber-300"    :
                    valueColor === "text-sky-400"      ? "bg-sky-500/20 border-sky-500/40 text-sky-300"          :
                    valueColor === "text-violet-400"   ? "bg-violet-500/20 border-violet-500/40 text-violet-300" :
                    "bg-orange-500/20 border-orange-500/40 text-orange-300"
                  )
                : "border-white/5 text-slate-500 hover:text-slate-300",
            )}
          >{optionDisplay(o)}</button>
        ))}
      </div>
    </div>
  );
}

/** For fields stored as raw fractions with non-×100 display (e.g. ATR multiplier stored as 1.5, options [10,15,20,25] meaning 1.0,1.5,2.0,2.5) */
function RawRow({
  label, value, options, onChange, valueColor, display, optLabel,
}: {
  label: string; value: number; options: number[];
  onChange: (v: number) => void; valueColor: string;
  display: (v: number) => string; optLabel: (o: number) => string;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs">
        <span className="text-slate-300 font-medium">{label}</span>
        <span className={clsx("font-mono font-semibold", valueColor)}>{display(value)}</span>
      </div>
      <div className="flex gap-1.5">
        {options.map((o) => (
          <button key={o}
            onClick={() => onChange(o)}
            className={clsx(
              "flex-1 py-1.5 rounded-lg text-xs font-mono font-medium transition-all border",
              Math.abs(value - o) < 0.0001
                ? clsx(
                    valueColor === "text-sky-400"    ? "bg-sky-500/20 border-sky-500/40 text-sky-300"       :
                    valueColor === "text-violet-400" ? "bg-violet-500/20 border-violet-500/40 text-violet-300" :
                    "bg-brand-500/20 border-brand-500/40 text-brand-300"
                  )
                : "border-white/5 text-slate-500 hover:text-slate-300",
            )}
          >{optLabel(o)}</button>
        ))}
      </div>
    </div>
  );
}

function OptionRow<T extends string>({
  label, sublabel, value, current, onSelect, accent,
}: {
  label: string; sublabel?: string; value: T; current: T;
  onSelect: (v: T) => void; accent?: string;
}) {
  const active = value === current;
  return (
    <button
      onClick={() => onSelect(value)}
      className={clsx(
        "w-full text-left px-4 py-3 rounded-xl border transition-all",
        active ? `${accent ?? "border-brand-500/40 bg-brand-500/10"}` : "border-white/5 hover:border-white/10 hover:bg-white/[0.02]",
      )}
    >
      <div className="flex items-center justify-between">
        <div>
          <div className={clsx("text-sm font-medium", active ? (accent ? "" : "text-brand-300") : "text-slate-300")}>{label}</div>
          {sublabel && <div className="text-[11px] text-slate-500 mt-0.5">{sublabel}</div>}
        </div>
        <div className={clsx("w-4 h-4 rounded-full border-2 flex items-center justify-center transition-colors", active ? "border-brand-500 bg-brand-500" : "border-slate-600")}>
          {active && <div className="w-1.5 h-1.5 rounded-full bg-white" />}
        </div>
      </div>
    </button>
  );
}

function SecondSlider({ label, value, options, onChange }: {
  label: string; value: number; options: number[]; onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex justify-between text-xs">
        <span className="text-slate-400">{label}</span>
        <span className="font-mono font-semibold text-slate-200">{value}s</span>
      </div>
      <div className="flex gap-2">
        {options.map((o) => (
          <button key={o} onClick={() => onChange(o)}
            className={clsx(
              "flex-1 py-1.5 rounded-lg text-xs font-mono font-medium transition-all border",
              value === o ? "bg-brand-500/20 border-brand-500/40 text-brand-300" : "border-white/5 text-slate-500 hover:text-slate-300",
            )}
          >{o}s</button>
        ))}
      </div>
    </div>
  );
}

function NumberSlider({ label, value, options, onChange }: {
  label: string; value: number; options: number[]; onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex justify-between text-xs">
        <span className="text-slate-400">{label}</span>
        <span className="font-mono font-semibold text-slate-200">{value}%</span>
      </div>
      <div className="flex gap-2">
        {options.map((o) => (
          <button key={o} onClick={() => onChange(o)}
            className={clsx(
              "flex-1 py-1.5 rounded-lg text-xs font-mono font-medium transition-all border",
              value === o ? "bg-brand-500/20 border-brand-500/40 text-brand-300" : "border-white/5 text-slate-500 hover:text-slate-300",
            )}
          >{o}%</button>
        ))}
      </div>
    </div>
  );
}

// ── Brain / LLM configuration panel ──────────────────────────────────────────

const PROVIDER_LABELS: Record<string, string> = {
  openrouter: "OpenRouter",
  openai:     "OpenAI",
  anthropic:  "Anthropic",
  deepseek:   "DeepSeek",
  xai:        "xAI (Grok)",
  qwen:       "Qwen (Alibaba)",
  kimi:       "Kimi (Moonshot)",
};

const LOW_CONFIDENCE_PROVIDERS = new Set(["qwen", "kimi"]);

const PROVIDER_KEY_FIELDS: { provider: string; field: keyof LlmSavePayload }[] = [
  { provider: "openrouter", field: "openrouter_key" },
  { provider: "openai",     field: "openai_key" },
  { provider: "anthropic",  field: "anthropic_key" },
  { provider: "deepseek",   field: "deepseek_key" },
  { provider: "xai",        field: "xai_key" },
  { provider: "qwen",       field: "qwen_key" },
  { provider: "kimi",       field: "kimi_key" },
];

function BrainLLMPanel() {
  const llm = useLlmSettings();

  // Local draft — tracks in-progress changes before Save
  const [draft, setDraft] = useState<LlmSavePayload | null>(null);
  // Tracks which key fields have been touched (to know if a value should be sent)
  const [keyDraft, setKeyDraft] = useState<Record<string, string>>({});
  // Controls key field visibility (show/hide per provider)
  const [keyVisible, setKeyVisible] = useState<Record<string, boolean>>({});

  const base: LlmSavePayload = draft ?? {
    tactical_provider:  llm.settings?.tactical_provider  ?? "openrouter",
    tactical_model:     llm.settings?.tactical_model     ?? "google/gemini-2.5-flash-lite",
    synthesis_provider: llm.settings?.synthesis_provider ?? "openrouter",
    synthesis_model:    llm.settings?.synthesis_model    ?? "deepseek/deepseek-chat-v3-0324",
  };

  function updateDraft(partial: Partial<LlmSavePayload>) {
    setDraft((prev) => ({ ...(prev ?? base), ...partial }));
  }

  const providers = llm.models?.providers ?? PROVIDER_LABELS;
  const modelsByProvider = llm.models?.models ?? {};
  const confidenceNotes = llm.models?.confidence_notes ?? {};
  const keysConfigured = new Set(llm.settings?.keys_configured ?? []);

  function modelsFor(provider: string): string[] {
    return modelsByProvider[provider] ?? [];
  }

  async function handleSave() {
    const payload: LlmSavePayload = {
      ...base,
      ...keyDraft,  // include any key fields the user typed
    };
    await llm.save(payload);
    setKeyDraft({});
    setKeyVisible({});
  }

  if (!llm.settings && !llm.models) {
    return (
      <div className="text-xs text-slate-500 font-mono animate-pulse">
        Loading Brain settings… (requires login)
      </div>
    );
  }

  function ProviderSelect({ label, value, onChange }: {
    label: string; value: string; onChange: (v: string) => void;
  }) {
    return (
      <div className="space-y-1.5">
        <span className="text-xs text-slate-400">{label}</span>
        <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
          {Object.entries(providers).map(([key, name]) => (
            <button key={key} onClick={() => onChange(key)}
              className={clsx(
                "py-2 px-2 rounded-xl text-xs font-medium border transition-all text-center leading-tight",
                value === key
                  ? "bg-brand-500/20 border-brand-500/40 text-brand-300"
                  : "border-white/5 text-slate-400 hover:text-slate-200 hover:border-white/10",
              )}
            >
              {name}
              {LOW_CONFIDENCE_PROVIDERS.has(key) && (
                <div className="text-[9px] text-amber-400/70 mt-0.5">~{key === "qwen" ? "92" : "90"}% conf</div>
              )}
            </button>
          ))}
        </div>
        {LOW_CONFIDENCE_PROVIDERS.has(value) && (
          <SectionNote variant="warn">{confidenceNotes[value] ?? `${value} endpoint confidence is below 95% — verify the URL before use.`}</SectionNote>
        )}
      </div>
    );
  }

  function ModelSelect({ label, provider, value, onChange }: {
    label: string; provider: string; value: string; onChange: (v: string) => void;
  }) {
    const [custom, setCustom] = useState(false);
    const models = modelsFor(provider);
    const isKnown = models.includes(value);
    return (
      <div className="space-y-1.5">
        <span className="text-xs text-slate-400">{label}</span>
        {models.length > 0 && !custom ? (
          <>
            <div className="space-y-1">
              {models.map((m) => (
                <button key={m} onClick={() => onChange(m)}
                  className={clsx(
                    "w-full text-left px-3 py-2 rounded-lg text-xs font-mono border transition-all",
                    value === m
                      ? "bg-brand-500/15 border-brand-500/30 text-brand-300"
                      : "border-white/5 text-slate-400 hover:text-slate-200 hover:border-white/10",
                  )}
                >{m}</button>
              ))}
            </div>
            <button onClick={() => setCustom(true)} className="text-[11px] text-slate-500 hover:text-slate-300 font-mono underline">
              Enter custom model ID
            </button>
          </>
        ) : (
          <>
            <input
              type="text"
              value={value}
              onChange={(e) => onChange(e.target.value)}
              placeholder="e.g. provider/model-name"
              className="w-full bg-surface-700 border border-white/10 rounded-xl px-3 py-2 text-xs font-mono text-slate-200 outline-none focus:ring-1 focus:ring-brand-500"
            />
            {models.length > 0 && (
              <button onClick={() => { setCustom(false); if (!isKnown) onChange(models[0]); }}
                className="text-[11px] text-slate-500 hover:text-slate-300 font-mono underline">
                Choose from list
              </button>
            )}
          </>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <SectionNote>
        Each user configures their own LLM provider and API key — stored encrypted in your session.
        Keys are <strong>write-only</strong>: once saved, values are never returned.
        The auto-trader orchestrator always uses the system OpenRouter key; only browser-initiated
        signals use these per-user settings.
      </SectionNote>

      {/* ── Tactical agents (25 analysts + personas) ─────────────────────── */}
      <SubSection title="Tactical Agents (25 analysts)" />
      <ProviderSelect
        label="Provider"
        value={base.tactical_provider}
        onChange={(v) => updateDraft({ tactical_provider: v, tactical_model: modelsFor(v)[0] ?? base.tactical_model })}
      />
      <ModelSelect
        label="Model"
        provider={base.tactical_provider}
        value={base.tactical_model}
        onChange={(v) => updateDraft({ tactical_model: v })}
      />

      {/* ── Synthesis agents (StrategyCoach + RiskManager) ───────────────── */}
      <SubSection title="Synthesis Agents (StrategyCoach + RiskManager)" />
      <ProviderSelect
        label="Provider"
        value={base.synthesis_provider}
        onChange={(v) => updateDraft({ synthesis_provider: v, synthesis_model: modelsFor(v)[0] ?? base.synthesis_model })}
      />
      <ModelSelect
        label="Model"
        provider={base.synthesis_provider}
        value={base.synthesis_model}
        onChange={(v) => updateDraft({ synthesis_model: v })}
      />

      {/* ── API Keys (write-only) ─────────────────────────────────────────── */}
      <SubSection title="API Keys" />
      <SectionNote>
        Enter the API key for each provider you use. Leave blank to keep the stored key unchanged.
        A green dot indicates a key is already saved.
      </SectionNote>
      <div className="space-y-2">
        {PROVIDER_KEY_FIELDS.map(({ provider, field }) => {
          const isSet = keysConfigured.has(provider);
          const isVisible = keyVisible[provider];
          return (
            <div key={provider} className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-400 w-28 shrink-0 font-mono">{PROVIDER_LABELS[provider]}</span>
                {isSet && !keyDraft[field as string] && (
                  <span className="w-2 h-2 rounded-full bg-emerald-400 shrink-0" title="Key saved" />
                )}
                <div className="flex-1 relative">
                  <input
                    type={isVisible ? "text" : "password"}
                    value={keyDraft[field as string] ?? ""}
                    onChange={(e) => setKeyDraft((prev) => ({ ...prev, [field as string]: e.target.value }))}
                    placeholder={isSet ? "••••••••  (stored — leave blank to keep)" : "Paste API key…"}
                    autoComplete="off"
                    className="w-full bg-surface-700 border border-white/10 rounded-lg px-3 py-1.5 text-xs font-mono text-slate-200 outline-none focus:ring-1 focus:ring-brand-500 pr-16"
                  />
                  <button
                    type="button"
                    onClick={() => setKeyVisible((p) => ({ ...p, [provider]: !p[provider] }))}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] text-slate-500 hover:text-slate-300 font-mono"
                  >
                    {isVisible ? "hide" : "show"}
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* ── Error / Save ──────────────────────────────────────────────────── */}
      {llm.error && <p className="text-xs text-red-400 font-mono">{llm.error}</p>}
      <button
        onClick={handleSave}
        disabled={llm.saving}
        className="w-full py-2 rounded-xl bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-xs font-medium transition-colors"
      >
        {llm.saving ? "Saving…" : llm.saved ? "Saved ✓" : "Save Brain settings"}
      </button>
    </div>
  );
}

// ── Full engine config panel ──────────────────────────────────────────────────

type EngineLocal = RiskConfigFields;

const ENGINE_DEFAULTS: EngineLocal = {
  stop_loss_pct: 0.02, take_profit_pct: 0.05, trailing_stop_pct: 0.015,
  partial_exit_pct: 0.50, runner_trail_pct: 0.10,
  max_position_pct: 0.05, hot_position_pct: 0.08, max_crypto_allocation_pct: 0.30,
  max_exposure_pct: 0.50, max_concurrent_positions: 15,
  circuit_breaker_drawdown: 0.10, drawdown_scale_threshold: 0.08, drawdown_scale_factor: 0.80,
  correlation_halving_threshold: 0.70,
  signal_confidence_threshold: 0.70, lookback_days: 300,
  atr_multiplier: 1.5, atr_stop_floor: 0.005, atr_stop_cap: 0.04,
  loss_cooldown_hits: 2, loss_cooldown_window_days: 5, loss_cooldown_skip_cycles: 2,
  max_telegram_order_usd: 1000,
};

function EngineConfigPanel() {
  const riskCfg = useRiskConfig();
  const [local, setLocal] = useState<EngineLocal | null>(null);

  const c = riskCfg.config;
  const vals: EngineLocal = local ?? (c ? { ...c } : ENGINE_DEFAULTS);

  function set<K extends keyof EngineLocal>(key: K) {
    return (v: EngineLocal[K]) => setLocal({ ...vals, [key]: v });
  }

  return (
    <div className="space-y-4">
      <SectionNote>
        All parameters below control the live auto-trader. Changes apply on the next monitor tick
        (&le;1 min) without a redeploy. The <strong>Reset</strong> button reverts to Railway env var
        defaults.
        {c && (
          <span className={clsx(
            "ml-1.5 px-1.5 py-0.5 rounded text-[10px] font-semibold",
            c.source === "dynamic" ? "bg-brand-500/20 text-brand-300" : "bg-slate-500/20 text-slate-400",
          )}>
            {c.source === "dynamic" ? "custom values active" : "using Railway defaults"}
          </span>
        )}
      </SectionNote>

      {c === null ? (
        <div className="text-xs text-slate-500 font-mono animate-pulse">Loading engine config…</div>
      ) : (
        <>
          {/* ── Entry / Exit ───────────────────────────────────────────────── */}
          <SubSection title="Entry / Exit" />

          <SectionNote variant="warn">
            <strong>Stop Loss</strong> is the <em>fallback</em> used only when ATR data is unavailable.
            The actual stop placed on Alpaca is ATR-based: <strong>atr_multiplier × ATR14</strong>,
            clamped to [ATR Floor, ATR Cap] below. Set those to control real stop width.
          </SectionNote>
          <RiskRow label="Stop Loss (ATR fallback)" value={vals.stop_loss_pct} options={[1,2,3,5]} onChange={set("stop_loss_pct")} valueColor="text-red-400" />

          <SectionNote variant="warn">
            <strong>Take Profit</strong> is the base TP. The orchestrator adjusts it by regime:
            TRENDING_UP → min 8% · RANGING → max 3% · HIGH_VOLATILITY → max 5%.
            These regime overrides override whatever value you set here.
          </SectionNote>
          <RiskRow label="Take Profit (base)" value={vals.take_profit_pct} options={[3,5,8,10,15]} onChange={set("take_profit_pct")} valueColor="text-emerald-400" />

          <RiskRow label="Trailing Stop %" value={vals.trailing_stop_pct} options={[1,1.5,2,2.5,3]} onChange={set("trailing_stop_pct")} valueColor="text-sky-400"
            formatFn={(v) => `${(v * 100).toFixed(1)}%`} />

          <RiskRow label="Partial Exit (Layer 1 fraction)" value={vals.partial_exit_pct} options={[25,33,40,50]} onChange={set("partial_exit_pct")} valueColor="text-sky-400"
            formatFn={(v) => `${(v * 100).toFixed(0)}%`} />

          <RiskRow label="Runner Trail %" value={vals.runner_trail_pct} options={[5,8,10,12,15]} onChange={set("runner_trail_pct")} valueColor="text-sky-400"
            formatFn={(v) => `${(v * 100).toFixed(0)}%`} />

          {/* ── Position Sizing ────────────────────────────────────────────── */}
          <SubSection title="Position Sizing" />

          <RiskRow label="Max Position % (WARM signals)" value={vals.max_position_pct} options={[3,5,8,10]} onChange={set("max_position_pct")} valueColor="text-amber-400" />
          <RiskRow label="Max Position % (HOT signals)" value={vals.hot_position_pct} options={[5,8,10,15]} onChange={set("hot_position_pct")} valueColor="text-amber-400" />
          <RiskRow label="Max Crypto Allocation" value={vals.max_crypto_allocation_pct} options={[10,20,30,40]} onChange={set("max_crypto_allocation_pct")} valueColor="text-violet-400" />

          {/* ── Portfolio Exposure ─────────────────────────────────────────── */}
          <SubSection title="Portfolio Exposure" />

          <RiskRow label="Max Portfolio Exposure" value={vals.max_exposure_pct} options={[30,40,50,62,75]} onChange={set("max_exposure_pct")} valueColor="text-amber-400"
            formatFn={(v) => `${(v * 100).toFixed(0)}%`} />

          <RawRow label="Max Concurrent Positions"
            value={vals.max_concurrent_positions} options={[5,10,15,20,25]}
            onChange={set("max_concurrent_positions")} valueColor="text-amber-400"
            display={(v) => `${v}`} optLabel={(o) => `${o}`} />

          {/* ── Circuit Breaker / Drawdown ─────────────────────────────────── */}
          <SubSection title="Circuit Breaker &amp; Drawdown" />

          <RiskRow label="Circuit Breaker (halt all trading)" value={vals.circuit_breaker_drawdown} options={[5,10,15,20]} onChange={set("circuit_breaker_drawdown")} valueColor="text-orange-400" />
          <RiskRow label="Drawdown Scale Threshold" value={vals.drawdown_scale_threshold} options={[5,8,10,15]} onChange={set("drawdown_scale_threshold")} valueColor="text-orange-400" />
          <RiskRow label="Drawdown Scale Factor" value={vals.drawdown_scale_factor} options={[60,70,80,90]} onChange={set("drawdown_scale_factor")} valueColor="text-orange-400"
            formatFn={(v) => `${(v * 100).toFixed(0)}%`} />

          {/* ── Correlation ────────────────────────────────────────────────── */}
          <SubSection title="Correlation Protection" />

          <SectionNote>
            When a new BUY signal correlates above this threshold with any open position over the last
            60 days, the position size is automatically halved.
          </SectionNote>
          <RiskRow label="Correlation Halving Threshold" value={vals.correlation_halving_threshold} options={[50,60,70,80]} onChange={set("correlation_halving_threshold")}
            valueColor="text-slate-300" formatFn={(v) => `${(v * 100).toFixed(0)}%`} />

          {/* ── ATR Stop Sizing ────────────────────────────────────────────── */}
          <SubSection title="ATR Stop Sizing" />

          <SectionNote>
            Actual stop = <strong>ATR Multiplier × ATR14</strong>, then clamped to [Floor, Cap].
            Higher multiplier = wider stops (fewer false exits). Raise the Cap to allow wider stops
            on volatile stocks.
          </SectionNote>
          <RawRow label="ATR Multiplier"
            value={vals.atr_multiplier} options={[1.0,1.5,2.0,2.5]}
            onChange={set("atr_multiplier")} valueColor="text-sky-400"
            display={(v) => `${v.toFixed(1)}×`} optLabel={(o) => `${o}×`} />
          <RiskRow label="ATR Floor (min stop)" value={vals.atr_stop_floor} options={[0.25,0.5,1.0]} onChange={set("atr_stop_floor")} valueColor="text-sky-400" />
          <RiskRow label="ATR Cap (max stop)" value={vals.atr_stop_cap} options={[2,3,4,5]} onChange={set("atr_stop_cap")} valueColor="text-sky-400" />

          {/* ── Signal Quality ─────────────────────────────────────────────── */}
          <SubSection title="Signal Quality" />

          <RiskRow label="Signal Confidence Threshold" value={vals.signal_confidence_threshold} options={[50,60,70,80]} onChange={set("signal_confidence_threshold")}
            valueColor="text-violet-400" formatFn={(v) => `${(v * 100).toFixed(0)}%`} />

          <RawRow label="Lookback Days (historical window)"
            value={vals.lookback_days} options={[90,150,200,300]}
            onChange={set("lookback_days")} valueColor="text-violet-400"
            display={(v) => `${v}d`} optLabel={(o) => `${o}d`} />

          {/* ── Loss Cooldown ──────────────────────────────────────────────── */}
          <SubSection title="Loss Cooldown" />

          <SectionNote>
            When a symbol hits stop-loss <strong>N times within W days</strong>, it is skipped for
            the next <strong>S scan cycles</strong>. Prevents re-entering a symbol that is breaking down.
          </SectionNote>
          <RawRow label="Trigger Hits"
            value={vals.loss_cooldown_hits} options={[1,2,3,5]}
            onChange={set("loss_cooldown_hits")} valueColor="text-orange-400"
            display={(v) => `${v} hits`} optLabel={(o) => `${o}`} />
          <RawRow label="Lookback Window"
            value={vals.loss_cooldown_window_days} options={[3,5,7,14]}
            onChange={set("loss_cooldown_window_days")} valueColor="text-orange-400"
            display={(v) => `${v} days`} optLabel={(o) => `${o}d`} />
          <RawRow label="Skip Cycles on Cooldown"
            value={vals.loss_cooldown_skip_cycles} options={[1,2,3,5]}
            onChange={set("loss_cooldown_skip_cycles")} valueColor="text-orange-400"
            display={(v) => `${v} cycles`} optLabel={(o) => `${o}`} />

          {/* ── Telegram ──────────────────────────────────────────────────── */}
          <SubSection title="Telegram Safety" />

          <RawRow label="Max Order Size (USD)"
            value={vals.max_telegram_order_usd} options={[100,500,1000,5000,10000]}
            onChange={set("max_telegram_order_usd")} valueColor="text-slate-300"
            display={(v) => `$${v.toLocaleString()}`} optLabel={(o) => `$${(o >= 1000 ? `${o / 1000}k` : o)}`} />

          {/* ── Errors & actions ──────────────────────────────────────────── */}
          {riskCfg.error && <p className="text-xs text-red-400 font-mono">{riskCfg.error}</p>}

          <div className="flex gap-2 pt-1">
            <button
              onClick={() => riskCfg.save(vals)}
              disabled={riskCfg.saving}
              className="flex-1 py-2 rounded-xl bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-xs font-medium transition-colors"
            >
              {riskCfg.saving ? "Saving…" : riskCfg.saved ? "Saved ✓" : "Push to engine"}
            </button>
            <button
              onClick={() => { riskCfg.reset(); setLocal(null); }}
              disabled={riskCfg.saving}
              title="Reset to Railway env var defaults"
              className="px-3 py-2 rounded-xl border border-white/10 text-slate-400 hover:text-slate-200 hover:border-white/20 transition-colors disabled:opacity-50"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          </div>

          {c.source === "dynamic" && (
            <p className="text-[10px] text-slate-500 font-mono">
              Railway defaults: SL {(c.defaults.stop_loss_pct * 100).toFixed(1)}% · TP {(c.defaults.take_profit_pct * 100).toFixed(1)}%
              · Trail {(c.defaults.trailing_stop_pct * 100).toFixed(1)}% · MaxPos {(c.defaults.max_position_pct * 100).toFixed(0)}%
              &nbsp;— &uarr; to revert.
            </p>
          )}
        </>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function SettingsPage() {
  const [profile, setProfile] = useState<UserProfile>(loadProfile);
  const [saved, setSaved] = useState(false);
  const configStatus = useConfigStatus();

  function update(partial: Partial<UserProfile>) {
    setProfile((p) => ({ ...p, ...partial }));
    setSaved(false);
  }
  function handleSave() {
    saveProfile(profile);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }
  function handleReset() {
    setProfile(DEFAULT_PROFILE);
    saveProfile(DEFAULT_PROFILE);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  return (
    <div className="max-w-2xl space-y-6">

      {/* ── Auto-Trade Engine status ──────────────────────────────────────── */}
      <Section icon={<Zap className="w-4 h-4" />} title="Auto-Trade Engine">
        {configStatus === null ? (
          <div className="text-xs text-slate-500 font-mono animate-pulse">Checking engine status…</div>
        ) : configStatus.auto_trade ? (
          <div className="flex items-start gap-3 bg-emerald-500/10 border border-emerald-500/30 rounded-xl px-4 py-3">
            <span className="mt-0.5 w-2 h-2 rounded-full bg-emerald-400 shrink-0 animate-pulse" />
            <div className="space-y-1">
              <p className="text-sm font-medium text-emerald-300">Orchestrator running</p>
              <p className="text-[11px] text-slate-400 font-mono">
                Scanning {configStatus?.total_symbols ?? "…"} symbols every {configStatus?.cycle_interval_minutes ?? 15} minutes
                ({configStatus?.watchlist_stocks?.length ?? "…"} stocks · {configStatus?.watchlist_etfs?.length ?? "…"} ETFs · {configStatus?.watchlist_crypto?.length ?? "…"} crypto).
                BUY/SELL signals are executed automatically on Alpaca.
              </p>
            </div>
          </div>
        ) : (
          <div className="flex items-start gap-3 bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3">
            <span className="mt-0.5 w-2 h-2 rounded-full bg-red-400 shrink-0" />
            <div className="space-y-1.5">
              <p className="text-sm font-medium text-red-300">Orchestrator not running — no trades will be placed</p>
              <p className="text-[11px] text-slate-400 font-mono leading-relaxed">
                Add the following environment variable in Railway to enable auto-trading:
              </p>
              <div className="bg-surface-800 rounded-lg px-3 py-2 font-mono text-[11px] text-emerald-400 border border-white/5">
                AUTO_TRADE = true
              </div>
            </div>
          </div>
        )}
      </Section>

      {/* ── Execution Mode ────────────────────────────────────────────────── */}
      <Section icon={<Brain className="w-4 h-4" />} title="Execution Mode (Dashboard)">
        <SectionNote variant="warn">
          This controls how <strong>dashboard signal cards</strong> behave — it does not affect the
          background orchestrator. Set AUTO_TRADE=true above for real background trading.
        </SectionNote>
        <div className="space-y-2">
          {(["auto", "assisted", "manual"] as HITLMode[]).map((m) => (
            <OptionRow key={m} value={m} current={profile.mode}
              onSelect={(v) => update({ mode: v })}
              label={MODE_CONFIG[m].label} sublabel={MODE_CONFIG[m].description}
              accent={
                m === "auto"     ? "border-emerald-500/40 bg-emerald-500/10" :
                m === "assisted" ? "border-amber-500/40 bg-amber-500/10"     :
                                   "border-slate-500/40 bg-slate-500/10"
              }
            />
          ))}
        </div>
        <SectionNote>
          {configStatus
            ? `Signal tier logic: HOT = ${configStatus.hot_min_votes}+/${configStatus.agent_count} votes · WARM = ${configStatus.warm_min_votes}–${configStatus.hot_min_votes - 1}/${configStatus.agent_count} · COLD = <${configStatus.warm_min_votes} or panels conflict`
            : "Signal tier logic: loading…"}
        </SectionNote>
      </Section>

      {/* ── Brain / LLM ───────────────────────────────────────────────────── */}
      <Section
        icon={<Brain className="w-4 h-4" />}
        title="Brain / LLM"
        subtitle="Per-user LLM provider, model, and API key — stored encrypted in your session"
      >
        <BrainLLMPanel />
      </Section>

      {/* ── Engine Config (all parameters) ───────────────────────────────── */}
      <Section
        icon={<Shield className="w-4 h-4" />}
        title="Auto-Trade Engine Config"
        subtitle="All parameters that drive live trading — changes apply within 1 minute without redeploy"
      >
        <EngineConfigPanel />
      </Section>

      {/* ── Trader Profile (local only) ───────────────────────────────────── */}
      <Section
        icon={<TrendingUp className="w-4 h-4" />}
        title="Trader Profile"
        subtitle="Used by Strategy Coach for personalised coaching — stored locally, does not affect the auto-trader"
      >
        <SectionNote>
          Strategy Coach uses this profile to separate market analysis from personalised coaching.
          Be honest — the system optimises for your real tolerance, not your aspirational one.
        </SectionNote>
        <div className="space-y-3">
          <div className="space-y-2">
            <span className="text-xs text-slate-400">Time Horizon</span>
            <div className="grid grid-cols-4 gap-2">
              {([
                { v: "scalper",  label: "Scalper",  sub: "5m–1h" },
                { v: "intraday", label: "Intraday", sub: "1h–4h" },
                { v: "swing",    label: "Swing",    sub: "1D–1W" },
                { v: "position", label: "Position", sub: "1W+"   },
              ] as const).map(({ v, label, sub }) => (
                <button key={v} onClick={() => update({ timeHorizon: v })}
                  className={clsx(
                    "py-2.5 rounded-xl text-xs font-medium border transition-all text-center",
                    profile.timeHorizon === v
                      ? "bg-brand-500/20 border-brand-500/40 text-brand-300"
                      : "border-white/5 text-slate-400 hover:text-slate-200",
                  )}
                >
                  <div>{label}</div>
                  <div className="text-[10px] text-slate-500 mt-0.5 font-mono">{sub}</div>
                </button>
              ))}
            </div>
          </div>
          <NumberSlider label="Max drawdown tolerance" value={profile.maxDrawdownPct} options={[5,10,15,20]} onChange={(v) => update({ maxDrawdownPct: v })} />
        </div>
      </Section>

      {/* ── Order Defaults (local only, NO duplicate stop/TP) ─────────────── */}
      <Section
        icon={<Package className="w-4 h-4" />}
        title="Manual Order Defaults"
        subtitle="Used for the manual order window in the dashboard — does not affect the auto-trader"
      >
        <SectionNote>
          Sets the default share/unit count and sizing method for manual orders placed from dashboard
          signal cards. Auto-trader sizing is controlled entirely by Engine Config above.
        </SectionNote>

        <div className="space-y-2">
          <span className="text-xs text-slate-400">Sizing method</span>
          <div className="grid grid-cols-2 gap-2">
            {([
              { v: false, label: "Position-based", sub: "Equity × position % (recommended)" },
              { v: true,  label: "Fixed quantity",  sub: "Exact share / unit count" },
            ] as const).map(({ v, label, sub }) => (
              <button key={String(v)} onClick={() => update({ useFixedQty: v })}
                className={clsx(
                  "text-left px-4 py-3 rounded-xl border transition-all",
                  profile.useFixedQty === v ? "border-brand-500/40 bg-brand-500/10" : "border-white/5 hover:border-white/10 hover:bg-white/[0.02]",
                )}
              >
                <div className={clsx("text-sm font-medium", profile.useFixedQty === v ? "text-brand-300" : "text-slate-300")}>{label}</div>
                <div className="text-[11px] text-slate-500 mt-0.5">{sub}</div>
              </button>
            ))}
          </div>
        </div>

        {profile.useFixedQty && (
          <div className="space-y-2">
            <div className="flex justify-between text-xs">
              <span className="text-slate-400">Default quantity (shares / units)</span>
              <span className="font-mono font-semibold text-slate-200">{profile.defaultQty} shares</span>
            </div>
            <input
              type="number" min={1} step={1} value={profile.defaultQty}
              onChange={(e) => { const v = parseFloat(e.target.value); if (!isNaN(v) && v > 0) update({ defaultQty: v }); }}
              className="w-full bg-surface-700 border border-white/10 rounded-xl px-4 py-2.5 text-sm font-mono text-slate-200 outline-none focus:ring-1 focus:ring-brand-500"
              placeholder="e.g. 10"
            />
            <p className="text-[11px] text-slate-500 font-mono">
              This many shares will be submitted to Alpaca for every BUY / SELL order.
              For crypto, enter fractional units (e.g. 0.01 BTC).
            </p>
          </div>
        )}
      </Section>

      {/* ── Confirmation Timing ───────────────────────────────────────────── */}
      <Section icon={<Clock className="w-4 h-4" />} title="Confirmation Timing">
        <SecondSlider label="Warm signal veto window" value={profile.warmVetoSeconds} options={[10,30,60]} onChange={(v) => update({ warmVetoSeconds: v })} />
        <SecondSlider label="Over-limit cool-off timer (Manual mode)" value={profile.coolOffSeconds} options={[15,30,60]} onChange={(v) => update({ coolOffSeconds: v })} />
        <SectionNote>
          Cool-off activates when a manual trade exceeds your position size limit. It doesn&apos;t
          block — it inconveniences the impulse.
        </SectionNote>
      </Section>

      {/* ── Save / Reset profile ─────────────────────────────────────────── */}
      <div className="flex items-center gap-3">
        <button onClick={handleSave} className="flex-1 py-2.5 rounded-xl bg-brand-600 hover:bg-brand-500 text-sm font-medium transition-colors">
          {saved ? "Saved ✓" : "Save dashboard profile"}
        </button>
        <button onClick={handleReset} className="px-4 py-2.5 rounded-xl border border-white/10 text-sm text-slate-400 hover:text-slate-200 hover:border-white/20 transition-colors">
          Reset defaults
        </button>
      </div>

    </div>
  );
}
