import clsx from "clsx";
import { Brain, Clock, Database, Eye, Landmark, Link, Package, RefreshCw, Shield, TrendingUp, Zap } from "lucide-react";
import {
  HITLMode, UserProfile, DEFAULT_PROFILE,
  MODE_CONFIG, loadProfile, saveProfile,
} from "../lib/hitl";
import { useConfigStatus, useRiskConfig, RiskConfigFields, useLlmSettings, LlmSavePayload, useAlpacaSettings, AlpacaSavePayload, useWebhookSettings, useBrokerSettings, useTastytradeSettings, TastytradeSavePayload, usePolygonSettings, useNgxPulseSettings, useSchwabSettings, useIBKRSettings, useKrakenSettings, useCoinbaseSettings, useTradeStationSettings, useFmpSettings, useDisclosureSettings, DisclosureSettings } from "../lib/api";
import { useEffect, useState } from "react";

// ── Layout helpers ────────────────────────────────────────────────────────────

function Section({ icon, title, subtitle, children }: {
  icon: React.ReactNode; title: string; subtitle?: string; children: React.ReactNode;
}) {
  return (
    <div className="glass rounded-2xl p-5 space-y-4">
      <div className="flex items-start gap-2.5">
        <div className="w-7 h-7 rounded-lg bg-brand-500/15 flex items-center justify-center text-brand-400 shrink-0 mt-0.5">
          {icon}
        </div>
        <div>
          <h3 className="text-sm font-semibold">{title}</h3>
          {subtitle && <p className="text-[11px] text-slate-500 font-mono mt-0.5">{subtitle}</p>}
        </div>
      </div>
      {children}
    </div>
  );
}

function SectionNote({ children, variant = "info" }: { children: React.ReactNode; variant?: "info" | "warn" }) {
  return (
    <div className={clsx(
      "text-[11px] font-mono rounded-xl px-3 py-2 leading-relaxed",
      variant === "warn"
        ? "text-amber-400/90 bg-amber-500/10 border border-amber-500/20"
        : "text-slate-400 bg-surface-700",
    )}>
      {children}
    </div>
  );
}

function SubSection({ title }: { title: string }) {
  return (
    <div className="flex items-center gap-2 pt-1">
      <div className="h-px flex-1 bg-white/5" />
      <span className="text-[10px] font-mono uppercase tracking-widest text-slate-600">{title}</span>
      <div className="h-px flex-1 bg-white/5" />
    </div>
  );
}

// ── Row components ────────────────────────────────────────────────────────────

function RiskRow({
  label, value, options, onChange, valueColor, unit = "%", formatFn,
}: {
  label: string; value: number; options: number[];
  onChange: (v: number) => void; valueColor: string;
  unit?: string; formatFn?: (v: number) => string;
}) {
  const display = formatFn ? formatFn(value) : `${(value * 100).toFixed(1)}${unit}`;
  const optionDisplay = formatFn
    ? (o: number) => formatFn(o / 100)
    : (o: number) => `${o}${unit}`;
  const optionVal = (o: number) => o / 100;

  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs">
        <span className="text-slate-300 font-medium">{label}</span>
        <span className={clsx("font-mono font-semibold", valueColor)}>{display}</span>
      </div>
      <div className="flex gap-1.5">
        {options.map((o) => (
          <button key={o}
            onClick={() => onChange(optionVal(o))}
            className={clsx(
              "flex-1 py-1.5 rounded-lg text-xs font-mono font-medium transition-all border",
              Math.abs(value - optionVal(o)) < 0.0001
                ? clsx(
                    valueColor === "text-red-400"      ? "bg-red-500/20 border-red-500/40 text-red-300"         :
                    valueColor === "text-emerald-400"  ? "bg-emerald-500/20 border-emerald-500/40 text-emerald-300" :
                    valueColor === "text-amber-400"    ? "bg-amber-500/20 border-amber-500/40 text-amber-300"    :
                    valueColor === "text-sky-400"      ? "bg-sky-500/20 border-sky-500/40 text-sky-300"          :
                    valueColor === "text-violet-400"   ? "bg-violet-500/20 border-violet-500/40 text-violet-300" :
                    "bg-orange-500/20 border-orange-500/40 text-orange-300"
                  )
                : "border-white/5 text-slate-500 hover:text-slate-300",
            )}
          >{optionDisplay(o)}</button>
        ))}
      </div>
    </div>
  );
}

/** For fields stored as raw fractions with non-×100 display (e.g. ATR multiplier stored as 1.5, options [10,15,20,25] meaning 1.0,1.5,2.0,2.5) */
function RawRow({
  label, value, options, onChange, valueColor, display, optLabel,
}: {
  label: string; value: number; options: number[];
  onChange: (v: number) => void; valueColor: string;
  display: (v: number) => string; optLabel: (o: number) => string;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs">
        <span className="text-slate-300 font-medium">{label}</span>
        <span className={clsx("font-mono font-semibold", valueColor)}>{display(value)}</span>
      </div>
      <div className="flex gap-1.5">
        {options.map((o) => (
          <button key={o}
            onClick={() => onChange(o)}
            className={clsx(
              "flex-1 py-1.5 rounded-lg text-xs font-mono font-medium transition-all border",
              Math.abs(value - o) < 0.0001
                ? clsx(
                    valueColor === "text-sky-400"    ? "bg-sky-500/20 border-sky-500/40 text-sky-300"       :
                    valueColor === "text-violet-400" ? "bg-violet-500/20 border-violet-500/40 text-violet-300" :
                    "bg-brand-500/20 border-brand-500/40 text-brand-300"
                  )
                : "border-white/5 text-slate-500 hover:text-slate-300",
            )}
          >{optLabel(o)}</button>
        ))}
      </div>
    </div>
  );
}

function OptionRow<T extends string>({
  label, sublabel, value, current, onSelect, accent,
}: {
  label: string; sublabel?: string; value: T; current: T;
  onSelect: (v: T) => void; accent?: string;
}) {
  const active = value === current;
  return (
    <button
      onClick={() => onSelect(value)}
      className={clsx(
        "w-full text-left px-4 py-3 rounded-xl border transition-all",
        active ? `${accent ?? "border-brand-500/40 bg-brand-500/10"}` : "border-white/5 hover:border-white/10 hover:bg-white/[0.02]",
      )}
    >
      <div className="flex items-center justify-between">
        <div>
          <div className={clsx("text-sm font-medium", active ? (accent ? "" : "text-brand-300") : "text-slate-300")}>{label}</div>
          {sublabel && <div className="text-[11px] text-slate-500 mt-0.5">{sublabel}</div>}
        </div>
        <div className={clsx("w-4 h-4 rounded-full border-2 flex items-center justify-center transition-colors", active ? "border-brand-500 bg-brand-500" : "border-slate-600")}>
          {active && <div className="w-1.5 h-1.5 rounded-full bg-white" />}
        </div>
      </div>
    </button>
  );
}

function SecondSlider({ label, value, options, onChange }: {
  label: string; value: number; options: number[]; onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex justify-between text-xs">
        <span className="text-slate-400">{label}</span>
        <span className="font-mono font-semibold text-slate-200">{value}s</span>
      </div>
      <div className="flex gap-2">
        {options.map((o) => (
          <button key={o} onClick={() => onChange(o)}
            className={clsx(
              "flex-1 py-1.5 rounded-lg text-xs font-mono font-medium transition-all border",
              value === o ? "bg-brand-500/20 border-brand-500/40 text-brand-300" : "border-white/5 text-slate-500 hover:text-slate-300",
            )}
          >{o}s</button>
        ))}
      </div>
    </div>
  );
}

function NumberSlider({ label, value, options, onChange }: {
  label: string; value: number; options: number[]; onChange: (v: number) => void;
}) {
  return (
    <div className="space-y-2">
      <div className="flex justify-between text-xs">
        <span className="text-slate-400">{label}</span>
        <span className="font-mono font-semibold text-slate-200">{value}%</span>
      </div>
      <div className="flex gap-2">
        {options.map((o) => (
          <button key={o} onClick={() => onChange(o)}
            className={clsx(
              "flex-1 py-1.5 rounded-lg text-xs font-mono font-medium transition-all border",
              value === o ? "bg-brand-500/20 border-brand-500/40 text-brand-300" : "border-white/5 text-slate-500 hover:text-slate-300",
            )}
          >{o}%</button>
        ))}
      </div>
    </div>
  );
}

// ── Alpaca account panel ──────────────────────────────────────────────────────

