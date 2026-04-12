import clsx from "clsx";
import { SignalAction } from "../lib/types";

export function SignalBadge({ action }: { action: SignalAction }) {
  return (
    <span className={clsx(
      "inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold font-mono",
      action === "BUY"  && "bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/30",
      action === "SELL" && "bg-red-500/15 text-red-400 ring-1 ring-red-500/30",
      action === "HOLD" && "bg-slate-500/15 text-slate-400 ring-1 ring-slate-500/30",
    )}>
      {action === "BUY"  && <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />}
      {action === "SELL" && <span className="w-1.5 h-1.5 rounded-full bg-red-400" />}
      {action === "HOLD" && <span className="w-1.5 h-1.5 rounded-full bg-slate-400" />}
      {action}
    </span>
  );
}
