import { useState, useEffect, useRef, useCallback } from "react";
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
import { IndicesPage } from "./pages/IndicesPage";
import { SettingsPage } from "./pages/SettingsPage";
import { HITLProvider, useHITLContext } from "./context/HITLContext";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { LoginPage } from "./pages/LoginPage";
import { SetupBanner } from "./components/SetupBanner";
import { MODE_CONFIG, HOT_VETO_SECONDS } from "./lib/hitl";
import { useCreditStatus, getActiveUserId } from "./lib/api";
import { AlertTriangle, Loader2, X } from "lucide-react";

type Page = "dashboard" | "signals" | "positions" | "technical" | "fundamental" | "charts" | "indices" | "brain" | "settings";
type TradingEnv = "paper" | "live";

function CreditWarningBanner() {
  const status = useCreditStatus();
  const [dismissed, setDismissed] = useState(false);

  if (!status || !status.warning || dismissed) return null;

  const balance    = status.balance_usd ?? 0;
  const critThresh = status.critical_threshold ?? 2;
  const urgent     = balance < critThresh;

  return (
    <div className={clsx(
      "shrink-0 flex items-center gap-3 px-8 py-2.5 border-b text-sm font-medium",
      urgent
        ? "bg-red-500/15 border-red-500/30 text-red-300"
        : "bg-amber-500/15 border-amber-500/30 text-amber-300",
    )}>
      <AlertTriangle className="w-4 h-4 shrink-0 animate-pulse" />
      <span className="flex-1">
        <strong>API credit low:</strong> ${balance.toFixed(2)} remaining on OpenRouter.
        {urgent ? " Trading may stop soon — " : " "}
        <a
          href="https://openrouter.ai/settings/billing"
          target="_blank" rel="noreferrer"
          className="underline underline-offset-2 hover:opacity-80"
        >
          Top up now
        </a>
      </span>
      <button
        onClick={() => setDismissed(true)}
        className="opacity-60 hover:opacity-100 transition-opacity"
        aria-label="Dismiss"
      >
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}

const PAGE_TITLE: Partial<Record<Page, string>> = {
  fundamental: "Fundamental Analysis",
  technical:   "Technical Analysis",
  charts:      "TradingView Charts",
  indices:     "Market Indices",
  settings:    "Settings",
};

function _tradingEnvKey(): string {
  const uid = getActiveUserId();
  return uid ? `ta:tradingEnv:${uid}` : "ta:tradingEnv";
}

function AppInner() {
  const [page, setPage] = useState<Page>("dashboard");
  const [tradingEnv, setTradingEnvState] = useState<TradingEnv>(() => {
    try { return (localStorage.getItem(_tradingEnvKey()) as TradingEnv) || "paper"; } catch { return "paper"; }
  });
  const hitl    = useHITLContext();
  const modeCfg = MODE_CONFIG[hitl.profile.mode];
  const isPaper = tradingEnv === "paper";

  const setTradingEnv = useCallback((env: TradingEnv) => {
    setTradingEnvState(env);
    try { localStorage.setItem(_tradingEnvKey(), env); } catch {}
  }, []);

  // Reload Paper/Live preference when the logged-in user changes.
  useEffect(() => {
    function onUserChanged() {
      try {
        setTradingEnvState((localStorage.getItem(_tradingEnvKey()) as TradingEnv) || "paper");
      } catch {}
    }
    window.addEventListener("ta:userChanged", onUserChanged);
    return () => window.removeEventListener("ta:userChanged", onUserChanged);
  }, []);

  // Toast state for execute results
  const [toast, setToast] = useState<{ type: "success" | "error"; msg: string } | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function showToast(type: "success" | "error", msg: string) {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast({ type, msg });
    toastTimer.current = setTimeout(() => setToast(null), 6000);
  }

  // Auto-execute when the veto countdown expires in Assisted mode.
  // This is the correct place: HITLContext has both the pending signal AND execute().
  // The `prev > 0` guard prevents firing in Manual mode where vetoSecsLeft starts at 0.
  const prevVetoRef = useRef(0);
  useEffect(() => {
    const prev = prevVetoRef.current;
    prevVetoRef.current = hitl.vetoSecsLeft;

    if (prev > 0 && hitl.vetoSecsLeft === 0 && hitl.pendingSignal) {
      const sig = hitl.pendingSignal;
      hitl.confirmSignal(); // clear banner immediately
      hitl.executeSignal(sig).then((result) => {
        if (result) {
          showToast("success",
            `Order submitted · ${result.symbol} ${result.action} · ${result.qty ?? result.notional ?? ""}${result.qty ? " shares" : " USD"} · ID ${result.order_id.slice(0, 8)}`
          );
        } else {
          showToast("error",
            `Order failed · ${sig.symbol} ${sig.action} · ${hitl.executeErrorRef.current ?? "unknown error"}`
          );
        }
      });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hitl.vetoSecsLeft]);

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

            {/* Status badges + trading env toggle */}
            <div className="flex items-center gap-2 text-xs text-slate-500 font-mono">
              <span className={clsx(
                "px-2.5 py-1 rounded-lg border text-[11px] font-semibold",
                hitl.profile.mode === "auto"     ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-400" :
                hitl.profile.mode === "assisted" ? "bg-amber-500/10   border-amber-500/20   text-amber-400"   :
                                                   "bg-slate-500/10   border-slate-600/40   text-slate-400",
              )}>
                {modeCfg.label}
              </span>

              {/* Paper ↔ Live toggle */}
              <div className="flex items-center rounded-lg overflow-hidden border border-white/10 text-[11px] font-semibold">
                <button
                  onClick={() => setTradingEnv("paper")}
                  className={clsx(
                    "px-2.5 py-1 transition-colors",
                    isPaper
                      ? "bg-sky-500/20 text-sky-300 border-r border-sky-500/30"
                      : "bg-surface-700 text-slate-500 hover:text-slate-300 border-r border-white/10",
                  )}
                >
                  Paper
                </button>
                <button
                  onClick={() => setTradingEnv("live")}
                  className={clsx(
                    "px-2.5 py-1 transition-colors",
                    !isPaper
                      ? "bg-red-500/20 text-red-300"
                      : "bg-surface-700 text-slate-500 hover:text-slate-300",
                  )}
                >
                  Live
                </button>
              </div>

              {!isPaper && (
                <span className="px-2 py-0.5 rounded bg-red-500/15 border border-red-500/30 text-red-400 text-[10px] font-bold animate-pulse">
                  LIVE
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Setup banner — only visible when Brain API is online but keys are missing */}
        <SetupBanner />

        {/* Credit warning — shown when OpenRouter balance drops below $5 */}
        <CreditWarningBanner />

        <div className={page === "charts" ? "flex-1 min-h-0 flex flex-col" : "p-8"}>
          {page === "dashboard"   && <Dashboard />}
          {page === "signals"     && <SignalsPage />}
          {page === "positions"   && <PositionsPage />}
          {page === "technical"   && <TechnicalPage />}
          {page === "fundamental" && <FundamentalPage />}
          {page === "charts"      && <ChartsPage />}
          {page === "indices"     && <IndicesPage paperMode={isPaper} />}
          {page === "brain"       && <BrainPage paperMode={isPaper} />}
          {page === "settings"    && <SettingsPage />}
        </div>
      </main>

      {/* Warm/Hot signal veto banner */}
      {hitl.pendingSignal && hitl.vetoSecsLeft > 0 && (
        <WarmSignalBanner
          signal={hitl.pendingSignal}
          secsLeft={hitl.vetoSecsLeft}
          totalSecs={hitl.pendingSignal.tier === "HOT" ? HOT_VETO_SECONDS : hitl.profile.warmVetoSeconds}
          onVeto={hitl.vetoSignal}
          onConfirm={async () => {
            await hitl.executeSignal(hitl.pendingSignal!);
            hitl.confirmSignal();
          }}
        />
      )}

      {/* Execute result toast */}
      {toast && (
        <div
          className={`fixed top-6 right-6 z-50 max-w-sm rounded-2xl border px-4 py-3 text-xs font-mono shadow-2xl glass ${
            toast.type === "success"
              ? "border-emerald-500/30 text-emerald-400"
              : "border-red-500/30 text-red-400"
          }`}
        >
          <div className="font-semibold mb-0.5">{toast.type === "success" ? "Order submitted" : "Order failed"}</div>
          <div className="text-slate-400">{toast.msg}</div>
        </div>
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

function AuthGate() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen bg-surface-900 flex items-center justify-center">
        <Loader2 className="w-6 h-6 text-brand-400 animate-spin" />
      </div>
    );
  }

  if (!user) {
    return <LoginPage />;
  }

  return (
    <HITLProvider>
      <AppInner />
    </HITLProvider>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <AuthGate />
    </AuthProvider>
  );
}
