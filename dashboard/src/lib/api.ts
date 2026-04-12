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
 * Returns the data immediately from mock so the UI is never blank.
 */
export function usePortfolio() {
  const [portfolio, setPortfolio] = useState<PortfolioSnapshot>(mockPortfolio);
  const [state, setState] = useState<ApiState>("loading");

  useEffect(() => {
    fetchPortfolio()
      .then((data) => {
        setPortfolio(data);
        setState("live");
      })
      .catch(() => setState("mock"));
  }, []);

  return { portfolio, apiState: state };
}

/**
 * Loads cached signals from the real API, falls back to mock.
 */
export function useSignals() {
  const [signals, setSignals] = useState<Signal[]>(mockSignals);
  const [apiState, setApiState] = useState<ApiState>("loading");

  useEffect(() => {
    fetchCachedSignals()
      .then((data) => {
        if (data.length > 0) {
          setSignals(data as Signal[]);
          setApiState("live");
        } else {
          // Empty cache — show mock but mark as live (backend is running)
          setApiState("live");
        }
      })
      .catch(() => setApiState("mock"));
  }, []);

  return { signals, apiState };
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
