import { useState, useRef, useEffect, useCallback } from "react";
import {
  Brain, Loader2, Send, CheckCircle2, XCircle, Clock,
  Zap, DollarSign, BarChart2, AlertCircle, Trash2, Sparkles, Bell, BellOff, Mic, MicOff,
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
  watchRuleId?: string;   // Category C — registered rule ID
}

interface BrainQueryResponse {
  category: string;
  symbol?: string;
  asset_class?: string;
  text?: string;
  error?: string;
  condition_type?: string;
  threshold?: number;
}

interface WatchRule {
  rule_id: string;
  symbol: string;
  condition_type: string;
  threshold: number;
  asset_class: string;
  created_at: string;
}

interface WatchAlert {
  alert_id: string;
  rule_id: string;
  symbol: string;
  condition_type: string;
  threshold: number;
  trigger_price: number;
  trigger_debate: boolean;
  triggered_at: string;
}

// ── Speech recognition hook ───────────────────────────────────────────────────

type SpeechState = "idle" | "listening" | "unsupported";

function useSpeechInput(onInterim: (t: string) => void, onFinal: (t: string) => void) {
  const [state, setState] = useState<SpeechState>("idle");
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const recRef = useRef<any>(null);

  useEffect(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const w = window as any;
    const SR = w.SpeechRecognition ?? w.webkitSpeechRecognition;
    if (!SR) { setState("unsupported"); return; }

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const rec: any = new SR();
    rec.continuous      = false;
    rec.interimResults  = true;
    rec.lang            = "en-US";
    rec.maxAlternatives = 1;

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    rec.onresult = (e: any) => {
      let interim = "";
      let finalText = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const t = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalText += t;
        else interim += t;
      }
      if (interim)   onInterim(interim);
      if (finalText) onFinal(finalText);
    };

    rec.onerror = () => setState("idle");
    rec.onend   = () => setState("idle");

    recRef.current = rec;
    setState("idle");
  // onInterim / onFinal are stable callbacks — intentionally omitted from deps
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function toggle() {
    if (!recRef.current || state === "unsupported") return;
    if (state === "listening") {
      recRef.current.stop();
    } else {
      recRef.current.start();
      setState("listening");
    }
  }

  return { state, toggle };
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

  // Category C confirmation — watch rule registered
  if (msg.watchRuleId) {
    return (
      <div className="flex justify-start">
        <div className="max-w-[90%] bg-amber-500/10 border border-amber-500/20 rounded-2xl rounded-tl-sm px-4 py-3 text-sm text-amber-300 space-y-1">
          <div className="flex items-center gap-2 font-semibold text-xs text-amber-400">
            <Bell className="w-3.5 h-3.5" /> Watch rule active
          </div>
          <div>{msg.content}</div>
          <div className="text-[10px] font-mono text-amber-500/70">
            Rule ID: {msg.watchRuleId.slice(0, 8)}… · Evaluated every orchestrator cycle
          </div>
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

function _conditionLabel(ctype: string, threshold: number): string {
  return ctype === "price_above"
    ? `price rises above $${threshold.toLocaleString()}`
    : `price drops below $${threshold.toLocaleString()}`;
}

export function BrainPage({ paperMode: _paperMode = true, signalPaperMode = false }: BrainPageProps) {
  const [messages, setMessages]     = useState<ConversationMessage[]>([]);
  const [input, setInput]           = useState("");
  const [assetClass, setAssetClass] = useState<"stock" | "crypto">("stock");
  const [isProcessing, setIsProcessing] = useState(false);
  const [activeRules, setActiveRules]   = useState<WatchRule[]>([]);
  const hitl     = useHITLContext();
  const inputRef = useRef<HTMLInputElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Speech input: interim results populate the field live; final result replaces it cleanly
  const speech = useSpeechInput(
    (interim) => setInput(interim),
    (final)   => {
      setInput(final);
      setTimeout(() => inputRef.current?.focus(), 50);
    },
  );

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  function updateMessage(id: string, updates: Partial<ConversationMessage>) {
    setMessages(prev => prev.map(m => m.id === id ? { ...m, ...updates } : m));
  }

  // Load active watch rules on mount
  useEffect(() => {
    fetch("/api/brain/rules", { headers: apiHeaders() })
      .then(r => r.ok ? r.json() : { rules: [] })
      .then(d => setActiveRules((d as { rules: WatchRule[] }).rules))
      .catch(() => {});
  }, []);

  // ── SSE: receive fired watch alerts ──────────────────────────────────────
  useEffect(() => {
    const controller = new AbortController();

    async function connectAlertStream() {
      try {
        const resp = await fetch("/api/brain/alerts/stream", {
          headers: apiHeaders(),
          signal: controller.signal,
        });
        if (!resp.ok || !resp.body) return;

        const reader  = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer    = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const chunks = buffer.split("\n\n");
          buffer = chunks.pop() ?? "";
          for (const chunk of chunks) {
            const line = chunk.trim();
            if (!line || line.startsWith(":")) continue; // keep-alive comment
            const dataLine = line.startsWith("data: ") ? line.slice(6) : line;
            try {
              const alert = JSON.parse(dataLine) as WatchAlert;
              const alertMsgId = crypto.randomUUID();
              const label = _conditionLabel(alert.condition_type, alert.threshold);
              setMessages(prev => [
                ...prev,
                {
                  id:      alertMsgId,
                  role:    "assistant",
                  content: `Alert fired: ${alert.symbol} ${label} — current price $${alert.trigger_price.toLocaleString()}.`,
                },
              ]);
              // Remove triggered rule from active rules list
              setActiveRules(prev => prev.filter(r => r.rule_id !== alert.rule_id));
              // If trigger_debate: auto-submit a debate for this symbol
              if (alert.trigger_debate) {
                setTimeout(() => handleQuery(`Analyse ${alert.symbol}`), 300);
              }
            } catch {
              // malformed SSE payload — ignore
            }
          }
        }
      } catch (err: unknown) {
        if (err instanceof Error && err.name === "AbortError") return;
        // Reconnect after 10 s on unexpected disconnect
        setTimeout(connectAlertStream, 10_000);
      }
    }

    connectAlertStream();
    return () => controller.abort();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

      } else if (classification.category === "C") {
        // ── Category C: register a watch rule ────────────────────────────
        const sym   = classification.symbol ?? "";
        const ctype = classification.condition_type ?? "";
        const thr   = classification.threshold ?? 0;
        const cls   = classification.asset_class ?? assetClass;

        updateMessage(assistantMsgId, { content: `Registering price alert for ${sym}…` });

        const ruleResp = await fetch("/api/brain/rule", {
          method:  "POST",
          headers: apiHeaders({ "Content-Type": "application/json" }),
          body:    JSON.stringify({
            symbol:         sym,
            asset_class:    cls,
            condition_type: ctype,
            threshold:      thr,
            trigger_debate: true,
          }),
        });

        if (!ruleResp.ok) {
          const err = await ruleResp.json().catch(() => ({})) as { detail?: string };
          updateMessage(assistantMsgId, {
            loading: false, content: "",
            error: err.detail ?? `Could not register rule: server error ${ruleResp.status}`,
          });
          return;
        }

        const rule = await ruleResp.json() as WatchRule;
        const label = _conditionLabel(ctype, thr);
        updateMessage(assistantMsgId, {
          loading: false,
          content: `Got it. I'll alert you when ${sym} ${label}. The debate will auto-run when it fires.`,
          watchRuleId: rule.rule_id,
        });
        setActiveRules(prev => [rule, ...prev]);

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

  async function deleteRule(ruleId: string) {
    await fetch(`/api/brain/rule/${ruleId}`, {
      method: "DELETE",
      headers: apiHeaders(),
    }).catch(() => {});
    setActiveRules(prev => prev.filter(r => r.rule_id !== ruleId));
  }

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
              {speech.state === "unsupported" ? "Enter to send" : "Enter to send · mic to speak"}
            </span>
          </div>

          {/* Query input + mic + send */}
          <div className="flex gap-2">
            <div className="relative flex-1">
              <input
                ref={inputRef}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                disabled={isProcessing}
                placeholder={
                  speech.state === "listening"
                    ? "Listening… speak your query"
                    : "Ask the agents anything… or type a ticker to run a debate"
                }
                className={clsx(
                  "w-full bg-surface-700 rounded-xl px-4 py-2.5 pr-10 text-sm font-mono outline-none focus:ring-1 focus:ring-brand-500 placeholder:text-slate-600 disabled:opacity-50 transition-all",
                  speech.state === "listening" && "ring-1 ring-red-500/60 placeholder:text-red-400/60",
                )}
              />
              {/* Live recording pulse dot inside the field */}
              {speech.state === "listening" && (
                <span className="absolute right-3 top-1/2 -translate-y-1/2 w-2 h-2 rounded-full bg-red-500 animate-pulse" />
              )}
            </div>

            {/* Mic button — hidden when unsupported */}
            {speech.state !== "unsupported" && (
              <button
                onClick={speech.toggle}
                disabled={isProcessing}
                aria-label={speech.state === "listening" ? "Stop recording" : "Start voice input"}
                title={speech.state === "listening" ? "Stop recording" : "Speak your query"}
                className={clsx(
                  "flex items-center justify-center w-10 py-2.5 rounded-xl border transition-all shrink-0 disabled:opacity-40",
                  speech.state === "listening"
                    ? "bg-red-500/20 border-red-500/40 text-red-400 hover:bg-red-500/30"
                    : "border-white/5 bg-surface-700 text-slate-500 hover:text-slate-300 hover:border-white/10",
                )}
              >
                {speech.state === "listening"
                  ? <MicOff className="w-4 h-4" />
                  : <Mic className="w-4 h-4" />}
              </button>
            )}

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

      {/* ── Active watch rules ──────────────────────────────────────────── */}
      {activeRules.length > 0 && (
        <div className="glass rounded-2xl p-5">
          <h2 className="text-xs font-semibold uppercase tracking-widest text-slate-400 mb-3 flex items-center gap-2">
            <Bell className="w-3.5 h-3.5 text-amber-400" />
            Active Watch Rules
            <span className="ml-1 text-[10px] font-mono text-slate-600 normal-case tracking-normal">
              evaluated every orchestrator cycle
            </span>
          </h2>
          <div className="space-y-2">
            {activeRules.map(rule => (
              <div key={rule.rule_id}
                className="flex items-center justify-between gap-3 bg-surface-700/50 rounded-xl px-3 py-2.5"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <span className="text-sm font-mono font-semibold text-slate-200">{rule.symbol}</span>
                  <span className={clsx(
                    "text-xs font-mono px-2 py-0.5 rounded-md",
                    rule.condition_type === "price_above"
                      ? "bg-emerald-500/10 text-emerald-400"
                      : "bg-red-500/10 text-red-400",
                  )}>
                    {rule.condition_type === "price_above" ? "↑ above" : "↓ below"} ${rule.threshold.toLocaleString()}
                  </span>
                </div>
                <button
                  onClick={() => deleteRule(rule.rule_id)}
                  title="Delete rule"
                  className="text-slate-600 hover:text-red-400 transition-colors shrink-0"
                >
                  <BellOff className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

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
