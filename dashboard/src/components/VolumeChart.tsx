import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import type { Candle } from "../lib/marketMock";

interface Props { candles: Candle[]; height?: number }

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="glass rounded-xl px-3 py-2 text-xs font-mono">
      <span className="text-slate-400">{label} — </span>
      <span className="text-brand-400">{(payload[0]?.value / 1e6).toFixed(2)}M</span>
    </div>
  );
};

export function VolumeChart({ candles, height = 80 }: Props) {
  const visible = candles.slice(-60);
  return (
    <div>
      <span className="text-[10px] text-slate-500 uppercase tracking-widest block mb-2">Volume</span>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={visible} margin={{ top: 0, right: 4, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1a1e35" vertical={false} />
          <XAxis dataKey="time" hide />
          <YAxis tick={{ fill: "#64748b", fontSize: 9, fontFamily: "JetBrains Mono" }}
            tickLine={false} axisLine={false} width={40}
            tickFormatter={(v) => `${(v / 1e6).toFixed(0)}M`} />
          <Tooltip content={<CustomTooltip />} />
          <Bar dataKey="volume" isAnimationActive={false} maxBarSize={8} radius={[2, 2, 0, 0]}>
            {visible.map((c, i) => (
              <Cell key={i} fill={c.close >= c.open ? "#10b98166" : "#ef444466"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