function WebhookPanel() {
  const wh = useWebhookSettings();
  const [confirmRevoke, setConfirmRevoke] = useState(false);
  const [copied, setCopied] = useState(false);

  const fullUrl = wh.revealed
    ? window.location.origin + wh.revealed.webhook_path
    : null;

  function copyUrl() {
    if (!fullUrl) return;
    navigator.clipboard.writeText(fullUrl).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    });
  }

  if (!wh.settings) {
    return (
      <div className="text-xs text-slate-500 font-mono animate-pulse">
        Loading webhook settings… (requires login)
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <SectionNote variant="info">
        TradingView alerts fire this URL to place trades directly into your Alpaca account.
        The secret in the URL is the only auth — treat it like a password.
      </SectionNote>

      {/* Status row */}
      <div className="flex items-center gap-2">
        <div className={clsx(
          "w-2 h-2 rounded-full shrink-0",
          wh.settings.configured ? "bg-emerald-400" : "bg-slate-600",
        )} />
        <span className="text-xs text-slate-400 font-mono">
          {wh.settings.configured ? "Webhook active" : "No webhook configured"}
        </span>
      </div>

      {/* One-time revealed secret */}
      {wh.revealed && fullUrl && (
        <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-3 space-y-2">
          <p className="text-[10px] text-amber-300 font-mono uppercase tracking-widest">
            Save this now — shown once only
          </p>
          <div className="flex items-center gap-2">
            <code className="flex-1 text-[10px] font-mono text-slate-200 break-all bg-surface-700 rounded-lg px-2 py-1.5 border border-white/5">
              {fullUrl}
            </code>
            <button
              onClick={copyUrl}
              className="shrink-0 text-[10px] font-mono px-3 py-1.5 rounded-lg border border-white/10 bg-surface-700 text-slate-300 hover:text-white hover:border-white/20 transition-all"
            >
              {copied ? "Copied!" : "Copy"}
            </button>
          </div>
          <p className="text-[10px] text-slate-500 font-mono">
            Paste this URL into TradingView → Alerts → Webhook URL
          </p>
          <button
            onClick={wh.dismiss}
            className="text-[10px] text-slate-500 hover:text-slate-300 font-mono underline"
          >
            I've saved it — dismiss
          </button>
        </div>
      )}

      {/* Alert message template */}
      {wh.settings.configured && !wh.revealed && (
        <div className="space-y-1">
          <div className="text-[10px] text-slate-500 uppercase tracking-widest font-mono">TradingView alert message</div>
          <pre className="text-[10px] font-mono text-slate-300 bg-surface-700 rounded-xl px-3 py-2 border border-white/5 overflow-x-auto">{`{
  "symbol":      "{{ticker}}",
  "action":      "{{strategy.order.action}}",
  "asset_class": "stock",
  "qty":         0
}`}</pre>
          <p className="text-[10px] text-slate-500 font-mono">
            Paste this into the TradingView alert Message field. Set qty to 0 to size by your risk config.
          </p>
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-2">
        <button
          onClick={wh.generate}
          disabled={wh.generating}
          className="flex-1 py-2 rounded-xl text-xs font-mono font-semibold border border-brand-500/40 bg-brand-500/15 text-brand-300 hover:bg-brand-500/25 disabled:opacity-50 transition-all"
        >
          {wh.generating ? "Generating…" : wh.settings.configured ? "Regenerate secret" : "Generate webhook URL"}
        </button>

        {wh.settings.configured && !confirmRevoke && (
          <button
            onClick={() => setConfirmRevoke(true)}
            className="px-4 py-2 rounded-xl text-xs font-mono border border-red-500/30 bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-all"
          >
            Revoke
          </button>
        )}

        {confirmRevoke && (
          <div className="flex gap-1">
            <button
              onClick={() => { wh.revoke(); setConfirmRevoke(false); }}
              disabled={wh.revoking}
              className="px-3 py-2 rounded-xl text-xs font-mono border border-red-500/50 bg-red-500/20 text-red-300 hover:bg-red-500/30 disabled:opacity-50 transition-all"
            >
              {wh.revoking ? "Revoking…" : "Confirm revoke"}
            </button>
            <button
              onClick={() => setConfirmRevoke(false)}
              className="px-3 py-2 rounded-xl text-xs font-mono border border-white/10 bg-surface-700 text-slate-400 hover:text-white transition-all"
            >
              Cancel
            </button>
          </div>
        )}
      </div>

      {wh.error && (
        <p className="text-xs text-red-400 font-mono">{wh.error}</p>
      )}
    </div>
  );
}

function BrokerPanel() {
  const { settings, saving, saved, error, selectBroker } = useBrokerSettings();

  if (!settings) {
    return <p className="text-sm text-brand-300/50">Loading broker options…</p>;
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {settings.available_brokers.map((broker) => {
          const isActive = broker.id === settings.current_broker;
          const isLive   = broker.status === "live";
          return (
            <button
              key={broker.id}
              type="button"
              disabled={!isLive || saving}
              onClick={() => { if (isLive) selectBroker(broker.id); }}
              className={clsx(
                "text-left rounded-xl border p-3.5 transition-all",
                isActive
                  ? "border-brand-400/60 bg-brand-500/10 ring-1 ring-brand-400/30"
                  : isLive
                  ? "border-white/10 bg-white/[0.04] hover:border-brand-400/30 hover:bg-brand-500/[0.06] cursor-pointer"
                  : "border-white/[0.06] bg-white/[0.02] opacity-50 cursor-not-allowed",
              )}
            >
              <div className="flex items-center justify-between gap-2 mb-1">
                <span className="text-sm font-semibold text-brand-100">{broker.name}</span>
                {isActive && (
                  <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-brand-500/20 text-brand-300 leading-none">
                    Active
                  </span>
                )}
                {!isActive && broker.status === "coming_soon" && (
                  <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-white/[0.08] text-brand-400/60 leading-none">
                    Soon
                  </span>
                )}
              </div>
              <p className="text-xs text-brand-300/60 leading-snug">{broker.tagline}</p>
            </button>
          );
        })}
      </div>
      {saving && <p className="text-xs text-brand-400/60">Saving…</p>}
      {saved  && <p className="text-xs text-green-400">Active broker updated.</p>}
      {error  && <p className="text-xs text-red-400">{error}</p>}
    </div>
  );
}

function PolygonPanel() {
  const poly = usePolygonSettings();
  const [apiKeyVal, setApiKeyVal] = useState("");

  const sourceLabel: Record<string, string> = {
    user:   "Your key — real-time data",
    system: "System key — real-time data",
    none:   "Not configured — using Alpaca (15-min delayed)",
  };

  return (
    <div className="space-y-4">
      {/* Status badge */}
      <div className={clsx(
        "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium border",
        poly.settings?.effective_source === "none"
          ? "border-white/10 bg-white/5 text-slate-400"
          : "border-green-400/30 bg-green-500/10 text-green-400",
      )}>
        <span className={clsx("w-1.5 h-1.5 rounded-full", poly.settings?.effective_source === "none" ? "bg-slate-500" : "bg-green-400")} />
        {poly.settings ? sourceLabel[poly.settings.effective_source] : "Loading…"}
      </div>

      {/* API key input */}
      <div className="space-y-1">
        <label className="text-[11px] text-slate-400 uppercase tracking-wide">
          Polygon API Key {poly.settings?.user_key_configured && <span className="text-green-400/80 ml-1 normal-case">(saved)</span>}
        </label>
        <div className="flex gap-2">
          <input
            type="password"
            autoComplete="off"
            placeholder={poly.settings?.user_key_configured ? "leave blank to keep saved key" : "pk_xxxxxxxxxxxxxxxx"}
            value={apiKeyVal}
            onChange={(e) => setApiKeyVal(e.target.value)}
            className="flex-1 px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm text-brand-100 placeholder-slate-500 focus:outline-none focus:border-brand-400/50"
          />
          <button
            type="button"
            onClick={() => { poly.saveKey(apiKeyVal); setApiKeyVal(""); }}
            disabled={poly.saving || !apiKeyVal.trim()}
            className="px-4 py-2 rounded-lg bg-brand-500/20 border border-brand-400/30 text-sm text-brand-300 hover:bg-brand-500/30 transition-colors disabled:opacity-40 shrink-0"
          >
            {poly.saving ? "Saving…" : "Save"}
          </button>
          {poly.settings?.user_key_configured && (
            <button
              type="button"
              onClick={poly.removeKey}
              disabled={poly.saving}
              className="px-3 py-2 rounded-lg border border-white/10 text-xs text-slate-400 hover:text-red-400 hover:border-red-400/30 transition-colors disabled:opacity-40 shrink-0"
            >
              Remove
            </button>
          )}
        </div>
      </div>

      {poly.saved  && <p className="text-xs text-green-400">Saved — signals will now use Polygon data.</p>}
      {poly.error  && <p className="text-xs text-red-400">{poly.error}</p>}

      <p className="text-[11px] text-slate-500 leading-relaxed">
        Polygon.io provides adjusted daily bars for equity signals.
        Free tier: 15-min delayed.
        Starter plan: real-time. Without a key, the system falls back to Alpaca market data.
        Get a free key at <span className="text-brand-400/70">polygon.io</span>.
      </p>
    </div>
  );
}

function NgxPulsePanel() {
  const ngx = useNgxPulseSettings();
  const [apiKeyVal, setApiKeyVal] = useState("");

  const sourceLabel: Record<string, string> = {
    stored: "Your key — NGX market data active",
    env:    "System key — NGX market data active",
    none:   "Not configured — NGX charts unavailable",
  };

  return (
    <div className="space-y-4">
      {/* Status badge */}
      <div className={clsx(
        "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium border",
        ngx.settings?.source === "none"
          ? "border-white/10 bg-white/5 text-slate-400"
          : "border-green-400/30 bg-green-500/10 text-green-400",
      )}>
        <span className={clsx("w-1.5 h-1.5 rounded-full", ngx.settings?.source === "none" ? "bg-slate-500" : "bg-green-400")} />
        {ngx.settings ? sourceLabel[ngx.settings.source] : "Loading…"}
      </div>

      {/* API key input */}
      <div className="space-y-1">
        <label className="text-[11px] text-slate-400 uppercase tracking-wide">
          NGX Pulse API Key {ngx.settings?.stored_key && <span className="text-green-400/80 ml-1 normal-case">(saved)</span>}
        </label>
        <div className="flex gap-2">
          <input
            type="password"
            autoComplete="off"
            placeholder={ngx.settings?.stored_key ? "leave blank to keep saved key" : "ngx_xxxxxxxxxxxxxxxx"}
            value={apiKeyVal}
            onChange={(e) => setApiKeyVal(e.target.value)}
            className="flex-1 px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm text-brand-100 placeholder-slate-500 focus:outline-none focus:border-brand-400/50"
          />
          <button
            type="button"
            onClick={() => { ngx.saveKey(apiKeyVal); setApiKeyVal(""); }}
            disabled={ngx.saving || !apiKeyVal.trim()}
            className="px-4 py-2 rounded-lg bg-brand-500/20 border border-brand-400/30 text-sm text-brand-300 hover:bg-brand-500/30 transition-colors disabled:opacity-40 shrink-0"
          >
            {ngx.saving ? "Saving…" : "Save"}
          </button>
          {ngx.settings?.stored_key && (
            <button
              type="button"
              onClick={ngx.removeKey}
              disabled={ngx.saving}
              className="px-3 py-2 rounded-lg border border-white/10 text-xs text-slate-400 hover:text-red-400 hover:border-red-400/30 transition-colors disabled:opacity-40 shrink-0"
            >
              Remove
            </button>
          )}
        </div>
      </div>

      {ngx.saved  && <p className="text-xs text-green-400">Saved — NGX charts will now use live market data.</p>}
      {ngx.error  && <p className="text-xs text-red-400">{ngx.error}</p>}

      <p className="text-[11px] text-slate-500 leading-relaxed">
        NGX Pulse provides Nigerian Exchange (NGX) stock prices updated every 30 seconds during market hours (9 AM–4 PM WAT).
        Required for Technical Analysis charts on NGX symbols.
        Get a key at <span className="text-brand-400/70">ngxpulse.ng</span>.
      </p>
    </div>
  );
}

function TastytradePanel() {
  const tt = useTastytradeSettings();

  const [username,   setUsername]   = useState("");
  const [password,   setPassword]   = useState("");
  const [accountNum, setAccountNum] = useState("");
  const [paperMode,  setPaperMode]  = useState(true);
  const [dirty,      setDirty]      = useState(false);

  useEffect(() => {
    if (tt.settings) {
      setUsername(tt.settings.username || "");
      setAccountNum(tt.settings.account_number || "");
      setPaperMode(tt.settings.paper_mode);
    }
  }, [tt.settings]);

  function handleChange<T>(setter: (v: T) => void) {
    return (v: T) => { setter(v); setDirty(true); };
  }

  function handleSave() {
    const payload: TastytradeSavePayload = { paper_mode: paperMode };
    if (username) payload.username = username;
    if (password) payload.password = password;
    if (accountNum) payload.account_number = accountNum;
    tt.save(payload).then(() => setDirty(false));
  }

  return (
    <div className="space-y-4">
      {/* Paper / Live toggle — matches Alpaca style */}
      <div className="space-y-1.5">
        <div className="text-[10px] text-slate-500 uppercase tracking-widest font-mono">Account mode</div>
        <div className="flex gap-2">
          {(["paper", "live"] as const).map((mode) => {
            const active = mode === "paper" ? paperMode : !paperMode;
            return (
              <button
                key={mode}
                type="button"
                onClick={() => { setPaperMode(mode === "paper"); setDirty(true); }}
                className={clsx(
                  "flex-1 py-2 rounded-xl text-xs font-mono font-semibold transition-all border",
                  active
                    ? mode === "paper"
                      ? "border-sky-500/60 bg-sky-500/15 text-sky-300"
                      : "border-amber-500/60 bg-amber-500/15 text-amber-300"
                    : "border-white/5 bg-surface-700 text-slate-500 hover:border-white/10",
                )}
              >
                {mode === "paper" ? "Paper trading" : "Live trading"}
              </button>
            );
          })}
        </div>
        {paperMode
          ? <p className="text-[11px] text-slate-500">Paper mode uses tastytrade&apos;s Certification environment — no real money.</p>
          : <SectionNote variant="warn">Live mode places real orders against your tastytrade account.</SectionNote>
        }
      </div>

      {/* Credential fields */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="space-y-1">
          <label className="text-[11px] text-slate-400 uppercase tracking-wide">Username / Email</label>
          <input
            type="text"
            autoComplete="username"
            placeholder="you@example.com"
            value={username}
            onChange={(e) => handleChange(setUsername)(e.target.value)}
            className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm text-brand-100 placeholder-slate-500 focus:outline-none focus:border-brand-400/50"
          />
        </div>
        <div className="space-y-1">
          <label className="text-[11px] text-slate-400 uppercase tracking-wide">
            Password {tt.settings?.keys_configured && <span className="text-green-400/80 ml-1">(saved)</span>}
          </label>
          <input
            type="password"
            autoComplete="current-password"
            placeholder="leave blank to keep saved password"
            value={password}
            onChange={(e) => handleChange(setPassword)(e.target.value)}
            className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm text-brand-100 placeholder-slate-500 focus:outline-none focus:border-brand-400/50"
          />
        </div>
        <div className="space-y-1 sm:col-span-2">
          <label className="text-[11px] text-slate-400 uppercase tracking-wide">Account Number <span className="text-slate-500 normal-case">(optional — defaults to first account)</span></label>
          <input
            type="text"
            placeholder="5WX12345"
            value={accountNum}
            onChange={(e) => handleChange(setAccountNum)(e.target.value)}
            className="w-full sm:w-64 px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm text-brand-100 placeholder-slate-500 focus:outline-none focus:border-brand-400/50"
          />
        </div>
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleSave}
          disabled={tt.saving || !dirty}
          className={clsx(
            "px-4 py-2 rounded-xl text-xs font-mono font-semibold transition-all",
            tt.saving || !dirty
              ? "bg-surface-700 text-slate-500 cursor-not-allowed"
              : "bg-brand-500 hover:bg-brand-400 text-white",
          )}
        >
          {tt.saving ? "Saving…" : tt.saved ? "Saved ✓" : "Save tastytrade settings"}
        </button>
        {tt.error && <span className="text-xs text-red-400 font-mono">{tt.error}</span>}
      </div>
    </div>
  );
}

function SchwabPanel() {
  const schwab = useSchwabSettings();

  const statusText = schwab.settings?.connected
    ? schwab.settings.refresh_expired
      ? "Session expired — reconnect"
      : schwab.settings.access_expired
        ? "Token refreshing…"
        : "Connected"
    : "Not connected";

  const statusColor = schwab.settings?.connected
    ? schwab.settings.refresh_expired
      ? "text-red-400"
      : "text-green-400"
    : "text-slate-400";

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <span className={`text-sm font-medium ${statusColor}`}>{statusText}</span>
        {schwab.settings?.account_hash && (
          <span className="text-xs text-slate-500 font-mono">
            Account: …{schwab.settings.account_hash.slice(-6)}
          </span>
        )}
      </div>

      <p className="text-xs text-slate-400 leading-relaxed">
        Schwab uses OAuth — click Connect to authorize in a new tab. No password is ever stored.
        Access tokens refresh automatically; you'll need to reconnect if you see a session-expired error.
      </p>

      <div className="flex items-center gap-3 flex-wrap">
        {!schwab.settings?.connected || schwab.settings?.refresh_expired ? (
          <button
            type="button"
            onClick={schwab.connect}
            disabled={schwab.connecting}
            className="px-4 py-2 rounded-xl bg-brand-500/20 border border-brand-400/30 text-sm text-brand-300 hover:bg-brand-500/30 transition-colors disabled:opacity-40"
          >
            {schwab.connecting ? "Opening…" : "Connect Schwab"}
          </button>
        ) : (
          <>
            <button
              type="button"
              onClick={schwab.refresh}
              disabled={schwab.loading}
              className="px-4 py-2 rounded-xl bg-white/5 border border-white/10 text-sm text-slate-300 hover:bg-white/10 transition-colors disabled:opacity-40"
            >
              {schwab.loading ? "Refreshing…" : "Refresh Status"}
            </button>
            <button
              type="button"
              onClick={schwab.disconnect}
              disabled={schwab.disconnecting}
              className="px-4 py-2 rounded-xl bg-red-500/10 border border-red-400/20 text-sm text-red-400 hover:bg-red-500/20 transition-colors disabled:opacity-40"
            >
              {schwab.disconnecting ? "Disconnecting…" : "Disconnect"}
            </button>
          </>
        )}
      </div>

      {schwab.error && <p className="text-xs text-red-400">{schwab.error}</p>}

      <p className="text-[11px] text-orange-400/70">
        Charles Schwab Individual Trader API is live-only — paper trading is not available.
        Only use with funds you intend to trade.
      </p>
    </div>
  );
}

function IBKRPanel() {
  const ibkr = useIBKRSettings();

  function toggleMode(newPaper: boolean) {
    ibkr.update("paper_mode", newPaper);
    // Auto-sync port only when it's still at an IB Gateway default — never overwrite a custom port
    const currentPort = ibkr.draft.port;
    if (currentPort === 4001 || currentPort === 4002 || currentPort === 7496 || currentPort === 7497) {
      ibkr.update("port", newPaper ? 4002 : 4001);
    }
  }

  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-400 leading-relaxed">
        Run IB Gateway (or TWS) on your machine or a VPS, then enter its address here.
        IB Gateway handles authentication — no password is stored.
      </p>

      {/* Paper / Live toggle — matches Alpaca style */}
      <div className="space-y-1.5">
        <div className="text-[10px] text-slate-500 uppercase tracking-widest font-mono">Account mode</div>
        <div className="flex gap-2">
          {(["paper", "live"] as const).map((mode) => {
            const active = mode === "paper" ? ibkr.draft.paper_mode : !ibkr.draft.paper_mode;
            return (
              <button
                key={mode}
                type="button"
                onClick={() => toggleMode(mode === "paper")}
                className={clsx(
                  "flex-1 py-2 rounded-xl text-xs font-mono font-semibold transition-all border",
                  active
                    ? mode === "paper"
                      ? "border-sky-500/60 bg-sky-500/15 text-sky-300"
                      : "border-amber-500/60 bg-amber-500/15 text-amber-300"
                    : "border-white/5 bg-surface-700 text-slate-500 hover:border-white/10",
                )}
              >
                {mode === "paper" ? "Paper trading" : "Live trading"}
              </button>
            );
          })}
        </div>
        {!ibkr.draft.paper_mode && (
          <SectionNote variant="warn">Live mode places real orders. Ensure IB Gateway is connected to a funded live account.</SectionNote>
        )}
      </div>

      {/* Connection fields */}
      <div className="space-y-2">
        <div className="text-[10px] text-slate-500 uppercase tracking-widest font-mono">IB Gateway connection</div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="space-y-1">
            <label className="text-xs text-slate-400 font-mono">Host</label>
            <input
              type="text"
              placeholder="127.0.0.1"
              value={ibkr.draft.host}
              onChange={(e) => ibkr.update("host", e.target.value)}
              className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm text-brand-100 placeholder-slate-500 font-mono focus:outline-none focus:border-brand-400/50"
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs text-slate-400 font-mono">
              Port
              <span className="text-slate-600 ml-1 normal-case">
                ({ibkr.draft.paper_mode ? "4002 = Gateway paper, 7497 = TWS paper" : "4001 = Gateway live, 7496 = TWS live"})
              </span>
            </label>
            <input
              type="number"
              min={1}
              max={65535}
              value={ibkr.draft.port}
              onChange={(e) => ibkr.update("port", parseInt(e.target.value, 10) || (ibkr.draft.paper_mode ? 4002 : 4001))}
              className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm text-brand-100 font-mono focus:outline-none focus:border-brand-400/50"
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs text-slate-400 font-mono">
              Client ID <span className="text-slate-600">(0–32, unique per simultaneous connection)</span>
            </label>
            <input
              type="number"
              min={0}
              max={32}
              value={ibkr.draft.client_id}
              onChange={(e) => ibkr.update("client_id", parseInt(e.target.value, 10) || 1)}
              className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm text-brand-100 font-mono focus:outline-none focus:border-brand-400/50"
            />
          </div>

          <div className="space-y-1">
            <label className="text-xs text-slate-400 font-mono">
              Account ID <span className="text-slate-600">(optional — auto-detected)</span>
            </label>
            <input
              type="text"
              placeholder="U1234567"
              value={ibkr.draft.account_id}
              onChange={(e) => ibkr.update("account_id", e.target.value)}
              className="w-full px-3 py-2 rounded-lg bg-white/5 border border-white/10 text-sm text-brand-100 placeholder-slate-500 font-mono focus:outline-none focus:border-brand-400/50"
            />
          </div>
        </div>
      </div>

      {/* Save / Remove */}
      <div className="flex items-center gap-3 flex-wrap">
        <button
          type="button"
          onClick={ibkr.save}
          disabled={ibkr.saving || !ibkr.dirty}
          className={clsx(
            "px-4 py-2 rounded-xl text-xs font-mono font-semibold transition-all",
            ibkr.saving || !ibkr.dirty
              ? "bg-surface-700 text-slate-500 cursor-not-allowed"
              : "bg-brand-500 hover:bg-brand-400 text-white",
          )}
        >
          {ibkr.saving ? "Saving…" : ibkr.saved ? "Saved ✓" : "Save IBKR settings"}
        </button>
        {ibkr.settings?.configured && (
          <button
            type="button"
            onClick={ibkr.remove}
            disabled={ibkr.saving}
            className="px-4 py-2 rounded-xl border border-white/10 text-xs font-mono text-slate-400 hover:text-red-400 hover:border-red-400/30 transition-colors disabled:opacity-40"
          >
            Remove
          </button>
        )}
        {ibkr.error && <span className="text-xs text-red-400 font-mono">{ibkr.error}</span>}
      </div>
    </div>
  );
}

