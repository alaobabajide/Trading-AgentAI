import { useState } from "react";
import { Brain, FlaskConical, Loader2, Send, CheckCircle2 } from "lucide-react";
import clsx from "clsx";
import { SignalCard } from "../components/SignalCard";
import type { Signal } from "../lib/types";
import { mockSignals } from "../lib/mock";
import { useHITLContext } from "../context/HITLContext";
import { apiHeaders } from "../lib/api";

/** Build a plausible mock signal for any symbol when the backend is offline. */
function mockSignalFor(sym: string, cls: "stock" | "crypto"): Signal {
  const base = mockSignals.find((s) => s.symbol === sym.toUpperCase())
    ?? mockSignals[Math.floor(Math.random() * mockSignals.length)];
  return {
    ...base,
    symbol: sym.toUpperCase(),
    asset_class: cls,
    generated_at: new Date().toISOString(),
  };
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
  const [usedMock, setUsedMock] = useState(false);
  const [execStatus, setExecStatus] = useState<string | null>(null);
  const hitl = useHITLContext();

  async function handleRun() {
    setLoading(true);
    setError(null);
    setResult(null);
    setUsedMock(false);
    setExecStatus(null);
    try {
      const resp = await fetch("/api/signal", {
        method: "POST",
        headers: apiHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ symbol: symbol.toUpperCase(), asset_class: assetClass, paper_mode: paperMode }),
      });
      if (!resp.ok) {
        const data = await safeJson(resp) as { detail?: string };
        const msg = data?.detail ?? `HTTP ${resp.status}`;
        setError(msg);
        setUsedMock(true);
        setResult(mockSignalFor(symbol, assetClass));
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
        }
        // "queue_manual" → execute button on the card handles it
      }
    } catch (err) {
      setError((err as Error).message ?? "Network error — backend not reachable");
      setUsedMock(true);
      setResult(mockSignalFor(symbol, assetClass));
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
            : "Live mode — full 9-agent LLM debate (requires Anthropic credits)"}
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
            <CheckCircle2 className="w-4 h-4 shrink-0" />
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

      {usedMock && !error && (
        <div className="flex items-center gap-2 text-xs text-amber-400/80 font-mono bg-amber-500/10 border border-amber-500/20 rounded-xl px-4 py-2.5">
          <FlaskConical className="w-3.5 h-3.5 shrink-0" />
          Brain API offline — showing simulated signal. Start the backend to run live analysis.
        </div>
      )}

      {result && <SignalCard signal={result} />}
    </div>
  );
}
