/**
 * API client — calls the brain FastAPI backend.
 * All calls go to /api/* which nginx proxies to uvicorn.
 * Falls back silently to mock data if the backend is unavailable.
 */
import { useEffect, useState } from "react";
import { EquityPoint, PortfolioSnapshot, Signal } from "./types";

const BASE = "/api";

// ── Auth token management ─────────────────────────────────────────────────────
// AuthContext calls setActiveToken() + setActiveUserId() whenever the Supabase
// session changes. Browser requests use Bearer <jwt>; M2M falls back to X-Api-Key.
let _activeToken: string | null = null;
let _activeUserId: string | null = null;

export function setActiveToken(token: string | null): void {
  _activeToken = token;
}

export function getActiveUserId(): string | null {
  return _activeUserId;
}

// Fires whenever the active user changes so hooks can re-seed from localStorage
// and trigger a fresh server fetch — auth resolution is always async.
const _userChangeBus = new EventTarget();

export function setActiveUserId(userId: string | null): void {
  _activeUserId = userId;
  // Notify hooks to re-seed from localStorage and re-poll the server now that
  // the user ID is known. Auth resolution is always async so the initial mount
  // renders with _activeUserId === null and empty local state.
  _userChangeBus.dispatchEvent(new Event("userChanged"));
  // Also fire on window so modules outside api.ts (e.g. useHITL) can reload
  // their own per-user localStorage state without importing _userChangeBus.
  try { window.dispatchEvent(new Event("ta:userChanged")); } catch {}
}

function _apiKey(): string {
  return (
    (window as unknown as { __TA_CONFIG__?: { apiKey?: string } }).__TA_CONFIG__
      ?.apiKey ?? ""
  );
}

export function apiHeaders(extra?: Record<string, string>): Record<string, string> {
  if (_activeToken) {
    return { Authorization: `Bearer ${_activeToken}`, ...extra };
  }
  // Fallback: legacy X-Api-Key (dev mode / orchestrator)
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

const _SIGNALS_BASE_KEY = "ta_signals_cache_v3";

// Returns the user-namespaced localStorage key, or null when no user is logged in.
// Without a user_id we refuse to read/write so User B never sees User A's signals.
function _signalsKey(): string | null {
  return _activeUserId ? `${_SIGNALS_BASE_KEY}_${_activeUserId}` : null;
}

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
  const key = _signalsKey();
  if (!key) return [];  // no user logged in — return empty, never read another user's data
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return [];
    const all    = JSON.parse(raw) as Signal[];
    const clean  = all.filter((s) => !hasAgentErrors(s));
    if (clean.length !== all.length) {
      try { localStorage.setItem(key, JSON.stringify(clean)); } catch { /* quota */ }
    }
    return clean;
  } catch {
    return [];
  }
}

