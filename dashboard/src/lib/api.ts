/**
 * API client — calls the brain FastAPI backend.
 * All calls go to /api/* which nginx proxies to uvicorn.
 * Falls back silently to mock data if the backend is unavailable.
 */
import { useEffect, useState } from "react";
import { EquityPoint, PortfolioSnapshot, Signal } from "./types";
import { mockPortfolio, mockSignals } from "./mock";

const BASE = "/api";

async function safeJson<T>(res: Response): Promise<T> {
  const text = await res.text();
  if (!text) throw new Error(`Empty response (HTTP ${res.status})`);
  return JSON.parse(text) as T;
}

// ── Raw fetchers ──────────────────────────────────────────────────────────────

export async function fetchHealth(): Promise<{ status: string }> {
  const res = await fetch(`${BASE}/health`, { signal: AbortSignal.timeout(5000) });
  return safeJson(res);
}

export interface ConfigStatus {
  anthropic:          boolean;
  alpaca:             boolean;
  binance:            boolean;
  telegram:           boolean;
  alpaca_base_url:    string;
  binance_testnet:    boolean;
  auto_trade:         boolean;
  ready_for_signals:  boolean;
  ready_for_trading:  boolean;
}

export async function fetchConfigStatus(): Promise<ConfigStatus> {
  const res = await fetch(`${BASE}/config-status`, { signal: AbortSignal.timeout(5000) });
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
  const res = await fetch(`${BASE}/portfolio`, { signal: AbortSignal.timeout(15000) });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return safeJson(res);
}

export async function fetchCachedSignals(): Promise<Signal[]> {
  const res = await fetch(`${BASE}/signals/cached`, { signal: AbortSignal.timeout(10000) });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return safeJson(res);
}

// ── Signal persistence helpers ────────────────────────────────────────────────

const SIGNALS_STORAGE_KEY = "ta_signals_cache_v1";

function loadStoredSignals(): Signal[] {
  try {
    const raw = localStorage.getItem(SIGNALS_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Signal[]) : [];
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
 */
function mergeSignals(local: Signal[], incoming: Signal[]): Signal[] {
  const bySymbol = new Map<string, Signal>(local.map((s) => [s.symbol, s]));
  for (const s of incoming) bySymbol.set(s.symbol, s);
  return [...bySymbol.values()].sort(
    (a, b) => new Date(b.generated_at).getTime() - new Date(a.generated_at).getTime(),
  );
}

// ── React hooks ───────────────────────────────────────────────────────────────

type ApiState = "loading" | "live" | "mock";

/**
 * Loads portfolio from the real API, falls back to mock if unavailable.
 * Returns mock immediately so the UI is never blank, then polls every 30s.
 */
export function usePortfolio() {
  const [portfolio, setPortfolio] = useState<PortfolioSnapshot>(mockPortfolio);
  const [state, setState] = useState<ApiState>("loading");

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const data = await fetchPortfolio();
        if (!cancelled) { setPortfolio(data); setState("live"); }
      } catch {
        if (!cancelled) setState((s) => s === "loading" ? "mock" : s);
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
 */
export function useSignals() {
  // liveSignals: only real (non-mock) signals; seed from localStorage
  const [liveSignals, setLiveSignals] = useState<Signal[]>(() => loadStoredSignals());
  const [apiState, setApiState] = useState<ApiState>("loading");
  const [refreshing, setRefreshing] = useState(false);

  // Show real signals if we have any; fall back to mock placeholder until then
  const signals = liveSignals.length > 0 ? liveSignals : mockSignals;

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
        if (!cancelled) setApiState((s) => s === "loading" ? "mock" : s);
      }
    }

    poll();
    const id = setInterval(poll, 30_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function load(manual = false) {
    if (manual) setRefreshing(true);
    try {
      const data = await fetchCachedSignals();
      applyIncoming(data as Signal[]);
      setApiState("live");
    } catch {
      setApiState((s) => s === "loading" ? "mock" : s);
    } finally {
      if (manual) setRefreshing(false);
    }
  }

  const refresh = () => load(true);

  return { signals, apiState, refresh, refreshing };
}

/**
 * Fetches the real equity curve from Alpaca portfolio history.
 * Falls back to mock series if the backend is unavailable or returns
 * no data (e.g. weekend / pre-market with no trading activity).
 * Re-polls every 60 s so intraday moves stay current.
 */
export function useEquitySeries() {
  const [series, setSeries]   = useState<EquityPoint[]>([]);
  const [isLive, setIsLive]   = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const res = await fetch(`${BASE}/portfolio/history`, {
          signal: AbortSignal.timeout(15_000),
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
  }, []);

  return { series, isLive };
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
