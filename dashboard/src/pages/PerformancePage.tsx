import React, { useState, useEffect, useCallback } from "react";
import {
  BarChart2, ChevronLeft, ChevronRight, RefreshCw, Trophy,
  TrendingUp, Database, Play, CheckCircle, Clock, XCircle,
} from "lucide-react";
import clsx from "clsx";
import {
  apiHeaders,
  fetchTrackRecordStats, fetchTrackRecordLeaderboard, fetchEquityCurve,
  fetchBacktestRuns, triggerBacktest,
  type TrackRecordStats, type EquityCurvePoint,
  type BacktestRun, type TrackRecordLeaderboardRow,
} from "../lib/api";

// ── Types ──────────────────────────────────────────────────────────────────

type Outcome = "WIN" | "LOSS" | "NEUTRAL" | "EXPIRED" | null;
type Action  = "BUY" | "SELL" | "HOLD";
type Tier    = "HOT" | "WARM" | "COLD";
type GroupBy = "tier" | "asset_class" | "regime";

interface HistoryRow {
  id: string;
  symbol: string;
  asset_class: string;
  action: Action;
  tier: Tier;
  regime: string;
  confidence: number;
  votes_for: number;
  price_at_signal: number | null;
  generated_at: string;
  outcome_final: Outcome;
  outcome_1h: Outcome;
  outcome_24h: Outcome;
  outcome_7d: Outcome;
  price_7d: number | null;
}

interface LeaderboardRow {
  group_key: string;
  total: number;
  wins: number;
  losses: number;
  neutrals: number;
  expired: number;
  pending: number;
  win_rate: number | null;
  avg_confidence: number;
  avg_votes: number;
}

// ── Helpers ────────────────────────────────────────────────────────────────

const OUTCOME_STYLE: Record<string, string> = {
  WIN:     "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
  LOSS:    "bg-red-500/15 text-red-400 border-red-500/30",
  NEUTRAL: "bg-slate-500/15 text-slate-400 border-slate-500/20",
  EXPIRED: "bg-amber-500/10 text-amber-500/70 border-amber-500/20",
};

const ACTION_STYLE: Record<string, string> = {
  BUY:  "text-emerald-400",
  SELL: "text-red-400",
  HOLD: "text-slate-400",
};

const TIER_STYLE: Record<string, string> = {
  HOT:  "bg-red-500/15 text-red-400",
  WARM: "bg-amber-500/15 text-amber-400",
  COLD: "bg-slate-500/15 text-slate-400",
};

function OutcomeBadge({ v }: { v: Outcome }) {
  if (!v) return <span className="text-slate-600 text-xs font-mono">pending</span>;
  return (
    <span className={clsx(
      "text-[10px] font-semibold px-1.5 py-0.5 rounded border",
      OUTCOME_STYLE[v] ?? "text-slate-400",
    )}>
      {v}
    </span>
  );
}

function WinBar({ wins, losses, neutrals }: { wins: number; losses: number; neutrals: number }) {
  const total = wins + losses + neutrals;
  if (!total) return <div className="text-slate-600 text-xs">—</div>;
  const wp = (wins / total) * 100;
  const lp = (losses / total) * 100;
  return (
    <div className="flex items-center gap-2">
      <div className="flex h-2 w-24 rounded-full overflow-hidden bg-surface-700">
        <div className="bg-emerald-500" style={{ width: `${wp}%` }} />
        <div className="bg-red-500"     style={{ width: `${lp}%` }} />
      </div>
      <span className="text-xs font-mono text-slate-300">{wp.toFixed(0)}%</span>
    </div>
  );
}

