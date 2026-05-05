import clsx from "clsx";
import { Brain, Package, RefreshCw, Shield, Timer, TrendingUp, Zap } from "lucide-react";
import {
  HITLMode, UserProfile, DEFAULT_PROFILE,
  MODE_CONFIG, loadProfile, saveProfile,
} from "../lib/hitl";
import { useConfigStatus, useRiskConfig } from "../lib/api";
import { useState } from "react";

function Section({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="glass rounded-2xl p-5 space-y-4">
      <div className="flex items-center gap-2.5">
        <div className="w-7 h-7 rounded-lg bg-brand-500/15 flex items-center justify-center text-brand-400">
          {icon}
        </div>
        <h3 className="text-sm font-semibold">{title}</h3>
      </div>
      {children}
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
        active
          ? `${accent ?? "border-brand-500/40 bg-brand-500/10"}`
          : "border-white/5 hover:border-white/10 hover:bg-white/[0.02]",
      )}
    >
      <div className="flex items-center justify-between">
        <div>
          <div className={clsx("text-sm font-medium", active ? (accent ? "" : "text-brand-300") : "text-slate-300")}>
            {label}
          </div>
          {sublabel && <div className="text-[11px] text-slate-500 mt-0.5">{sublabel}</div>}
        </div>
        <div className={clsx(
          "w-4 h-4 rounded-full border-2 flex items-center justify-center transition-colors",
          active ? "border-brand-500 bg-brand-500" : "border-slate-600",
        )}>
          {active && <div className="w-1.5 h-1.5 rounded-full bg-white" />}
        </div>
      </div>
    </button>
  );
}

function NumberSlider({
  label, value, options, onChange,
}: {
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
          <button
            key={o}
            onClick={() => onChange(o)}
            className={clsx(
              "flex-1 py-1.5 rounded-lg text-xs font-mono font-medium transition-all border",
              value === o
                ? "bg-brand-500/20 border-brand-500/40 text-brand-300"
                : "border-white/5 text-slate-500 hover:text-slate-300",
            )}
          >
            {o}%
          </button>
        ))}
      </div>
    </div>
  );
}

function SecondSlider({
  label, value, options, onChange,
}: {
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
          <button
            key={o}
            onClick={() => onChange(o)}
            className={clsx(
              "flex-1 py-1.5 rounded-lg text-xs font-mono font-medium transition-all border",
              value === o
                ? "bg-brand-500/20 border-brand-500/40 text-brand-300"
                : "border-white/5 text-slate-500 hover:text-slate-300",
            )}
          >
            {o}s
          </button>
        ))}
      </div>
    </div>
  );
}

type RiskLocal = {
  stop_loss_pct: number;
  take_profit_pct: number;
  max_position_pct: number;
  circuit_breaker_drawdown: number;
};

function RiskRow({
  label, value, options, onChange, valueColor,
}: {
  label: string; value: number; options: number[];
  onChange: (v: number) => void;
  valueColor: string;
  suffix?: string;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs">
        <span className="text-slate-300 font-medium">{label}</span>
        <span className={clsx("font-mono font-semibold", valueColor)}>{(value * 100).toFixed(1)}%</span>
      </div>
      <div className="flex gap-1.5">
        {options.map((o) => (
          <button key={o}
            onClick={() => onChange(o / 100)}
            className={clsx(
              "flex-1 py-1.5 rounded-lg text-xs font-mono font-medium transition-all border",
              Math.abs(value - o / 100) < 0.001
                ? clsx(
                    valueColor === "text-red-400"     ? "bg-red-500/20 border-red-500/40 text-red-300"     :
                    valueColor === "text-emerald-400" ? "bg-emerald-500/20 border-emerald-500/40 text-emerald-300" :
                    valueColor === "text-amber-400"   ? "bg-amber-500/20 border-amber-500/40 text-amber-300"   :
                    "bg-orange-500/20 border-orange-500/40 text-orange-300"
                  )
                : "border-white/5 text-slate-500 hover:text-slate-300",
            )}
          >{o}%</button>
        ))}
      </div>
    </div>
  );
}

