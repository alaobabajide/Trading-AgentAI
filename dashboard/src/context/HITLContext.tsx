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
    (signal: Signal) =>
      execute({
        symbol:                signal.symbol,
        asset_class:           signal.asset_class,
        action:                signal.action,
        suggested_position_pct: signal.suggested_position_pct,
        stop_loss_pct:         signal.stop_loss_pct,
        take_profit_pct:       signal.take_profit_pct,
      }),
    [execute],
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
