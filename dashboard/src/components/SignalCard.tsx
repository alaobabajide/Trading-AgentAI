import { useState } from "react";
import { ChevronDown, ChevronUp, Loader2, ShieldAlert, Zap } from "lucide-react";
import { format } from "date-fns";
import { Signal, VoteTally } from "../lib/types";
import { SignalBadge } from "./SignalBadge";
import { TIER_CONFIG, FIT_CONFIG } from "../lib/hitl";
import { useHITLContext } from "../context/HITLContext";
import clsx from "clsx";

// ── Agent row definitions ─────────────────────────────────────────────────────

const ANALYSTS = [
  { key: "fundamental",  label: "Fundamental",  color: "text-blue-400"   },
  { key: "technical",    label: "Technical",    color: "text-cyan-400"   },
  { key: "sentiment",    label: "Sentiment",    color: "text-purple-400" },
  { key: "macro",        label: "Macro",        color: "text-yellow-400" },
  { key: "quant",        label: "Quant",        color: "text-teal-400"   },
  { key: "options_flow", label: "Options Flow", color: "text-orange-400" },
  { key: "regime",       label: "Regime",       color: "text-pink-400"   },
] as const;

const INVESTORS = [
  { key: "buffett", label: "Buffett",  color: "text-amber-400"  },
  { key: "munger",  label: "Munger",   color: "text-amber-300"  },
  { key: "lynch",   label: "Lynch",    color: "text-lime-400"   },
  { key: "ackman",  label: "Ackman",   color: "text-sky-400"    },
  { key: "cohen",   label: "Cohen",    color: "text-violet-400" },
  { key: "dalio",   label: "Dalio",    color: "text-blue-300"   },
  { key: "wood",    label: "Wood",     color: "text-fuchsia-400"},
  { key: "bogle",   label: "Bogle",    color: "text-slate-300"  },
] as const;

// ── Vote tally display ────────────────────────────────────────────────────────

function TallyChips({ tally }: { tally: VoteTally }) {
  return (
    <span className="flex items-center gap-1.5 text-[11px] font-mono">
      <span className="text-emerald-400">{tally.bullish}B</span>
      <span className="text-slate-600">·</span>
      <span className="text-red-400">{tally.bearish}Br</span>
      <span className="text-slate-600">·</span>
      <span className="text-slate-400">{tally.neutral}N</span>
    </span>
  );
}

function VoteTallyRow({ tally, panelA, panelB, action, votesForAction }: {
  tally: VoteTally;
  panelA?: VoteTally;
  panelB?: VoteTally;
  action: string;
  votesForAction: number;
}) {
  const total = tally.bullish + tally.bearish + tally.neutral;
  const hasPanels = panelA && panelB;

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-3 flex-wrap">
        {hasPanels ? (
          <>
            <span className="text-[10px] text-slate-500 font-mono">Combined</span>
            <TallyChips tally={tally} />
          </>
        ) : (
          <TallyChips tally={tally} />
        )}
        {action !== "HOLD" && (
          <span className={clsx(
            "text-[10px] font-semibold px-1.5 py-0.5 rounded",
            action === "BUY"
              ? "bg-emerald-500/15 text-emerald-300"
              : "bg-red-500/15 text-red-300",
          )}>
            {votesForAction}/{total} {action === "BUY" ? "BULLISH" : "BEARISH"}
          </span>
        )}
      </div>
      {hasPanels && (
        <div className="flex items-center gap-4 text-[10px] font-mono text-slate-500">
          <span>Analysts <TallyChips tally={panelA} /></span>
          <span className="text-slate-700">|</span>
          <span>Investors <TallyChips tally={panelB} /></span>
        </div>
      )}
    </div>
  );
}

// ── Reusable agent view row ───────────────────────────────────────────────────

