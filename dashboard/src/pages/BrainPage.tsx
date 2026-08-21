import { useState } from "react";
import { Brain, Loader2, Send, CheckCircle2, XCircle, Clock, Zap, DollarSign, BarChart2, AlertCircle } from "lucide-react";
import clsx from "clsx";
import { SignalCard } from "../components/SignalCard";
import type { Signal } from "../lib/types";
import { useHITLContext } from "../context/HITLContext";
import { apiHeaders, useCreditStatus, useApiUsage } from "../lib/api";

// ── Usage & Credits panel ─────────────────────────────────────────────────────

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
      {/* Credits card */}
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

            {/* Progress bar */}
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
                Balance below ${credits.warning_threshold} threshold. A Telegram alert has been (or will be) sent.
                <a href="https://openrouter.ai/settings/billing" target="_blank" rel="noreferrer"
                  className="ml-1 underline underline-offset-2">
                  Add credits →
                </a>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Today's usage */}
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
                { label: "API Calls", value: today.calls.toLocaleString(), color: "text-brand-400" },
                { label: "Input Tokens", value: fmtTokens(today.input_tokens), color: "text-sky-400" },
                { label: "Output Tokens", value: fmtTokens(today.output_tokens), color: "text-violet-400" },
                { label: "Est. Cost", value: `$${today.cost_usd.toFixed(4)}`, color: "text-emerald-400" },
              ].map((m) => (
                <div key={m.label} className="bg-surface-700 rounded-xl p-3 text-center">
                  <div className="text-[9px] text-slate-500 uppercase tracking-wider mb-1">{m.label}</div>
                  <div className={clsx("text-sm font-mono font-semibold", m.color)}>{m.value}</div>
                </div>
              ))}
            </div>

            {/* Per-model breakdown */}
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

      {/* Daily history table */}
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

async function safeJson(resp: Response): Promise<unknown> {
  const text = await resp.text();
  if (!text) throw new Error(resp.statusText || `HTTP ${resp.status}`);
  try { return JSON.parse(text); } catch { throw new Error(text.slice(0, 200)); }
}

interface BrainPageProps {
  paperMode?: boolean;
}

