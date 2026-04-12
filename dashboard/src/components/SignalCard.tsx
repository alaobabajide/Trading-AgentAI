import { useState } from "react";
import { ChevronDown, ChevronUp, ShieldAlert } from "lucide-react";
import { format } from "date-fns";
import { Signal } from "../lib/types";
import { SignalBadge } from "./SignalBadge";
import { ConfidenceBar } from "./ConfidenceBar";
import { TIER_CONFIG, FIT_CONFIG } from "../lib/hitl";
import clsx from "clsx";

// ── Analyst rows config ───────────────────────────────────────────────────────

const ANALYSTS = [
  { key: "fundamental",  label: "Fundamental",  color: "text-blue-400"    },
  { key: "technical",    label: "Technical",    color: "text-cyan-400"    },
  { key: "sentiment",    label: "Sentiment",    color: "text-purple-400"  },
  { key: "macro",        label: "Macro",        color: "text-yellow-400"  },
  { key: "quant",        label: "Quant",        color: "text-teal-400"    },
  { key: "options_flow", label: "Options Flow", color: "text-orange-400"  },
  { key: "regime",       label: "Regime",       color: "text-pink-400"    },
] as const;

// ── Devil's Advocate bar ──────────────────────────────────────────────────────

function DevilAdvocateBar({ score, caseText }: { score: number; caseText: string }) {
  const barColor =
    score >= 70 ? "bg-red-500"    :
    score >= 40 ? "bg-amber-500"  :
                  "bg-emerald-500";

  return (
    <div className="bg-surface-700 rounded-xl p-3 space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <ShieldAlert className="w-3.5 h-3.5 text-slate-400" />
          <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
            Devil's Advocate
          </span>
        </div>
        <span className={clsx(
          "text-[10px] font-mono font-bold",
          score >= 70 ? "text-red-400" : score >= 40 ? "text-amber-400" : "text-emerald-400",
        )}>
          {score}/100
        </span>
      </div>
      <div className="h-1.5 bg-white/5 rounded-full overflow-hidden">
        <div
          className={clsx("h-full rounded-full transition-all", barColor)}
          style={{ width: `${score}%` }}
        />
      </div>
      <p className="text-xs text-slate-400 italic">&ldquo;{caseText}&rdquo;</p>
    </div>
  );
}

// ── Strategy fit badge ────────────────────────────────────────────────────────

function StrategyFitBadge({ signal }: { signal: Signal }) {
  const fit    = signal.strategy_fit ?? "ALIGNED";
  const config = FIT_CONFIG[fit];
  const view   = signal.agent_views.strategy ?? "";
  const coachMatch = view.match(/COACHING:\s*(.+)/is);
  const coaching   = coachMatch?.[1]?.trim() ?? "";
  const adjMatch   = view.match(/ADJUSTMENT:\s*(.+?)(?:\n|COACHING:|$)/is);
  const adjustment = adjMatch?.[1]?.trim() ?? "";

  return (
    <div className={clsx("rounded-xl p-3 space-y-1.5 border", config.bg,
      fit === "ALIGNED"    ? "border-emerald-500/20" :
      fit === "PARTIAL"    ? "border-amber-500/20"   :
                             "border-red-500/20"
    )}>
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
          Strategy Coach
        </span>
        <span className={clsx("text-[10px] font-semibold", config.color)}>
          {config.label}
        </span>
      </div>
      {adjustment && fit !== "ALIGNED" && (
        <p className="text-xs text-slate-300 font-mono">→ {adjustment}</p>
      )}
      {coaching && <p className="text-xs text-slate-400">{coaching}</p>}
    </div>
  );
}

// ── Main card ─────────────────────────────────────────────────────────────────

