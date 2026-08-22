import { useState, useRef, useEffect, useCallback } from "react";
import {
  Brain, Loader2, Send, CheckCircle2, XCircle, Clock,
  Zap, DollarSign, BarChart2, AlertCircle, Trash2, Sparkles,
} from "lucide-react";
import clsx from "clsx";
import { SignalCard } from "../components/SignalCard";
import type { Signal } from "../lib/types";
import { useHITLContext } from "../context/HITLContext";
import { apiHeaders, useCreditStatus, useApiUsage } from "../lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

interface ConversationMessage {
  id: string;
  role: "user" | "assistant";
  content: string;        // user: raw query; assistant: preamble or text response
  signal?: Signal;        // assistant Category A result
  execStatus?: string;    // HITL disposition status
  loading?: boolean;      // pending placeholder
  error?: string;         // failed query error
}

interface BrainQueryResponse {
  category: string;
  symbol?: string;
  asset_class?: string;
  text?: string;
  error?: string;
}

// ── Suggestion chips ──────────────────────────────────────────────────────────

const SUGGESTIONS = [
  "What do the agents think about AAPL right now?",
  "Which is the strongest HOT signal today?",
  "Analyse BTCUSDT",
  "Show me any SELL signals",
];

// ── UsagePanel (unchanged from original) ─────────────────────────────────────

