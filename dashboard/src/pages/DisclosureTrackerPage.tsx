import { useState, useEffect, useCallback } from "react";
import clsx from "clsx";
import { RefreshCw, AlertTriangle, ChevronDown, TrendingUp, TrendingDown, Copy, X, CheckCircle } from "lucide-react";
import { apiHeaders, executeOrder } from "../lib/api";

const API_BASE = "/api";

// ── Types ────────────────────────────────────────────────────────────────────

interface Investor {
  id: string;
  name: string;
  fund: string;
  confidence_pct: number;
  est_alpha_pct: number;
  note: string;
  last_fetched_at: string | null;
}

interface Holding {
  id: string;
  company_name: string;
  symbol: string;
  cusip: string;
  shares: number;
  value_usd: number;
  pct_portfolio: number;
  period_of_report: string;
  filed_at: string;
}

interface CongressTrade {
  id: string;
  member_name: string;
  party: string;
  chamber: string;
  state: string;
  symbol: string;
  company_name: string;
  trade_type: string;
  amount_range: string;
  transaction_date: string;
  disclosure_date: string;
  comment: string;
}

// ── Data hook ────────────────────────────────────────────────────────────────

function useBrainFetch<T>(path: string, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [seq, setSeq] = useState(0);

  const refetch = useCallback(() => setSeq(s => s + 1), []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    fetch(`${API_BASE}${path}`, { headers: apiHeaders() })
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(d => { if (active) { setData(d); setLoading(false); } })
      .catch(e => { if (active) { setError(e.message); setLoading(false); } });
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, seq, ...deps]);

  return { data, loading, error, refetch };
}

// ── Sub-components ───────────────────────────────────────────────────────────

function ConfidenceBadge({ pct }: { pct: number }) {
  const colour =
    pct >= 90 ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" :
    pct >= 85 ? "bg-blue-500/15 text-blue-400 border-blue-500/30" :
                "bg-amber-500/15 text-amber-400 border-amber-500/30";
  return (
    <span className={clsx("text-xs px-2 py-0.5 rounded border font-medium", colour)}>
      {pct}% confidence
    </span>
  );
}

function LagWarning() {
  return (
    <div className="flex items-start gap-2 rounded-lg border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-sm text-amber-300">
      <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
      <span>
        <strong>13F Disclosure Lag:</strong> SEC quarterly filings reflect holdings up to 45 days
        before the filing date. Positions may have changed. This is public information only —
        do not treat as trading advice.
      </span>
    </div>
  );
}

function TradeTypeBadge({ type }: { type: string }) {
  const t = type.toLowerCase();
  if (t.includes("purchase") || t.includes("buy")) {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
        <TrendingUp className="h-3 w-3" /> Purchase
      </span>
    );
  }
  if (t.includes("sale") || t.includes("sell")) {
    return (
      <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-rose-500/15 text-rose-400 border border-rose-500/30">
        <TrendingDown className="h-3 w-3" /> Sale
      </span>
    );
  }
  return <span className="text-xs text-slate-400">{type || "—"}</span>;
}

function fmt(n: number | null | undefined, decimals = 1) {
  if (n == null || isNaN(n)) return "—";
  if (n >= 1_000_000_000) return `$${(n / 1_000_000_000).toFixed(decimals)}B`;
  if (n >= 1_000_000)     return `$${(n / 1_000_000).toFixed(decimals)}M`;
  if (n >= 1_000)         return `$${(n / 1_000).toFixed(decimals)}K`;
  return `$${n.toFixed(2)}`;
}

// ── Investor 13F tab ─────────────────────────────────────────────────────────

