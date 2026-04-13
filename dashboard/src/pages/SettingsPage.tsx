import clsx from "clsx";
import { Brain, Shield, Timer, TrendingUp } from "lucide-react";
import {
  HITLMode, UserProfile, DEFAULT_PROFILE,
  MODE_CONFIG, loadProfile, saveProfile,
} from "../lib/hitl";
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

export function SettingsPage() {
  const [profile, setProfile] = useState<UserProfile>(loadProfile);
  const [saved, setSaved] = useState(false);

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
      {/* HITL Mode */}
      <Section icon={<Brain className="w-4 h-4" />} title="Execution Mode">
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
          Signal tier logic: HOT = 6–7 analysts aligned + trending regime · WARM = 4–5 aligned · COLD = ≤3 aligned or high volatility
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

      {/* Risk Controls */}
      <Section icon={<Shield className="w-4 h-4" />} title="Hardcoded Risk Controls">
        <div className="space-y-2 text-xs text-slate-400 font-mono">
          {[
            ["Circuit breaker",      "10% daily drawdown halt"],
            ["Crypto cap",           "30% of portfolio NAV"],
            ["Max position (hard)",  "5% NAV per signal"],
            ["Vote gate",             "≥ 4/7 analysts to execute"],
            ["Regime weight purge",  "Auto when ATR shifts >20%"],
          ].map(([k, v]) => (
            <div key={k} className="flex justify-between py-1.5 border-b border-white/[0.04] last:border-0">
              <span>{k}</span>
              <span className="text-slate-300">{v}</span>
            </div>
          ))}
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
