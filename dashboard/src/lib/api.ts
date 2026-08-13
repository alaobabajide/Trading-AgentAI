/**
 * API client — calls the brain FastAPI backend.
 * All calls go to /api/* which nginx proxies to uvicorn.
 * Falls back silently to mock data if the backend is unavailable.
 */
import { useEffect, useState } from "react";
import { EquityPoint, PortfolioSnapshot, Signal } from "./types";

const BASE = "/api";

// Read the API key injected by start.sh into /runtime-config.js at container startup.
// Falls back to empty string if not set (unauthenticated dev mode).
function _apiKey(): string {
  return (
    (window as unknown as { __TA_CONFIG__?: { apiKey?: string } }).__TA_CONFIG__
      ?.apiKey ?? ""
  );
}

export function apiHeaders(extra?: Record<string, string>): Record<string, string> {
  const key = _apiKey();
  return key ? { "X-Api-Key": key, ...extra } : { ...extra };
}

async function safeJson<T>(res: Response): Promise<T> {
  const text = await res.text();
  if (!text) throw new Error(`Empty response (HTTP ${res.status})`);
  return JSON.parse(text) as T;
}

// ── Raw fetchers ──────────────────────────────────────────────────────────────

export async function fetchHealth(): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/health`, {
    signal: AbortSignal.timeout(5000),
    headers: apiHeaders(),
  });
  return safeJson(res);
}

export interface ConfigStatus {
  // Key presence (boolean — values never exposed by backend)
  llm_provider:       boolean;
  llm_provider_name:  string;
  llm_provider_url:   string;
  llm_env_var:        string;
  alpaca:             boolean;
  binance:            boolean;
  telegram:           boolean;
  alpaca_base_url:    string;
  binance_testnet:    boolean;
  auto_trade:         boolean;
  ready_for_signals:  boolean;
  ready_for_trading:  boolean;
  // Engine metadata — use these instead of hardcoding in components
  agent_count:            number;
  hot_min_votes:          number;
  warm_min_votes:         number;
  cycle_interval_minutes: number;
  watchlist_stocks:       string[];
  watchlist_etfs:         string[];
  watchlist_crypto:       string[];
  total_symbols:          number;
}

export async function fetchConfigStatus(): Promise<ConfigStatus> {
  const res = await fetch(`${BASE}/config-status`, {
    signal: AbortSignal.timeout(5000),
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return safeJson(res);
}

/** Polls /api/config-status so the dashboard knows which services are wired up. */
export function useConfigStatus() {
  const [status, setStatus] = useState<ConfigStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function check() {
      try {
        const s = await fetchConfigStatus();
        if (!cancelled) setStatus(s);
      } catch { /* backend not up yet */ }
    }
    check();
    const id = setInterval(check, 30_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  return status;
}

export async function fetchPortfolio(): Promise<PortfolioSnapshot> {
  const res = await fetch(`${BASE}/portfolio`, {
    signal: AbortSignal.timeout(15000),
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return safeJson(res);
}

export async function fetchCachedSignals(): Promise<Signal[]> {
  const res = await fetch(`${BASE}/signals/cached`, {
    signal: AbortSignal.timeout(10000),
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return safeJson(res);
}

export async function clearCachedSignals(): Promise<void> {
  const res = await fetch(`${BASE}/signals/cached`, {
    method: "DELETE",
    signal: AbortSignal.timeout(8000),
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

// ── Signal persistence helpers ────────────────────────────────────────────────

const SIGNALS_STORAGE_KEY = "ta_signals_cache_v3";

// On startup, evict any signals left in the old key (e.g. error-contaminated batches)
try {
  localStorage.removeItem("ta_signals_cache_v2");
  localStorage.removeItem("ta_signals_cache_v1");
} catch { /* ignore */ }

/**
 * Returns true if a majority of the agent_views in this signal contain error text.
 * Such signals are produced when the LLM API is misconfigured (bad model ID, quota, etc.)
 * and should never be stored or shown to the user.
 */
function hasAgentErrors(signal: Signal): boolean {
  const views = signal.agent_views;
  if (!views) return false;
  const vals = (Object.values(views) as string[]).filter(Boolean);
  if (vals.length === 0) return false;
  const errCount = vals.filter((v) => v.includes("Agent error")).length;
  return errCount > vals.length / 2;
}

function loadStoredSignals(): Signal[] {
  try {
    const raw = localStorage.getItem(SIGNALS_STORAGE_KEY);
    if (!raw) return [];
    const all    = JSON.parse(raw) as Signal[];
    const clean  = all.filter((s) => !hasAgentErrors(s));
    // Self-heal: if any bad signals were removed, persist the cleaned list immediately
    if (clean.length !== all.length) {
      try { localStorage.setItem(SIGNALS_STORAGE_KEY, JSON.stringify(clean)); } catch { /* quota */ }
    }
    return clean;
  } catch {
    return [];
  }
}

function persistSignals(signals: Signal[]) {
  try { localStorage.setItem(SIGNALS_STORAGE_KEY, JSON.stringify(signals)); } catch { /* quota */ }
}

/**
 * Merge server signals into the local list.
 * - Same symbol → server entry replaces local (it's fresher; re-running brings it to top)
 * - New symbol  → appended
 * - Result sorted newest → oldest by generated_at
 * - Error signals (majority of agent_views contain "Agent error") are silently discarded
 */
function mergeSignals(local: Signal[], incoming: Signal[]): Signal[] {
  const bySymbol = new Map<string, Signal>(local.map((s) => [s.symbol, s]));
  for (const s of incoming) bySymbol.set(s.symbol, s);
  return [...bySymbol.values()]
    .filter((s) => !hasAgentErrors(s))
    .sort((a, b) => new Date(b.generated_at).getTime() - new Date(a.generated_at).getTime());
}

// ── React hooks ───────────────────────────────────────────────────────────────

type ApiState = "loading" | "live" | "mock" | "error";

/**
 * Loads portfolio from the real API. Returns null until the first successful
 * fetch, then polls every 30s.
 */
export function usePortfolio() {
  const [portfolio, setPortfolio] = useState<PortfolioSnapshot | null>(null);
  const [state, setState] = useState<ApiState>("loading");

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const data = await fetchPortfolio();
        if (!cancelled) { setPortfolio(data); setState("live"); }
      } catch {
        if (!cancelled) setState((s) => s === "loading" ? "mock" : "error");
      }
    }

    load();
    const id = setInterval(load, 30_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  return { portfolio, apiState: state };
}

/**
 * Loads cached signals from the real API, merges with locally-persisted list.
 *
 * Behaviour:
 * - Signals survive server restarts — stored in localStorage between sessions.
 * - Generating a signal for an existing symbol updates it in place and brings
 *   it to the top (newest generated_at sorts first).
 * - Generating a signal for a new symbol appends it without clearing others.
 * - Falls back to mock placeholder cards only when no real signals exist yet.
 * - clearAll() wipes both localStorage and the backend cache for a clean slate.
 */
export function useSignals(pollIntervalMs = 30_000) {
  // liveSignals: only real (non-mock) signals; seed from localStorage
  const [liveSignals, setLiveSignals] = useState<Signal[]>(() => loadStoredSignals());
  const [apiState, setApiState] = useState<ApiState>("loading");
  const [refreshing, setRefreshing] = useState(false);
  const [clearing, setClearing] = useState(false);

  const signals = liveSignals;

  function applyIncoming(data: Signal[]) {
    if (data.length === 0) return;
    setLiveSignals((prev) => {
      const merged = mergeSignals(prev, data);
      persistSignals(merged);
      return merged;
    });
  }

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const data = await fetchCachedSignals();
        if (!cancelled) {
          applyIncoming(data as Signal[]);
          setApiState("live");
        }
      } catch {
        if (!cancelled) setApiState((s) => s === "loading" ? "mock" : "error");
      }
    }

    poll();
    const id = setInterval(poll, pollIntervalMs);
    return () => { cancelled = true; clearInterval(id); };
  }, [pollIntervalMs]); // eslint-disable-line react-hooks/exhaustive-deps

  async function load(manual = false) {
    if (manual) setRefreshing(true);
    try {
      const data = await fetchCachedSignals();
      applyIncoming(data as Signal[]);
      setApiState("live");
    } catch {
      setApiState((s) => s === "loading" ? "mock" : "error");
    } finally {
      if (manual) setRefreshing(false);
    }
  }

  async function clearAll() {
    setClearing(true);
    try {
      await clearCachedSignals();
    } catch { /* backend clear failed — still wipe local */ }
    localStorage.removeItem(SIGNALS_STORAGE_KEY);
    setLiveSignals([]);
    setApiState("live");
    setClearing(false);
  }

  const refresh = () => load(true);

  return { signals, apiState, refresh, refreshing, clearAll, clearing };
}

/**
 * Fetches the real equity curve from Alpaca portfolio history.
 * Accepts a period ("1D" | "1M" | "1Y") and re-fetches whenever it changes.
 * Re-polls every 60 s so intraday moves stay current.
 */
export function useEquitySeries(period: "1D" | "1M" | "1Y" = "1D") {
  const [series, setSeries]   = useState<EquityPoint[]>([]);
  const [isLive, setIsLive]   = useState(false);

  useEffect(() => {
    let cancelled = false;
    setSeries([]);   // clear stale data while new period loads
    setIsLive(false);

    async function load() {
      try {
        const res = await fetch(`${BASE}/portfolio/history?period=${period}`, {
          signal: AbortSignal.timeout(15_000),
          headers: apiHeaders(),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await safeJson<EquityPoint[]>(res);
        if (!cancelled && data.length >= 2) {
          setSeries(data);
          setIsLive(true);
        }
      } catch {
        // leave whatever is already in state — mock stays as fallback
      }
    }

    load();
    const id = setInterval(load, 60_000);
    return () => { cancelled = true; clearInterval(id); };
  }, [period]);

  return { series, isLive };
}

// ── Dynamic risk config ───────────────────────────────────────────────────────

export interface RiskConfigFields {
  // Entry / exit
  stop_loss_pct:                  number;
  take_profit_pct:                number;
  trailing_stop_pct:              number;
  partial_exit_pct:               number;
  runner_trail_pct:               number;
  // Position sizing
  max_position_pct:               number;
  hot_position_pct:               number;
  max_crypto_allocation_pct:      number;
  // Portfolio exposure
  max_exposure_pct:               number;
  max_concurrent_positions:       number;
  // Circuit breaker / drawdown
  circuit_breaker_drawdown:       number;
  drawdown_scale_threshold:       number;
  drawdown_scale_factor:          number;
  // Correlation
  correlation_halving_threshold:  number;
  // Signal quality
  signal_confidence_threshold:    number;
  lookback_days:                  number;
  // ATR stop sizing
  atr_multiplier:                 number;
  atr_stop_floor:                 number;
  atr_stop_cap:                   number;
  // Loss cooldown
  loss_cooldown_hits:             number;
  loss_cooldown_window_days:      number;
  loss_cooldown_skip_cycles:      number;
  // Telegram
  max_telegram_order_usd:         number;
}

export interface RiskConfig extends RiskConfigFields {
  source:    "dynamic" | "env";
  overrides: Partial<RiskConfigFields>;
  defaults:  RiskConfigFields;
}

export async function fetchRiskConfig(): Promise<RiskConfig> {
  const res = await fetch(`${BASE}/config`, {
    signal: AbortSignal.timeout(5000),
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return safeJson(res);
}

export async function patchRiskConfig(updates: Partial<RiskConfigFields>): Promise<{ updated: object; current: object }> {
  const res = await fetch(`${BASE}/config`, {
    method:  "PATCH",
    headers: apiHeaders({ "Content-Type": "application/json" }),
    body:    JSON.stringify(updates),
    signal:  AbortSignal.timeout(8000),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error((data as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  return safeJson(res);
}

export async function resetRiskConfig(): Promise<{ reset: boolean; current: object }> {
  const res = await fetch(`${BASE}/config`, {
    method: "DELETE",
    signal: AbortSignal.timeout(5000),
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return safeJson(res);
}

export function useRiskConfig() {
  const [config, setConfig]   = useState<RiskConfig | null>(null);
  const [saving,  setSaving]  = useState(false);
  const [error,   setError]   = useState<string | null>(null);
  const [saved,   setSaved]   = useState(false);

  useEffect(() => {
    let cancelled = false;
    function load() {
      fetchRiskConfig()
        .then((c) => { if (!cancelled) setConfig(c); })
        .catch(() => { /* backend may not be up yet */ });
    }
    load();
    const id = setInterval(load, 60_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  async function save(updates: Partial<RiskConfigFields>) {
    setSaving(true);
    setError(null);
    try {
      await patchRiskConfig(updates);
      const fresh = await fetchRiskConfig();
      setConfig(fresh);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function reset() {
    setSaving(true);
    setError(null);
    try {
      await resetRiskConfig();
      const fresh = await fetchRiskConfig();
      setConfig(fresh);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return { config, saving, saved, error, save, reset };
}

export interface AlpacaOrder {
  order_id:         string;
  client_order_id:  string;
  symbol:           string;
  side:             string;
  order_type:       string;
  qty:              number;
  filled_qty:       number;
  status:           string;
  submitted_at:     string | null;
  filled_at:        string | null;
  limit_price:      number | null;
  stop_price:       number | null;
  filled_avg_price: number | null;
}

export interface OrdersResponse {
  orders:      AlpacaOrder[];
  fetch_error: string | null;
}

export function useOrders(statusFilter: "open" | "all" | "closed" = "open") {
  const [orders, setOrders]     = useState<AlpacaOrder[]>([]);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [loading, setLoading]   = useState(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await fetch(`${BASE}/orders?status=${statusFilter}`, {
          headers: apiHeaders(),
          signal: AbortSignal.timeout(12000),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await safeJson<OrdersResponse>(res);
        if (!cancelled) {
          setOrders(data.orders ?? []);
          setFetchError(data.fetch_error ?? null);
        }
      } catch (e) {
        if (!cancelled) setFetchError((e as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    const id = setInterval(load, 30_000);
    return () => { cancelled = true; clearInterval(id); };
  }, [statusFilter]);

  return { orders, fetchError, loading };
}

/**
 * Polls /api/health every 30s to drive the "Brain live" indicator.
 */
export function useBrainHealth() {
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function check() {
      try {
        await fetchHealth();
        if (!cancelled) setOnline(true);
      } catch {
        if (!cancelled) setOnline(false);
      }
    }

    check();
    const id = setInterval(check, 30_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  return online;
}