function UsagePanel() {
  const credits = useCreditStatus();
  const usage   = useApiUsage();

  const today   = usage?.today;
  const history = usage?.history ?? [];

  const critThresh = credits?.critical_threshold ?? 2;
  const warnThresh = credits?.warning_threshold  ?? 5;
  const creditColor =
    !credits || !credits.configured  ? "text-slate-400" :
    credits.balance_usd === null      ? "text-slate-400" :
    credits.balance_usd < critThresh  ? "text-red-400"   :
    credits.balance_usd < warnThresh  ? "text-amber-400" :
                                        "text-emerald-400";

  function fmtTokens(n: number): string {
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
    if (n >= 1_000)     return `${(n / 1_000).toFixed(1)}K`;
    return String(n);
  }

  return (
    <div className="space-y-4">
      <div className="glass rounded-2xl p-5">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-4 flex items-center gap-2">
          <DollarSign className="w-3.5 h-3.5" />
          OpenRouter Credit Balance
        </h2>
        {!credits ? (
          <div className="text-xs text-slate-500 font-mono animate-pulse">Fetching balance…</div>
        ) : !credits.configured ? (
          <div className="text-xs text-slate-500 font-mono">{credits.error}</div>
        ) : credits.error ? (
          <div className="flex items-center gap-2 text-xs text-amber-400 font-mono">
            <AlertCircle className="w-3.5 h-3.5 shrink-0" />
            {credits.error}
          </div>
        ) : (
          <div className="space-y-3">
            <div className="flex items-end gap-3">
              <span className={clsx("text-3xl font-semibold font-mono", creditColor)}>
                {credits.balance_usd !== null ? `$${credits.balance_usd.toFixed(2)}` : "—"}
              </span>
              <span className="text-xs text-slate-500 font-mono pb-1">
                {credits.limit_usd !== null
                  ? `of $${credits.limit_usd.toFixed(2)} limit · $${(credits.used_usd ?? 0).toFixed(2)} used`
                  : `$${(credits.used_usd ?? 0).toFixed(4)} used this billing period`}
              </span>
            </div>
            {credits.limit_usd && credits.balance_usd !== null && (
              <div className="space-y-1">
                <div className="h-2 bg-surface-700 rounded-full overflow-hidden">
                  <div
                    className={clsx(
                      "h-full rounded-full transition-all",
                      credits.balance_usd < critThresh ? "bg-red-500"   :
                      credits.balance_usd < warnThresh ? "bg-amber-500" : "bg-emerald-500",
                    )}
                    style={{ width: `${Math.max(2, (credits.balance_usd / credits.limit_usd) * 100).toFixed(1)}%` }}
                  />
                </div>
                <div className="flex justify-between text-[10px] font-mono text-slate-600">
                  <span>$0</span>
                  <span className={clsx(credits.warning ? "text-amber-500" : "text-slate-600")}>
                    ${credits.warning_threshold} warning
                  </span>
                  <span>${credits.limit_usd.toFixed(2)}</span>
                </div>
              </div>
            )}
            {credits.warning && (
              <div className="text-[11px] font-mono text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded-xl px-3 py-2">
                Balance below ${credits.warning_threshold} threshold.
                <a href="https://openrouter.ai/settings/billing" target="_blank" rel="noreferrer"
                  className="ml-1 underline underline-offset-2">
                  Add credits →
                </a>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="glass rounded-2xl p-5">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-4 flex items-center gap-2">
          <Zap className="w-3.5 h-3.5" />
          Today's Usage
          <span className="ml-auto text-[10px] font-mono text-slate-600 normal-case tracking-normal">
            {today?.date ?? new Date().toISOString().slice(0, 10)} · resets at midnight UTC
          </span>
        </h2>
        {!today || today.calls === 0 ? (
          <div className="text-xs text-slate-500 font-mono">
            No LLM calls recorded today yet — usage appears here after the first live signal runs.
          </div>
        ) : (
          <div className="space-y-3">
            <div className="grid grid-cols-4 gap-2">
              {[
                { label: "API Calls",     value: today.calls.toLocaleString(),       color: "text-brand-400" },
                { label: "Input Tokens",  value: fmtTokens(today.input_tokens),      color: "text-sky-400" },
                { label: "Output Tokens", value: fmtTokens(today.output_tokens),     color: "text-violet-400" },
                { label: "Est. Cost",     value: `$${today.cost_usd.toFixed(4)}`,    color: "text-emerald-400" },
              ].map((m) => (
                <div key={m.label} className="bg-surface-700 rounded-xl p-3 text-center">
                  <div className="text-[9px] text-slate-500 uppercase tracking-wider mb-1">{m.label}</div>
                  <div className={clsx("text-sm font-mono font-semibold", m.color)}>{m.value}</div>
                </div>
              ))}
            </div>
            {Object.keys(today.by_model).length > 0 && (
              <div className="space-y-1.5">
                <div className="text-[10px] text-slate-600 uppercase tracking-widest">Per model</div>
                {Object.entries(today.by_model).map(([model, m]) => (
                  <div key={model} className="flex items-center justify-between text-xs font-mono bg-surface-700 rounded-xl px-3 py-2 gap-3">
                    <span className="text-slate-400 truncate">{model}</span>
                    <div className="flex items-center gap-4 shrink-0 text-slate-500">
                      <span>{m.calls} calls</span>
                      <span className="text-sky-400/80">{fmtTokens(m.input_tokens)} in</span>
                      <span className="text-violet-400/80">{fmtTokens(m.output_tokens)} out</span>
                      <span className="text-emerald-400 font-semibold">${m.cost_usd.toFixed(4)}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {history.filter(d => d.calls > 0).length > 1 && (
        <div className="glass rounded-2xl p-5">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-4 flex items-center gap-2">
            <BarChart2 className="w-3.5 h-3.5" />
            Daily History (last 14 days)
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="text-[10px] text-slate-600 uppercase tracking-widest border-b border-white/5">
                  <th className="text-left pb-2 pr-4">Date</th>
                  <th className="text-right pb-2 px-3">Calls</th>
                  <th className="text-right pb-2 px-3">Input</th>
                  <th className="text-right pb-2 px-3">Output</th>
                  <th className="text-right pb-2 pl-3">Est. Cost</th>
                </tr>
              </thead>
              <tbody>
                {history.filter(d => d.calls > 0).slice(0, 14).map((d) => (
                  <tr key={d.date} className="border-b border-white/[0.03] hover:bg-white/[0.02]">
                    <td className="py-2 pr-4 text-slate-400">{d.date}</td>
                    <td className="py-2 px-3 text-right text-brand-400">{d.calls.toLocaleString()}</td>
                    <td className="py-2 px-3 text-right text-sky-400">{fmtTokens(d.input_tokens)}</td>
                    <td className="py-2 px-3 text-right text-violet-400">{fmtTokens(d.output_tokens)}</td>
                    <td className="py-2 pl-3 text-right text-emerald-400 font-semibold">
                      ${d.cost_usd.toFixed(4)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="text-[10px] text-slate-600 font-mono mt-3">
            Costs are estimates based on OpenRouter published pricing · Resets on process restart ·
            Authoritative billing at openrouter.ai/activity
          </p>
        </div>
      )}
    </div>
  );
}

// ── Message bubbles ───────────────────────────────────────────────────────────

function UserBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[85%] bg-brand-600/20 border border-brand-500/20 rounded-2xl rounded-tr-sm px-4 py-2.5 text-sm text-slate-200">
        {content}
      </div>
    </div>
  );
}

interface AssistantBubbleProps {
  msg: ConversationMessage;
}

function AssistantBubble({ msg }: AssistantBubbleProps) {
  if (msg.loading) {
    return (
      <div className="flex justify-start">
        <div className="flex items-center gap-2.5 px-4 py-3 text-slate-500 text-xs font-mono">
          <Loader2 className="w-3.5 h-3.5 animate-spin text-brand-400 shrink-0" />
          <span className="animate-pulse">{msg.content || "Agents working…"}</span>
        </div>
      </div>
    );
  }

  if (msg.error) {
    return (
      <div className="flex justify-start">
        <div className="max-w-[90%] bg-red-500/10 border border-red-500/20 rounded-2xl rounded-tl-sm px-4 py-3 text-sm text-red-400 font-mono">
          <div className="flex items-center gap-2 mb-1 font-semibold text-xs">
            <XCircle className="w-3.5 h-3.5" /> Error
          </div>
          {msg.error}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Text preamble or Category B text response */}
      {msg.content && (
        <div className="flex justify-start">
          <div className="max-w-[90%] bg-surface-700/60 border border-white/5 rounded-2xl rounded-tl-sm px-4 py-3 text-sm text-slate-300 leading-relaxed">
            {msg.content}
          </div>
        </div>
      )}

      {/* Signal card for Category A */}
      {msg.signal && <SignalCard signal={msg.signal} />}

      {/* HITL execution status */}
      {msg.execStatus && msg.execStatus !== "auto_executing" && (
        <div className={clsx(
          "rounded-xl px-4 py-3 text-sm font-mono flex items-center gap-2",
          msg.execStatus.startsWith("Auto-executed")
            ? "bg-emerald-500/10 border border-emerald-500/20 text-emerald-400"
            : msg.execStatus.startsWith("Queued")
            ? "bg-amber-500/10 border border-amber-500/20 text-amber-400"
            : "bg-red-500/10 border border-red-500/20 text-red-400",
        )}>
          {msg.execStatus.startsWith("Auto-executed") ? <CheckCircle2 className="w-4 h-4 shrink-0" />
          : msg.execStatus.startsWith("Queued")       ? <Clock className="w-4 h-4 shrink-0" />
          :                                             <XCircle className="w-4 h-4 shrink-0" />}
          {msg.execStatus}
        </div>
      )}
      {msg.execStatus === "auto_executing" && (
        <div className="rounded-xl bg-sky-500/10 border border-sky-500/20 text-sky-400 text-sm px-4 py-3 font-mono flex items-center gap-2">
          <Loader2 className="w-4 h-4 animate-spin shrink-0" />
          Sending order to broker…
        </div>
      )}
    </div>
  );
}

// ── Empty state with suggestion chips ─────────────────────────────────────────

function EmptyState({ onSuggestion }: { onSuggestion: (s: string) => void }) {
  return (
    <div className="flex flex-col items-center justify-center py-8 gap-5">
      <div className="flex flex-col items-center gap-2 text-center">
        <Sparkles className="w-8 h-8 text-brand-400/60" />
        <p className="text-sm text-slate-400">Ask the agents anything, or type a ticker to start a debate.</p>
        <p className="text-[11px] text-slate-600 font-mono">
          Analyses trigger the full 27-agent panel · Category B queries answer from cached signals
        </p>
      </div>
      <div className="grid grid-cols-2 gap-2 w-full max-w-sm">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            onClick={() => onSuggestion(s)}
            className="text-left px-3 py-2.5 rounded-xl border border-white/5 bg-surface-700/50 hover:border-brand-500/30 hover:bg-brand-500/5 text-xs text-slate-400 hover:text-slate-200 transition-all leading-snug"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

interface BrainPageProps {
  paperMode?: boolean;
  signalPaperMode?: boolean;
}

export function BrainPage({ paperMode: _paperMode = true, signalPaperMode = false }: BrainPageProps) {
  const [messages, setMessages]     = useState<ConversationMessage[]>([]);
  const [input, setInput]           = useState("");
  const [assetClass, setAssetClass] = useState<"stock" | "crypto">("stock");
  const [isProcessing, setIsProcessing] = useState(false);
  const hitl     = useHITLContext();
  const inputRef = useRef<HTMLInputElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function updateMessage(id: string, updates: Partial<ConversationMessage>) {
    setMessages(prev => prev.map(m => m.id === id ? { ...m, ...updates } : m));
  }

  // Build conversation history for LLM context (last 4 exchanges)
  const conversationHistory = messages
    .filter(m => !m.loading && !m.error)
    .slice(-8)
    .map(m => ({
      role: m.role as "user" | "assistant",
      content: m.signal
        ? `Analyzed ${m.signal.symbol}: ${m.signal.action} signal (${m.signal.tier} tier, confidence ${m.signal.confidence?.toFixed(2) ?? "?"}) — ${m.signal.rationale}`
        : m.content,
    }));

  const handleQuery = useCallback(async (query: string) => {
    const q = query.trim();
    if (!q || isProcessing) return;

    const userMsgId      = crypto.randomUUID();
    const assistantMsgId = crypto.randomUUID();

    setMessages(prev => [
      ...prev,
      { id: userMsgId,      role: "user",      content: q },
      { id: assistantMsgId, role: "assistant",  content: "Classifying…", loading: true },
    ]);
    setInput("");
    setIsProcessing(true);

    try {
      // ── Step 1: Classify intent ───────────────────────────────────────────
      const classifyResp = await fetch("/api/brain/query", {
        method:  "POST",
        headers: apiHeaders({ "Content-Type": "application/json" }),
        body:    JSON.stringify({
          query:                q,
          conversation_history: conversationHistory,
          asset_class_hint:     assetClass,
        }),
      });

      if (!classifyResp.ok) {
        const err = await classifyResp.json().catch(() => ({})) as { detail?: string };
        updateMessage(assistantMsgId, { loading: false, content: "", error: err.detail ?? `Server error ${classifyResp.status}` });
        return;
      }

      const classification = await classifyResp.json() as BrainQueryResponse;

      if (classification.category === "A") {
        // ── Category A: trigger the 27-agent debate ───────────────────────
        const sym = classification.symbol ?? "";
        const cls = classification.asset_class ?? assetClass;

        updateMessage(assistantMsgId, {
          content: `Running ${signalPaperMode ? "rule-based analysis" : "27-agent LLM debate"} for ${sym}…`,
        });

        const signalResp = await fetch("/api/signal", {
          method:  "POST",
          headers: apiHeaders({ "Content-Type": "application/json" }),
          body:    JSON.stringify({ symbol: sym, asset_class: cls, paper_mode: signalPaperMode }),
        });

        if (!signalResp.ok) {
          const err = await signalResp.json().catch(() => ({})) as { detail?: string };
          updateMessage(assistantMsgId, {
            loading: false,
            content: "",
            error: err.detail ?? `Signal error ${signalResp.status}`,
          });
          return;
        }

        const signal: Signal = await signalResp.json();
        updateMessage(assistantMsgId, { loading: false, content: `Debate complete for ${sym}:`, signal });

        // ── HITL integration ──────────────────────────────────────────────
        if (signal.action !== "HOLD") {
          const disposition = hitl.receiveSignal(signal);
          let execStatus = "";
          if (disposition === "auto_execute") {
            updateMessage(assistantMsgId, { execStatus: "auto_executing" });
            const execResult = await hitl.executeSignal(signal);
            execStatus = execResult
              ? `Auto-executed: Order ${execResult.order_id} · ${execResult.status} on ${execResult.exchange}`
              : `Auto-execute failed: ${hitl.executeError ?? "unknown error"}`;
          } else if (disposition === "veto_window") {
            execStatus = "Queued for approval — review the confirmation banner.";
          } else if (disposition === "queue_manual") {
            execStatus = "Queued for manual execution — click Execute on the signal card below.";
          }
          if (execStatus) updateMessage(assistantMsgId, { execStatus });
        }

      } else {
        // ── Category B: text synthesis answer ────────────────────────────
        const text = classification.text ?? "No answer generated.";
        updateMessage(assistantMsgId, { loading: false, content: text });
      }

    } catch (err) {
      updateMessage(assistantMsgId, {
        loading: false,
        content: "",
        error: (err as Error).message ?? "Network error — backend not reachable",
      });
    } finally {
      setIsProcessing(false);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [assetClass, conversationHistory, hitl, isProcessing, signalPaperMode]);

  function handleKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleQuery(input);
    }
  }

  const isEmpty = messages.length === 0;

  return (
    <div className="space-y-6 max-w-2xl">
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold flex items-center gap-2">
            <Brain className="w-5 h-5 text-brand-400" />
            Brain Console
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            Ask the agents anything, or type a ticker to trigger a full debate.
          </p>
          <div className={clsx(
            "inline-flex items-center gap-1.5 mt-2 px-2.5 py-1 rounded-lg text-[11px] font-mono font-semibold border",
            signalPaperMode
              ? "bg-sky-500/10 border-sky-500/20 text-sky-400"
              : "bg-brand-500/10 border-brand-500/20 text-brand-400",
          )}>
            <span className={clsx(
              "w-1.5 h-1.5 rounded-full",
              signalPaperMode ? "bg-sky-400" : "bg-brand-400 animate-pulse",
            )} />
            {signalPaperMode
              ? "Rule-based signals — no LLM credits used"
              : "LLM agent debate — uses OpenRouter credits"}
          </div>
        </div>

        {!isEmpty && (
          <button
            onClick={() => setMessages([])}
            title="Clear conversation"
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl border border-white/5 bg-surface-700/50 text-xs text-slate-500 hover:text-slate-300 hover:border-white/10 transition-all shrink-0"
          >
            <Trash2 className="w-3.5 h-3.5" />
            Clear
          </button>
        )}
      </div>

      {/* ── Conversation card ────────────────────────────────────────────── */}
      <div className="glass rounded-2xl overflow-hidden">
        {/* Message thread */}
        <div
          className={clsx(
            "p-4 space-y-4 overflow-y-auto transition-all",
            isEmpty ? "min-h-[220px]" : "max-h-[56vh] min-h-[220px]",
          )}
        >
          {isEmpty ? (
            <EmptyState onSuggestion={handleQuery} />
          ) : (
            <>
              {messages.map(msg =>
                msg.role === "user"
                  ? <UserBubble key={msg.id} content={msg.content} />
                  : <AssistantBubble key={msg.id} msg={msg} />
              )}
              <div ref={bottomRef} />
            </>
          )}
        </div>

        {/* Divider */}
        <div className="border-t border-white/5" />

        {/* Input area */}
        <div className="p-4 space-y-3">
          {/* Asset class context selector */}
          <div className="flex items-center gap-2">
            <span className="text-[10px] text-slate-600 font-mono uppercase tracking-wider">
              Default context
            </span>
            <div className="flex rounded-lg overflow-hidden border border-white/5 ml-1">
              {(["stock", "crypto"] as const).map((cls) => (
                <button
                  key={cls}
                  onClick={() => setAssetClass(cls)}
                  className={clsx(
                    "px-3 py-1 text-xs font-mono transition-colors",
                    assetClass === cls
                      ? "bg-brand-500 text-white"
                      : "bg-surface-700 text-slate-500 hover:text-slate-300",
                  )}
                >
                  {cls}
                </button>
              ))}
            </div>
            <span className="text-[10px] text-slate-700 font-mono ml-auto">
              Enter to send
            </span>
          </div>

          {/* Query input + send button */}
          <div className="flex gap-2">
            <input
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isProcessing}
              placeholder="Ask the agents anything… or type a ticker to run a debate"
              className="flex-1 bg-surface-700 rounded-xl px-4 py-2.5 text-sm font-mono outline-none focus:ring-1 focus:ring-brand-500 placeholder:text-slate-600 disabled:opacity-50"
            />
            <button
              onClick={() => handleQuery(input)}
              disabled={!input.trim() || isProcessing}
              className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-brand-600 hover:bg-brand-500 text-sm font-medium transition-colors disabled:opacity-40 shrink-0"
            >
              {isProcessing
                ? <Loader2 className="w-4 h-4 animate-spin" />
                : <Send className="w-4 h-4" />}
            </button>
          </div>
        </div>
      </div>

      {/* ── API Usage & Credits ──────────────────────────────────────────── */}
      <div className="pt-2">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-3 flex items-center gap-2">
          <DollarSign className="w-3.5 h-3.5" />
          API Usage &amp; Credits
        </h2>
        <UsagePanel />
      </div>
    </div>
  );
}
