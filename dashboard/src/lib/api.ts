/**
 * API client — calls the brain FastAPI backend.
 * All calls go to /api/* which nginx proxies to uvicorn.
 * Falls back silently to mock data if the backend is unavailable.
 */
import { useEffect, useState } from "react";
import { PortfolioSnapshot, Signal } from "./types";
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
 * Loads cached signals from the real API, falls back to mock.
 * Polls every 30s so new signals generated from the Brain Console appear automatically.
 * Exposes a `refresh()` imperative trigger for the manual refresh button.
 */
export function useSignals() {
  const [signals, setSignals]   = useState<Signal[]>(mockSignals);
  const [apiState, setApiState] = useState<ApiState>("loading");
  const [refreshing, setRefreshing] = useState(false);

  // Stable load function — shared by polling and manual refresh
  async function load(manual = false) {
    if (manual) setRefreshing(true);
    try {
      const data = await fetchCachedSignals();
      if (data.length > 0) setSignals(data as Signal[]);
      setApiState("live");
    } catch {
      setApiState((s) => s === "loading" ? "mock" : s);
    } finally {
      if (manual) setRefreshing(false);
    }
  }

  useEffect(() => {
    let cancelled = false;

    async function poll() {
      try {
        const data = await fetchCachedSignals();
        if (!cancelled) {
          if (data.length > 0) setSignals(data as Signal[]);
          setApiState("live");
        }
      } catch {
        if (!cancelled) setApiState((s) => s === "loading" ? "mock" : s);
      }
    }

    poll();
    const id = setInterval(poll, 30_000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const refresh = () => load(true);

  return { signals, apiState, refresh, refreshing };
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
