import { Zap } from "lucide-react";
import { SignalCard } from "../components/SignalCard";
import { useSignals } from "../lib/api";

export function SignalsPage() {
  const { signals, apiState } = useSignals();

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold flex items-center gap-2">
          <Zap className="w-5 h-5 text-brand-400" />
          Signal Feed
        </h1>
        <div className="flex items-center gap-2">
          <span className="text-xs text-slate-500 font-mono">{signals.length} signals</span>
          <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded border ${
            apiState === "live"
              ? "bg-emerald-500/10 text-emerald-400 border-emerald-500/20"
              : apiState === "loading"
              ? "bg-slate-500/10 text-slate-400 border-slate-600/20"
              : "bg-amber-500/10 text-amber-400 border-amber-500/20"
          }`}>
            {apiState === "live" ? "Live cache" : apiState === "loading" ? "Loading…" : "Mock"}
          </span>
        </div>
      </div>

      {apiState === "live" && signals.length === 0 && (
        <div className="glass rounded-2xl p-8 text-center text-slate-500 text-sm">
          No signals in cache yet. Use the Brain Console to generate one.
        </div>
      )}

      <div className="space-y-3">
        {signals.map((s) => (
          <SignalCard key={`${s.symbol}-${s.generated_at}`} signal={s} />
        ))}
      </div>
    </div>
  );
}