function AgentViewRow({ agentKey, label, color, views }: {
  agentKey: string;
  label: string;
  color: string;
  views: Record<string, string | undefined>;
}) {
  const raw         = views[agentKey] ?? "";
  const dirMatch    = raw.match(/DIRECTION:\s*(\w+)/i);
  const reasonMatch = raw.match(/REASONING:\s*(.+)/is);
  const dir    = dirMatch?.[1]  ?? "–";
  const reason = reasonMatch?.[1]?.trim() ?? raw;
  return (
    <div className="bg-surface-700 rounded-xl p-3 space-y-1">
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
}

// ── Devil's Advocate (text only — score bar removed) ─────────────────────────

function DevilAdvocate({ caseText }: { caseText: string }) {
  return (
    <div className="bg-surface-700 rounded-xl p-3 space-y-1.5">
      <div className="flex items-center gap-1.5">
        <ShieldAlert className="w-3.5 h-3.5 text-slate-400" />
        <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
          Contrarian View
        </span>
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

// ── Execute button — all modes, any non-HOLD signal ──────────────────────────

function ExecuteButton({ signal, compact = false }: { signal: Signal; compact?: boolean }) {
  const { profile, receiveSignal, executeSignal, executing } = useHITLContext();
  const [result, setResult] = useState<string | null>(null);
  const [error,  setError]  = useState<string | null>(null);
  const mode = profile.mode;

  if (signal.action === "HOLD") return null;

  const isAssisted = mode === "assisted";
  const label      = isAssisted ? `Queue ${signal.action}` : `Execute ${signal.action}`;
  const colorClass = signal.action === "BUY"
    ? "bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30 border-emerald-500/30"
    : "bg-red-500/20 text-red-300 hover:bg-red-500/30 border-red-500/30";

  const handleClick = async (e: React.MouseEvent) => {
    e.stopPropagation(); // don't toggle card expand
    setResult(null);
    setError(null);
    if (isAssisted) {
      receiveSignal(signal);
      setResult("Queued for approval — check the banner above");
      return;
    }
    // Manual or Auto (manual override): fire directly to Alpaca
    const res = await executeSignal(signal);
    if (res) setResult(`Order ${res.order_id} · ${res.status} · ${res.exchange}`);
    else     setError("Execution failed — check credentials in Settings");
  };

  return (
    <div className={clsx("space-y-1.5", !compact && "mt-1")}>
      <button
        onClick={handleClick}
        disabled={executing}
        className={clsx(
          "flex items-center justify-center gap-2 rounded-xl border font-semibold transition-colors",
          compact ? "px-3 py-1.5 text-xs" : "w-full py-2.5 text-sm",
          colorClass,
          executing && "opacity-50 cursor-not-allowed",
        )}
      >
        {executing
          ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
          : <Zap className="w-3.5 h-3.5" />}
        {executing ? "Sending…" : label}
      </button>
      {result && (
        <p className="text-[11px] text-emerald-400 font-mono text-center">{result}</p>
      )}
      {error && (
        <p className="text-[11px] text-red-400 font-mono text-center">{error}</p>
      )}
    </div>
  );
}

// ── Main card ─────────────────────────────────────────────────────────────────

export function SignalCard({ signal }: { signal: Signal }) {
  const [expanded, setExpanded] = useState(false);

  const tier    = signal.tier ?? "WARM";
  const tierCfg = TIER_CONFIG[tier];

  // Vote tally — use real data if present, else derive from confidence for mock signals
  const tally: VoteTally = signal.vote_tally ?? {
    bullish: signal.action === "BUY"  ? Math.round(signal.confidence * 7) : 1,
    bearish: signal.action === "SELL" ? Math.round(signal.confidence * 7) : 1,
    neutral: 7 - Math.round(signal.confidence * 7) - 1,
  };
  const votesForAction = signal.votes_for_action ?? (
    signal.action === "BUY"  ? tally.bullish :
    signal.action === "SELL" ? tally.bearish : 0
  );
  const regimeLabel     = signal.regime_label;
  const panelA          = signal.panel_a_votes;
  const panelB          = signal.panel_b_votes;
  const panelsConflict  = signal.panels_conflict ?? false;
  const conflictNote    = signal.conflict_note ?? "";
  const totalAgents     = (panelA && panelB) ? 15 : 7;

  return (
    <div className={clsx("glass rounded-2xl overflow-hidden border", tierCfg.border)}>
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full text-left p-4 hover:bg-white/[0.02] transition-colors"
      >
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            {/* Tier dot */}
            <span className={clsx("relative flex h-2 w-2 mt-1", tier === "HOT" && "animate-pulse")}>
              {tier === "HOT" && (
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
              )}
              <span className={clsx("relative inline-flex rounded-full h-2 w-2", tierCfg.dot)} />
            </span>

            <div className="flex flex-col">
              <div className="flex items-center gap-2">
                <span className="font-semibold font-mono text-sm">{signal.symbol}</span>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-700 text-slate-400 uppercase">
                  {signal.asset_class}
                </span>
                <span className={clsx("text-[10px] px-1.5 py-0.5 rounded-full font-semibold", tierCfg.bg, tierCfg.color)}>
                  {tierCfg.label}
                </span>
                {regimeLabel && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-700 text-slate-500 font-mono">
                    {regimeLabel.replace(/_/g, " ")}
                  </span>
                )}
              </div>
              <span className="text-xs text-slate-500 mt-0.5">
                {format(new Date(signal.generated_at), "HH:mm:ss · MMM d")}
              </span>
            </div>
          </div>

          <div className="flex items-center gap-3 shrink-0">
            <SignalBadge action={signal.action} />
            {/* Compact execute button — always visible, no expand needed */}
            {signal.action !== "HOLD" && (
              <ExecuteButton signal={signal} compact />
            )}
            {expanded
              ? <ChevronUp   className="w-4 h-4 text-slate-500" />
              : <ChevronDown className="w-4 h-4 text-slate-500" />}
          </div>
        </div>

        {/* Vote tally row */}
        <div className="mt-3 space-y-1.5">
          <VoteTallyRow
            tally={tally}
            panelA={panelA}
            panelB={panelB}
            action={signal.action}
            votesForAction={votesForAction}
          />
          {panelsConflict && (
            <div className="flex items-center gap-1.5 text-[10px] text-amber-400 font-mono">
              <span>⚠</span>
              <span>{conflictNote || "Panel conflict — analysts and investors disagree"}</span>
            </div>
          )}
          <p className="text-xs text-slate-400 line-clamp-2">{signal.rationale}</p>
        </div>
      </button>

      {expanded && (
        <div className="border-t border-white/5 p-4 space-y-4">
          {/* Sizing hints */}
          <div className="grid grid-cols-3 gap-2 text-center">
            {[
              { label: "Position", value: `${(signal.suggested_position_pct * 100).toFixed(1)}%` },
              { label: "Stop",     value: `-${(signal.stop_loss_pct * 100).toFixed(1)}%`         },
              { label: "Target",   value: `+${(signal.take_profit_pct * 100).toFixed(1)}%`       },
            ].map(({ label, value }) => (
              <div key={label} className="bg-surface-700 rounded-xl p-2">
                <div className="text-[10px] text-slate-500 uppercase tracking-wider">{label}</div>
                <div className="text-sm font-mono font-medium mt-0.5">{value}</div>
              </div>
            ))}
          </div>

          {/* Devil's Advocate — text only, no score */}
          {signal.devil_advocate_case && (
            <DevilAdvocate caseText={signal.devil_advocate_case} />
          )}

          {/* Strategy Coach */}
          <StrategyFitBadge signal={signal} />

          {/* Panel conflict banner */}
          {panelsConflict && (
            <div className="bg-amber-500/10 border border-amber-500/20 rounded-xl px-3 py-2.5 space-y-0.5">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-amber-400">
                Panel Conflict — HOLD Enforced
              </div>
              <p className="text-xs text-amber-300/80">{conflictNote}</p>
            </div>
          )}

          {/* Panel A — Analyst views */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <h4 className="text-[10px] text-slate-500 uppercase tracking-widest">
                Analyst Panel
              </h4>
              {panelA && (
                <span className="text-[10px] font-mono text-slate-600">
                  {panelA.bullish}B · {panelA.bearish}Br · {panelA.neutral}N
                </span>
              )}
            </div>
            {ANALYSTS.map(({ key, label, color }) => (
              <AgentViewRow
                key={key}
                agentKey={key}
                label={label}
                color={color}
                views={signal.agent_views}
              />
            ))}
          </div>

          {/* Panel B — Investor persona views */}
          {INVESTORS.some(({ key }) => signal.agent_views[key]) && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <h4 className="text-[10px] text-slate-500 uppercase tracking-widest">
                  Investor Panel
                </h4>
                {panelB && (
                  <span className="text-[10px] font-mono text-slate-600">
                    {panelB.bullish}B · {panelB.bearish}Br · {panelB.neutral}N
                  </span>
                )}
              </div>
              {INVESTORS.map(({ key, label, color }) => (
                <AgentViewRow
                  key={key}
                  agentKey={key}
                  label={label}
                  color={color}
                  views={signal.agent_views}
                />
              ))}
            </div>
          )}

          {/* Vote gate status */}
          <div className={clsx(
            "text-xs font-mono rounded-xl px-3 py-2 text-center",
            panelsConflict
              ? "bg-amber-500/10 text-amber-400"
              : signal.action !== "HOLD"
                ? "bg-emerald-500/10 text-emerald-400"
                : "bg-yellow-500/10 text-yellow-400",
          )}>
            {panelsConflict
              ? "⚠ Panel conflict — analysts and investors disagree, HOLD enforced"
              : signal.action !== "HOLD"
                ? `✓ Vote gate passed — ${votesForAction}/${totalAgents} agents ${signal.action === "BUY" ? "BULLISH" : "BEARISH"}`
                : `⚠ No majority — signal downgraded to HOLD`
            }
          </div>

          {/* Execute / Queue button — shown in Manual and Assisted modes */}
          <ExecuteButton signal={signal} />
        </div>
      )}
    </div>
  );
}
