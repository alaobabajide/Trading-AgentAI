import {
  ComposedChart, Bar, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Cell, ReferenceLine,
} from "recharts";
import type { IndicatorPoint } from "../lib/marketMock";
import clsx from "clsx";

interface Props { data: IndicatorPoint[]; height?: number }

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  const find = (k: string) => payload.find((p: any) => p.dataKey === k)?.value;
  return (
    <div className="glass rounded-xl px-3 py-2 text-xs font-mono space-y-0.5">
      <div className="text-slate-400 mb-1">{label}</div>
      <div><span className="text-slate-500">MACD   </span><span className="text-brand-400">{find("macd")?.toFixed(4)}</span></div>
      <div><span className="text-slate-500">Signal </span><span className="text-orange-400">{find("signal")?.toFixed(4)}</span></div>
      <div><span className="text-slate-500">Hist   </span>
        <span className={find("hist") >= 0 ? "text-emerald-400" : "text-red-400"}>{find("hist")?.toFixed(4)}</span>
      </div>
    </div>
  );
};

export function MacdChart({ data, height = 120 }: Props) {
  const visible = data.slice(-60);
  const latest  = visible[visible.length - 1];
  const crossover = latest && latest.macd > latest.signal ? "Bullish crossover" : "Bearish crossover";
  const crossColor = latest?.macd > latest?.signal ? "text-emerald-400" : "text-red-400";

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-[10px] text-slate-500 uppercase tracking-widest">MACD (12, 26, 9)</span>
        <span className={clsx("text-[10px] font-mono", crossColor)}>{crossover}</span>
      </div>
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart data={visible} margin={{ top: 2, right: 4, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1a1e35" vertical={false} />
          <XAxis dataKey="time" hide />
          <YAxis tick={{ fill: "#64748b", fontSize: 9, fontFamily: "JetBrains Mono" }}
            tickLine={false} axisLine={false} width={40}
            tickFormatter={(v) => v.toFixed(1)} />
          <Tooltip content={<CustomTooltip />} />
          <ReferenceLine y={0} stroke="#334155" strokeWidth={1} />

          {/* Histogram */}
          <Bar dataKey="hist" isAnimationActive={false} maxBarSize={6}>
            {visible.map((d, i) => (
              <Cell key={i} fill={d.hist >= 0 ? "#10b981" : "#ef4444"} fillOpacity={0.7} />
            ))}
          </Bar>

          {/* MACD line */}
          <Line dataKey="macd" stroke="#6366f1" strokeWidth={1.5} dot={false}
            activeDot={{ r: 3 }} isAnimationActive={false} />
          {/* Signal line */}
          <Line dataKey="signal" stroke="#f97316" strokeWidth={1.5} dot={false}
            activeDot={{ r: 3 }} isAnimationActive={false} strokeDasharray="4 3" />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