function InvestorRow({
  investor,
  isOpen,
  onToggle,
}: {
  investor: Investor;
  isOpen: boolean;
  onToggle: () => void;
}) {
  const [copyTarget, setCopyTarget] = useState<CopyTradeTarget | null>(null);
  const holdingsPath = `/disclosures/investors/${investor.id}/holdings`;
  const { data, loading } = useBrainFetch<{
    period: string;
    periods_available: string[];
    holdings: Holding[];
    lag_warning: string;
  }>(holdingsPath, [isOpen]);

  const [period, setPeriod] = useState<string>("");

  const periodsPath = `/disclosures/investors/${investor.id}/periods`;
  const { data: periodsData } = useBrainFetch<{ periods: string[] }>(periodsPath, []);

  const periods = periodsData?.periods ?? [];
  const activePeriod = period || data?.period || periods[0] || "";
  const currentHoldings = isOpen && data ? data.holdings : [];

  return (
    <div className="border border-slate-700 rounded-lg overflow-hidden">
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-3 px-4 py-3 bg-slate-800/60 hover:bg-slate-800 text-left transition-colors"
      >
        <ChevronDown
          className={clsx("h-4 w-4 text-slate-400 transition-transform shrink-0", isOpen && "rotate-180")}
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-white">{investor.name}</span>
            <span className="text-slate-400 text-sm">{investor.fund}</span>
          </div>
          {investor.note && (
            <p className="text-xs text-slate-500 mt-0.5 truncate">{investor.note}</p>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs text-slate-400">
            ~{investor.est_alpha_pct > 0 ? "+" : ""}{investor.est_alpha_pct}% α/yr
          </span>
          <ConfidenceBadge pct={investor.confidence_pct} />
        </div>
      </button>

      {isOpen && (
        <div className="px-4 py-4 space-y-3">
          {periods.length > 1 && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400">Filing period:</span>
              <select
                value={activePeriod}
                onChange={e => setPeriod(e.target.value)}
                className="text-xs bg-slate-700 border border-slate-600 rounded px-2 py-1 text-white"
              >
                {periods.map(p => (
                  <option key={p} value={p}>{p}</option>
                ))}
              </select>
            </div>
          )}

          {loading ? (
            <div className="text-center py-6 text-slate-400 text-sm">Loading holdings…</div>
          ) : currentHoldings.length === 0 ? (
            <div className="text-center py-6 text-slate-500 text-sm">
              No holdings on file yet. Data loads automatically every 24 hours from SEC EDGAR.
            </div>
          ) : (
            <div className="overflow-x-auto rounded border border-slate-700">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-700 bg-slate-800/40">
                    <th className="text-left px-3 py-2 text-xs text-slate-400 font-medium">Company</th>
                    <th className="text-left px-3 py-2 text-xs text-slate-400 font-medium">Symbol</th>
                    <th className="text-right px-3 py-2 text-xs text-slate-400 font-medium">Value</th>
                    <th className="text-right px-3 py-2 text-xs text-slate-400 font-medium">% Portfolio</th>
                    <th className="text-right px-3 py-2 text-xs text-slate-400 font-medium">Shares</th>
                    <th className="px-3 py-2" />
                  </tr>
                </thead>
                <tbody>
                  {currentHoldings.map((h, i) => (
                    <tr
                      key={h.id}
                      className={clsx(
                        "border-b border-slate-700/50 hover:bg-slate-700/30 transition-colors",
                        i % 2 === 0 ? "bg-slate-800/20" : ""
                      )}
                    >
                      <td className="px-3 py-2 text-white truncate max-w-[16rem]">{h.company_name}</td>
                      <td className="px-3 py-2 text-blue-400 font-mono font-medium">{h.symbol || "—"}</td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums text-slate-200">
                        {fmt(h.value_usd)}
                      </td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums text-slate-200">
                        {h.pct_portfolio != null ? `${h.pct_portfolio.toFixed(2)}%` : "—"}
                      </td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums text-slate-400">
                        {h.shares != null ? h.shares.toLocaleString(undefined, { maximumFractionDigits: 0 }) : "—"}
                      </td>
                      <td className="px-3 py-2">
                        {h.symbol && (
                          <button
                            onClick={() => setCopyTarget({
                              symbol:       h.symbol,
                              action:       "BUY",
                              member_name:  investor.name,
                              amount_range: fmt(h.value_usd),
                              trade_type:   "purchase",
                            })}
                            className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs border border-slate-600 text-slate-300 hover:border-blue-500 hover:text-blue-400 transition-colors"
                          >
                            <Copy className="h-3 w-3" />
                            Copy
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {data?.lag_warning && currentHoldings.length > 0 && (
            <p className="text-xs text-amber-400/70">{data.lag_warning}</p>
          )}
        </div>
      )}
      {copyTarget && (
        <CopyTradeModal target={copyTarget} onClose={() => setCopyTarget(null)} />
      )}
    </div>
  );
}

function InstitutionalTab() {
  const { data: investors, loading, error, refetch } = useBrainFetch<Investor[]>("/disclosures/investors");
  const [openId, setOpenId] = useState<string | null>(null);

  if (loading) return <div className="text-center py-12 text-slate-400">Loading investors…</div>;
  if (error) return (
    <div className="text-center py-12 text-rose-400">
      Failed to load: {error}
      <button onClick={refetch} className="ml-2 text-blue-400 underline text-sm">Retry</button>
    </div>
  );
  if (!investors || investors.length === 0) return (
    <div className="text-center py-12 text-slate-500">No tracked investors found.</div>
  );

  return (
    <div className="space-y-4">
      <LagWarning />
      <div className="space-y-2">
        {investors.map(inv => (
          <InvestorRow
            key={inv.id}
            investor={inv}
            isOpen={openId === inv.id}
            onToggle={() => setOpenId(openId === inv.id ? null : inv.id)}
          />
        ))}
      </div>
    </div>
  );
}

// ── Copy Trade Modal ──────────────────────────────────────────────────────────

interface CopyTradeTarget {
  symbol:      string;
  action:      "BUY" | "SELL";
  member_name: string;
  amount_range: string;
  trade_type:  string;
}

function CopyTradeModal({ target, onClose }: { target: CopyTradeTarget; onClose: () => void }) {
  const [positionPct, setPositionPct] = useState(2);
  const [slPct,       setSlPct]       = useState(2);
  const [tpPct,       setTpPct]       = useState(5);
  const [submitting,  setSubmitting]  = useState(false);
  const [done,        setDone]        = useState(false);
  const [error,       setError]       = useState<string | null>(null);

  async function handleExecute() {
    if (!target.symbol) return;
    setSubmitting(true);
    setError(null);
    try {
      await executeOrder({
        symbol:                target.symbol,
        asset_class:           "stock",
        action:                target.action,
        suggested_position_pct: positionPct / 100,
        stop_loss_pct:          slPct / 100,
        take_profit_pct:        tpPct / 100,
      });
      setDone(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-2xl w-full max-w-md shadow-2xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700">
          <div className="flex items-center gap-2">
            <Copy className="h-4 w-4 text-blue-400" />
            <span className="font-semibold text-white">Copy Trade</span>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white transition-colors">
            <X className="h-5 w-5" />
          </button>
        </div>

        {done ? (
          <div className="px-5 py-8 text-center space-y-3">
            <CheckCircle className="h-10 w-10 text-emerald-400 mx-auto" />
            <p className="text-white font-medium">Order submitted successfully</p>
            <p className="text-slate-400 text-sm">
              {target.action} {target.symbol} order sent to your broker.
            </p>
            <button onClick={onClose} className="mt-4 px-6 py-2 rounded-xl bg-slate-700 hover:bg-slate-600 text-sm text-white transition-colors">
              Close
            </button>
          </div>
        ) : (
          <div className="px-5 py-4 space-y-4">
            <div className="rounded-xl bg-slate-800 px-4 py-3 space-y-1">
              <p className="text-xs text-slate-400">Copying trade from</p>
              <p className="font-medium text-white">{target.member_name}</p>
              <div className="flex items-center gap-2 mt-1">
                <span className={clsx(
                  "text-xs px-2 py-0.5 rounded border font-medium",
                  target.action === "BUY"
                    ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
                    : "bg-rose-500/15 text-rose-400 border-rose-500/30"
                )}>
                  {target.action === "BUY" ? "▲ Purchase" : "▼ Sale"}
                </span>
                <span className="font-mono font-bold text-blue-400 text-sm">{target.symbol}</span>
                {target.amount_range && (
                  <span className="text-xs text-slate-400">{target.amount_range}</span>
                )}
              </div>
            </div>

            <div className="rounded-xl border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-xs text-amber-300">
              <AlertTriangle className="inline h-3.5 w-3.5 mr-1 -mt-0.5" />
              This disclosure may be up to 45 days old. Review before executing.
            </div>

            <div className="space-y-3">
              {[
                { label: "Position size", value: positionPct, set: setPositionPct, opts: [1,2,3,5,10], suffix: "% of equity" },
                { label: "Stop-loss",     value: slPct,       set: setSlPct,       opts: [1,2,3,5],    suffix: "% below entry" },
                { label: "Take-profit",   value: tpPct,       set: setTpPct,       opts: [3,5,10,15],  suffix: "% above entry" },
              ].map(({ label, value, set, opts, suffix }) => (
                <div key={label} className="space-y-1">
                  <div className="flex justify-between text-xs">
                    <span className="text-slate-400">{label}</span>
                    <span className="text-slate-200 font-mono font-medium">{value}% {suffix}</span>
                  </div>
                  <div className="flex gap-1.5">
                    {opts.map(o => (
                      <button
                        key={o}
                        onClick={() => set(o)}
                        className={clsx(
                          "flex-1 py-1.5 rounded-lg text-xs font-medium transition-colors border",
                          value === o
                            ? "bg-blue-600 border-blue-500 text-white"
                            : "bg-slate-800 border-slate-600 text-slate-300 hover:border-slate-400"
                        )}
                      >
                        {o}%
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>

            {error && <p className="text-xs text-rose-400 font-mono">{error}</p>}

            <div className="flex gap-3 pt-1">
              <button
                onClick={onClose}
                className="flex-1 py-2.5 rounded-xl border border-slate-600 text-sm text-slate-300 hover:border-slate-400 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleExecute}
                disabled={submitting || !target.symbol}
                className={clsx(
                  "flex-1 py-2.5 rounded-xl text-sm font-medium transition-colors",
                  target.action === "BUY"
                    ? "bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-white"
                    : "bg-rose-600 hover:bg-rose-500 disabled:opacity-40 text-white"
                )}
              >
                {submitting ? "Submitting…" : `Confirm ${target.action} ${target.symbol}`}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Congressional STOCK Act tab ───────────────────────────────────────────────

function CongressTab() {
  const [memberFilter, setMemberFilter] = useState("");
  const [symbolFilter, setSymbolFilter] = useState("");
  const [appliedMember, setAppliedMember] = useState("");
  const [appliedSymbol, setAppliedSymbol] = useState("");
  const [copyTarget, setCopyTarget] = useState<CopyTradeTarget | null>(null);

  const path = `/disclosures/congress/feed?limit=200${appliedMember ? `&member=${encodeURIComponent(appliedMember)}` : ""}${appliedSymbol ? `&symbol=${encodeURIComponent(appliedSymbol.toUpperCase())}` : ""}`;
  const { data, loading, error, refetch } = useBrainFetch<{
    count: number;
    lag_warning: string;
    trades: CongressTrade[];
  }>(path, [appliedMember, appliedSymbol]);

  const trades = data?.trades ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 rounded-lg border border-blue-500/25 bg-blue-500/10 px-4 py-3 text-sm text-blue-300">
        <AlertTriangle className="h-4 w-4 shrink-0" />
        <span>
          <strong>STOCK Act Disclosures:</strong> Public government data. Congressional trades must be
          reported within 45 days of the transaction. Source: HouseStockWatcher &amp; SenateStockWatcher.
        </span>
      </div>

      <div className="flex gap-2 flex-wrap">
        <input
          value={memberFilter}
          onChange={e => setMemberFilter(e.target.value)}
          onKeyDown={e => e.key === "Enter" && setAppliedMember(memberFilter)}
          placeholder="Filter by member name…"
          className="flex-1 min-w-[200px] text-sm bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
        />
        <input
          value={symbolFilter}
          onChange={e => setSymbolFilter(e.target.value.toUpperCase())}
          onKeyDown={e => e.key === "Enter" && setAppliedSymbol(symbolFilter)}
          placeholder="Symbol (e.g. NVDA)…"
          className="w-36 text-sm bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 font-mono"
        />
        <button
          onClick={() => { setAppliedMember(memberFilter); setAppliedSymbol(symbolFilter); }}
          className="px-4 py-2 text-sm bg-blue-600 hover:bg-blue-500 text-white rounded-lg transition-colors"
        >
          Filter
        </button>
        {(appliedMember || appliedSymbol) && (
          <button
            onClick={() => { setMemberFilter(""); setSymbolFilter(""); setAppliedMember(""); setAppliedSymbol(""); }}
            className="px-4 py-2 text-sm bg-slate-700 hover:bg-slate-600 text-slate-300 rounded-lg transition-colors"
          >
            Clear
          </button>
        )}
      </div>

      {loading ? (
        <div className="text-center py-12 text-slate-400">Loading disclosures…</div>
      ) : error ? (
        <div className="text-center py-12 text-rose-400">
          Failed to load: {error}
          <button onClick={refetch} className="ml-2 text-blue-400 underline text-sm">Retry</button>
        </div>
      ) : trades.length === 0 ? (
        <div className="text-center py-12 text-slate-500">
          No trades on file yet. Data loads automatically every 6 hours.
        </div>
      ) : (
        <>
          <div className="text-xs text-slate-500">{data?.count ?? trades.length} disclosures</div>
          <div className="overflow-x-auto rounded-lg border border-slate-700">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-700 bg-slate-800/60">
                  <th className="text-left px-3 py-2 text-xs text-slate-400 font-medium">Member</th>
                  <th className="text-left px-3 py-2 text-xs text-slate-400 font-medium">Chamber</th>
                  <th className="text-left px-3 py-2 text-xs text-slate-400 font-medium">Symbol</th>
                  <th className="text-left px-3 py-2 text-xs text-slate-400 font-medium">Company</th>
                  <th className="text-left px-3 py-2 text-xs text-slate-400 font-medium">Type</th>
                  <th className="text-left px-3 py-2 text-xs text-slate-400 font-medium">Amount</th>
                  <th className="text-left px-3 py-2 text-xs text-slate-400 font-medium">Tx Date</th>
                  <th className="text-left px-3 py-2 text-xs text-slate-400 font-medium">Disclosed</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody>
                {trades.map((t, i) => {
                  const isBuy = t.trade_type?.toLowerCase().includes("purchase") || t.trade_type?.toLowerCase().includes("buy");
                  const isSell = t.trade_type?.toLowerCase().includes("sale") || t.trade_type?.toLowerCase().includes("sell");
                  const canCopy = t.symbol && (isBuy || isSell);
                  return (
                    <tr
                      key={t.id}
                      className={clsx(
                        "border-b border-slate-700/50 hover:bg-slate-700/30 transition-colors",
                        i % 2 === 0 ? "bg-slate-800/20" : ""
                      )}
                    >
                      <td className="px-3 py-2 text-white font-medium">
                        <div>{t.member_name}</div>
                        {t.party && (
                          <div className="text-xs text-slate-500">{t.party} · {t.state}</div>
                        )}
                      </td>
                      <td className="px-3 py-2 text-slate-300 text-xs">{t.chamber}</td>
                      <td className="px-3 py-2 text-blue-400 font-mono font-medium">{t.symbol || "—"}</td>
                      <td className="px-3 py-2 text-slate-300 truncate max-w-[12rem] text-xs">{t.company_name || "—"}</td>
                      <td className="px-3 py-2"><TradeTypeBadge type={t.trade_type} /></td>
                      <td className="px-3 py-2 text-slate-300 text-xs whitespace-nowrap">{t.amount_range || "—"}</td>
                      <td className="px-3 py-2 text-slate-400 text-xs font-mono">{t.transaction_date || "—"}</td>
                      <td className="px-3 py-2 text-slate-400 text-xs font-mono">{t.disclosure_date || "—"}</td>
                      <td className="px-3 py-2">
                        {canCopy && (
                          <button
                            onClick={() => setCopyTarget({
                              symbol:       t.symbol,
                              action:       isBuy ? "BUY" : "SELL",
                              member_name:  t.member_name,
                              amount_range: t.amount_range || "",
                              trade_type:   t.trade_type,
                            })}
                            className="flex items-center gap-1 px-2 py-1 rounded-lg text-xs border border-slate-600 text-slate-300 hover:border-blue-500 hover:text-blue-400 transition-colors whitespace-nowrap"
                          >
                            <Copy className="h-3 w-3" />
                            Copy
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {copyTarget && (
            <CopyTradeModal target={copyTarget} onClose={() => setCopyTarget(null)} />
          )}
          {data?.lag_warning && (
            <p className="text-xs text-amber-400/70">{data.lag_warning}</p>
          )}
        </>
      )}
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

type Tab = "institutional" | "congress";

export function DisclosureTrackerPage() {
  const [tab, setTab] = useState<Tab>("institutional");
  const [refreshing, setRefreshing] = useState(false);

  async function triggerRefresh() {
    setRefreshing(true);
    try {
      await fetch(`${API_BASE}/disclosures/refresh`, {
        method: "POST",
        headers: apiHeaders({ "Content-Type": "application/json" }),
      });
    } catch {
      // ignore
    } finally {
      setTimeout(() => setRefreshing(false), 2000);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Public Disclosure Tracker</h1>
          <p className="text-slate-400 text-sm mt-1">
            13F institutional filings (SEC EDGAR) and STOCK Act congressional trade disclosures.
            Read-only — public data only.
          </p>
        </div>
        <button
          onClick={triggerRefresh}
          disabled={refreshing}
          title="Trigger background data refresh"
          className={clsx(
            "flex items-center gap-2 px-3 py-2 text-sm rounded-lg border transition-colors",
            refreshing
              ? "border-slate-600 text-slate-500 cursor-not-allowed"
              : "border-slate-600 text-slate-300 hover:border-blue-500 hover:text-blue-400"
          )}
        >
          <RefreshCw className={clsx("h-4 w-4", refreshing && "animate-spin")} />
          {refreshing ? "Refreshing…" : "Refresh data"}
        </button>
      </div>

      <div className="flex gap-1 border-b border-slate-700">
        {([
          { id: "institutional" as Tab, label: "Institutional 13F" },
          { id: "congress" as Tab, label: "Congressional STOCK Act" },
        ] as { id: Tab; label: string }[]).map(t => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={clsx(
              "px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors",
              tab === t.id
                ? "border-blue-500 text-blue-400"
                : "border-transparent text-slate-400 hover:text-white"
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "institutional" && <InstitutionalTab />}
      {tab === "congress" && <CongressTab />}
    </div>
  );
}
