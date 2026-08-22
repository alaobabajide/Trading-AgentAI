/** HITL (Human-in-the-Loop) types and configuration. */

export type HITLMode    = "auto" | "assisted" | "manual";
export type SignalTier  = "HOT"  | "WARM"     | "COLD";
export type StrategyFit = "ALIGNED" | "MISALIGNED" | "PARTIAL";

export interface UserProfile {
  mode:              HITLMode;
  timeHorizon:       "scalper" | "intraday" | "swing" | "position";
  maxDrawdownPct:    number;  // 5 | 10 | 15 | 20
  maxPositionPct:    number;  // 3 | 5 | 10 | 15
  warmVetoSeconds:   number;  // 10 | 30 | 60
  coolOffSeconds:    number;  // 15 | 30 | 60
  // Order quantity settings
  useFixedQty:       boolean; // true = fixed share count; false = position-% based
  defaultQty:        number;  // shares (or units for crypto) — used when useFixedQty=true
  defaultStopLossPct:   number; // e.g. 2 = 2%
  defaultTakeProfitPct: number; // e.g. 5 = 5%
}

export const DEFAULT_PROFILE: UserProfile = {
  mode:            "assisted",
  timeHorizon:     "swing",
  maxDrawdownPct:  10,
  maxPositionPct:  5,
  warmVetoSeconds: 10,
  coolOffSeconds:  15,
  useFixedQty:        false,
  defaultQty:         10,
  defaultStopLossPct:   2,
  defaultTakeProfitPct: 5,
};

export const TIER_CONFIG: Record<SignalTier, {
  label: string;
  description: string;
  color: string;
  bg: string;
  border: string;
  dot: string;
}> = {
  HOT: {
    label:       "Hot",
    description: "6–7 analysts aligned, low volatility — auto-executes in Auto mode",
    color:       "text-emerald-400",
    bg:          "bg-emerald-500/10",
    border:      "border-emerald-500/30",
    dot:         "bg-emerald-400",
  },
  WARM: {
    label:       "Warm",
    description: "4–5 analysts aligned — veto window in Assisted mode",
    color:       "text-amber-400",
    bg:          "bg-amber-500/10",
    border:      "border-amber-500/30",
    dot:         "bg-amber-400",
  },
  COLD: {
    label:       "Cold",
    description: "≤3 analysts aligned or high volatility — explicit confirmation required",
    color:       "text-slate-400",
    bg:          "bg-slate-500/10",
    border:      "border-slate-500/30",
    dot:         "bg-slate-500",
  },
};

export const FIT_CONFIG: Record<StrategyFit, { label: string; color: string; bg: string }> = {
  ALIGNED:    { label: "Profile aligned",   color: "text-emerald-400", bg: "bg-emerald-500/10" },
  PARTIAL:    { label: "Partial fit",        color: "text-amber-400",   bg: "bg-amber-500/10"   },
  MISALIGNED: { label: "Outside profile",    color: "text-red-400",     bg: "bg-red-500/10"     },
};

export const MODE_CONFIG: Record<HITLMode, { label: string; description: string; color: string }> = {
  auto:     { label: "Auto",     color: "text-emerald-400", description: "HOT signals execute instantly; WARM get 10s veto; COLD queued" },
  assisted: { label: "Assisted", color: "text-amber-400",   description: "All signals require explicit confirmation — default mode" },
  manual:   { label: "Manual",   color: "text-slate-400",   description: "Full control — agents advise only, you execute" },
};

/** Fixed veto window for HOT signals (seconds). WARM window comes from UserProfile.warmVetoSeconds. */
export const HOT_VETO_SECONDS = 5;

/** Storage key for persisting profile to localStorage — namespaced by user ID. */
function _profileKey(userId: string | null): string {
  return userId ? `tradeagent:profile:${userId}` : "tradeagent:profile";
}

export function loadProfile(userId?: string | null): UserProfile {
  try {
    const raw = localStorage.getItem(_profileKey(userId ?? null));
    if (raw) return { ...DEFAULT_PROFILE, ...JSON.parse(raw) };
  } catch {}
  return DEFAULT_PROFILE;
}

export function saveProfile(p: UserProfile, userId?: string | null): void {
  try {
    localStorage.setItem(_profileKey(userId ?? null), JSON.stringify(p));
  } catch {}
}
