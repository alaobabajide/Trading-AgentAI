import { Activity, BarChart2, BookOpen, Brain, CandlestickChart, LayoutDashboard, Settings, Zap } from "lucide-react";
import clsx from "clsx";

type Page = "dashboard" | "signals" | "positions" | "technical" | "fundamental" | "charts" | "brain" | "settings";

interface Props {
  active: Page;
  onNav: (p: Page) => void;
}

const NAV: { id: Page; label: string; icon: typeof LayoutDashboard; group?: string }[] = [
  { id: "dashboard",   label: "Dashboard",   icon: LayoutDashboard },
  { id: "signals",     label: "Signals",     icon: Zap },
  { id: "positions",   label: "Positions",   icon: BarChart2 },
  { id: "technical",   label: "Technical",   icon: Activity,           group: "Analysis" },
  { id: "fundamental", label: "Fundamental", icon: BookOpen,           group: "Analysis" },
  { id: "charts",      label: "TV Charts",   icon: CandlestickChart,   group: "Analysis" },
  { id: "brain",       label: "Brain",       icon: Brain },
  { id: "settings",    label: "Settings",    icon: Settings },
];

export function Sidebar({ active, onNav }: Props) {
  return (
    <aside className="w-56 shrink-0 glass border-r border-white/5 flex flex-col py-6 px-3">
      {/* Logo */}
      <div className="px-3 mb-8">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-brand-500 to-brand-700 flex items-center justify-center">
            <Zap className="w-4 h-4 text-white" />
          </div>
          <div>
            <div className="text-sm font-semibold leading-none">TradeAgent</div>
            <div className="text-[10px] text-slate-500 mt-0.5">Hybrid AI</div>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 space-y-1">
        {NAV.map(({ id, label, icon: Icon, group }, i) => {
          const prevGroup = NAV[i - 1]?.group;
          const showDivider = group && group !== prevGroup;
          return (
            <div key={id}>
              {showDivider && (
                <div className="px-3 pt-3 pb-1">
                  <span className="text-[10px] text-slate-600 uppercase tracking-widest font-medium">{group}</span>
                </div>
              )}
              <button
                onClick={() => onNav(id)}
                className={clsx(
                  "w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition-all",
                  active === id
                    ? "bg-brand-500/20 text-brand-400 font-medium"
                    : "text-slate-400 hover:bg-white/[0.03] hover:text-slate-200",
                )}
              >
                <Icon className="w-4 h-4 shrink-0" />
                {label}
              </button>
            </div>
          );
        })}
      </nav>

      {/* Status dot */}
      <div className="px-3 mt-4">
        <div className="glass rounded-xl px-3 py-2.5 flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
          </span>
          <span className="text-xs text-slate-400">Brain live</span>
        </div>
      </div>
    </aside>
  );
}
