import { mockSignals } from "../lib/mock";
import { SignalCard } from "../components/SignalCard";
import { Zap } from "lucide-react";

export function SignalsPage() {
  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold flex items-center gap-2">
          <Zap className="w-5 h-5 text-brand-400" />
          Signal Feed
        </h1>
        <span className="text-xs text-slate-500 font-mono">{mockSignals.length} signals</span>
      </div>
      <div className="space-y-3">
        {mockSignals.map((s) => (
          <SignalCard key={`${s.symbol}-${s.generated_at}`} signal={s} />
        ))}
      </div>
    </div>
  );
}
