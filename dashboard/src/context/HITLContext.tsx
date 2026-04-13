import { createContext, useContext, useCallback, ReactNode } from "react";
import { useHITL } from "../hooks/useHITL";
import { useExecute, ExecuteResult } from "../hooks/useExecute";
import type { Signal } from "../lib/types";

type HITLContextValue = ReturnType<typeof useHITL> & {
  executeSignal:  (signal: Signal) => Promise<ExecuteResult | null>;
  executing:      boolean;
  executeError:   string | null;
  clearExecError: () => void;
};

const HITLContext = createContext<HITLContextValue | null>(null);

export function HITLProvider({ children }: { children: ReactNode }) {
  const hitl = useHITL();
  const { execute, executing, error: executeError, clearError: clearExecError } = useExecute();

  const executeSignal = useCallback(
    (signal: Signal) => {
      const p = hitl.profile;
      return execute({
        symbol:                 signal.symbol,
        asset_class:            signal.asset_class,
        action:                 signal.action,
        suggested_position_pct: signal.suggested_position_pct,
        // Profile stop/take-profit overrides (stored as %, sent as fraction)
        stop_loss_pct:   p.defaultStopLossPct   > 0 ? p.defaultStopLossPct   / 100 : signal.stop_loss_pct,
        take_profit_pct: p.defaultTakeProfitPct > 0 ? p.defaultTakeProfitPct / 100 : signal.take_profit_pct,
        // Fixed qty: >0 = exact share count; 0 = let backend use notional sizing
        qty: p.useFixedQty && p.defaultQty > 0 ? p.defaultQty : 0,
      });
    },
    [execute, hitl.profile],
  );

  return (
    <HITLContext.Provider value={{ ...hitl, executeSignal, executing, executeError, clearExecError }}>
      {children}
    </HITLContext.Provider>
  );
}

export function useHITLContext(): HITLContextValue {
  const ctx = useContext(HITLContext);
  if (!ctx) throw new Error("useHITLContext must be used inside <HITLProvider>");
  return ctx;
}