function RiskConfigPanel() {
  const riskCfg = useRiskConfig();
  const [local, setLocal] = useState<RiskLocal | null>(null);

  // Seed local state from fetched config (once)
  if (riskCfg.config && local === null) {
    // intentionally not in useEffect — we want synchronous first-render seeding
  }

  const c = riskCfg.config;
  const vals: RiskLocal = local ?? (c ? {
    stop_loss_pct:            c.stop_loss_pct,
    take_profit_pct:          c.take_profit_pct,
    max_position_pct:         c.max_position_pct,
    circuit_breaker_drawdown: c.circuit_breaker_drawdown,
  } : { stop_loss_pct: 0.02, take_profit_pct: 0.05, max_position_pct: 0.05, circuit_breaker_drawdown: 0.10 });

  function set(key: keyof RiskLocal) {
    return (v: number) => setLocal((p) => ({ ...vals, ...p, [key]: v }));
  }

  return (
    <div className="space-y-4">
      <div className="text-[11px] text-slate-400 font-mono bg-surface-700 rounded-xl px-3 py-2 leading-relaxed">
        These thresholds control the background orchestrator — positions are closed automatically
        when unrealized P&amp;L hits the stop-loss or take-profit level.
        Changes apply on the next monitor tick (≤1 min) without a redeploy.
        {c && (
          <span className={clsx(
            "ml-1.5 px-1.5 py-0.5 rounded text-[10px] font-semibold",
            c.source === "dynamic"
              ? "bg-brand-500/20 text-brand-300"
              : "bg-slate-500/20 text-slate-400",
          )}>
            {c.source === "dynamic" ? "custom values active" : "using Railway defaults"}
          </span>
        )}
      </div>

      {c === null ? (
        <div className="text-xs text-slate-500 font-mono animate-pulse">Loading engine config…</div>
      ) : (
        <>
          <RiskRow label="Stop loss"       value={vals.stop_loss_pct}            options={[1, 2, 3, 5]}        onChange={set("stop_loss_pct")}            valueColor="text-red-400"     />
          <RiskRow label="Take profit"     value={vals.take_profit_pct}          options={[3, 5, 8, 10, 15]}   onChange={set("take_profit_pct")}          valueColor="text-emerald-400" />
          <RiskRow label="Max position"    value={vals.max_position_pct}         options={[3, 5, 10, 15]}      onChange={set("max_position_pct")}         valueColor="text-amber-400"   />
          <RiskRow label="Circuit breaker" value={vals.circuit_breaker_drawdown} options={[5, 10, 15, 20]}     onChange={set("circuit_breaker_drawdown")} valueColor="text-orange-400"  />

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
              Railway defaults: SL {(c.defaults.stop_loss_pct * 100).toFixed(1)}% · TP {(c.defaults.take_profit_pct * 100).toFixed(1)}% · max pos {(c.defaults.max_position_pct * 100).toFixed(0)}%
              &nbsp;— ↺ to revert.
            </p>
          )}
        </>
      )}
    </div>
  );
}

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
      {/* Auto-Trade engine status */}
      <Section icon={<Zap className="w-4 h-4" />} title="Auto-Trade Engine">
        {configStatus === null ? (
          <div className="text-xs text-slate-500 font-mono animate-pulse">Checking engine status…</div>
        ) : configStatus.auto_trade ? (
          <div className="flex items-start gap-3 bg-emerald-500/10 border border-emerald-500/30 rounded-xl px-4 py-3">
            <span className="mt-0.5 w-2 h-2 rounded-full bg-emerald-400 shrink-0 animate-pulse" />
            <div className="space-y-1">
              <p className="text-sm font-medium text-emerald-300">Orchestrator running</p>
              <p className="text-[11px] text-slate-400 font-mono">
                Scanning watchlist every 15 minutes — AAPL, MSFT, NVDA, TSLA, SPY, QQQ, BTCUSDT, ETHUSDT + more.
                BUY/SELL signals are executed automatically on Alpaca / Binance.
              </p>
            </div>
          </div>
        ) : (
          <div className="flex items-start gap-3 bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3">
            <span className="mt-0.5 w-2 h-2 rounded-full bg-red-400 shrink-0" />
            <div className="space-y-1.5">
              <p className="text-sm font-medium text-red-300">Orchestrator not running — no trades will be placed</p>
              <p className="text-[11px] text-slate-400 font-mono leading-relaxed">
                To enable auto-trading, add the following environment variable in Railway:
              </p>
              <div className="bg-surface-800 rounded-lg px-3 py-2 font-mono text-[11px] text-emerald-400 border border-white/5">
                AUTO_TRADE = true
              </div>
              <p className="text-[11px] text-slate-500 font-mono">
                Then redeploy. The orchestrator will scan symbols every 15 min and submit orders when signals are HOT or WARM.
              </p>
            </div>
          </div>
        )}
      </Section>

      {/* HITL Mode */}
      <Section icon={<Brain className="w-4 h-4" />} title="Execution Mode (Dashboard)">
        <div className="text-[11px] text-amber-400/80 bg-amber-500/10 border border-amber-500/20 rounded-xl px-3 py-2 font-mono">
          This controls how the <b>dashboard signal cards</b> behave — it does not affect the background orchestrator.
          Set AUTO_TRADE=true above to enable real background trading.
        </div>
        <div className="space-y-2">
          {(["auto", "assisted", "manual"] as HITLMode[]).map((m) => (
            <OptionRow
              key={m}
              value={m}
              current={profile.mode}
              onSelect={(v) => update({ mode: v })}
              label={MODE_CONFIG[m].label}
              sublabel={MODE_CONFIG[m].description}
              accent={
                m === "auto"     ? "border-emerald-500/40 bg-emerald-500/10" :
                m === "assisted" ? "border-amber-500/40 bg-amber-500/10"     :
                                   "border-slate-500/40 bg-slate-500/10"
              }
            />
          ))}
        </div>
        <div className="text-[11px] text-slate-500 font-mono bg-surface-700 rounded-xl px-3 py-2">
          Signal tier logic: HOT = 11+/15 agents aligned · WARM = 8–10/15 aligned · COLD = ≤7 aligned or panels conflict
        </div>
      </Section>

      {/* Trader Profile */}
      <Section icon={<TrendingUp className="w-4 h-4" />} title="Trader Profile">
        <div className="space-y-1 text-xs text-amber-400/80 bg-amber-500/10 border border-amber-500/20 rounded-xl px-3 py-2.5 font-mono">
          Strategy Coach uses this profile to separate market analysis from personalised coaching.
          Be honest — the system optimises for your real tolerance, not your aspirational one.
        </div>
        <div className="space-y-3">
          <div className="space-y-2">
            <span className="text-xs text-slate-400">Time Horizon</span>
            <div className="grid grid-cols-4 gap-2">
              {([
                { v: "scalper",  label: "Scalper",  sub: "5m–1h"  },
                { v: "intraday", label: "Intraday", sub: "1h–4h"  },
                { v: "swing",    label: "Swing",    sub: "1D–1W"  },
                { v: "position", label: "Position", sub: "1W+"    },
              ] as const).map(({ v, label, sub }) => (
                <button
                  key={v}
                  onClick={() => update({ timeHorizon: v })}
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
          <NumberSlider
            label="Max drawdown tolerance"
            value={profile.maxDrawdownPct}
            options={[5, 10, 15, 20]}
            onChange={(v) => update({ maxDrawdownPct: v })}
          />
          <NumberSlider
            label="Max single position size"
            value={profile.maxPositionPct}
            options={[3, 5, 10, 15]}
            onChange={(v) => update({ maxPositionPct: v })}
          />
        </div>
      </Section>

      {/* Auto-Trade Risk Controls */}
      <Section icon={<Shield className="w-4 h-4" />} title="Auto-Trade Risk Controls">
        <RiskConfigPanel />
      </Section>

      {/* Order Quantity */}
      <Section icon={<Package className="w-4 h-4" />} title="Order Quantity">
        <div className="text-[11px] text-slate-500 font-mono bg-surface-700 rounded-xl px-3 py-2">
          Sets the default share/unit count sent to Alpaca. Used in Assisted and Auto modes.
          Manual mode respects this too unless you override on the signal card.
        </div>

        {/* Sizing mode toggle */}
        <div className="space-y-2">
          <span className="text-xs text-slate-400">Sizing method</span>
          <div className="grid grid-cols-2 gap-2">
            {([
              { v: false, label: "Position-based",  sub: "Equity × position % (recommended)" },
              { v: true,  label: "Fixed quantity",   sub: "Exact share / unit count" },
            ] as const).map(({ v, label, sub }) => (
              <button
                key={String(v)}
                onClick={() => update({ useFixedQty: v })}
                className={clsx(
                  "text-left px-4 py-3 rounded-xl border transition-all",
                  profile.useFixedQty === v
                    ? "border-brand-500/40 bg-brand-500/10"
                    : "border-white/5 hover:border-white/10 hover:bg-white/[0.02]",
                )}
              >
                <div className={clsx("text-sm font-medium", profile.useFixedQty === v ? "text-brand-300" : "text-slate-300")}>
                  {label}
                </div>
                <div className="text-[11px] text-slate-500 mt-0.5">{sub}</div>
              </button>
            ))}
          </div>
        </div>

        {/* Fixed qty input */}
        {profile.useFixedQty && (
          <div className="space-y-2">
            <div className="flex justify-between text-xs">
              <span className="text-slate-400">Default quantity (shares / units)</span>
              <span className="font-mono font-semibold text-slate-200">{profile.defaultQty} shares</span>
            </div>
            <input
              type="number"
              min={1}
              step={1}
              value={profile.defaultQty}
              onChange={(e) => {
                const v = parseFloat(e.target.value);
                if (!isNaN(v) && v > 0) update({ defaultQty: v });
              }}
              className="w-full bg-surface-700 border border-white/10 rounded-xl px-4 py-2.5 text-sm font-mono text-slate-200 outline-none focus:ring-1 focus:ring-brand-500"
              placeholder="e.g. 10"
            />
            <p className="text-[11px] text-slate-500 font-mono">
              This many shares will be submitted to Alpaca for every BUY / SELL order.
              For crypto, enter fractional units (e.g. 0.01 BTC).
            </p>
          </div>
        )}

        {/* Stop loss / take profit defaults */}
        <div className="grid grid-cols-2 gap-4">
          <div className="space-y-2">
            <div className="flex justify-between text-xs">
              <span className="text-slate-400">Default stop loss</span>
              <span className="font-mono font-semibold text-red-400">{profile.defaultStopLossPct}%</span>
            </div>
            <div className="flex gap-2">
              {[1, 2, 3, 5].map((o) => (
                <button
                  key={o}
                  onClick={() => update({ defaultStopLossPct: o })}
                  className={clsx(
                    "flex-1 py-1.5 rounded-lg text-xs font-mono font-medium transition-all border",
                    profile.defaultStopLossPct === o
                      ? "bg-red-500/20 border-red-500/40 text-red-300"
                      : "border-white/5 text-slate-500 hover:text-slate-300",
                  )}
                >
                  {o}%
                </button>
              ))}
            </div>
          </div>
          <div className="space-y-2">
            <div className="flex justify-between text-xs">
              <span className="text-slate-400">Default take profit</span>
              <span className="font-mono font-semibold text-emerald-400">{profile.defaultTakeProfitPct}%</span>
            </div>
            <div className="flex gap-2">
              {[3, 5, 10, 15].map((o) => (
                <button
                  key={o}
                  onClick={() => update({ defaultTakeProfitPct: o })}
                  className={clsx(
                    "flex-1 py-1.5 rounded-lg text-xs font-mono font-medium transition-all border",
                    profile.defaultTakeProfitPct === o
                      ? "bg-emerald-500/20 border-emerald-500/40 text-emerald-300"
                      : "border-white/5 text-slate-500 hover:text-slate-300",
                  )}
                >
                  {o}%
                </button>
              ))}
            </div>
          </div>
        </div>
      </Section>

      {/* HITL Timing */}
      <Section icon={<Timer className="w-4 h-4" />} title="Confirmation Timing">
        <SecondSlider
          label="Warm signal veto window"
          value={profile.warmVetoSeconds}
          options={[10, 30, 60]}
          onChange={(v) => update({ warmVetoSeconds: v })}
        />
        <SecondSlider
          label="Over-limit cool-off timer (Manual mode)"
          value={profile.coolOffSeconds}
          options={[15, 30, 60]}
          onChange={(v) => update({ coolOffSeconds: v })}
        />
        <div className="text-[11px] text-slate-500 font-mono bg-surface-700 rounded-xl px-3 py-2">
          Cool-off activates when a manual trade exceeds your position size limit. It doesn't block — it inconveniences the impulse.
        </div>
      </Section>

      {/* Actions */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          className="flex-1 py-2.5 rounded-xl bg-brand-600 hover:bg-brand-500 text-sm font-medium transition-colors"
        >
          {saved ? "Saved ✓" : "Save profile"}
        </button>
        <button
          onClick={handleReset}
          className="px-4 py-2.5 rounded-xl border border-white/10 text-sm text-slate-400 hover:text-slate-200 hover:border-white/20 transition-colors"
        >
          Reset defaults
        </button>
      </div>
    </div>
  );
}