function fmtPrice(p: number | null) {
  if (!p) return "—";
  return `$${p.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function fmtDate(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

// ── Signal History table ───────────────────────────────────────────────────

const PAGE_SIZE = 50;

const FILTER_ACTIONS: (Action | "ALL")[] = ["ALL", "BUY", "SELL", "HOLD"];
const FILTER_TIERS:   (Tier  | "ALL")[] = ["ALL", "HOT", "WARM", "COLD"];
const FILTER_OUTCOMES: (string)[]        = ["ALL", "WIN", "LOSS", "NEUTRAL", "EXPIRED"];

function SignalHistoryTable() {
  const [rows, setRows]       = useState<HistoryRow[]>([]);
  const [total, setTotal]     = useState(0);
  const [page, setPage]       = useState(0);
  const [loading, setLoading] = useState(true);

  const [filterAction,  setFilterAction]  = useState("ALL");
  const [filterTier,    setFilterTier]    = useState("ALL");
  const [filterOutcome, setFilterOutcome] = useState("ALL");
  const [filterSymbol,  setFilterSymbol]  = useState("");

  const fetch = useCallback(async () => {
    setLoading(true);
    const params = new URLSearchParams({
      limit:  String(PAGE_SIZE),
      offset: String(page * PAGE_SIZE),
    });
    if (filterAction  !== "ALL") params.set("action",  filterAction);
    if (filterTier    !== "ALL") params.set("tier",    filterTier);
    if (filterOutcome !== "ALL") params.set("outcome", filterOutcome);
    if (filterSymbol.trim())     params.set("symbol",  filterSymbol.trim().toUpperCase());

    try {
      const res = await window.fetch(`/api/signal/history?${params}`, { headers: apiHeaders() });
      if (res.ok) {
        const d = await res.json();
        setRows(d.rows ?? []);
        setTotal(d.total ?? 0);
      }
    } finally {
      setLoading(false);
    }
  }, [page, filterAction, filterTier, filterOutcome, filterSymbol]);

  useEffect(() => { fetch(); }, [fetch]);

  // Reset page when filters change
  useEffect(() => { setPage(0); }, [filterAction, filterTier, filterOutcome, filterSymbol]);

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div className="glass rounded-2xl overflow-hidden">
      <div className="px-5 py-4 border-b border-white/5 flex flex-wrap items-center gap-3">
        <h2 className="text-sm font-semibold flex items-center gap-2">
          <BarChart2 className="w-4 h-4 text-brand-400" />
          Signal History
          <span className="text-xs text-slate-500 font-mono font-normal ml-1">{total} records</span>
        </h2>

        {/* Filters */}
        <div className="flex flex-wrap gap-2 ml-auto items-center">
          <input
            value={filterSymbol}
            onChange={e => setFilterSymbol(e.target.value)}
            placeholder="Symbol…"
            className="bg-surface-700 border border-white/10 rounded-lg px-2.5 py-1 text-xs font-mono w-24 text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-brand-500/50"
          />
          {([["Action", FILTER_ACTIONS, filterAction, setFilterAction],
             ["Tier",   FILTER_TIERS,   filterTier,   setFilterTier],
             ["Outcome",FILTER_OUTCOMES,filterOutcome,setFilterOutcome]] as const).map(
            ([label, opts, val, set]) => (
              <select
                key={label as string}
                value={val as string}
                onChange={e => (set as (v: string) => void)(e.target.value)}
                className="bg-surface-700 border border-white/10 rounded-lg px-2 py-1 text-xs font-mono text-slate-300 focus:outline-none focus:border-brand-500/50"
              >
                {(opts as readonly string[]).map(o => (
                  <option key={o} value={o}>{label as string}: {o}</option>
                ))}
              </select>
            )
          )}
          <button onClick={fetch} className="p-1.5 rounded-lg hover:bg-white/5 text-slate-400 hover:text-slate-200">
            <RefreshCw className={clsx("w-3.5 h-3.5", loading && "animate-spin")} />
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs font-mono">
          <thead>
            <tr className="border-b border-white/5 text-slate-500 uppercase tracking-wider text-[10px]">
              {["Time", "Symbol", "Action", "Tier", "Regime", "Conf", "Votes", "Price", "1h", "24h", "7d", "Final"].map(h => (
                <th key={h} className="px-4 py-2.5 text-left font-medium whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.03]">
            {rows.length === 0 && !loading && (
              <tr>
                <td colSpan={12} className="px-4 py-10 text-center text-slate-600">
                  No signals recorded yet — they appear here as the system generates them.
                </td>
              </tr>
            )}
            {rows.map(r => (
              <tr key={r.id} className="hover:bg-white/[0.02] transition-colors">
                <td className="px-4 py-2.5 text-slate-500 whitespace-nowrap">{fmtDate(r.generated_at)}</td>
                <td className="px-4 py-2.5 font-semibold text-slate-200">{r.symbol}</td>
                <td className={clsx("px-4 py-2.5 font-semibold", ACTION_STYLE[r.action])}>{r.action}</td>
                <td className="px-4 py-2.5">
                  <span className={clsx("px-1.5 py-0.5 rounded text-[10px] font-semibold", TIER_STYLE[r.tier])}>
                    {r.tier}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-slate-400 max-w-[120px] truncate">{r.regime}</td>
                <td className="px-4 py-2.5 text-slate-300">{(r.confidence * 100).toFixed(0)}%</td>
                <td className="px-4 py-2.5 text-slate-300">{r.votes_for.toFixed(1)}</td>
                <td className="px-4 py-2.5 text-slate-300">{fmtPrice(r.price_at_signal)}</td>
                <td className="px-4 py-2.5"><OutcomeBadge v={r.outcome_1h} /></td>
                <td className="px-4 py-2.5"><OutcomeBadge v={r.outcome_24h} /></td>
                <td className="px-4 py-2.5"><OutcomeBadge v={r.outcome_7d} /></td>
                <td className="px-4 py-2.5"><OutcomeBadge v={r.outcome_final} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="px-5 py-3 border-t border-white/5 flex items-center justify-between text-xs text-slate-500">
          <span>{page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, total)} of {total}</span>
          <div className="flex gap-1">
            <button
              disabled={page === 0}
              onClick={() => setPage(p => p - 1)}
              className="p-1 rounded hover:bg-white/5 disabled:opacity-30"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button
              disabled={page >= totalPages - 1}
              onClick={() => setPage(p => p + 1)}
              className="p-1 rounded hover:bg-white/5 disabled:opacity-30"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Leaderboard ────────────────────────────────────────────────────────────

function Leaderboard() {
  const [groupBy, setGroupBy]   = useState<GroupBy>("tier");
  const [rows, setRows]         = useState<LeaderboardRow[]>([]);
  const [loading, setLoading]   = useState(true);

  useEffect(() => {
    setLoading(true);
    window.fetch(`/api/signal/leaderboard?group_by=${groupBy}`, { headers: apiHeaders() })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setRows(d.rows ?? []); })
      .finally(() => setLoading(false));
  }, [groupBy]);

  const GROUP_LABELS: Record<GroupBy, string> = {
    tier: "Tier", asset_class: "Asset Class", regime: "Regime",
  };

  return (
    <div className="glass rounded-2xl overflow-hidden">
      <div className="px-5 py-4 border-b border-white/5 flex items-center gap-3">
        <h2 className="text-sm font-semibold flex items-center gap-2">
          <Trophy className="w-4 h-4 text-amber-400" />
          Performance Leaderboard
        </h2>
        <div className="ml-auto flex gap-1">
          {(["tier", "asset_class", "regime"] as GroupBy[]).map(g => (
            <button
              key={g}
              onClick={() => setGroupBy(g)}
              className={clsx(
                "px-3 py-1 rounded-lg text-xs font-mono font-medium border transition-all",
                groupBy === g
                  ? "bg-brand-500/20 border-brand-500/40 text-brand-300"
                  : "border-white/10 text-slate-500 hover:text-slate-300 hover:border-white/20",
              )}
            >
              {GROUP_LABELS[g]}
            </button>
          ))}
          {loading && <RefreshCw className="w-3.5 h-3.5 animate-spin text-slate-500 self-center ml-1" />}
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-xs font-mono">
          <thead>
            <tr className="border-b border-white/5 text-slate-500 uppercase tracking-wider text-[10px]">
              {[GROUP_LABELS[groupBy], "Signals", "Win Rate", "W / L / N", "Pending", "Avg Conf", "Avg Votes"].map(h => (
                <th key={h} className="px-4 py-2.5 text-left font-medium whitespace-nowrap">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-white/[0.03]">
            {rows.length === 0 && !loading && (
              <tr>
                <td colSpan={7} className="px-4 py-10 text-center text-slate-600">
                  No resolved outcomes yet — check back once signals have had time to mature.
                </td>
              </tr>
            )}
            {rows.map(r => (
              <tr key={r.group_key} className="hover:bg-white/[0.02] transition-colors">
                <td className="px-4 py-3 font-semibold text-slate-200">{r.group_key}</td>
                <td className="px-4 py-3 text-slate-300">{r.total}</td>
                <td className="px-4 py-3">
                  {r.win_rate !== null
                    ? <WinBar wins={r.wins} losses={r.losses} neutrals={r.neutrals} />
                    : <span className="text-slate-600">—</span>
                  }
                </td>
                <td className="px-4 py-3">
                  <span className="text-emerald-400">{r.wins}</span>
                  <span className="text-slate-600"> / </span>
                  <span className="text-red-400">{r.losses}</span>
                  <span className="text-slate-600"> / </span>
                  <span className="text-slate-400">{r.neutrals}</span>
                </td>
                <td className="px-4 py-3 text-slate-500">{r.pending}</td>
                <td className="px-4 py-3 text-slate-300">{(r.avg_confidence * 100).toFixed(0)}%</td>
                <td className="px-4 py-3 text-slate-300">{r.avg_votes.toFixed(1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Page ───────────────────────────────────────────────────────────────────

// ── Track Record tab ──────────────────────────────────────────────────────────

function pct(v: number | null, decimals = 1) {
  if (v == null) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(decimals)}%`;
}

function MetricCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="glass rounded-xl p-4">
      <div className="text-[10px] text-slate-500 uppercase tracking-wider mb-1">{label}</div>
      <div className="text-xl font-bold font-mono text-slate-100">{value}</div>
      {sub && <div className="text-[10px] text-slate-500 mt-0.5">{sub}</div>}
    </div>
  );
}

function MiniEquityChart({ points }: { points: EquityCurvePoint[] }) {
  if (points.length < 2) return null;
  const navs = points.map(p => p.nav);
  const min  = Math.min(...navs);
  const max  = Math.max(...navs);
  const w = 300, h = 60;
  const xs = points.map((_, i) => (i / (points.length - 1)) * w);
  const ys = navs.map(n => h - ((n - min) / Math.max(max - min, 1)) * h);
  const d  = xs.map((x, i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${ys[i].toFixed(1)}`).join(" ");
  const positive = (navs[navs.length - 1] ?? 0) >= (navs[0] ?? 0);
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-14" preserveAspectRatio="none">
      <path d={d} fill="none" stroke={positive ? "#10b981" : "#ef4444"} strokeWidth="1.5" />
    </svg>
  );
}

function TrackRecordTab() {
  const [stats,  setStats]  = useState<TrackRecordStats | null>(null);
  const [lb,     setLb]     = useState<TrackRecordLeaderboardRow[]>([]);
  const [curve,  setCurve]  = useState<EquityCurvePoint[]>([]);
  const [lbGroup, setLbGroup] = useState<"tier" | "asset_class" | "regime">("tier");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      fetchTrackRecordStats().catch(() => null),
      fetchEquityCurve(90).catch(() => []),
    ]).then(([s, c]) => {
      if (!cancelled) {
        setStats(s);
        setCurve(Array.isArray(c) ? c : []);
        setLoading(false);
      }
    });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    fetchTrackRecordLeaderboard(lbGroup)
      .then(d => setLb(d.rows ?? []))
      .catch(() => {});
  }, [lbGroup]);

  const latestCurve = curve[curve.length - 1];
  const firstCurve  = curve[0];
  const totalReturn = latestCurve && firstCurve
    ? (latestCurve.nav - 100_000) / 100_000 * 100
    : null;
  const maxDD = curve.length
    ? Math.min(...curve.map(p => p.drawdown ?? 0))
    : null;

  const w7  = stats?.["7d"];
  const w30 = stats?.["30d"];

  return (
    <div className="space-y-5">
      {/* Source label */}
      <div className="text-[11px] text-slate-500 bg-slate-800/60 rounded-lg px-3 py-2 border border-slate-700/50">
        <strong className="text-slate-400">Data source:</strong> Live paper trading (LLM debate, forward-looking).
        Track record started <strong className="text-slate-400">2026-08-24</strong> — data accumulates over time.
      </div>

      {loading ? (
        <div className="text-center py-8 text-slate-600 text-sm">Loading track record…</div>
      ) : (
        <>
          {/* Key metrics */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <MetricCard
              label="Total Return"
              value={pct(totalReturn)}
              sub="Since 2026-08-24"
            />
            <MetricCard
              label="7d Win Rate"
              value={w7?.win_rate != null ? `${w7.win_rate.toFixed(0)}%` : "—"}
              sub={w7 ? `${w7.wins}W / ${w7.losses}L` : "No resolved signals"}
            />
            <MetricCard
              label="30d Win Rate"
              value={w30?.win_rate != null ? `${w30.win_rate.toFixed(0)}%` : "—"}
              sub={w30 ? `${w30.wins}W / ${w30.losses}L` : "No resolved signals"}
            />
            <MetricCard
              label="Max Drawdown"
              value={maxDD != null ? pct(maxDD) : "—"}
              sub="From NAV peak"
            />
          </div>

          {/* Equity curve */}
          {curve.length > 1 ? (
            <div className="glass rounded-2xl p-5">
              <h3 className="text-sm font-semibold mb-3">Portfolio NAV — 90-day window</h3>
              <MiniEquityChart points={curve} />
              <div className="flex justify-between text-[10px] text-slate-600 font-mono mt-1">
                <span>{curve[0]?.snapshot_date}</span>
                <span>${(latestCurve?.nav ?? 100_000).toLocaleString()}</span>
              </div>
            </div>
          ) : (
            <div className="glass rounded-2xl p-5 text-sm text-slate-600">
              Equity curve data accumulates after each market close. Check back tomorrow.
            </div>
          )}

          {/* Tier accuracy leaderboard */}
          <div className="glass rounded-2xl overflow-hidden">
            <div className="px-5 py-4 border-b border-white/5 flex items-center gap-3">
              <h3 className="text-sm font-semibold">Tier Accuracy</h3>
              <div className="flex gap-1 ml-auto">
                {(["tier", "asset_class", "regime"] as const).map(g => (
                  <button
                    key={g}
                    onClick={() => setLbGroup(g)}
                    className={clsx(
                      "text-[10px] px-2 py-0.5 rounded capitalize transition-colors",
                      lbGroup === g
                        ? "bg-brand-600 text-white"
                        : "text-slate-400 hover:text-white"
                    )}
                  >
                    {g.replace("_", " ")}
                  </button>
                ))}
              </div>
            </div>
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="border-b border-white/5 text-slate-500 text-[10px] uppercase tracking-wider">
                  {["Group", "Total", "Wins", "Losses", "Neutral", "Pending", "Win Rate", "Avg Conf"].map(h => (
                    <th key={h} className="px-4 py-2.5 text-left font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.03]">
                {lb.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-8 text-center text-slate-600">
                      Signal data accumulates over time — check back after signals resolve (≥1h after generation).
                    </td>
                  </tr>
                ) : lb.map(r => (
                  <tr key={r.group_key} className="hover:bg-white/[0.02]">
                    <td className="px-4 py-2.5 font-semibold text-slate-200">{r.group_key}</td>
                    <td className="px-4 py-2.5 text-slate-400">{r.total}</td>
                    <td className="px-4 py-2.5 text-emerald-400">{r.wins}</td>
                    <td className="px-4 py-2.5 text-red-400">{r.losses}</td>
                    <td className="px-4 py-2.5 text-slate-400">{r.neutral}</td>
                    <td className="px-4 py-2.5 text-slate-500">{r.pending}</td>
                    <td className="px-4 py-2.5">
                      {r.win_rate != null ? (
                        <span className={r.win_rate >= 50 ? "text-emerald-400" : "text-red-400"}>
                          {r.win_rate.toFixed(0)}%
                        </span>
                      ) : <span className="text-slate-600">—</span>}
                    </td>
                    <td className="px-4 py-2.5 text-slate-300">
                      {r.avg_confidence != null ? r.avg_confidence.toFixed(1) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

// ── Backtest Results tab ───────────────────────────────────────────────────────

const RUN_STATUS_ICON = {
  completed: <CheckCircle className="w-3.5 h-3.5 text-emerald-400" />,
  running:   <Clock       className="w-3.5 h-3.5 text-amber-400 animate-pulse" />,
  failed:    <XCircle     className="w-3.5 h-3.5 text-red-400" />,
};

const PRESET_RUNS = [
  { name: "bull_2024",    start_date: "2024-01-01", end_date: "2024-12-31", label: "Bull 2024" },
  { name: "mixed_2025",   start_date: "2025-01-01", end_date: "2025-12-31", label: "Mixed 2025" },
  { name: "current_2026", start_date: "2026-01-01", end_date: "",           label: "Current 2026" },
  { name: "full_cycle",   start_date: "2024-01-01", end_date: "",           label: "Full Cycle" },
];

function BacktestResultsTab() {
  const [runs,       setRuns]       = useState<BacktestRun[]>([]);
  const [loading,    setLoading]    = useState(true);
  const [launching,  setLaunching]  = useState<string | null>(null);
  const [msg,        setMsg]        = useState<string | null>(null);
  const [expanded,   setExpanded]   = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    fetchBacktestRuns()
      .then(r => { setRuns(r); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  async function launch(preset: typeof PRESET_RUNS[0]) {
    setLaunching(preset.name);
    setMsg(null);
    try {
      await triggerBacktest({
        name:       preset.name,
        start_date: preset.start_date,
        end_date:   preset.end_date || undefined,
        symbols:    "all",
      });
      setMsg(`Backtest "${preset.label}" started — refresh in a few minutes.`);
      setTimeout(load, 3000);
    } catch (e) {
      setMsg(`Error: ${(e as Error).message}`);
    } finally {
      setLaunching(null);
    }
  }

  return (
    <div className="space-y-5">
      <div className="text-[11px] text-slate-500 bg-slate-800/60 rounded-lg px-3 py-2 border border-slate-700/50">
        <strong className="text-slate-400">Rule-based engine only</strong> — deterministic, reproducible.
        Same symbols and parameters as the live system, replayed against historical daily bars.
        Results are clearly labeled as backtest data and never mixed with live signals.
      </div>

      {/* Preset launch buttons */}
      <div className="glass rounded-2xl p-5 space-y-3">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Play className="w-4 h-4 text-brand-400" />
          Run Preset Backtests
        </h3>
        <div className="flex flex-wrap gap-2">
          {PRESET_RUNS.map(p => {
            const alreadyRun = runs.some(r => r.name === p.name);
            return (
              <button
                key={p.name}
                onClick={() => launch(p)}
                disabled={!!launching}
                className={clsx(
                  "flex items-center gap-2 px-4 py-2 text-sm rounded-lg border transition-colors",
                  alreadyRun
                    ? "border-emerald-500/30 text-emerald-400 bg-emerald-500/5"
                    : "border-slate-600 text-slate-300 hover:border-brand-500 hover:text-brand-400",
                  launching === p.name && "opacity-60 cursor-not-allowed"
                )}
              >
                {launching === p.name ? (
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                ) : alreadyRun ? (
                  <CheckCircle className="w-3.5 h-3.5" />
                ) : (
                  <Play className="w-3.5 h-3.5" />
                )}
                {p.label}
                <span className="text-[10px] text-slate-500 font-mono">
                  {p.start_date}→{p.end_date || "now"}
                </span>
              </button>
            );
          })}
        </div>
        {msg && (
          <div className="text-xs text-brand-400 bg-brand-500/10 rounded px-3 py-2 border border-brand-500/20">
            {msg}
          </div>
        )}
      </div>

      {/* Results table */}
      <div className="glass rounded-2xl overflow-hidden">
        <div className="px-5 py-4 border-b border-white/5 flex items-center gap-2">
          <h3 className="text-sm font-semibold">
            <Database className="w-4 h-4 text-slate-400 inline mr-2" />
            Backtest Runs
          </h3>
          <button onClick={load} className="ml-auto p-1.5 rounded hover:bg-white/5 text-slate-400">
            <RefreshCw className={clsx("w-3.5 h-3.5", loading && "animate-spin")} />
          </button>
        </div>
        {loading ? (
          <div className="px-5 py-8 text-sm text-slate-600">Loading…</div>
        ) : runs.length === 0 ? (
          <div className="px-5 py-8 text-sm text-slate-600">
            No backtests run yet. Click a preset above to start one.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="border-b border-white/5 text-slate-500 text-[10px] uppercase tracking-wider">
                  {["", "Name", "Period", "Engine", "Return", "Ann. Return", "Sharpe", "Max DD", "Win Rate", "Trades", "vs SPY", "vs BTC"].map(h => (
                    <th key={h} className="px-3 py-2.5 text-left font-medium whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-white/[0.03]">
                {runs.map(r => (
                  <>
                    <tr
                      key={r.id}
                      className="hover:bg-white/[0.02] cursor-pointer"
                      onClick={() => setExpanded(e => e === r.id ? null : r.id)}
                    >
                      <td className="px-3 py-2.5">{RUN_STATUS_ICON[r.status] ?? null}</td>
                      <td className="px-3 py-2.5 font-semibold text-slate-200">{r.name}</td>
                      <td className="px-3 py-2.5 text-slate-400 whitespace-nowrap">
                        {r.start_date} → {r.end_date}
                      </td>
                      <td className="px-3 py-2.5 text-slate-400">{r.engine}</td>
                      <td className={clsx("px-3 py-2.5", (r.total_return ?? 0) >= 0 ? "text-emerald-400" : "text-red-400")}>
                        {pct(r.total_return ? r.total_return * 100 : null)}
                      </td>
                      <td className={clsx("px-3 py-2.5", (r.annualized_return ?? 0) >= 0 ? "text-emerald-400" : "text-red-400")}>
                        {pct(r.annualized_return ? r.annualized_return * 100 : null)}
                      </td>
                      <td className="px-3 py-2.5 text-slate-300">
                        {r.sharpe_ratio != null ? r.sharpe_ratio.toFixed(2) : "—"}
                      </td>
                      <td className="px-3 py-2.5 text-red-400">
                        {r.max_drawdown != null ? pct(r.max_drawdown * 100) : "—"}
                      </td>
                      <td className="px-3 py-2.5">
                        {r.win_rate != null ? (
                          <span className={r.win_rate >= 50 ? "text-emerald-400" : "text-red-400"}>
                            {r.win_rate.toFixed(0)}%
                          </span>
                        ) : "—"}
                      </td>
                      <td className="px-3 py-2.5 text-slate-300">
                        {r.total_trades ?? "—"}
                      </td>
                      <td className={clsx("px-3 py-2.5", (r.spy_return ?? 0) >= 0 ? "text-emerald-400" : "text-red-400")}>
                        {pct(r.spy_return ? r.spy_return * 100 : null)}
                      </td>
                      <td className={clsx("px-3 py-2.5", (r.btc_return ?? 0) >= 0 ? "text-emerald-400" : "text-red-400")}>
                        {pct(r.btc_return ? r.btc_return * 100 : null)}
                      </td>
                    </tr>
                    {expanded === r.id && (
                      <tr key={`${r.id}-detail`}>
                        <td colSpan={12} className="px-5 py-4 bg-slate-800/40 text-xs text-slate-400 space-y-1">
                          <div>
                            <strong className="text-slate-300">Symbols tested:</strong>{" "}
                            {r.symbol_universe?.slice(0, 15).join(", ")}
                            {(r.symbol_universe?.length ?? 0) > 15 ? ` … +${(r.symbol_universe?.length ?? 0) - 15} more` : ""}
                          </div>
                          <div>
                            <strong className="text-slate-300">Final NAV:</strong>{" "}
                            ${r.final_nav?.toLocaleString() ?? "—"}
                          </div>
                          <div className="text-[10px] text-slate-600 mt-1">
                            Run ID: {r.id} · Created: {new Date(r.created_at).toLocaleDateString()}
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Main page with tabs ───────────────────────────────────────────────────────

type PageTab = "leaderboard" | "history" | "track_record" | "backtests";

export function PerformancePage() {
  const [tab, setTab] = useState<PageTab>("leaderboard");

  return (
    <div className="space-y-5">
      <h1 className="text-lg font-semibold flex items-center gap-2">
        <Trophy className="w-5 h-5 text-amber-400" />
        Performance
      </h1>

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-slate-700">
        {([
          { id: "leaderboard",  label: "Leaderboard",    icon: <Trophy       className="w-3.5 h-3.5" /> },
          { id: "history",      label: "Signal History",  icon: <BarChart2    className="w-3.5 h-3.5" /> },
          { id: "track_record", label: "Track Record",    icon: <TrendingUp   className="w-3.5 h-3.5" /> },
          { id: "backtests",    label: "Backtests",       icon: <Database     className="w-3.5 h-3.5" /> },
        ] as { id: PageTab; label: string; icon: React.ReactNode }[]).map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={clsx(
              "flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
              tab === t.id
                ? "border-brand-500 text-brand-400"
                : "border-transparent text-slate-400 hover:text-white"
            )}
          >
            {t.icon}
            {t.label}
          </button>
        ))}
      </div>

      {tab === "leaderboard"  && <Leaderboard />}
      {tab === "history"      && <SignalHistoryTable />}
      {tab === "track_record" && <TrackRecordTab />}
      {tab === "backtests"    && <BacktestResultsTab />}
    </div>
  );
}