export function BrainPage({ paperMode = true }: BrainPageProps) {
  const [symbol, setSymbol] = useState("AAPL");
  const [assetClass, setAssetClass] = useState<"stock" | "crypto">("stock");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<Signal | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [execStatus, setExecStatus] = useState<string | null>(null);
  const hitl = useHITLContext();

  async function handleRun() {
    const sym = symbol.trim().toUpperCase();
    if (!sym || !/^[A-Z0-9]{1,20}$/.test(sym)) {
      setError("Invalid symbol — use 1–20 uppercase letters/digits (e.g. AAPL, BTCUSDT)");
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    setExecStatus(null);
    try {
      const resp = await fetch("/api/signal", {
        method: "POST",
        headers: apiHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ symbol: sym, asset_class: assetClass, paper_mode: paperMode }),
      });
      if (!resp.ok) {
        const data = await safeJson(resp) as { detail?: string };
        setError(data?.detail ?? `HTTP ${resp.status}`);
        return;
      }
      const data = await safeJson(resp) as Signal;
      setResult(data);

      // ── Wire into HITL: act on the signal based on current mode ──────────
      if (data.action !== "HOLD") {
        const disposition = hitl.receiveSignal(data);
        if (disposition === "auto_execute") {
          setExecStatus("auto_executing");
          const execResult = await hitl.executeSignal(data);
          if (execResult) {
            setExecStatus(
              `Auto-executed: Order ${execResult.order_id} · ${execResult.status} on ${execResult.exchange}`
            );
          } else {
            setExecStatus(`Auto-execute failed: ${hitl.executeError ?? "unknown error"}`);
          }
        } else if (disposition === "veto_window") {
          setExecStatus("Queued for approval — review the confirmation banner.");
        } else if (disposition === "queue_manual") {
          setExecStatus("Queued for manual execution — click Execute on the signal card below.");
        }
      }
    } catch (err) {
      setError((err as Error).message ?? "Network error — backend not reachable");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-lg font-semibold flex items-center gap-2">
          <Brain className="w-5 h-5 text-brand-400" />
          Brain Console
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Trigger the multi-agent debate for any symbol and inspect agent views live.
        </p>
        <div className={clsx(
          "inline-flex items-center gap-1.5 mt-2 px-2.5 py-1 rounded-lg text-[11px] font-mono font-semibold border",
          paperMode
            ? "bg-sky-500/10 border-sky-500/20 text-sky-400"
            : "bg-red-500/10 border-red-500/20 text-red-400",
        )}>
          <span className={clsx("w-1.5 h-1.5 rounded-full", paperMode ? "bg-sky-400" : "bg-red-400 animate-pulse")} />
          {paperMode
            ? "Paper mode — rule-based analysis, no API credits needed"
            : "Live mode — full 27-agent LLM debate (requires OpenRouter credits)"}
        </div>
      </div>

      <div className="glass rounded-2xl p-5 space-y-4">
        <div className="flex gap-3">
          <input
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            placeholder="Symbol (e.g. AAPL)"
            className="flex-1 bg-surface-700 rounded-xl px-4 py-2.5 text-sm font-mono outline-none focus:ring-1 focus:ring-brand-500 placeholder:text-slate-600"
          />
          <div className="flex rounded-xl overflow-hidden border border-white/5">
            {(["stock", "crypto"] as const).map((cls) => (
              <button
                key={cls}
                onClick={() => setAssetClass(cls)}
                className={clsx(
                  "px-4 py-2.5 text-sm transition-colors",
                  assetClass === cls
                    ? "bg-brand-500 text-white"
                    : "bg-surface-700 text-slate-400 hover:text-slate-200",
                )}
              >
                {cls}
              </button>
            ))}
          </div>
          <button
            onClick={handleRun}
            disabled={loading}
            className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-brand-600 hover:bg-brand-500 text-sm font-medium transition-colors disabled:opacity-50"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
            {loading ? "Debating…" : "Run"}
          </button>
        </div>

        {loading && (
          <div className="text-xs text-slate-400 font-mono space-y-1 animate-pulse">
            <div>→ Fetching market data…</div>
            {paperMode ? (
              <>
                <div>→ Running rule-based technical analysis…</div>
                <div>→ Running rule-based quant (Bollinger Bands)…</div>
                <div>→ Running rule-based fundamental (momentum)…</div>
                <div>→ Computing regime + risk assessment…</div>
              </>
            ) : (
              <>
                <div>→ Running fundamental analyst…</div>
                <div>→ Running technical analyst…</div>
                <div>→ Running sentiment analyst…</div>
                <div>→ Risk manager synthesising…</div>
              </>
            )}
          </div>
        )}

        {error && (
          <div className="rounded-xl bg-red-500/10 border border-red-500/20 text-red-400 text-sm px-4 py-3 font-mono space-y-1">
            <div className="font-semibold">Backend error</div>
            <div>{error}</div>
          </div>
        )}

        {execStatus && execStatus !== "auto_executing" && (
          <div className={clsx(
            "rounded-xl px-4 py-3 text-sm font-mono flex items-center gap-2",
            execStatus.startsWith("Auto-executed")
              ? "bg-emerald-500/10 border border-emerald-500/20 text-emerald-400"
              : execStatus.startsWith("Queued")
              ? "bg-amber-500/10 border border-amber-500/20 text-amber-400"
              : "bg-red-500/10 border border-red-500/20 text-red-400",
          )}>
            {execStatus.startsWith("Auto-executed") ? (
              <CheckCircle2 className="w-4 h-4 shrink-0" />
            ) : execStatus.startsWith("Queued") ? (
              <Clock className="w-4 h-4 shrink-0" />
            ) : (
              <XCircle className="w-4 h-4 shrink-0" />
            )}
            {execStatus}
          </div>
        )}
        {execStatus === "auto_executing" && (
          <div className="rounded-xl bg-sky-500/10 border border-sky-500/20 text-sky-400 text-sm px-4 py-3 font-mono flex items-center gap-2">
            <Loader2 className="w-4 h-4 animate-spin shrink-0" />
            Sending order to Alpaca…
          </div>
        )}
      </div>

      {result && <SignalCard signal={result} />}

      {/* API usage & credit transparency */}
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
