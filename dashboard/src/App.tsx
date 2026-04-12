import { useState } from "react";
import clsx from "clsx";
import { Sidebar } from "./components/Sidebar";
import { WarmSignalBanner } from "./components/WarmSignalBanner";
import { Dashboard } from "./pages/Dashboard";
import { SignalsPage } from "./pages/SignalsPage";
import { PositionsPage } from "./pages/PositionsPage";
import { BrainPage } from "./pages/BrainPage";
import { TechnicalPage } from "./pages/TechnicalPage";
import { FundamentalPage } from "./pages/FundamentalPage";
import { ChartsPage } from "./pages/ChartsPage";
import { SettingsPage } from "./pages/SettingsPage";
import { HITLProvider, useHITLContext } from "./context/HITLContext";
import { MODE_CONFIG } from "./lib/hitl";

type Page = "dashboard" | "signals" | "positions" | "technical" | "fundamental" | "charts" | "brain" | "settings";

const PAGE_TITLE: Partial<Record<Page, string>> = {
  fundamental: "Fundamental Analysis",
  technical:   "Technical Analysis",
  charts:      "TradingView Charts",
  settings:    "Settings",
};

function AppInner() {
  const [page, setPage] = useState<Page>("dashboard");
  const hitl    = useHITLContext();
  const modeCfg = MODE_CONFIG[hitl.profile.mode];

  return (
    <div className="flex h-screen overflow-hidden bg-surface-900">
      <Sidebar active={page} onNav={setPage} />

      <main className={`flex-1 flex flex-col min-w-0 ${page === "charts" ? "overflow-hidden" : "overflow-y-auto"}`}>
        {/* Top bar */}
        <div className="shrink-0 z-10 glass border-b border-white/5 px-8 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-sm font-semibold capitalize">
              {PAGE_TITLE[page] ?? page}
            </h1>
            <p className="text-[11px] text-slate-500 font-mono mt-0.5">
              {new Date().toLocaleString("en-US", {
                weekday: "short", month: "short", day: "numeric",
                hour: "2-digit", minute: "2-digit",
              })}
            </p>
          </div>

          <div className="flex items-center gap-2">
            {/* HITL Mode selector */}
            <div className="flex items-center gap-0.5 bg-surface-700 rounded-xl p-1 border border-white/5">
              {(["auto", "assisted", "manual"] as const).map((m) => (
                <button
                  key={m}
                  onClick={() => hitl.setMode(m)}
                  className={clsx(
                    "px-3 py-1.5 rounded-lg text-xs font-medium transition-all capitalize",
                    hitl.profile.mode === m
                      ? m === "auto"     ? "bg-emerald-500/20 text-emerald-300"
                        : m === "assisted" ? "bg-amber-500/20 text-amber-300"
                        :                   "bg-slate-500/20 text-slate-300"
                      : "text-slate-500 hover:text-slate-300",
                  )}
                >
                  {m}
                </button>
              ))}
            </div>

            {/* Status badges */}
            <div className="flex items-center gap-2 text-xs text-slate-500 font-mono">
              <span className={clsx(
                "px-2.5 py-1 rounded-lg border text-[11px] font-semibold",
                hitl.profile.mode === "auto"     ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-400" :
                hitl.profile.mode === "assisted" ? "bg-amber-500/10   border-amber-500/20   text-amber-400"   :
                                                   "bg-slate-500/10   border-slate-600/40   text-slate-400",
              )}>
                {modeCfg.label}
              </span>
              <span className="px-2.5 py-1 rounded-lg bg-surface-700 border border-white/5">
                Paper trading
              </span>
              <span className="px-2.5 py-1 rounded-lg bg-surface-700 border border-white/5">
                Testnet
              </span>
            </div>
          </div>
        </div>

        <div className={page === "charts" ? "flex-1 min-h-0 flex flex-col" : "p-8"}>
          {page === "dashboard"   && <Dashboard />}
          {page === "signals"     && <SignalsPage />}
          {page === "positions"   && <PositionsPage />}
          {page === "technical"   && <TechnicalPage />}
          {page === "fundamental" && <FundamentalPage />}
          {page === "charts"      && <ChartsPage />}
          {page === "brain"       && <BrainPage />}
          {page === "settings"    && <SettingsPage />}
        </div>
      </main>

      {/* Warm/Hot signal veto banner */}
      {hitl.pendingSignal && hitl.vetoSecsLeft > 0 && (
        <WarmSignalBanner
          signal={hitl.pendingSignal}
          secsLeft={hitl.vetoSecsLeft}
          onVeto={hitl.vetoSignal}
          onConfirm={async () => {
            await hitl.executeSignal(hitl.pendingSignal!);
            hitl.confirmSignal();
          }}
        />
      )}

      {/* Manual mode cool-off overlay */}
      {hitl.coolOffActive && (
        <div className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center">
          <div className="glass rounded-2xl border border-amber-500/30 p-8 max-w-sm text-center space-y-4 shadow-2xl">
            <div className="w-14 h-14 rounded-2xl bg-amber-500/15 flex items-center justify-center mx-auto">
              <span className="text-2xl font-mono font-bold text-amber-400">{hitl.coolOffSecsLeft}</span>
            </div>
            <div>
              <h3 className="font-semibold text-sm">Cool-off period active</h3>
              <p className="text-xs text-slate-400 mt-1.5 leading-relaxed">
                This trade exceeds your self-defined position limit. Execute in{" "}
                <span className="text-amber-400 font-mono font-semibold">{hitl.coolOffSecsLeft}s</span>.
              </p>
              <p className="text-[11px] text-slate-500 mt-1 italic">
                "Give your prefrontal cortex time to catch up to your amygdala."
              </p>
            </div>
            <div className="flex gap-2">
              <button
                onClick={hitl.confirmCoolOff}
                className="flex-1 py-2 rounded-xl bg-amber-500/20 text-amber-300 text-sm font-medium hover:bg-amber-500/30 transition-colors"
              >
                Execute anyway
              </button>
              <button
                onClick={hitl.confirmCoolOff}
                className="flex-1 py-2 rounded-xl border border-white/10 text-slate-400 text-sm hover:text-slate-200 transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function App() {
  return (
    <HITLProvider>
      <AppInner />
    </HITLProvider>
  );
}
