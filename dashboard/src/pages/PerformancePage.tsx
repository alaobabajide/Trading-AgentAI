import { useState, useEffect, useCallback } from "react";
import { BarChart2, ChevronLeft, ChevronRight, RefreshCw, Trophy } from "lucide-react";
import clsx from "clsx";
import { apiHeaders } from "../lib/api";

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

export function PerformancePage() {
  return (
    <div className="space-y-5">
      <h1 className="text-lg font-semibold flex items-center gap-2">
        <Trophy className="w-5 h-5 text-amber-400" />
        Performance
      </h1>
      <Leaderboard />
      <SignalHistoryTable />
    </div>
  );
}
