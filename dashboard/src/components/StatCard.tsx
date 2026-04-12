import { ReactNode } from "react";
import clsx from "clsx";

interface StatCardProps {
  label: string;
  value: string;
  sub?: string;
  trend?: "up" | "down" | "neutral";
  icon?: ReactNode;
  accent?: boolean;
}

export function StatCard({ label, value, sub, trend, icon, accent }: StatCardProps) {
  return (
    <div className={clsx(
      "glass rounded-2xl p-5 flex flex-col gap-1",
      accent && "glow-brand border-brand-500/30",
    )}>
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-medium text-slate-400 uppercase tracking-widest">{label}</span>
        {icon && <span className="text-slate-500">{icon}</span>}
      </div>
      <span className="text-2xl font-semibold font-mono tracking-tight">{value}</span>
      {sub && (
        <span className={clsx(
          "text-xs font-mono",
          trend === "up"   && "text-emerald-400",
          trend === "down" && "text-red-400",
          trend === "neutral" && "text-slate-400",
          !trend             && "text-slate-400",
        )}>
          {sub}
        </span>
      )}
    </div>
  );
}