type PaperSignalMode = "llm" | "rule-based";

interface AlpacaPanelProps {
  paperSignalMode?: PaperSignalMode;
  onPaperSignalModeChange?: (mode: PaperSignalMode) => void;
}

function AlpacaPanel({ paperSignalMode = "llm", onPaperSignalModeChange }: AlpacaPanelProps) {
  const alpaca = useAlpacaSettings();

  const [draft, setDraft]         = useState<AlpacaSavePayload | null>(null);
  const [apiKeyVal, setApiKeyVal] = useState("");
  const [secKeyVal, setSecKeyVal] = useState("");
  const [apiVisible, setApiVisible] = useState(false);
  const [secVisible, setSecVisible] = useState(false);

  const paperMode = draft?.paper_mode ?? alpaca.settings?.paper_mode ?? true;
  const configured = alpaca.settings?.keys_configured ?? false;

  async function handleSave() {
    const payload: AlpacaSavePayload = {
      paper_mode: paperMode,
      ...(apiKeyVal ? { api_key: apiKeyVal } : {}),
      ...(secKeyVal ? { secret_key: secKeyVal } : {}),
    };
    await alpaca.save(payload);
    setApiKeyVal("");
    setSecKeyVal("");
    setApiVisible(false);
    setSecVisible(false);
    setDraft(null);
  }

  if (!alpaca.settings) {
    return (
      <div className="text-xs text-slate-500 font-mono animate-pulse">
        Loading Alpaca settings… (requires login)
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <SectionNote variant="warn">
        This only affects signals you run manually from the dashboard. The background
        orchestrator always uses the system Alpaca key set in Railway — your open
        positions are never impacted.
      </SectionNote>

      {/* Paper / Live toggle */}
      <div className="space-y-1.5">
        <div className="text-[10px] text-slate-500 uppercase tracking-widest font-mono">Account mode</div>
        <div className="flex gap-2">
          {(["paper", "live"] as const).map((mode) => {
            const active = mode === "paper" ? paperMode : !paperMode;
            return (
              <button
                key={mode}
                onClick={() => setDraft({ paper_mode: mode === "paper" })}
                className={clsx(
                  "flex-1 py-2 rounded-xl text-xs font-mono font-semibold transition-all border",
                  active
                    ? mode === "paper"
                      ? "border-sky-500/60 bg-sky-500/15 text-sky-300"
                      : "border-amber-500/60 bg-amber-500/15 text-amber-300"
                    : "border-white/5 bg-surface-700 text-slate-500 hover:border-white/10",
                )}
              >
                {mode === "paper" ? "Paper trading" : "Live trading"}
              </button>
            );
          })}
        </div>
        {!paperMode && (
          <SectionNote variant="warn">
            Live mode places real orders. Double-check your key is scoped to the correct Alpaca account.
          </SectionNote>
        )}
      </div>

      {/* Signal engine for paper trading */}
      <div className="space-y-1.5">
        <div className="text-[10px] text-slate-500 uppercase tracking-widest font-mono">Signal engine (paper trading)</div>
        <div className="flex gap-2">
          {(["llm", "rule-based"] as const).map((mode) => (
            <button
              key={mode}
              onClick={() => onPaperSignalModeChange?.(mode)}
              className={clsx(
                "flex-1 py-2 rounded-xl text-xs font-mono font-semibold transition-all border",
                paperSignalMode === mode
                  ? "border-brand-500/60 bg-brand-500/15 text-brand-300"
                  : "border-white/5 bg-surface-700 text-slate-500 hover:border-white/10",
              )}
            >
              {mode === "llm" ? "LLM Agents" : "Rule-based"}
            </button>
          ))}
        </div>
        <p className="text-[10px] text-slate-600">
          {paperSignalMode === "llm"
            ? "Paper trading uses the full 27-agent LLM debate for signals. Uses OpenRouter credits."
            : "Paper trading uses fast rule-based analysis with no LLM calls. Zero credit cost."}
        </p>
      </div>

      {/* Key fields */}
      <div className="space-y-2">
        <div className="text-[10px] text-slate-500 uppercase tracking-widest font-mono">API credentials</div>
        {([
          { label: "API Key",    val: apiKeyVal, setVal: setApiKeyVal, visible: apiVisible, setVisible: setApiVisible },
          { label: "Secret Key", val: secKeyVal, setVal: setSecKeyVal, visible: secVisible, setVisible: setSecVisible },
        ]).map(({ label, val, setVal, visible, setVisible }) => (
          <div key={label} className="flex items-center gap-2">
            <div className={clsx(
              "w-2 h-2 rounded-full shrink-0",
              configured ? "bg-emerald-400" : "bg-slate-600",
            )} title={configured ? "Keys saved" : "No keys saved"} />
            <span className="text-xs text-slate-400 w-20 shrink-0 font-mono">{label}</span>
            <div className="flex-1 relative">
              <input
                type={visible ? "text" : "password"}
                value={val}
                onChange={(e) => setVal(e.target.value)}
                placeholder={configured ? "••••••••  (leave blank to keep saved key)" : "Paste key…"}
                className="w-full bg-surface-700 border border-white/5 rounded-xl px-3 py-1.5 text-xs font-mono text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-brand-500/40 pr-8"
              />
              <button
                type="button"
                onClick={() => setVisible((v) => !v)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-600 hover:text-slate-400 text-[10px] font-mono"
              >
                {visible ? "hide" : "show"}
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* Save button */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleSave}
          disabled={alpaca.saving}
          className={clsx(
            "px-4 py-2 rounded-xl text-xs font-mono font-semibold transition-all",
            alpaca.saving
              ? "bg-surface-700 text-slate-500 cursor-not-allowed"
              : "bg-brand-500 hover:bg-brand-400 text-white",
          )}
        >
          {alpaca.saving ? "Saving…" : alpaca.saved ? "Saved ✓" : "Save Alpaca settings"}
        </button>
        {alpaca.error && (
          <span className="text-xs text-red-400 font-mono">{alpaca.error}</span>
        )}
      </div>
    </div>
  );
}


// ── Brain / LLM configuration panel ──────────────────────────────────────────

const PROVIDER_LABELS: Record<string, string> = {
  openrouter: "OpenRouter",
  openai:     "OpenAI",
  anthropic:  "Anthropic",
  deepseek:   "DeepSeek",
  xai:        "xAI (Grok)",
  qwen:       "Qwen (Alibaba)",
  kimi:       "Kimi (Moonshot)",
};

const LOW_CONFIDENCE_PROVIDERS = new Set(["qwen", "kimi"]);

const PROVIDER_KEY_FIELDS: { provider: string; field: keyof LlmSavePayload }[] = [
  { provider: "openrouter", field: "openrouter_key" },
  { provider: "openai",     field: "openai_key" },
  { provider: "anthropic",  field: "anthropic_key" },
  { provider: "deepseek",   field: "deepseek_key" },
  { provider: "xai",        field: "xai_key" },
  { provider: "qwen",       field: "qwen_key" },
  { provider: "kimi",       field: "kimi_key" },
];

function BrainLLMPanel() {
  const llm = useLlmSettings();

  // Local draft — tracks in-progress changes before Save
  const [draft, setDraft] = useState<LlmSavePayload | null>(null);
  // Tracks which key fields have been touched (to know if a value should be sent)
  const [keyDraft, setKeyDraft] = useState<Record<string, string>>({});
  // Controls key field visibility (show/hide per provider)
  const [keyVisible, setKeyVisible] = useState<Record<string, boolean>>({});

  const base: LlmSavePayload = draft ?? {
    tactical_provider:  llm.settings?.tactical_provider  ?? "openrouter",
    tactical_model:     llm.settings?.tactical_model     ?? "google/gemini-2.5-flash-lite",
    synthesis_provider: llm.settings?.synthesis_provider ?? "openrouter",
    synthesis_model:    llm.settings?.synthesis_model    ?? "deepseek/deepseek-chat-v3-0324",
  };

  function updateDraft(partial: Partial<LlmSavePayload>) {
    setDraft((prev) => ({ ...(prev ?? base), ...partial }));
  }

  const providers = llm.models?.providers ?? PROVIDER_LABELS;
  const modelsByProvider = llm.models?.models ?? {};
  const confidenceNotes = llm.models?.confidence_notes ?? {};
  const keysConfigured = new Set(llm.settings?.keys_configured ?? []);

  function modelsFor(provider: string): string[] {
    return modelsByProvider[provider] ?? [];
  }

  async function handleSave() {
    const payload: LlmSavePayload = {
      ...base,
      ...keyDraft,  // include any key fields the user typed
    };
    await llm.save(payload);
    setKeyDraft({});
    setKeyVisible({});
  }

  if (!llm.settings && !llm.models) {
    return (
      <div className="text-xs text-slate-500 font-mono animate-pulse">
        Loading Brain settings… (requires login)
      </div>
    );
  }

  function ProviderSelect({ label, value, onChange }: {
    label: string; value: string; onChange: (v: string) => void;
  }) {
    return (
      <div className="space-y-1.5">
        <span className="text-xs text-slate-400">{label}</span>
        <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
          {Object.entries(providers).map(([key, name]) => (
            <button key={key} onClick={() => onChange(key)}
              className={clsx(
                "py-2 px-2 rounded-xl text-xs font-medium border transition-all text-center leading-tight",
                value === key
                  ? "bg-brand-500/20 border-brand-500/40 text-brand-300"
                  : "border-white/5 text-slate-400 hover:text-slate-200 hover:border-white/10",
              )}
            >
              {name}
              {LOW_CONFIDENCE_PROVIDERS.has(key) && (
                <div className="text-[9px] text-amber-400/70 mt-0.5">~{key === "qwen" ? "92" : "90"}% conf</div>
              )}
            </button>
          ))}
        </div>
        {LOW_CONFIDENCE_PROVIDERS.has(value) && (
          <SectionNote variant="warn">{confidenceNotes[value] ?? `${value} endpoint confidence is below 95% — verify the URL before use.`}</SectionNote>
        )}
      </div>
    );
  }

  function ModelSelect({ label, provider, value, onChange }: {
    label: string; provider: string; value: string; onChange: (v: string) => void;
  }) {
    const [custom, setCustom] = useState(false);
    const models = modelsFor(provider);
    const isKnown = models.includes(value);
    return (
      <div className="space-y-1.5">
        <span className="text-xs text-slate-400">{label}</span>
        {models.length > 0 && !custom ? (
          <>
            <div className="space-y-1">
              {models.map((m) => (
                <button key={m} onClick={() => onChange(m)}
                  className={clsx(
                    "w-full text-left px-3 py-2 rounded-lg text-xs font-mono border transition-all",
                    value === m
                      ? "bg-brand-500/15 border-brand-500/30 text-brand-300"
                      : "border-white/5 text-slate-400 hover:text-slate-200 hover:border-white/10",
                  )}
                >{m}</button>
              ))}
            </div>
            <button onClick={() => setCustom(true)} className="text-[11px] text-slate-500 hover:text-slate-300 font-mono underline">
              Enter custom model ID
            </button>
          </>
        ) : (
          <>
            <input
              type="text"
              value={value}
              onChange={(e) => onChange(e.target.value)}
              placeholder="e.g. provider/model-name"
              className="w-full bg-surface-700 border border-white/10 rounded-xl px-3 py-2 text-xs font-mono text-slate-200 outline-none focus:ring-1 focus:ring-brand-500"
            />
            {models.length > 0 && (
              <button onClick={() => { setCustom(false); if (!isKnown) onChange(models[0]); }}
                className="text-[11px] text-slate-500 hover:text-slate-300 font-mono underline">
                Choose from list
              </button>
            )}
          </>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <SectionNote>
        Each user configures their own LLM provider and API key — stored encrypted in your session.
        Keys are <strong>write-only</strong>: once saved, values are never returned.
        The auto-trader orchestrator always uses the system OpenRouter key; only browser-initiated
        signals use these per-user settings.
      </SectionNote>

      {/* ── Tactical agents (25 analysts + personas) ─────────────────────── */}
      <SubSection title="Tactical Agents (25 analysts)" />
      <ProviderSelect
        label="Provider"
        value={base.tactical_provider}
        onChange={(v) => updateDraft({ tactical_provider: v, tactical_model: modelsFor(v)[0] ?? base.tactical_model })}
      />
      <ModelSelect
        label="Model"
        provider={base.tactical_provider}
        value={base.tactical_model}
        onChange={(v) => updateDraft({ tactical_model: v })}
      />

      {/* ── Synthesis agents (StrategyCoach + RiskManager) ───────────────── */}
      <SubSection title="Synthesis Agents (StrategyCoach + RiskManager)" />
      <ProviderSelect
        label="Provider"
        value={base.synthesis_provider}
        onChange={(v) => updateDraft({ synthesis_provider: v, synthesis_model: modelsFor(v)[0] ?? base.synthesis_model })}
      />
      <ModelSelect
        label="Model"
        provider={base.synthesis_provider}
        value={base.synthesis_model}
        onChange={(v) => updateDraft({ synthesis_model: v })}
      />

      {/* ── API Keys (write-only) ─────────────────────────────────────────── */}
      <SubSection title="API Keys" />
      <SectionNote>
        Enter the API key for each provider you use. Leave blank to keep the stored key unchanged.
        A green dot indicates a key is already saved.
      </SectionNote>
      <div className="space-y-2">
        {PROVIDER_KEY_FIELDS.map(({ provider, field }) => {
          const isSet = keysConfigured.has(provider);
          const isVisible = keyVisible[provider];
          return (
            <div key={provider} className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-400 w-28 shrink-0 font-mono">{PROVIDER_LABELS[provider]}</span>
                {isSet && !keyDraft[field as string] && (
                  <span className="w-2 h-2 rounded-full bg-emerald-400 shrink-0" title="Key saved" />
                )}
                <div className="flex-1 relative">
                  <input
                    type={isVisible ? "text" : "password"}
                    value={keyDraft[field as string] ?? ""}
                    onChange={(e) => setKeyDraft((prev) => ({ ...prev, [field as string]: e.target.value }))}
                    placeholder={isSet ? "••••••••  (stored — leave blank to keep)" : "Paste API key…"}
                    autoComplete="off"
                    className="w-full bg-surface-700 border border-white/10 rounded-lg px-3 py-1.5 text-xs font-mono text-slate-200 outline-none focus:ring-1 focus:ring-brand-500 pr-16"
                  />
                  <button
                    type="button"
                    onClick={() => setKeyVisible((p) => ({ ...p, [provider]: !p[provider] }))}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] text-slate-500 hover:text-slate-300 font-mono"
                  >
                    {isVisible ? "hide" : "show"}
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* ── Error / Save ──────────────────────────────────────────────────── */}
      {llm.error && <p className="text-xs text-red-400 font-mono">{llm.error}</p>}
      <button
        onClick={handleSave}
        disabled={llm.saving}
        className="w-full py-2 rounded-xl bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-xs font-medium transition-colors"
      >
        {llm.saving ? "Saving…" : llm.saved ? "Saved ✓" : "Save Brain settings"}
      </button>
    </div>
  );
}

// ── Full engine config panel ──────────────────────────────────────────────────

type EngineLocal = RiskConfigFields;

const ENGINE_DEFAULTS: EngineLocal = {
  stop_loss_pct: 0.02, take_profit_pct: 0.05, trailing_stop_pct: 0.015,
  partial_exit_pct: 0.50, runner_trail_pct: 0.10,
  max_position_pct: 0.05, hot_position_pct: 0.08, max_crypto_allocation_pct: 0.30,
  max_exposure_pct: 0.50, max_concurrent_positions: 15,
  circuit_breaker_drawdown: 0.10, drawdown_scale_threshold: 0.08, drawdown_scale_factor: 0.80,
  correlation_halving_threshold: 0.70,
  signal_confidence_threshold: 0.70, lookback_days: 300,
  atr_multiplier: 1.5, atr_stop_floor: 0.005, atr_stop_cap: 0.04,
  loss_cooldown_hits: 2, loss_cooldown_window_days: 5, loss_cooldown_skip_cycles: 2,
  max_telegram_order_usd: 1000,
  max_watch_rules: 10,
};

function EngineConfigPanel() {
  const riskCfg = useRiskConfig();
  const [local, setLocal] = useState<EngineLocal | null>(null);

  const c = riskCfg.config;
  const vals: EngineLocal = local ?? (c ? { ...c } : ENGINE_DEFAULTS);

  function set<K extends keyof EngineLocal>(key: K) {
    return (v: EngineLocal[K]) => setLocal({ ...vals, [key]: v });
  }

  return (
    <div className="space-y-4">
      <SectionNote>
        All parameters below control the live auto-trader. Changes apply on the next monitor tick
        (&le;1 min) without a redeploy. The <strong>Reset</strong> button reverts to Railway env var
        defaults.
        {c && (
          <span className={clsx(
            "ml-1.5 px-1.5 py-0.5 rounded text-[10px] font-semibold",
            c.source === "dynamic" ? "bg-brand-500/20 text-brand-300" : "bg-slate-500/20 text-slate-400",
          )}>
            {c.source === "dynamic" ? "custom values active" : "using Railway defaults"}
          </span>
        )}
      </SectionNote>

      {c === null ? (
        <div className="text-xs text-slate-500 font-mono animate-pulse">Loading engine config…</div>
      ) : (
        <>
          {/* ── Entry / Exit ───────────────────────────────────────────────── */}
          <SubSection title="Entry / Exit" />

          <SectionNote variant="warn">
            <strong>Stop Loss</strong> is the <em>fallback</em> used only when ATR data is unavailable.
            The actual stop placed on Alpaca is ATR-based: <strong>atr_multiplier × ATR14</strong>,
            clamped to [ATR Floor, ATR Cap] below. Set those to control real stop width.
          </SectionNote>
          <RiskRow label="Stop Loss (ATR fallback)" value={vals.stop_loss_pct} options={[1,2,3,5]} onChange={set("stop_loss_pct")} valueColor="text-red-400" />

          <SectionNote variant="warn">
            <strong>Take Profit</strong> is the base TP. The orchestrator adjusts it by regime:
            TRENDING_UP → min 8% · RANGING → max 3% · HIGH_VOLATILITY → max 5%.
            These regime overrides override whatever value you set here.
          </SectionNote>
          <RiskRow label="Take Profit (base)" value={vals.take_profit_pct} options={[3,5,8,10,15]} onChange={set("take_profit_pct")} valueColor="text-emerald-400" />

          <RiskRow label="Trailing Stop %" value={vals.trailing_stop_pct} options={[1,1.5,2,2.5,3]} onChange={set("trailing_stop_pct")} valueColor="text-sky-400"
            formatFn={(v) => `${(v * 100).toFixed(1)}%`} />

          <RiskRow label="Partial Exit (Layer 1 fraction)" value={vals.partial_exit_pct} options={[25,33,40,50]} onChange={set("partial_exit_pct")} valueColor="text-sky-400"
            formatFn={(v) => `${(v * 100).toFixed(0)}%`} />

          <RiskRow label="Runner Trail %" value={vals.runner_trail_pct} options={[5,8,10,12,15]} onChange={set("runner_trail_pct")} valueColor="text-sky-400"
            formatFn={(v) => `${(v * 100).toFixed(0)}%`} />

          {/* ── Position Sizing ────────────────────────────────────────────── */}
          <SubSection title="Position Sizing" />

          <RiskRow label="Max Position % (WARM signals)" value={vals.max_position_pct} options={[3,5,8,10]} onChange={set("max_position_pct")} valueColor="text-amber-400" />
          <RiskRow label="Max Position % (HOT signals)" value={vals.hot_position_pct} options={[5,8,10,15]} onChange={set("hot_position_pct")} valueColor="text-amber-400" />
          <RiskRow label="Max Crypto Allocation" value={vals.max_crypto_allocation_pct} options={[10,20,30,40]} onChange={set("max_crypto_allocation_pct")} valueColor="text-violet-400" />

          {/* ── Portfolio Exposure ─────────────────────────────────────────── */}
          <SubSection title="Portfolio Exposure" />

          <RiskRow label="Max Portfolio Exposure" value={vals.max_exposure_pct} options={[30,40,50,62,75]} onChange={set("max_exposure_pct")} valueColor="text-amber-400"
            formatFn={(v) => `${(v * 100).toFixed(0)}%`} />

          <RawRow label="Max Concurrent Positions"
            value={vals.max_concurrent_positions} options={[5,10,15,20,25]}
            onChange={set("max_concurrent_positions")} valueColor="text-amber-400"
            display={(v) => `${v}`} optLabel={(o) => `${o}`} />

          {/* ── Circuit Breaker / Drawdown ─────────────────────────────────── */}
          <SubSection title="Circuit Breaker &amp; Drawdown" />

          <RiskRow label="Circuit Breaker (halt all trading)" value={vals.circuit_breaker_drawdown} options={[5,10,15,20]} onChange={set("circuit_breaker_drawdown")} valueColor="text-orange-400" />
          <RiskRow label="Drawdown Scale Threshold" value={vals.drawdown_scale_threshold} options={[5,8,10,15]} onChange={set("drawdown_scale_threshold")} valueColor="text-orange-400" />
          <RiskRow label="Drawdown Scale Factor" value={vals.drawdown_scale_factor} options={[60,70,80,90]} onChange={set("drawdown_scale_factor")} valueColor="text-orange-400"
            formatFn={(v) => `${(v * 100).toFixed(0)}%`} />

          {/* ── Correlation ────────────────────────────────────────────────── */}
          <SubSection title="Correlation Protection" />

          <SectionNote>
            When a new BUY signal correlates above this threshold with any open position over the last
            60 days, the position size is automatically halved.
          </SectionNote>
          <RiskRow label="Correlation Halving Threshold" value={vals.correlation_halving_threshold} options={[50,60,70,80]} onChange={set("correlation_halving_threshold")}
            valueColor="text-slate-300" formatFn={(v) => `${(v * 100).toFixed(0)}%`} />

          {/* ── ATR Stop Sizing ────────────────────────────────────────────── */}
          <SubSection title="ATR Stop Sizing" />

          <SectionNote>
            Actual stop = <strong>ATR Multiplier × ATR14</strong>, then clamped to [Floor, Cap].
            Higher multiplier = wider stops (fewer false exits). Raise the Cap to allow wider stops
            on volatile stocks.
          </SectionNote>
          <RawRow label="ATR Multiplier"
            value={vals.atr_multiplier} options={[1.0,1.5,2.0,2.5]}
            onChange={set("atr_multiplier")} valueColor="text-sky-400"
            display={(v) => `${v.toFixed(1)}×`} optLabel={(o) => `${o}×`} />
          <RiskRow label="ATR Floor (min stop)" value={vals.atr_stop_floor} options={[0.25,0.5,1.0]} onChange={set("atr_stop_floor")} valueColor="text-sky-400" />
          <RiskRow label="ATR Cap (max stop)" value={vals.atr_stop_cap} options={[2,3,4,5]} onChange={set("atr_stop_cap")} valueColor="text-sky-400" />

          {/* ── Signal Quality ─────────────────────────────────────────────── */}
          <SubSection title="Signal Quality" />

          <RiskRow label="Signal Confidence Threshold" value={vals.signal_confidence_threshold} options={[50,60,70,80]} onChange={set("signal_confidence_threshold")}
            valueColor="text-violet-400" formatFn={(v) => `${(v * 100).toFixed(0)}%`} />

          <RawRow label="Lookback Days (historical window)"
            value={vals.lookback_days} options={[90,150,200,300]}
            onChange={set("lookback_days")} valueColor="text-violet-400"
            display={(v) => `${v}d`} optLabel={(o) => `${o}d`} />

          {/* ── Loss Cooldown ──────────────────────────────────────────────── */}
          <SubSection title="Loss Cooldown" />

          <SectionNote>
            When a symbol hits stop-loss <strong>N times within W days</strong>, it is skipped for
            the next <strong>S scan cycles</strong>. Prevents re-entering a symbol that is breaking down.
          </SectionNote>
          <RawRow label="Trigger Hits"
            value={vals.loss_cooldown_hits} options={[1,2,3,5]}
            onChange={set("loss_cooldown_hits")} valueColor="text-orange-400"
            display={(v) => `${v} hits`} optLabel={(o) => `${o}`} />
          <RawRow label="Lookback Window"
            value={vals.loss_cooldown_window_days} options={[3,5,7,14]}
            onChange={set("loss_cooldown_window_days")} valueColor="text-orange-400"
            display={(v) => `${v} days`} optLabel={(o) => `${o}d`} />
          <RawRow label="Skip Cycles on Cooldown"
            value={vals.loss_cooldown_skip_cycles} options={[1,2,3,5]}
            onChange={set("loss_cooldown_skip_cycles")} valueColor="text-orange-400"
            display={(v) => `${v} cycles`} optLabel={(o) => `${o}`} />

          {/* ── Telegram ──────────────────────────────────────────────────── */}
          <SubSection title="Telegram Safety" />

          <RawRow label="Max Order Size (USD)"
            value={vals.max_telegram_order_usd} options={[100,500,1000,5000,10000]}
            onChange={set("max_telegram_order_usd")} valueColor="text-slate-300"
            display={(v) => `$${v.toLocaleString()}`} optLabel={(o) => `$${(o >= 1000 ? `${o / 1000}k` : o)}`} />

          {/* ── Brain watch rules ─────────────────────────────────────────── */}
          <SubSection title="Brain Watch Rules" />

          <RawRow label="Max Active Rules (per user)"
            value={vals.max_watch_rules} options={[5,10,20,50]}
            onChange={set("max_watch_rules")} valueColor="text-amber-400"
            display={(v) => `${v} rules`} optLabel={(o) => `${o}`} />

          {/* ── Errors & actions ──────────────────────────────────────────── */}
          {riskCfg.error && <p className="text-xs text-red-400 font-mono">{riskCfg.error}</p>}

          <div className="flex gap-2 pt-1">
            <button
              onClick={() => riskCfg.save(vals)}
              disabled={riskCfg.saving}
              className="flex-1 py-2 rounded-xl bg-brand-600 hover:bg-brand-500 disabled:opacity-50 text-xs font-medium transition-colors"
            >
              {riskCfg.saving ? "Saving…" : riskCfg.saved ? "Saved ✓" : "Push to engine"}
            </button>
            <button
              onClick={() => { riskCfg.reset(); setLocal(null); }}
              disabled={riskCfg.saving}
              title="Reset to Railway env var defaults"
              className="px-3 py-2 rounded-xl border border-white/10 text-slate-400 hover:text-slate-200 hover:border-white/20 transition-colors disabled:opacity-50"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          </div>

          {c.source === "dynamic" && (
            <p className="text-[10px] text-slate-500 font-mono">
              Railway defaults: SL {(c.defaults.stop_loss_pct * 100).toFixed(1)}% · TP {(c.defaults.take_profit_pct * 100).toFixed(1)}%
              · Trail {(c.defaults.trailing_stop_pct * 100).toFixed(1)}% · MaxPos {(c.defaults.max_position_pct * 100).toFixed(0)}%
              &nbsp;— &uarr; to revert.
            </p>
          )}
        </>
      )}
    </div>
  );
}

// ── Kraken panel ─────────────────────────────────────────────────────────────

function KrakenPanel() {
  const k = useKrakenSettings();
  return (
    <div className="space-y-4">
      <SectionNote variant="warn">
        Kraken spot operates in <strong>live mode only</strong> — paper trading is not supported.
      </SectionNote>
      {k.settings?.configured && (
        <div className="flex items-center gap-2 text-xs text-emerald-400 font-mono">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          API key configured · prefix: {k.settings.key_prefix}
        </div>
      )}
      <div className="space-y-3">
        <div className="space-y-1">
          <label className="text-xs text-slate-400 font-mono">API Key</label>
          <input
            type="password"
            placeholder={k.settings?.configured ? "Leave blank to keep existing" : "Kraken API key"}
            value={k.apiKey}
            onChange={(e) => k.setApiKey(e.target.value)}
            className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-brand-500/40"
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-slate-400 font-mono">API Secret</label>
          <input
            type="password"
            placeholder={k.settings?.configured ? "Leave blank to keep existing" : "Base64-encoded secret"}
            value={k.apiSecret}
            onChange={(e) => k.setApiSecret(e.target.value)}
            className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-brand-500/40"
          />
        </div>
      </div>
      {k.error && <p className="text-xs text-red-400 font-mono">{k.error}</p>}
      {k.saved && <p className="text-xs text-emerald-400 font-mono">Saved.</p>}
      <div className="flex gap-2">
        <button
          onClick={k.save}
          disabled={k.saving || (!k.apiKey && !k.apiSecret)}
          className="flex-1 py-2 rounded-xl bg-brand-600 hover:bg-brand-500 disabled:opacity-40 text-sm font-semibold transition-colors"
        >
          {k.saving ? "Saving…" : "Save credentials"}
        </button>
        {k.settings?.configured && (
          <button
            onClick={k.remove}
            disabled={k.saving}
            className="px-4 py-2 rounded-xl border border-red-500/30 text-red-400 hover:bg-red-500/10 text-sm transition-colors disabled:opacity-40"
          >
            Disconnect
          </button>
        )}
      </div>
    </div>
  );
}

// ── Coinbase panel ────────────────────────────────────────────────────────────

function CoinbasePanel() {
  const cb = useCoinbaseSettings();
  return (
    <div className="space-y-4">
      <SectionNote variant="warn">
        Coinbase Advanced Trade operates in <strong>live mode only</strong>. Use CDP (Cloud Developer Platform) API keys — generate them at <span className="font-mono">cloud.coinbase.com/access/api</span>.
      </SectionNote>
      {cb.settings?.configured && (
        <div className="flex items-center gap-2 text-xs text-emerald-400 font-mono">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          Connected · {cb.settings.api_key_name}
        </div>
      )}
      <div className="space-y-3">
        <div className="space-y-1">
          <label className="text-xs text-slate-400 font-mono">API Key Name</label>
          <input
            type="text"
            placeholder="organizations/…/apiKeys/…"
            value={cb.keyName}
            onChange={(e) => cb.setKeyName(e.target.value)}
            className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-brand-500/40"
          />
        </div>
        <div className="space-y-1">
          <label className="text-xs text-slate-400 font-mono">Private Key (PEM)</label>
          <textarea
            rows={5}
            placeholder={"-----BEGIN EC PRIVATE KEY-----\n…\n-----END EC PRIVATE KEY-----"}
            value={cb.privateKey}
            onChange={(e) => cb.setPrivateKey(e.target.value)}
            className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-brand-500/40 resize-none"
          />
        </div>
      </div>
      {cb.error && <p className="text-xs text-red-400 font-mono">{cb.error}</p>}
      {cb.saved && <p className="text-xs text-emerald-400 font-mono">Saved.</p>}
      <div className="flex gap-2">
        <button
          onClick={cb.save}
          disabled={cb.saving || (!cb.keyName && !cb.privateKey)}
          className="flex-1 py-2 rounded-xl bg-brand-600 hover:bg-brand-500 disabled:opacity-40 text-sm font-semibold transition-colors"
        >
          {cb.saving ? "Saving…" : "Save credentials"}
        </button>
        {cb.settings?.configured && (
          <button
            onClick={cb.remove}
            disabled={cb.saving}
            className="px-4 py-2 rounded-xl border border-red-500/30 text-red-400 hover:bg-red-500/10 text-sm transition-colors disabled:opacity-40"
          >
            Disconnect
          </button>
        )}
      </div>
    </div>
  );
}

// ── TradeStation panel ────────────────────────────────────────────────────────

function TradeStationPanel() {
  const ts = useTradeStationSettings();
  const isPaper = ts.settings?.paper_mode ?? false;
  return (
    <div className="space-y-4">
      {ts.settings?.connected ? (
        <>
          <div className="flex items-center gap-2 text-xs text-emerald-400 font-mono">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            Connected · {isPaper ? "SIM (paper)" : "Live"} · {ts.settings.account_number}
          </div>
          <SectionNote variant={isPaper ? "info" : "warn"}>
            {isPaper
              ? "SIM account — orders go to the TradeStation paper trading environment."
              : "Live account — orders execute with real money."}
          </SectionNote>
          <div className="space-y-1">
            <label className="text-xs text-slate-400 font-mono">Account Number</label>
            <input
              type="text"
              value={ts.accountDraft}
              onChange={(e) => ts.setAccountDraft(e.target.value)}
              placeholder="e.g. 123456 or SIM123456"
              className="w-full bg-white/5 border border-white/10 rounded-lg px-3 py-2 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-brand-500/40"
            />
          </div>
          <p className="text-[10px] text-slate-500 font-mono">
            Prefix with SIM to switch to paper trading (e.g. SIM123456).
          </p>
          {ts.error && <p className="text-xs text-red-400 font-mono">{ts.error}</p>}
          {ts.saved && <p className="text-xs text-emerald-400 font-mono">Account updated.</p>}
          <div className="flex gap-2">
            <button
              onClick={ts.saveAccount}
              disabled={ts.saving || !ts.accountDraft.trim()}
              className="flex-1 py-2 rounded-xl bg-brand-600 hover:bg-brand-500 disabled:opacity-40 text-sm font-semibold transition-colors"
            >
              {ts.saving ? "Saving…" : "Update account"}
            </button>
            <button
              onClick={ts.disconnect}
              disabled={ts.saving}
              className="px-4 py-2 rounded-xl border border-red-500/30 text-red-400 hover:bg-red-500/10 text-sm transition-colors disabled:opacity-40"
            >
              Disconnect
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="text-sm text-slate-400">
            Connect your TradeStation account via OAuth. You will be redirected to TradeStation to authorise access, then returned here.
          </p>
          <SectionNote variant="info">
            Paper trading uses a SIM account — enter your SIM account number after connecting.
          </SectionNote>
          {ts.error && <p className="text-xs text-red-400 font-mono">{ts.error}</p>}
          <button
            onClick={ts.connect}
            className="w-full py-2 rounded-xl bg-brand-600 hover:bg-brand-500 text-sm font-semibold transition-colors"
          >
            Connect TradeStation
          </button>
        </>
      )}
    </div>
  );
}

// ── Disclosure Tracker settings panel ────────────────────────────────────────

function DisclosureSettingsPanel() {
  const { settings, saving, saved, error, save } = useDisclosureSettings();
  const [draft, setDraft] = useState<Partial<DisclosureSettings>>({});

  if (!settings) return <p className="text-xs text-slate-500">Loading…</p>;

  const field = <K extends keyof DisclosureSettings>(key: K) =>
    (draft[key] !== undefined ? draft[key] : settings[key]) as DisclosureSettings[K];

  const update = (k: keyof DisclosureSettings, v: string | number) =>
    setDraft(d => ({ ...d, [k]: v }));

  function handleSave() {
    if (Object.keys(draft).length === 0) return;
    save(draft).then(() => setDraft({}));
  }

  const textInput = (key: keyof DisclosureSettings, label: string, hint: string, placeholder = "") => (
    <div className="space-y-1">
      <label className="text-[11px] text-slate-400 uppercase tracking-wide">{label}</label>
      <input
        type="text"
        value={String(field(key))}
        onChange={e => update(key, e.target.value)}
        placeholder={placeholder}
        className="w-full bg-surface-700 border border-white/10 rounded-xl px-4 py-2.5 text-sm font-mono text-slate-200 outline-none focus:ring-1 focus:ring-brand-500"
      />
      <p className="text-[11px] text-slate-500">{hint}</p>
    </div>
  );

  const numInput = (key: keyof DisclosureSettings, label: string, hint: string, min = 1, max = 9999) => (
    <div className="space-y-1">
      <label className="text-[11px] text-slate-400 uppercase tracking-wide">{label}</label>
      <input
        type="number" min={min} max={max} step={1}
        value={Number(field(key))}
        onChange={e => { const v = parseInt(e.target.value); if (!isNaN(v)) update(key, v); }}
        className="w-full bg-surface-700 border border-white/10 rounded-xl px-4 py-2.5 text-sm font-mono text-slate-200 outline-none focus:ring-1 focus:ring-brand-500"
      />
      <p className="text-[11px] text-slate-500">{hint}</p>
    </div>
  );

  return (
    <div className="space-y-4">
      <SubSection title="SEC EDGAR" />
      {textInput(
        "edgar_user_agent",
        "EDGAR User-Agent",
        "Required by SEC fair-use policy. Must include your app name and contact email.",
        "TradingAgentAI/1.0 you@example.com"
      )}
      {numInput("edgar_request_timeout_secs", "Request timeout (seconds)", "How long to wait for an EDGAR response before giving up.", 5, 120)}
      {numInput("edgar_rate_limit_sleep_secs", "Rate-limit sleep (seconds)", "Pause between investor fetches to stay within SEC's 10 req/sec fair-use limit.", 0, 60)}

      <SubSection title="Congressional Feed URLs" />
      {textInput("house_feed_url", "House feed URL", "JSON API endpoint for House STOCK Act disclosures.", "https://housestockwatcher.com/api")}
      {textInput("senate_feed_url", "Senate feed URL", "JSON API endpoint for Senate STOCK Act disclosures.", "https://senatestockwatcher.com/api")}
      {numInput("congress_request_timeout_secs", "Request timeout (seconds)", "How long to wait for congressional feed responses.", 5, 120)}

      <SubSection title="Refresh Schedule" />
      {numInput("congress_refresh_hours", "Congress refresh interval (hours)", "How often the orchestrator pulls new STOCK Act disclosures. Changes take effect on next restart.", 1, 168)}
      {numInput("holdings_refresh_hours", "13F holdings refresh interval (hours)", "How often the orchestrator fetches new 13F filings from EDGAR. Daily (24h) is recommended.", 1, 168)}

      <SubSection title="Congressional Data Source" />
      <SectionNote variant="warn">
        The original free feeds (HouseStockWatcher, SenateStockWatcher) are no longer reachable.
        Add a free Quiver Quantitative API key to restore congressional trade data.
        Register at quiverquant.com — the free tier includes congressional trading.
      </SectionNote>
      <div className="space-y-1">
        <label className="text-[11px] text-slate-400 uppercase tracking-wide">
          Quiver Quantitative API Key
          {settings.quiver_api_key_configured && (
            <span className="text-emerald-400/80 ml-2 normal-case">(key saved)</span>
          )}
        </label>
        <input
          type="password"
          value={draft.quiver_api_key ?? ""}
          onChange={e => update("quiver_api_key", e.target.value)}
          placeholder={settings.quiver_api_key_configured ? "leave blank to keep saved key" : "Paste your Quiver Quantitative API key…"}
          className="w-full bg-surface-700 border border-white/10 rounded-xl px-4 py-2.5 text-sm font-mono text-slate-200 outline-none focus:ring-1 focus:ring-brand-500"
        />
        <p className="text-[11px] text-slate-500">
          Free at quiverquant.com → Dashboard → API Key. Enables congressional STOCK Act trade data.
        </p>
      </div>

      <SubSection title="Display Filter" />
      {numInput("min_confidence_pct", "Minimum confidence % to display", "Investors and congress members below this threshold are hidden in the Disclosures page.", 0, 100)}

      <div className="flex items-center gap-3 pt-2">
        <button
          onClick={handleSave}
          disabled={saving || Object.keys(draft).length === 0}
          className="flex-1 py-2.5 rounded-xl bg-brand-600 hover:bg-brand-500 disabled:opacity-40 text-sm font-medium transition-colors"
        >
          {saved ? "Saved ✓" : saving ? "Saving…" : "Save disclosure settings"}
        </button>
      </div>
      {error && <p className="text-[11px] text-red-400 font-mono">{error}</p>}
    </div>
  );
}

// ── FMP API key panel ─────────────────────────────────────────────────────────

function FmpKeyPanel() {
  const { settings, saving, saved, error: fmpError, saveKey, removeKey } = useFmpSettings();
  const [input, setInput] = useState("");
  const [showKey, setShowKey] = useState(false);

  if (!settings) return <div className="text-xs text-slate-500 animate-pulse">Loading…</div>;

  const src = settings.effective_source;

  return (
    <div className="space-y-3">
      {/* Current state */}
      {src === "user" && (
        <div className="flex items-center justify-between text-xs bg-emerald-500/10 border border-emerald-500/25 rounded-xl px-4 py-2.5">
          <span className="text-emerald-300">Your FMP API key is active</span>
          <button
            onClick={() => removeKey()}
            disabled={saving}
            className="text-slate-500 hover:text-red-400 transition-colors disabled:opacity-40"
          >
            Remove
          </button>
        </div>
      )}
      {src === "system" && (
        <div className="text-[11px] text-slate-500 font-mono bg-surface-700 rounded-xl px-3 py-2">
          Using system-wide FMP key (free tier). Add your own key below for higher limits.
        </div>
      )}
      {src === "none" && (
        <div className="text-[11px] text-amber-400/80 font-mono bg-amber-500/10 border border-amber-500/20 rounded-xl px-3 py-2">
          No FMP key configured — Research page uses free tier (limited requests/min).
        </div>
      )}

      {/* Key input */}
      {src !== "user" && (
        <div className="space-y-2">
          <label className="text-[11px] text-slate-400 font-mono">Financial Modeling Prep API key</label>
          <div className="flex gap-2">
            <input
              type={showKey ? "text" : "password"}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && input.trim()) saveKey(input.trim()).then(() => setInput("")); }}
              placeholder="Enter your FMP API key…"
              className="flex-1 bg-surface-700 border border-white/10 rounded-xl px-3 py-2 text-xs font-mono text-slate-200 placeholder-slate-600 focus:outline-none focus:border-brand-500/50"
            />
            <button
              onClick={() => setShowKey((v) => !v)}
              className="px-3 text-xs text-slate-500 hover:text-slate-300 transition-colors"
            >
              {showKey ? "Hide" : "Show"}
            </button>
            <button
              onClick={() => saveKey(input.trim()).then(() => setInput(""))}
              disabled={saving || !input.trim()}
              className="px-4 py-2 rounded-xl bg-brand-500/20 text-brand-300 text-xs font-medium hover:bg-brand-500/30 transition-colors disabled:opacity-40"
            >
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      )}

      {saved      && <p className="text-[11px] text-emerald-400 font-mono">Saved — key is isolated to your account only.</p>}
      {fmpError   && <p className="text-[11px] text-red-400 font-mono">{fmpError}</p>}

      <SectionNote>
        Your key is encrypted at rest and tied strictly to your session — other users cannot access it.
        Get a free key at{" "}
        <a href="https://financialmodelingprep.com/developer/docs" target="_blank" rel="noreferrer" className="underline">
          financialmodelingprep.com
        </a>.
      </SectionNote>
    </div>
  );
}

// ── Demo account snapshot panel ───────────────────────────────────────────────

function DemoSnapshotPanel() {
  const [info, setInfo]       = useState<{ available: boolean; captured_at: string | null; signal_count?: number; order_count?: number } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);
  const [done, setDone]       = useState(false);
  const [hidden, setHidden]   = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const { fetchDemoSnapshotInfo } = await import("../lib/api");
        const d = await fetchDemoSnapshotInfo();
        if (!cancelled) setInfo(d);
      } catch (e: unknown) {
        // 403 means not owner — hide the panel
        const msg = (e as Error).message ?? "";
        if (msg.includes("403")) setHidden(true);
      }
    }
    load();
    return () => { cancelled = true; };
  }, []);

  async function handleSnapshot() {
    setLoading(true); setError(null); setDone(false);
    try {
      const { takeDemoSnapshot } = await import("../lib/api");
      const result = await takeDemoSnapshot();
      setInfo({ available: true, captured_at: result.captured_at, signal_count: result.signal_count, order_count: result.order_count });
      setDone(true);
      setTimeout(() => setDone(false), 4000);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  if (hidden) return null;

  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-400 leading-relaxed">
        Capture a snapshot of your current portfolio, equity curve, signals, and orders.
        Demo users will see this data instead of any live broker connection — no real trades are ever placed from a demo session.
      </p>

      {info && (
        <div className={clsx(
          "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium border",
          info.available
            ? "border-green-400/30 bg-green-500/10 text-green-400"
            : "border-white/10 bg-white/5 text-slate-400",
        )}>
          <span className={clsx("w-1.5 h-1.5 rounded-full", info.available ? "bg-green-400" : "bg-slate-500")} />
          {info.available
            ? `Snapshot available — taken ${info.captured_at ? new Date(info.captured_at).toLocaleString() : "—"} · ${info.signal_count ?? 0} signals · ${info.order_count ?? 0} orders`
            : "No snapshot yet"}
        </div>
      )}

      <button
        type="button"
        onClick={handleSnapshot}
        disabled={loading}
        className="flex items-center gap-2 px-4 py-2 rounded-lg bg-brand-500/20 border border-brand-400/30 text-sm text-brand-300 hover:bg-brand-500/30 transition-colors disabled:opacity-40"
      >
        {loading && <RefreshCw className="w-3.5 h-3.5 animate-spin" />}
        {loading ? "Capturing snapshot…" : "Take Demo Snapshot Now"}
      </button>

      {done  && <p className="text-xs text-green-400">Snapshot saved — demo users will now see your current data.</p>}
      {error && <p className="text-xs text-red-400">{error}</p>}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

interface SettingsPageProps {
  paperSignalMode?: PaperSignalMode;
  onPaperSignalModeChange?: (mode: PaperSignalMode) => void;
}

export function SettingsPage({ paperSignalMode = "llm", onPaperSignalModeChange }: SettingsPageProps) {
  const [profile, setProfile] = useState<UserProfile>(loadProfile);
  const [saved, setSaved] = useState(false);
  const configStatus = useConfigStatus();
  const brokerState = useBrokerSettings();
  const currentBroker = brokerState.settings?.current_broker ?? "alpaca";

  function update(partial: Partial<UserProfile>) {
    setProfile((p) => ({ ...p, ...partial }));
    setSaved(false);
  }
  function handleSave() {
    saveProfile(profile);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }
  function handleReset() {
    setProfile(DEFAULT_PROFILE);
    saveProfile(DEFAULT_PROFILE);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  }

  return (
    <div className="max-w-2xl space-y-6">

      {/* ── Auto-Trade Engine status ──────────────────────────────────────── */}
      <Section icon={<Zap className="w-4 h-4" />} title="Auto-Trade Engine">
        {configStatus === null ? (
          <div className="text-xs text-slate-500 font-mono animate-pulse">Checking engine status…</div>
        ) : configStatus.auto_trade ? (
          <div className="flex items-start gap-3 bg-emerald-500/10 border border-emerald-500/30 rounded-xl px-4 py-3">
            <span className="mt-0.5 w-2 h-2 rounded-full bg-emerald-400 shrink-0 animate-pulse" />
            <div className="space-y-1">
              <p className="text-sm font-medium text-emerald-300">Orchestrator running</p>
              <p className="text-[11px] text-slate-400 font-mono">
                Scanning {configStatus?.total_symbols ?? "…"} symbols every {configStatus?.cycle_interval_minutes ?? 15} minutes
                ({configStatus?.watchlist_stocks?.length ?? "…"} stocks · {configStatus?.watchlist_etfs?.length ?? "…"} ETFs · {configStatus?.watchlist_crypto?.length ?? "…"} crypto).
                BUY/SELL signals are executed automatically on Alpaca.
              </p>
            </div>
          </div>
        ) : (
          <div className="flex items-start gap-3 bg-red-500/10 border border-red-500/30 rounded-xl px-4 py-3">
            <span className="mt-0.5 w-2 h-2 rounded-full bg-red-400 shrink-0" />
            <div className="space-y-1.5">
              <p className="text-sm font-medium text-red-300">Orchestrator not running — no trades will be placed</p>
              <p className="text-[11px] text-slate-400 font-mono leading-relaxed">
                Add the following environment variable in Railway to enable auto-trading:
              </p>
              <div className="bg-surface-800 rounded-lg px-3 py-2 font-mono text-[11px] text-emerald-400 border border-white/5">
                AUTO_TRADE = true
              </div>
            </div>
          </div>
        )}
      </Section>

      {/* ── Execution Mode ────────────────────────────────────────────────── */}
      <Section icon={<Brain className="w-4 h-4" />} title="Execution Mode (Dashboard)">
        <SectionNote variant="warn">
          This controls how <strong>dashboard signal cards</strong> behave — it does not affect the
          background orchestrator. Set AUTO_TRADE=true above for real background trading.
        </SectionNote>
        <div className="space-y-2">
          {(["auto", "assisted", "manual"] as HITLMode[]).map((m) => (
            <OptionRow key={m} value={m} current={profile.mode}
              onSelect={(v) => update({ mode: v })}
              label={MODE_CONFIG[m].label} sublabel={MODE_CONFIG[m].description}
              accent={
                m === "auto"     ? "border-emerald-500/40 bg-emerald-500/10" :
                m === "assisted" ? "border-amber-500/40 bg-amber-500/10"     :
                                   "border-slate-500/40 bg-slate-500/10"
              }
            />
          ))}
        </div>
        <SectionNote>
          {configStatus
            ? `Signal tier logic: HOT = ${configStatus.hot_min_votes}+/${configStatus.agent_count} votes · WARM = ${configStatus.warm_min_votes}–${configStatus.hot_min_votes - 1}/${configStatus.agent_count} · COLD = <${configStatus.warm_min_votes} or panels conflict`
            : "Signal tier logic: loading…"}
        </SectionNote>
      </Section>

      {/* ── Broker Selection ─────────────────────────────────────────────── */}
      <Section
        icon={<Landmark className="w-4 h-4" />}
        title="Broker"
        subtitle="Choose which brokerage the trading agent uses for your account — only live brokers can execute orders"
      >
        <BrokerPanel />
      </Section>

      {/* ── Alpaca Account (shown when Alpaca is selected) ────────────────── */}
      {currentBroker === "alpaca" && (
        <Section
          icon={<Zap className="w-4 h-4" />}
          title="Alpaca Account"
          subtitle="Per-user Alpaca key for manual signals from the dashboard — stored encrypted"
        >
          <AlpacaPanel paperSignalMode={paperSignalMode} onPaperSignalModeChange={onPaperSignalModeChange} />
        </Section>
      )}

      {/* ── tastytrade Account (shown when tastytrade is selected) ────────── */}
      {currentBroker === "tastytrade" && (
        <Section
          icon={<Zap className="w-4 h-4" />}
          title="tastytrade Account"
          subtitle="tastytrade credentials — password encrypted at rest, never returned by the API"
        >
          <TastytradePanel />
        </Section>
      )}

      {/* ── Charles Schwab Account (shown when schwab is selected) ──────── */}
      {currentBroker === "schwab" && (
        <Section
          icon={<Landmark className="w-4 h-4" />}
          title="Charles Schwab Account"
          subtitle="Connect via OAuth — no password stored; tokens encrypted at rest"
        >
          <SchwabPanel />
        </Section>
      )}

      {/* ── Interactive Brokers (shown when ibkr is selected) ────────────── */}
      {currentBroker === "ibkr" && (
        <Section
          icon={<Landmark className="w-4 h-4" />}
          title="Interactive Brokers Gateway"
          subtitle="Point to your running IB Gateway or TWS — no credentials stored here"
        >
          <IBKRPanel />
        </Section>
      )}

      {/* ── Kraken (shown when kraken is selected) ────────────────────────── */}
      {currentBroker === "kraken" && (
        <Section
          icon={<TrendingUp className="w-4 h-4" />}
          title="Kraken Account"
          subtitle="API key + base64 secret — generate keys at kraken.com/u/security/api"
        >
          <KrakenPanel />
        </Section>
      )}

      {/* ── Coinbase (shown when coinbase is selected) ────────────────────── */}
      {currentBroker === "coinbase" && (
        <Section
          icon={<TrendingUp className="w-4 h-4" />}
          title="Coinbase Advanced Trade"
          subtitle="CDP API key name + EC private key PEM — generate at cloud.coinbase.com/access/api"
        >
          <CoinbasePanel />
        </Section>
      )}

      {/* ── TradeStation (shown when tradestation is selected) ────────────── */}
      {currentBroker === "tradestation" && (
        <Section
          icon={<TrendingUp className="w-4 h-4" />}
          title="TradeStation Account"
          subtitle="OAuth 2.0 — authorise once and set your account number (prefix SIM for paper trading)"
        >
          <TradeStationPanel />
        </Section>
      )}

      {/* ── TradingView Webhook ───────────────────────────────────────────── */}
      <Section
        icon={<Link className="w-4 h-4" />}
        title="TradingView Webhook"
        subtitle="Receive TradingView alerts and execute trades automatically via your active broker"
      >
        <WebhookPanel />
      </Section>

      {/* ── Market Data ──────────────────────────────────────────────────── */}
      <Section
        icon={<Database className="w-4 h-4" />}
        title="Market Data"
        subtitle="Polygon.io for US equity signals; NGX Pulse for Nigerian Exchange (NGX) charts — both optional, each falls back gracefully"
      >
        <PolygonPanel />
        <div className="mt-6 pt-6 border-t border-white/5">
          <p className="text-xs font-semibold text-slate-300 mb-4">NGX Pulse — Nigerian Exchange Data</p>
          <NgxPulsePanel />
        </div>
      </Section>

      {/* ── Research Data ────────────────────────────────────────────────── */}
      <Section
        icon={<TrendingUp className="w-4 h-4" />}
        title="Research Data"
        subtitle="Financial Modeling Prep (FMP) API key — adds company profiles, key metrics, and analyst consensus to the Research page"
      >
        <FmpKeyPanel />
      </Section>

      {/* ── Public Disclosure Tracker ─────────────────────────────────────── */}
      <Section
        icon={<Eye className="w-4 h-4" />}
        title="Public Disclosure Tracker"
        subtitle="SEC EDGAR 13F feed, congressional STOCK Act feed URLs, refresh intervals, and display filter"
      >
        <DisclosureSettingsPanel />
      </Section>

      {/* ── Demo Account ──────────────────────────────────────────────────── */}
      <Section
        icon={<Package className="w-4 h-4" />}
        title="Demo Account"
        subtitle="Let prospective users explore the app with a snapshot of your real data — no live broker connection"
      >
        <DemoSnapshotPanel />
      </Section>

      {/* ── Brain / LLM ───────────────────────────────────────────────────── */}
      <Section
        icon={<Brain className="w-4 h-4" />}
        title="Brain / LLM"
        subtitle="Per-user LLM provider, model, and API key — stored encrypted in your session"
      >
        <BrainLLMPanel />
      </Section>

      {/* ── Engine Config (all parameters) ───────────────────────────────── */}
      <Section
        icon={<Shield className="w-4 h-4" />}
        title="Auto-Trade Engine Config"
        subtitle="All parameters that drive live trading — changes apply within 1 minute without redeploy"
      >
        <EngineConfigPanel />
      </Section>

      {/* ── Trader Profile (local only) ───────────────────────────────────── */}
      <Section
        icon={<TrendingUp className="w-4 h-4" />}
        title="Trader Profile"
        subtitle="Used by Strategy Coach for personalised coaching — stored locally, does not affect the auto-trader"
      >
        <SectionNote>
          Strategy Coach uses this profile to separate market analysis from personalised coaching.
          Be honest — the system optimises for your real tolerance, not your aspirational one.
        </SectionNote>
        <div className="space-y-3">
          <div className="space-y-2">
            <span className="text-xs text-slate-400">Time Horizon</span>
            <div className="grid grid-cols-4 gap-2">
              {([
                { v: "scalper",  label: "Scalper",  sub: "5m–1h" },
                { v: "intraday", label: "Intraday", sub: "1h–4h" },
                { v: "swing",    label: "Swing",    sub: "1D–1W" },
                { v: "position", label: "Position", sub: "1W+"   },
              ] as const).map(({ v, label, sub }) => (
                <button key={v} onClick={() => update({ timeHorizon: v })}
                  className={clsx(
                    "py-2.5 rounded-xl text-xs font-medium border transition-all text-center",
                    profile.timeHorizon === v
                      ? "bg-brand-500/20 border-brand-500/40 text-brand-300"
                      : "border-white/5 text-slate-400 hover:text-slate-200",
                  )}
                >
                  <div>{label}</div>
                  <div className="text-[10px] text-slate-500 mt-0.5 font-mono">{sub}</div>
                </button>
              ))}
            </div>
          </div>
          <NumberSlider label="Max drawdown tolerance" value={profile.maxDrawdownPct} options={[5,10,15,20]} onChange={(v) => update({ maxDrawdownPct: v })} />
        </div>
      </Section>

      {/* ── Order Defaults (local only, NO duplicate stop/TP) ─────────────── */}
      <Section
        icon={<Package className="w-4 h-4" />}
        title="Manual Order Defaults"
        subtitle="Used for the manual order window in the dashboard — does not affect the auto-trader"
      >
        <SectionNote>
          Sets the default share/unit count and sizing method for manual orders placed from dashboard
          signal cards. Auto-trader sizing is controlled entirely by Engine Config above.
        </SectionNote>

        <div className="space-y-2">
          <span className="text-xs text-slate-400">Sizing method</span>
          <div className="grid grid-cols-2 gap-2">
            {([
              { v: false, label: "Position-based", sub: "Equity × position % (recommended)" },
              { v: true,  label: "Fixed quantity",  sub: "Exact share / unit count" },
            ] as const).map(({ v, label, sub }) => (
              <button key={String(v)} onClick={() => update({ useFixedQty: v })}
                className={clsx(
                  "text-left px-4 py-3 rounded-xl border transition-all",
                  profile.useFixedQty === v ? "border-brand-500/40 bg-brand-500/10" : "border-white/5 hover:border-white/10 hover:bg-white/[0.02]",
                )}
              >
                <div className={clsx("text-sm font-medium", profile.useFixedQty === v ? "text-brand-300" : "text-slate-300")}>{label}</div>
                <div className="text-[11px] text-slate-500 mt-0.5">{sub}</div>
              </button>
            ))}
          </div>
        </div>

        {profile.useFixedQty && (
          <div className="space-y-2">
            <div className="flex justify-between text-xs">
              <span className="text-slate-400">Default quantity (shares / units)</span>
              <span className="font-mono font-semibold text-slate-200">{profile.defaultQty} shares</span>
            </div>
            <input
              type="number" min={1} step={1} value={profile.defaultQty}
              onChange={(e) => { const v = parseFloat(e.target.value); if (!isNaN(v) && v > 0) update({ defaultQty: v }); }}
              className="w-full bg-surface-700 border border-white/10 rounded-xl px-4 py-2.5 text-sm font-mono text-slate-200 outline-none focus:ring-1 focus:ring-brand-500"
              placeholder="e.g. 10"
            />
            <p className="text-[11px] text-slate-500 font-mono">
              This many shares will be submitted to Alpaca for every BUY / SELL order.
              For crypto, enter fractional units (e.g. 0.01 BTC).
            </p>
          </div>
        )}
      </Section>

      {/* ── Confirmation Timing ───────────────────────────────────────────── */}
      <Section icon={<Clock className="w-4 h-4" />} title="Confirmation Timing">
        <SecondSlider label="Warm signal veto window" value={profile.warmVetoSeconds} options={[10,30,60]} onChange={(v) => update({ warmVetoSeconds: v })} />
        <SecondSlider label="Over-limit cool-off timer (Manual mode)" value={profile.coolOffSeconds} options={[15,30,60]} onChange={(v) => update({ coolOffSeconds: v })} />
        <SectionNote>
          Cool-off activates when a manual trade exceeds your position size limit. It doesn&apos;t
          block — it inconveniences the impulse.
        </SectionNote>
      </Section>

      {/* ── Save / Reset profile ─────────────────────────────────────────── */}
      <div className="flex items-center gap-3">
        <button onClick={handleSave} className="flex-1 py-2.5 rounded-xl bg-brand-600 hover:bg-brand-500 text-sm font-medium transition-colors">
          {saved ? "Saved ✓" : "Save dashboard profile"}
        </button>
        <button onClick={handleReset} className="px-4 py-2.5 rounded-xl border border-white/10 text-sm text-slate-400 hover:text-slate-200 hover:border-white/20 transition-colors">
          Reset defaults
        </button>
      </div>

    </div>
  );
}
