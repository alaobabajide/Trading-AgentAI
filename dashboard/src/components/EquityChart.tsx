import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { format } from "date-fns";
import { EquityPoint } from "../lib/types";

/**
 * Parse an ISO timestamp and format its label without timezone shifting.
 *
 * date-fns `format(new Date(isoStr), ...)` uses the *browser* local timezone,
 * which causes Alpaca's end-of-day UTC bars (e.g. "2026-08-26T00:00:00Z" for
 * the Aug 25 ET session) to appear as "Aug 26" in timezones east of UTC.
 *
 * Fix:
 *  - Daily charts (1M/1Y): extract only the YYYY-MM-DD portion and construct
 *    a local-noon Date so the label is always the UTC calendar date, not the
 *    browser-local date of the underlying timestamp.
 *  - Intraday chart (1D): read UTC hours/minutes directly from the Date object
 *    so the time label matches the UTC clock (= market hours in ET + 4/5h, but
 *    consistent regardless of viewer timezone).
 */
function formatLabel(isoStr: string, period: "1D" | "1M" | "1Y"): string {
  if (period === "1D") {
    const d = new Date(isoStr);
    // Build HH:mm from UTC components so every viewer sees the same clock.
    const hh = String(d.getUTCHours()).padStart(2, "0");
    const mm = String(d.getUTCMinutes()).padStart(2, "0");
    return `${hh}:${mm}`;
  }
  // Daily bars: use only the date string (first 10 chars) to avoid tz shifts.
  const datePart = isoStr.substring(0, 10); // "YYYY-MM-DD"
  const [year, month, day] = datePart.split("-").map(Number);
  // Construct at local noon so DST can't push it into the previous/next day.
  const d = new Date(year, month - 1, day, 12, 0, 0);
  return format(d, period === "1M" ? "MMM d" : "MMM yy");
}

interface Props {
  data: EquityPoint[];
  period?: "1D" | "1M" | "1Y";
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="glass rounded-xl px-3 py-2 text-xs font-mono space-y-1">
      <div className="text-slate-400">{label}</div>
      <div className="text-brand-400">
        ${payload[0]?.value?.toLocaleString("en-US", { minimumFractionDigits: 2 })}
      </div>
    </div>
  );
};

export function EquityChart({ data, period = "1D" }: Props) {
  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-[220px] text-slate-500 text-sm font-mono">
        Connecting to Alpaca…
      </div>
    );
  }

  const formatted = data.map((d) => ({
    ...d,
    label: formatLabel(d.time, period),
  }));

  // Limit x-axis ticks so labels never overlap regardless of data density.
  // 1D: ~78 pts (5-min market bars) → show every 12th = ~6 labels (1 per hour)
  // 1M: ~30 pts (daily)             → show every 5th  = ~6 labels
  // 1Y: ~365 pts (daily)            → show every 60th = ~6 labels
  const tickInterval = period === "1D" ? 12 : period === "1M" ? 4 : 60;

  // Zoom Y-axis into the actual data range (same as Alpaca's own chart).
  // For 1D: a $1k move on a $100k account would look flat if axis started at $0.
  // For 1M/1Y: account may genuinely start near $0 — don't let padding go negative.
  const values  = data.map((d) => d.equity);
  const dataMin = Math.min(...values);
  const dataMax = Math.max(...values);
  const range   = dataMax - dataMin || dataMax * 0.002;   // at least 0.2% of value
  const pad     = range * 0.15;                           // 15% breathing room
  const yMin    = Math.max(0, Math.floor((dataMin - pad) / 100) * 100);
  const yMax    = Math.ceil ((dataMax + pad) / 100) * 100;

  // Tick formatter: show full dollar value (e.g. $101.5k) so small moves are legible
  const tickFmt = (v: number) => v === 0 ? "$0" : `$${(v / 1000).toFixed(1)}k`;

  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart data={formatted} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor="#6366f1" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#6366f1" stopOpacity={0}   />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#1a1e35" />
        <XAxis
          dataKey="label"
          tick={{ fill: "#64748b", fontSize: 11, fontFamily: "JetBrains Mono" }}
          tickLine={false}
          axisLine={false}
          interval={tickInterval}
        />
        <YAxis
          domain={[yMin, yMax]}
          tick={{ fill: "#64748b", fontSize: 11, fontFamily: "JetBrains Mono" }}
          tickLine={false}
          axisLine={false}
          width={72}
          tickFormatter={tickFmt}
        />
        <Tooltip content={<CustomTooltip />} />
        <Area
          type="monotone"
          dataKey="equity"
          stroke="#6366f1"
          strokeWidth={2}
          fill="url(#equityGrad)"
          dot={false}
          activeDot={{ r: 4, fill: "#818cf8" }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
