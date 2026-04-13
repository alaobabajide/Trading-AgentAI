import { useState, useCallback } from "react";

export interface ExecuteParams {
  symbol: string;
  asset_class: string;
  action: string;
  suggested_position_pct: number;
  stop_loss_pct: number;
  take_profit_pct: number;
  qty?: number;  // if > 0, use fixed share count instead of notional sizing
}

export interface ExecuteResult {
  order_id: string;
  status: string;
  symbol: string;
  action: string;
  notional?: number;
  qty?: number;
  avg_price?: number;
  exchange: string;
  stop_pct: number;
  target_pct: number;
}

export function useExecute() {
  const [executing, setExecuting] = useState(false);
  const [error, setError]         = useState<string | null>(null);
  const [lastResult, setResult]   = useState<ExecuteResult | null>(null);

  const execute = useCallback(async (params: ExecuteParams): Promise<ExecuteResult | null> => {
    setExecuting(true);
    setError(null);
    try {
      const resp = await fetch("/api/execute", {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify(params),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) {
        throw new Error((data as { detail?: string }).detail ?? `HTTP ${resp.status}`);
      }
      const result = data as ExecuteResult;
      setResult(result);
      return result;
    } catch (e) {
      setError((e as Error).message);
      return null;
    } finally {
      setExecuting(false);
    }
  }, []);

  const clearError = useCallback(() => setError(null), []);

  return { execute, executing, error, lastResult, clearError };
}