function persistSignals(signals: Signal[]) {
  const key = _signalsKey();
  if (!key) return;
  try { localStorage.setItem(key, JSON.stringify(signals)); } catch { /* quota */ }
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

  // Re-seed from localStorage and immediately re-poll the server whenever the
  // user ID becomes available. The initial mount always runs with _activeUserId
  // null (Supabase auth is async), so loadStoredSignals() returns [] on first
  // render. This effect catches the moment auth resolves and fills the gap.
  useEffect(() => {
    let cancelled = false;
    function onUserChanged() {
      const stored = loadStoredSignals();
      if (stored.length > 0) {
        setLiveSignals((prev) => mergeSignals(prev, stored));
      }
      fetchCachedSignals()
        .then((data) => { if (!cancelled) applyIncoming(data as Signal[]); })
        .catch(() => { /* regular poll will retry */ });
    }
    _userChangeBus.addEventListener("userChanged", onUserChanged);
    return () => { cancelled = true; _userChangeBus.removeEventListener("userChanged", onUserChanged); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

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
    const key = _signalsKey();
    if (key) localStorage.removeItem(key);
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

const _RISK_FIELD_KEYS = new Set([
  "stop_loss_pct","take_profit_pct","trailing_stop_pct","partial_exit_pct",
  "runner_trail_pct","max_position_pct","hot_position_pct",
  "max_crypto_allocation_pct","max_exposure_pct","max_concurrent_positions",
  "circuit_breaker_drawdown","drawdown_scale_threshold","drawdown_scale_factor",
  "correlation_halving_threshold","signal_confidence_threshold","lookback_days",
  "atr_multiplier","atr_stop_floor","atr_stop_cap",
  "loss_cooldown_hits","loss_cooldown_window_days","loss_cooldown_skip_cycles",
  "max_telegram_order_usd",
]);

export async function fetchRiskConfig(): Promise<RiskConfig> {
  const res = await fetch(`${BASE}/config`, {
    cache: "no-store",
    signal: AbortSignal.timeout(5000),
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return safeJson(res);
}

export async function patchRiskConfig(updates: Partial<RiskConfigFields>): Promise<{ updated: object; current: object }> {
  // Strip any non-RiskConfigField keys (source, overrides, defaults) before sending
  const clean: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(updates as Record<string, unknown>)) {
    if (_RISK_FIELD_KEYS.has(k) && v !== null && v !== undefined) clean[k] = v;
  }
  const res = await fetch(`${BASE}/config`, {
    method:  "PATCH",
    headers: apiHeaders({ "Content-Type": "application/json" }),
    body:    JSON.stringify(clean),
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

// ── Config persistence ────────────────────────────────────────────────────────
// User-saved overrides are stored in BOTH localStorage AND a cookie so that
// at least one survives browser privacy wipes, ITP, or extension interference.
// On every load() the saved values are merged on top of the backend response
// before display, so the UI is always correct regardless of backend state.
// The backend is re-synced in the background every 5 minutes so the trading
// engine picks up the user's values even after a Railway container restart.

const _CONFIG_BASE_KEY   = "ta_risk_config_v1";
const _CONFIG_COOKIE_BASE = "ta_rc_v1";
let _lastRestoreAttempt = 0; // epoch ms; 0 = never

// Per-user namespaced keys — returns null when no user is logged in so we
// never read one user's saved config into another user's session.
function _configStorageKey(): string | null {
  return _activeUserId ? `${_CONFIG_BASE_KEY}_${_activeUserId}` : null;
}
function _configCookieKey(): string | null {
  // Cookie names must be short — use first 12 chars of user ID (UUID, alphanumeric + hyphen)
  return _activeUserId ? `${_CONFIG_COOKIE_BASE}_${_activeUserId.slice(0, 12).replace(/-/g, "")}` : null;
}

function _saveConfigLocally(fields: Record<string, unknown>): void {
  const storageKey = _configStorageKey();
  const cookieKey  = _configCookieKey();
  if (!storageKey || !cookieKey) return; // no user — never persist to shared storage
  const clean: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(fields)) {
    if (_RISK_FIELD_KEYS.has(k) && v !== null && v !== undefined) clean[k] = v;
  }
  const json = Object.keys(clean).length > 0 ? JSON.stringify(clean) : "";
  try {
    json
      ? localStorage.setItem(storageKey, json)
      : localStorage.removeItem(storageKey);
  } catch { /* quota / blocked */ }
  try {
    const val = json ? encodeURIComponent(json) : "";
    document.cookie = `${cookieKey}=${val};max-age=${60 * 60 * 24 * 365};path=/;SameSite=Strict`;
  } catch { /* ignore */ }
}

function _loadConfigLocally(): Partial<RiskConfigFields> | null {
  const storageKey = _configStorageKey();
  const cookieKey  = _configCookieKey();
  if (!storageKey || !cookieKey) return null; // no user — never read stale data
  let raw: string | null = null;
  try { raw = localStorage.getItem(storageKey); } catch { /* ignore */ }
  if (!raw) {
    try {
      const m = document.cookie.match(new RegExp("(?:^|; )" + cookieKey + "=([^;]*)"));
      const v = m ? decodeURIComponent(m[1]) : "";
      raw = v || null;
    } catch { /* ignore */ }
  }
  if (!raw) return null;
  try { return JSON.parse(raw) as Partial<RiskConfigFields>; } catch { return null; }
}

// ── Shared event bus ──────────────────────────────────────────────────────────
const _configBus = new EventTarget();

// Hard-coded field defaults — used to build a synthetic RiskConfig from saved
// localStorage values before the first backend response arrives, so there is
// zero flash of incorrect defaults on page load.
const _FIELD_DEFAULTS: RiskConfigFields = {
  stop_loss_pct: 0.02, take_profit_pct: 0.05, trailing_stop_pct: 0.015,
  partial_exit_pct: 0.50, runner_trail_pct: 0.10,
  max_position_pct: 0.05, hot_position_pct: 0.08, max_crypto_allocation_pct: 0.30,
  max_exposure_pct: 0.50, max_concurrent_positions: 15,
  circuit_breaker_drawdown: 0.10, drawdown_scale_threshold: 0.08, drawdown_scale_factor: 0.80,
  correlation_halving_threshold: 0.70, signal_confidence_threshold: 0.70, lookback_days: 300,
  atr_multiplier: 1.5, atr_stop_floor: 0.005, atr_stop_cap: 0.04,
  loss_cooldown_hits: 2, loss_cooldown_window_days: 5, loss_cooldown_skip_cycles: 2,
  max_telegram_order_usd: 1000,
};

function _mergeWithSaved(base: RiskConfig): RiskConfig {
  const saved = _loadConfigLocally();
  if (!saved || Object.keys(saved).length === 0) return base;
  return { ...base, ...(saved as Partial<RiskConfig>), source: "dynamic" };
}

export function useRiskConfig() {
  // Initialise synchronously from localStorage so saved values show instantly
  // on every page load — no async fetch needed before the correct value appears.
  const [config, setConfig] = useState<RiskConfig | null>(() => {
    const saved = _loadConfigLocally();
    if (!saved || Object.keys(saved).length === 0) return null;
    return {
      ..._FIELD_DEFAULTS,
      ...(saved as Partial<RiskConfigFields>),
      source: "dynamic",
      overrides: saved as Partial<RiskConfigFields>,
      defaults:  _FIELD_DEFAULTS,
    };
  });
  const [saving,  setSaving]  = useState(false);
  const [error,   setError]   = useState<string | null>(null);
  const [saved,   setSaved]   = useState(false);

  useEffect(() => {
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;

    function load() {
      fetchRiskConfig()
        .then((c) => {
          if (cancelled) return;
          // Always merge saved localStorage values on top of the backend response.
          setConfig(_mergeWithSaved(c));

          // Re-sync backend every 5 minutes after a Railway container restart.
          const saved = _loadConfigLocally();
          const now = Date.now();
          if (saved && Object.keys(saved).length > 0
              && now - _lastRestoreAttempt > 5 * 60 * 1000) {
            _lastRestoreAttempt = now;
            patchRiskConfig(saved).catch(() => { /* will retry next cycle */ });
          }
        })
        .catch(() => {
          if (!cancelled && !retryTimer) {
            retryTimer = setTimeout(() => { retryTimer = null; if (!cancelled) load(); }, 5000);
          }
        });
    }

    const onUpdate = () => { if (!cancelled) load(); };
    _configBus.addEventListener("updated", onUpdate);
    load();
    const id = setInterval(load, 60_000);
    return () => {
      cancelled = true;
      clearInterval(id);
      if (retryTimer) clearTimeout(retryTimer);
      _configBus.removeEventListener("updated", onUpdate);
    };
  }, []);

  async function save(updates: Partial<RiskConfigFields>) {
    setSaving(true);
    setError(null);

    // 1. Write to localStorage/cookie immediately — independent of backend.
    //    This guarantees the display persists after refresh even if the network
    //    call fails (auth error, Railway cold start, timeout, etc.).
    const existing = _loadConfigLocally() ?? {};
    _saveConfigLocally({ ...existing, ...(updates as Record<string, unknown>) });

    // 2. Update display immediately from the now-saved local values.
    const base: RiskConfig = config ?? {
      ..._FIELD_DEFAULTS, source: "env", overrides: {}, defaults: _FIELD_DEFAULTS,
    };
    setConfig(_mergeWithSaved(base));

    try {
      // 3. Sync to backend so the trading engine picks up the new values.
      await patchRiskConfig(updates);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
      _configBus.dispatchEvent(new Event("updated"));
    } catch (e) {
      // Backend sync failed — localStorage already has the value, so the UI
      // will be correct after refresh. The background re-sync in load() will
      // retry the PATCH on the next polling cycle.
      setError(`Saved locally — backend sync failed: ${(e as Error).message}`);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } finally {
      setSaving(false);
    }
  }

  async function reset() {
    setSaving(true);
    setError(null);
    try {
      await resetRiskConfig();
      _saveConfigLocally({}); // clear saved overrides — user explicitly reset
      const fresh = await fetchRiskConfig();
      setConfig(fresh);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
      _configBus.dispatchEvent(new Event("updated"));
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

// ── Persistent order history (audit store) ────────────────────────────────────

export interface StoredOrder {
  order_id:          string;
  symbol:            string;
  side:              string;
  order_type:        string;
  qty:               number;
  filled_qty:        number;
  status:            string;
  submitted_at:      string | null;
  filled_at:         string | null;
  broker:            string;
  stop_price:        number | null;
  take_profit_price: number | null;
  filled_avg_price:  number | null;
  notional:          number | null;
  source:            string;
  user_id:           string;
}

export async function fetchOrderHistory(days = 365): Promise<StoredOrder[]> {
  const res = await fetch(`${BASE}/orders/history?days=${days}`, {
    headers: apiHeaders(),
    signal: AbortSignal.timeout(15000),
  });
  if (!res.ok) throw new Error(`Order history fetch failed (${res.status})`);
  const data = await safeJson<{ orders: StoredOrder[] }>(res);
  return data.orders ?? [];
}

export async function exportOrderHistory(format: "csv" | "pdf", days = 365): Promise<void> {
  const res = await fetch(`${BASE}/orders/history/export?format=${format}&days=${days}`, {
    headers: apiHeaders(),
    signal: AbortSignal.timeout(30000),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Export failed" }));
    throw new Error((err as { detail?: string }).detail ?? "Export failed");
  }
  const blob = await res.blob();
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement("a");
  a.href     = url;
  a.download = `order_history_${days}d.${format}`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function useOrderHistory(days = 365) {
  const [orders,  setOrders]  = useState<StoredOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchOrderHistory(days)
      .then((o) => { if (!cancelled) { setOrders(o); setLoading(false); } })
      .catch((e) => { if (!cancelled) { setError((e as Error).message); setLoading(false); } });
    return () => { cancelled = true; };
  }, [days]);

  return { orders, loading, error };
}

// ── Archive (per-year ZIP download) ──────────────────────────────────────────

export async function fetchArchiveYears(): Promise<number[]> {
  const res = await fetch(`${BASE}/orders/history/years`, {
    headers: apiHeaders(),
    signal: AbortSignal.timeout(10000),
  });
  if (!res.ok) throw new Error(`Archive years: ${res.status}`);
  const data = await safeJson<{ years: number[] }>(res);
  return data?.years ?? [];
}

export async function downloadArchiveZip(year: number): Promise<void> {
  const res = await fetch(`${BASE}/orders/archive/${year}`, {
    headers: apiHeaders(),
    signal: AbortSignal.timeout(60000),
  });
  if (!res.ok) throw new Error(`Archive ${year}: ${res.status}`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `orders_archive_${year}.zip`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function useArchiveYears() {
  const [years,   setYears]   = useState<number[]>([]);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchArchiveYears()
      .then((y) => { if (!cancelled) { setYears(y); setLoading(false); } })
      .catch((e) => { if (!cancelled) { setError((e as Error).message); setLoading(false); } });
    return () => { cancelled = true; };
  }, []);

  return { years, loading, error };
}

// ── API usage & credit tracking ───────────────────────────────────────────────

export interface ModelUsage {
  input_tokens:  number;
  output_tokens: number;
  cost_usd:      number;
  calls:         number;
}

export interface DailyUsage {
  date:          string;
  input_tokens:  number;
  output_tokens: number;
  cost_usd:      number;
  calls:         number;
  by_model:      Record<string, ModelUsage>;
}

export interface ApiUsageResponse {
  today:   DailyUsage;
  history: DailyUsage[];
}

export interface CreditStatus {
  provider:            string;
  configured:          boolean;
  balance_usd:         number | null;
  used_usd:            number | null;
  limit_usd:           number | null;
  warning:             boolean;
  warning_threshold:   number;
  critical_threshold:  number;
  error:               string | null;
}

export function useCreditStatus() {
  const [status, setStatus] = useState<CreditStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function check() {
      try {
        const res = await fetch(`${BASE}/credits`, {
          headers: apiHeaders(),
          signal: AbortSignal.timeout(12000),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await safeJson<CreditStatus>(res);
        if (!cancelled) setStatus(data);
      } catch { /* backend not up yet */ }
    }
    check();
    const id = setInterval(check, 5 * 60_000); // every 5 minutes
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  return status;
}

export function useApiUsage() {
  const [usage, setUsage] = useState<ApiUsageResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await fetch(`${BASE}/usage`, {
          headers: apiHeaders(),
          signal: AbortSignal.timeout(8000),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await safeJson<ApiUsageResponse>(res);
        if (!cancelled) setUsage(data);
      } catch { /* backend not up yet */ }
    }
    load();
    const id = setInterval(load, 60_000); // every 60s
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  return usage;
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

// ── LLM provider / model settings ────────────────────────────────────────────

export interface LlmSettings {
  tactical_provider:  string;
  tactical_model:     string;
  synthesis_provider: string;
  synthesis_model:    string;
  keys_configured:    string[];  // provider names — never the key values
}

export interface LlmSavePayload {
  tactical_provider:  string;
  tactical_model:     string;
  synthesis_provider: string;
  synthesis_model:    string;
  // API keys — only include when user is explicitly setting/updating a key.
  // Empty string or omitted = "don't change the stored key."
  openrouter_key?: string;
  anthropic_key?:  string;
  openai_key?:     string;
  deepseek_key?:   string;
  xai_key?:        string;
  qwen_key?:       string;
  kimi_key?:       string;
}

export interface ModelsResponse {
  providers:        Record<string, string>;
  models:           Record<string, string[]>;
  confidence_notes: Record<string, string>;
}

export async function fetchLlmSettings(): Promise<LlmSettings> {
  const res = await fetch(`${BASE}/llm-settings`, {
    signal: AbortSignal.timeout(8000),
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return safeJson(res);
}

export async function saveLlmSettings(payload: LlmSavePayload): Promise<{ saved: boolean; keys_configured: string[] }> {
  const res = await fetch(`${BASE}/llm-settings`, {
    method:  "POST",
    headers: apiHeaders({ "Content-Type": "application/json" }),
    body:    JSON.stringify(payload),
    signal:  AbortSignal.timeout(10000),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error((data as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  return safeJson(res);
}

export async function fetchModels(): Promise<ModelsResponse> {
  const res = await fetch(`${BASE}/models`, {
    signal: AbortSignal.timeout(5000),
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return safeJson(res);
}

const _DEFAULT_LLM: LlmSettings = {
  tactical_provider:  "openrouter",
  tactical_model:     "google/gemini-2.5-flash-lite",
  synthesis_provider: "openrouter",
  synthesis_model:    "deepseek/deepseek-chat-v3-0324",
  keys_configured:    [],
};

// ── Alpaca credential settings ────────────────────────────────────────────────

export interface AlpacaSettings {
  paper_mode:      boolean;
  keys_configured: boolean;
}

export interface AlpacaSavePayload {
  paper_mode:   boolean;
  api_key?:     string;  // plaintext; empty or omitted = "don't change stored key"
  secret_key?:  string;  // plaintext; empty or omitted = "don't change stored key"
}

export async function fetchAlpacaSettings(): Promise<AlpacaSettings> {
  const res = await fetch(`${BASE}/alpaca-settings`, {
    signal: AbortSignal.timeout(8000),
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return safeJson(res);
}

export async function saveAlpacaSettings(
  payload: AlpacaSavePayload,
): Promise<{ saved: boolean; keys_configured: boolean }> {
  const res = await fetch(`${BASE}/alpaca-settings`, {
    method:  "POST",
    headers: apiHeaders({ "Content-Type": "application/json" }),
    body:    JSON.stringify(payload),
    signal:  AbortSignal.timeout(10000),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error((data as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  return safeJson(res);
}

export function useAlpacaSettings() {
  const [settings, setSettings] = useState<AlpacaSettings | null>(null);
  const [saving,   setSaving]   = useState(false);
  const [saved,    setSaved]    = useState(false);
  const [error,    setError]    = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const s = await fetchAlpacaSettings();
        if (!cancelled) setSettings(s);
      } catch { /* not authenticated or backend not up */ }
    }
    load();
  }, []);

  async function save(payload: AlpacaSavePayload) {
    setSaving(true);
    setError(null);
    try {
      const result = await saveAlpacaSettings(payload);
      setSettings((prev) => prev
        ? { ...prev, paper_mode: payload.paper_mode, keys_configured: result.keys_configured }
        : { paper_mode: payload.paper_mode, keys_configured: result.keys_configured }
      );
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return { settings, saving, saved, error, save };
}

// ── Broker settings ────────────────────────────────────────────────────────────

export interface BrokerInfo {
  id:              string;
  name:            string;
  tagline:         string;
  supports_paper:  boolean;
  status:          "live" | "coming_soon";
}

export interface BrokerSettings {
  current_broker:    string;
  available_brokers: BrokerInfo[];
}

export async function fetchBrokerSettings(): Promise<BrokerSettings> {
  const res = await fetch(`${BASE}/broker-settings`, {
    signal:  AbortSignal.timeout(8000),
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return safeJson(res);
}

export async function saveBrokerSettings(
  brokerType: string,
): Promise<{ saved: boolean; broker_type: string }> {
  const res = await fetch(`${BASE}/broker-settings`, {
    method:  "POST",
    headers: apiHeaders({ "Content-Type": "application/json" }),
    body:    JSON.stringify({ broker_type: brokerType }),
    signal:  AbortSignal.timeout(10000),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error((data as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  return safeJson(res);
}

export async function resetBrokerSettings(): Promise<{ reset: boolean; broker_type: string }> {
  const res = await fetch(`${BASE}/broker-settings`, {
    method:  "DELETE",
    headers: apiHeaders(),
    signal:  AbortSignal.timeout(8000),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return safeJson(res);
}

export function useBrokerSettings() {
  const [settings,  setSettings]  = useState<BrokerSettings | null>(null);
  const [saving,    setSaving]    = useState(false);
  const [saved,     setSaved]     = useState(false);
  const [error,     setError]     = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const s = await fetchBrokerSettings();
        if (!cancelled) setSettings(s);
      } catch { /* not authenticated or backend not up */ }
    }
    load();
  }, []);

  async function selectBroker(brokerType: string) {
    setSaving(true);
    setError(null);
    try {
      await saveBrokerSettings(brokerType);
      setSettings((prev) => prev ? { ...prev, current_broker: brokerType } : null);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function resetBroker() {
    setSaving(true);
    setError(null);
    try {
      const result = await resetBrokerSettings();
      setSettings((prev) => prev ? { ...prev, current_broker: result.broker_type } : null);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return { settings, saving, saved, error, selectBroker, resetBroker };
}

// ── Polygon.io market data settings ──────────────────────────────────────────

export interface PolygonSettings {
  user_key_configured:   boolean;
  system_key_configured: boolean;
  effective_source:      "user" | "system" | "none";
}

export async function fetchPolygonSettings(): Promise<PolygonSettings> {
  const res = await fetch(`${BASE}/polygon-settings`, {
    signal:  AbortSignal.timeout(8000),
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return safeJson(res);
}

export async function savePolygonKey(
  apiKey: string,
): Promise<{ saved: boolean }> {
  const res = await fetch(`${BASE}/polygon-settings`, {
    method:  "POST",
    headers: apiHeaders({ "Content-Type": "application/json" }),
    body:    JSON.stringify({ api_key: apiKey }),
    signal:  AbortSignal.timeout(10000),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error((data as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  return safeJson(res);
}

export async function deletePolygonKey(): Promise<{ deleted: boolean }> {
  const res = await fetch(`${BASE}/polygon-settings`, {
    method:  "DELETE",
    headers: apiHeaders(),
    signal:  AbortSignal.timeout(8000),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return safeJson(res);
}

export function usePolygonSettings() {
  const [settings, setSettings] = useState<PolygonSettings | null>(null);
  const [saving,   setSaving]   = useState(false);
  const [saved,    setSaved]    = useState(false);
  const [error,    setError]    = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const s = await fetchPolygonSettings();
        if (!cancelled) setSettings(s);
      } catch { /* not authenticated or backend not up */ }
    }
    load();
  }, []);

  async function saveKey(apiKey: string) {
    setSaving(true);
    setError(null);
    try {
      await savePolygonKey(apiKey);
      setSettings((prev) => prev ? { ...prev, user_key_configured: true, effective_source: "user" } : null);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function removeKey() {
    setSaving(true);
    setError(null);
    try {
      await deletePolygonKey();
      setSettings((prev) => prev
        ? { ...prev, user_key_configured: false, effective_source: prev.system_key_configured ? "system" : "none" }
        : null
      );
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return { settings, saving, saved, error, saveKey, removeKey };
}

// ── tastytrade settings ────────────────────────────────────────────────────────

export interface TastytradeSettings {
  username:        string;
  account_number:  string;
  paper_mode:      boolean;
  keys_configured: boolean;
}

export interface TastytradeSavePayload {
  username?:       string;
  password?:       string;   // plaintext; omit = "don't change stored password"
  account_number?: string;   // optional
  paper_mode:      boolean;
}

export async function fetchTastytradeSettings(): Promise<TastytradeSettings> {
  const res = await fetch(`${BASE}/tastytrade-settings`, {
    signal:  AbortSignal.timeout(8000),
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return safeJson(res);
}

export async function saveTastytradeSettings(
  payload: TastytradeSavePayload,
): Promise<{ saved: boolean; keys_configured: boolean }> {
  const res = await fetch(`${BASE}/tastytrade-settings`, {
    method:  "POST",
    headers: apiHeaders({ "Content-Type": "application/json" }),
    body:    JSON.stringify(payload),
    signal:  AbortSignal.timeout(10000),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error((data as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  return safeJson(res);
}

export function useTastytradeSettings() {
  const [settings, setSettings] = useState<TastytradeSettings | null>(null);
  const [saving,   setSaving]   = useState(false);
  const [saved,    setSaved]    = useState(false);
  const [error,    setError]    = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const s = await fetchTastytradeSettings();
        if (!cancelled) setSettings(s);
      } catch { /* not authenticated or backend not up */ }
    }
    load();
  }, []);

  async function save(payload: TastytradeSavePayload) {
    setSaving(true);
    setError(null);
    try {
      const result = await saveTastytradeSettings(payload);
      setSettings((prev) => prev
        ? {
            ...prev,
            paper_mode:      payload.paper_mode,
            username:        payload.username ?? prev.username,
            account_number:  payload.account_number ?? prev.account_number,
            keys_configured: result.keys_configured,
          }
        : null
      );
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return { settings, saving, saved, error, save };
}

// ── Charles Schwab settings ────────────────────────────────────────────────────

export interface SchwabSettings {
  connected:       boolean;
  access_expired:  boolean;
  refresh_expired: boolean;
  account_hash:    string;
}

export async function fetchSchwabSettings(): Promise<SchwabSettings> {
  const res = await fetch(`${BASE}/schwab-settings`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(`Schwab settings fetch failed (${res.status})`);
  return safeJson<SchwabSettings>(res);
}

export async function fetchSchwabAuthUrl(): Promise<{ url: string }> {
  const res = await fetch(`${BASE}/schwab-auth/url`, {
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(`Could not generate Schwab auth URL (${res.status})`);
  return safeJson<{ url: string }>(res);
}

export async function disconnectSchwab(): Promise<{ disconnected: boolean; had_tokens: boolean }> {
  const res = await fetch(`${BASE}/schwab-settings`, {
    method: "DELETE",
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(`Schwab disconnect failed (${res.status})`);
  return safeJson(res);
}

export function useSchwabSettings() {
  const [settings,      setSettings]      = useState<SchwabSettings | null>(null);
  const [loading,       setLoading]       = useState(false);
  const [connecting,    setConnecting]    = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const [error,         setError]         = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    fetchSchwabSettings()
      .then((s) => { if (active) setSettings(s); })
      .catch((e) => { if (active) setError((e as Error).message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  async function connect() {
    setConnecting(true);
    setError(null);
    try {
      const { url } = await fetchSchwabAuthUrl();
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setConnecting(false);
    }
  }

  async function disconnect() {
    setDisconnecting(true);
    setError(null);
    try {
      await disconnectSchwab();
      setSettings({ connected: false, access_expired: false, refresh_expired: false, account_hash: "" });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setDisconnecting(false);
    }
  }

  async function refresh() {
    setLoading(true);
    setError(null);
    try {
      const s = await fetchSchwabSettings();
      setSettings(s);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return { settings, loading, connecting, disconnecting, error, connect, disconnect, refresh };
}

// ── Interactive Brokers settings ───────────────────────────────────────────────

export interface IBKRSettings {
  host:       string;
  port:       number;
  client_id:  number;
  account_id: string;
  paper_mode: boolean;
  configured: boolean;
}

export type IBKRSavePayload = Omit<IBKRSettings, "configured">;

export async function fetchIBKRSettings(): Promise<IBKRSettings> {
  const res = await fetch(`${BASE}/ibkr-settings`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(`IBKR settings fetch failed (${res.status})`);
  return safeJson<IBKRSettings>(res);
}

export async function saveIBKRSettings(payload: IBKRSavePayload): Promise<{ saved: boolean }> {
  const res = await fetch(`${BASE}/ibkr-settings`, {
    method:  "POST",
    headers: { ...apiHeaders(), "Content-Type": "application/json" },
    body:    JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Save failed" }));
    throw new Error(err.detail ?? "Save failed");
  }
  return safeJson(res);
}

export async function deleteIBKRSettings(): Promise<{ deleted: boolean }> {
  const res = await fetch(`${BASE}/ibkr-settings`, {
    method: "DELETE", headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(`IBKR settings delete failed (${res.status})`);
  return safeJson(res);
}

export function useIBKRSettings() {
  const defaults: IBKRSavePayload = { host: "127.0.0.1", port: 4002, client_id: 1, account_id: "", paper_mode: true };
  const [settings, setSettings] = useState<IBKRSettings | null>(null);
  const [draft,    setDraft]    = useState<IBKRSavePayload>(defaults);
  const [saving,   setSaving]   = useState(false);
  const [saved,    setSaved]    = useState(false);
  const [dirty,    setDirty]    = useState(false);
  const [error,    setError]    = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetchIBKRSettings()
      .then((s) => {
        if (!active) return;
        setSettings(s);
        setDraft({ host: s.host, port: s.port, client_id: s.client_id, account_id: s.account_id, paper_mode: s.paper_mode });
      })
      .catch((e) => { if (active) setError((e as Error).message); });
    return () => { active = false; };
  }, []);

  function update<K extends keyof IBKRSavePayload>(key: K, value: IBKRSavePayload[K]) {
    setDraft((d) => ({ ...d, [key]: value }));
    setDirty(true);
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      await saveIBKRSettings(draft);
      setSettings((prev) => prev ? { ...prev, ...draft, configured: true } : { ...draft, configured: true });
      setSaved(true);
      setDirty(false);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    setSaving(true);
    setError(null);
    try {
      await deleteIBKRSettings();
      setSettings((prev) => prev ? { ...prev, configured: false } : null);
      setDraft(defaults);
      setDirty(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return { settings, draft, saving, saved, dirty, error, update, save, remove };
}

// ── Kraken ────────────────────────────────────────────────────────────────────

export interface KrakenSettings {
  configured:  boolean;
  key_prefix:  string;
}

export async function fetchKrakenSettings(): Promise<KrakenSettings> {
  const res = await fetch(`${BASE}/kraken-settings`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(`Kraken settings: ${res.status}`);
  return safeJson<KrakenSettings>(res);
}

export async function saveKrakenSettings(api_key: string, api_secret: string): Promise<void> {
  const res = await fetch(`${BASE}/kraken-settings`, {
    method: "POST", headers: apiHeaders(),
    body: JSON.stringify({ api_key, api_secret }),
  });
  if (!res.ok) throw new Error(`Save failed: ${res.status}`);
}

export async function deleteKrakenSettings(): Promise<void> {
  const res = await fetch(`${BASE}/kraken-settings`, { method: "DELETE", headers: apiHeaders() });
  if (!res.ok) throw new Error(`Delete failed: ${res.status}`);
}

export function useKrakenSettings() {
  const [settings, setSettings] = useState<KrakenSettings | null>(null);
  const [apiKey,   setApiKey]   = useState("");
  const [apiSecret,setApiSecret]= useState("");
  const [saving,   setSaving]   = useState(false);
  const [saved,    setSaved]    = useState(false);
  const [error,    setError]    = useState<string | null>(null);

  useEffect(() => {
    fetchKrakenSettings().then(setSettings).catch((e) => setError((e as Error).message));
  }, []);

  async function save() {
    setSaving(true); setSaved(false); setError(null);
    try {
      await saveKrakenSettings(apiKey, apiSecret);
      const s = await fetchKrakenSettings();
      setSettings(s); setSaved(true);
      setApiKey(""); setApiSecret("");
    } catch (e) { setError((e as Error).message); }
    finally { setSaving(false); }
  }

  async function remove() {
    setSaving(true); setError(null);
    try {
      await deleteKrakenSettings();
      setSettings({ configured: false, key_prefix: "" });
    } catch (e) { setError((e as Error).message); }
    finally { setSaving(false); }
  }

  return { settings, apiKey, setApiKey, apiSecret, setApiSecret, saving, saved, error, save, remove };
}

// ── Coinbase Advanced Trade ───────────────────────────────────────────────────

export interface CoinbaseSettings {
  configured:   boolean;
  api_key_name: string;
}

export async function fetchCoinbaseSettings(): Promise<CoinbaseSettings> {
  const res = await fetch(`${BASE}/coinbase-settings`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(`Coinbase settings: ${res.status}`);
  return safeJson<CoinbaseSettings>(res);
}

export async function saveCoinbaseSettings(api_key_name: string, private_key: string): Promise<void> {
  const res = await fetch(`${BASE}/coinbase-settings`, {
    method: "POST", headers: apiHeaders(),
    body: JSON.stringify({ api_key_name, private_key }),
  });
  if (!res.ok) throw new Error(`Save failed: ${res.status}`);
}

export async function deleteCoinbaseSettings(): Promise<void> {
  const res = await fetch(`${BASE}/coinbase-settings`, { method: "DELETE", headers: apiHeaders() });
  if (!res.ok) throw new Error(`Delete failed: ${res.status}`);
}

export function useCoinbaseSettings() {
  const [settings,   setSettings]   = useState<CoinbaseSettings | null>(null);
  const [keyName,    setKeyName]    = useState("");
  const [privateKey, setPrivateKey] = useState("");
  const [saving,     setSaving]     = useState(false);
  const [saved,      setSaved]      = useState(false);
  const [error,      setError]      = useState<string | null>(null);

  useEffect(() => {
    fetchCoinbaseSettings().then(setSettings).catch((e) => setError((e as Error).message));
  }, []);

  async function save() {
    setSaving(true); setSaved(false); setError(null);
    try {
      await saveCoinbaseSettings(keyName, privateKey);
      const s = await fetchCoinbaseSettings();
      setSettings(s); setSaved(true);
      setKeyName(""); setPrivateKey("");
    } catch (e) { setError((e as Error).message); }
    finally { setSaving(false); }
  }

  async function remove() {
    setSaving(true); setError(null);
    try {
      await deleteCoinbaseSettings();
      setSettings({ configured: false, api_key_name: "" });
    } catch (e) { setError((e as Error).message); }
    finally { setSaving(false); }
  }

  return { settings, keyName, setKeyName, privateKey, setPrivateKey, saving, saved, error, save, remove };
}

// ── TradeStation ──────────────────────────────────────────────────────────────

export interface TradeStationSettings {
  connected:      boolean;
  account_number: string;
  paper_mode:     boolean;
  access_expires?: number;
}

export async function fetchTradeStationSettings(): Promise<TradeStationSettings> {
  const res = await fetch(`${BASE}/tradestation-settings`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(`TradeStation settings: ${res.status}`);
  return safeJson<TradeStationSettings>(res);
}

export async function fetchTradeStationAuthUrl(): Promise<string> {
  const res = await fetch(`${BASE}/tradestation-auth/url`, { headers: apiHeaders() });
  if (!res.ok) throw new Error(`Auth URL: ${res.status}`);
  const data = await safeJson<{ url: string }>(res);
  return data.url;
}

export async function setTradeStationAccount(account_number: string): Promise<void> {
  const res = await fetch(`${BASE}/tradestation-settings/account`, {
    method: "POST", headers: apiHeaders(),
    body: JSON.stringify({ account_number }),
  });
  if (!res.ok) throw new Error(`Account save failed: ${res.status}`);
}

export async function deleteTradeStationSettings(): Promise<void> {
  const res = await fetch(`${BASE}/tradestation-settings`, { method: "DELETE", headers: apiHeaders() });
  if (!res.ok) throw new Error(`Delete failed: ${res.status}`);
}

export function useTradeStationSettings() {
  const [settings,       setSettings]       = useState<TradeStationSettings | null>(null);
  const [accountDraft,   setAccountDraft]   = useState("");
  const [saving,         setSaving]         = useState(false);
  const [saved,          setSaved]          = useState(false);
  const [error,          setError]          = useState<string | null>(null);

  useEffect(() => {
    fetchTradeStationSettings()
      .then((s) => { setSettings(s); setAccountDraft(s.account_number ?? ""); })
      .catch((e) => setError((e as Error).message));
  }, []);

  async function connect() {
    try {
      const url = await fetchTradeStationAuthUrl();
      window.location.href = url;
    } catch (e) { setError((e as Error).message); }
  }

  async function saveAccount() {
    setSaving(true); setSaved(false); setError(null);
    try {
      await setTradeStationAccount(accountDraft);
      const s = await fetchTradeStationSettings();
      setSettings(s); setSaved(true);
    } catch (e) { setError((e as Error).message); }
    finally { setSaving(false); }
  }

  async function disconnect() {
    setSaving(true); setError(null);
    try {
      await deleteTradeStationSettings();
      setSettings({ connected: false, account_number: "", paper_mode: false });
      setAccountDraft("");
    } catch (e) { setError((e as Error).message); }
    finally { setSaving(false); }
  }

  return { settings, accountDraft, setAccountDraft, saving, saved, error, connect, saveAccount, disconnect };
}

export function useLlmSettings() {
  const [settings,  setSettings]  = useState<LlmSettings | null>(null);
  const [models,    setModels]    = useState<ModelsResponse | null>(null);
  const [saving,    setSaving]    = useState(false);
  const [saved,     setSaved]     = useState(false);
  const [error,     setError]     = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const [s, m] = await Promise.all([fetchLlmSettings(), fetchModels()]);
        if (!cancelled) { setSettings(s); setModels(m); }
      } catch { /* not authenticated or backend not up */ }
    }
    load();
  }, []);

  async function save(payload: LlmSavePayload) {
    setSaving(true);
    setError(null);
    try {
      const result = await saveLlmSettings(payload);
      setSettings((prev) => prev
        ? { ...prev, ...payload, keys_configured: result.keys_configured }
        : { ..._DEFAULT_LLM, ...payload, keys_configured: result.keys_configured }
      );
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return { settings, models, saving, saved, error, save };
}

// ── TradingView webhook settings ──────────────────────────────────────────────

export interface WebhookSettings {
  configured:   boolean;
  user_id:      string;
  webhook_path: string | null;
}

export interface WebhookGenerated {
  generated:    boolean;
  secret:       string;
  webhook_path: string;
  warning:      string;
}

export async function fetchWebhookSettings(): Promise<WebhookSettings> {
  const res = await fetch(`${BASE}/webhook-settings`, {
    signal:  AbortSignal.timeout(8000),
    headers: apiHeaders(),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return safeJson(res);
}

export async function generateWebhookSecret(): Promise<WebhookGenerated> {
  const res = await fetch(`${BASE}/webhook-settings`, {
    method:  "POST",
    headers: apiHeaders(),
    signal:  AbortSignal.timeout(10000),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error((data as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  return safeJson(res);
}

export async function revokeWebhookSecret(): Promise<{ revoked: boolean }> {
  const res = await fetch(`${BASE}/webhook-settings`, {
    method:  "DELETE",
    headers: apiHeaders(),
    signal:  AbortSignal.timeout(10000),
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error((data as { detail?: string }).detail ?? `HTTP ${res.status}`);
  }
  return safeJson(res);
}

export function useWebhookSettings() {
  const [settings,   setSettings]   = useState<WebhookSettings | null>(null);
  const [generating, setGenerating] = useState(false);
  const [revoking,   setRevoking]   = useState(false);
  const [revealed,   setRevealed]   = useState<WebhookGenerated | null>(null);
  const [error,      setError]      = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const s = await fetchWebhookSettings();
        if (!cancelled) setSettings(s);
      } catch { /* not authenticated or backend not up */ }
    }
    load();
  }, []);

  async function generate() {
    setGenerating(true);
    setError(null);
    setRevealed(null);
    try {
      const result = await generateWebhookSecret();
      setRevealed(result);
      setSettings((prev) => prev ? { ...prev, configured: true } : null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setGenerating(false);
    }
  }

  async function revoke() {
    setRevoking(true);
    setError(null);
    setRevealed(null);
    try {
      await revokeWebhookSecret();
      setSettings((prev) => prev ? { ...prev, configured: false, webhook_path: null } : null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRevoking(false);
    }
  }

  function dismiss() { setRevealed(null); }

  return { settings, generating, revoking, revealed, error, generate, revoke, dismiss };
}
