import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine,
} from "recharts";
import type { IndicatorPoint } from "../lib/marketMock";
import clsx from "clsx";

interface Props { data: IndicatorPoint[]; height?: number }

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  const rsi = payload[0]?.value as number;
  return (
    <div className="glass rounded-xl px-3 py-2 text-xs font-mono">
      <span className="text-slate-400">{label} — </span>
      <span className={rsi >= 70 ? "text-red-400" : rsi <= 30 ? "text-emerald-400" : "text-brand-400"}>
        RSI {rsi?.toFixed(1)}
      </span>
    </div>
  );
};

export function RsiChart({ data, height = 120 }: Props) {
  const visible = data.slice(-60);
  const latest  = visible[visible.length - 1]?.rsi ?? 50;
  const zone    = latest >= 70 ? "Overbought" : latest <= 30 ? "Oversold" : "Neutral";
  const zoneColor = latest >= 70 ? "text-red-400" : latest <= 30 ? "text-emerald-400" : "text-slate-400";

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] text-slate-500 uppercase tracking-widest">RSI (14)</span>
        <span className="text-xs font-mono">
          <span className={clsx("font-semibold", zoneColor)}>{latest.toFixed(1)}</span>
          <span className="text-slate-600 mx-1">·</span>
          <span className={clsx("text-[10px]", zoneColor)}>{zone}</span>
        </span>
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={visible} margin={{ top: 2, right: 4, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="rsiOB" x1="0" y1="0" x2="0" y2="1">
              <stop stopColor="#ef4444" stopOpacity={0.08} />
              <stop offset="1" stopColor="#ef4444" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#1a1e35" vertical={false} />
          <XAxis dataKey="time" hide />
          <YAxis domain={[0, 100]} tick={{ fill: "#64748b", fontSize: 9, fontFamily: "JetBrains Mono" }}
            tickLine={false} axisLine={false} width={28} ticks={[30, 50, 70]} />
          <Tooltip content={<CustomTooltip />} />
          <ReferenceLine y={70} stroke="#ef4444" strokeDasharray="4 3" strokeWidth={1} />
          <ReferenceLine y={30} stroke="#10b981" strokeDasharray="4 3" strokeWidth={1} />
          <ReferenceLine y={50} stroke="#334155" strokeDasharray="6 4" strokeWidth={1} />
          <Line dataKey="rsi" stroke="#f59e0b" strokeWidth={2} dot={false}
            activeDot={{ r: 3, fill: "#fbbf24" }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