export function SignalCard({ signal }: { signal: Signal }) {
  const [expanded, setExpanded] = useState(false);

  const tier   = signal.tier ?? "WARM";
  const tierCfg = TIER_CONFIG[tier];

  return (
    <div className={clsx("glass rounded-2xl overflow-hidden border", tierCfg.border)}>
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full text-left p-4 hover:bg-white/[0.02] transition-colors"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            {/* Tier dot */}
            <div className="flex flex-col items-center gap-1">
              <span className={clsx(
                "relative flex h-2 w-2",
                tier === "HOT" && "animate-pulse",
              )}>
                {tier === "HOT" && (
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                )}
                <span className={clsx("relative inline-flex rounded-full h-2 w-2", tierCfg.dot)} />
              </span>
            </div>

            <div className="flex flex-col">
              <div className="flex items-center gap-2">
                <span className="font-semibold font-mono text-sm">{signal.symbol}</span>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-700 text-slate-400 uppercase">
                  {signal.asset_class}
                </span>
                <span className={clsx("text-[10px] px-1.5 py-0.5 rounded-full font-semibold", tierCfg.bg, tierCfg.color)}>
                  {tierCfg.label}
                </span>
              </div>
              <span className="text-xs text-slate-500 mt-0.5">
                {format(new Date(signal.generated_at), "HH:mm:ss · MMM d")}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-3 shrink-0">
            <SignalBadge action={signal.action} />
            {expanded
              ? <ChevronUp  className="w-4 h-4 text-slate-500" />
              : <ChevronDown className="w-4 h-4 text-slate-500" />}
          </div>
        </div>

        <div className="mt-3 space-y-1">
          <ConfidenceBar value={signal.confidence} />
          <p className="text-xs text-slate-400 line-clamp-2">{signal.rationale}</p>
        </div>
      </button>

      {expanded && (
        <div className="border-t border-white/5 p-4 space-y-4">
          {/* Sizing hints */}
          <div className="grid grid-cols-3 gap-2 text-center">
            {[
              { label: "Position", value: `${(signal.suggested_position_pct * 100).toFixed(1)}%` },
              { label: "Stop",     value: `${(signal.stop_loss_pct * 100).toFixed(1)}%`           },
              { label: "Target",   value: `${(signal.take_profit_pct * 100).toFixed(1)}%`          },
            ].map(({ label, value }) => (
              <div key={label} className="bg-surface-700 rounded-xl p-2">
                <div className="text-[10px] text-slate-500 uppercase tracking-wider">{label}</div>
                <div className="text-sm font-mono font-medium mt-0.5">{value}</div>
              </div>
            ))}
          </div>

          {/* Devil's Advocate */}
          <DevilAdvocateBar
            score={signal.devil_advocate_score ?? 0}
            caseText={signal.devil_advocate_case ?? "No material counter-case identified."}
          />

          {/* Strategy Coach */}
          <StrategyFitBadge signal={signal} />

          {/* 7 Analyst views */}
          <div className="space-y-2">
            <h4 className="text-[10px] text-slate-500 uppercase tracking-widest">
              Analyst Views{" "}
              <span className="text-slate-600 normal-case tracking-normal font-normal">
                7 analysts · 1 risk manager
              </span>
            </h4>
            {ANALYSTS.map(({ key, label, color }) => {
              const raw         = signal.agent_views[key] ?? "";
              const dirMatch    = raw.match(/DIRECTION:\s*(\w+)/i);
              const reasonMatch = raw.match(/REASONING:\s*(.+)/is);
              const dir    = dirMatch?.[1]  ?? "–";
              const reason = reasonMatch?.[1]?.trim() ?? raw;
              return (
                <div key={key} className="bg-surface-700 rounded-xl p-3 space-y-1">
                  <div className="flex items-center justify-between">
                    <span className={clsx("text-[10px] font-semibold uppercase tracking-wider", color)}>
                      {label}
                    </span>
                    <span className={clsx(
                      "text-[10px] font-mono font-semibold",
                      dir === "BULLISH" ? "text-emerald-400"
                        : dir === "BEARISH" ? "text-red-400"
                        : "text-slate-400",
                    )}>
                      {dir}
                    </span>
                  </div>
                  <p className="text-xs text-slate-400">{reason}</p>
                </div>
              );
            })}
          </div>

          {/* Gate status */}
          <div className={clsx(
            "text-xs font-mono rounded-xl px-3 py-2 text-center",
            signal.passed_confidence_gate
              ? "bg-emerald-500/10 text-emerald-400"
              : "bg-yellow-500/10 text-yellow-400",
          )}>
            {signal.passed_confidence_gate
              ? "✓ Passed confidence gate — eligible for execution"
              : "⚠ Below threshold — downgraded to HOLD"}
          </div>
        </div>
      )}
    </div>
  );
}
