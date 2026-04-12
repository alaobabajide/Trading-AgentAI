import { X, Zap } from "lucide-react";
import clsx from "clsx";
import type { Signal } from "../lib/types";
import { SignalBadge } from "./SignalBadge";

interface Props {
  signal:    Signal;
  secsLeft:  number;
  onVeto:    () => void;
  onConfirm: () => void;
}

export function WarmSignalBanner({ signal, secsLeft, onVeto, onConfirm }: Props) {
  const isHot = signal.tier === "HOT";
  const progress = isHot
    ? (secsLeft / 5) * 100
    : (secsLeft / 10) * 100;

  return (
    <div className={clsx(
      "fixed bottom-6 left-1/2 -translate-x-1/2 z-50 w-[520px] rounded-2xl border shadow-2xl",
      "glass overflow-hidden",
      isHot
        ? "border-emerald-500/40 shadow-emerald-500/10"
        : "border-amber-500/40 shadow-amber-500/10",
    )}>
      {/* Progress bar */}
      <div className="h-0.5 bg-white/5">
        <div
          className={clsx(
            "h-full transition-all duration-1000",
            isHot ? "bg-emerald-500" : "bg-amber-500",
          )}
          style={{ width: `${progress}%` }}
        />
      </div>

      <div className="p-4">
        <div className="flex items-start gap-3">
          <div className={clsx(
            "w-8 h-8 rounded-xl flex items-center justify-center shrink-0",
            isHot ? "bg-emerald-500/20" : "bg-amber-500/20",
          )}>
            <Zap className={clsx("w-4 h-4", isHot ? "text-emerald-400" : "text-amber-400")} />
          </div>

          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span className="font-mono font-bold text-sm">{signal.symbol}</span>
              <SignalBadge action={signal.action} />
              <span className={clsx(
                "text-[10px] px-1.5 py-0.5 rounded-full font-semibold uppercase",
                isHot
                  ? "bg-emerald-500/15 text-emerald-400"
                  : "bg-amber-500/15 text-amber-400",
              )}>
                {isHot ? "HOT" : "WARM"}
              </span>
            </div>
            <p className="text-xs text-slate-400 line-clamp-1">{signal.rationale}</p>
            <p className={clsx(
              "text-[11px] font-mono mt-1",
              isHot ? "text-emerald-400" : "text-amber-400",
            )}>
              {secsLeft > 0
                ? isHot
                  ? `Auto-executing in ${secsLeft}s — click to veto`
                  : `Auto-confirming in ${secsLeft}s — click to veto`
                : "Executing…"}
            </p>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <button
              onClick={onConfirm}
              className={clsx(
                "px-3 py-1.5 rounded-xl text-xs font-medium transition-colors",
                isHot
                  ? "bg-emerald-500/20 text-emerald-300 hover:bg-emerald-500/30"
                  : "bg-amber-500/20 text-amber-300 hover:bg-amber-500/30",
              )}
            >
              Execute now
            </button>
            <button
              onClick={onVeto}
              className="p-1.5 rounded-xl text-slate-500 hover:text-slate-300 hover:bg-white/[0.05] transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
