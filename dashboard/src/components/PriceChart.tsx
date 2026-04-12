/**
 * Main price chart: close line + Bollinger Bands overlay + volume bars.
 * Used on the Technical Analysis page.
 */
import {
  ComposedChart, Area, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import type { IndicatorPoint } from "../lib/marketMock";

interface Props { data: IndicatorPoint[]; height?: number }

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  const find = (k: string) => payload.find((p: any) => p.dataKey === k)?.value;
  return (
    <div className="glass rounded-xl px-3 py-2.5 text-xs font-mono space-y-1 min-w-[160px]">
      <div className="text-slate-400 mb-1">{label}</div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
        <span className="text-slate-500">Price</span>
        <span className="text-brand-400">${find("close")?.toLocaleString()}</span>
        <span className="text-slate-500">BB Upper</span>
        <span className="text-violet-400">${find("bbUpper")?.toLocaleString()}</span>
        <span className="text-slate-500">BB Mid</span>
        <span className="text-slate-400">${find("bbMid")?.toLocaleString()}</span>
        <span className="text-slate-500">BB Lower</span>
        <span className="text-fuchsia-400">${find("bbLower")?.toLocaleString()}</span>
      </div>
    </div>
  );
};

export function PriceChart({ data, height = 280 }: Props) {
  const visible = data.slice(-60);
  const prices  = visible.flatMap((d) => [d.bbUpper, d.bbLower]);
  const minP    = Math.min(...prices);
  const maxP    = Math.max(...prices);
  const pad     = (maxP - minP) * 0.06;

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={visible} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="bbFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor="#7c3aed" stopOpacity={0.12} />
            <stop offset="95%" stopColor="#7c3aed" stopOpacity={0.02} />
          </linearGradient>
          <linearGradient id="priceGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor="#6366f1" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#6366f1" stopOpacity={0}   />
          </linearGradient>
        </defs>

        <CartesianGrid strokeDasharray="3 3" stroke="#1a1e35" vertical={false} />
        <XAxis
          dataKey="time"
          tick={{ fill: "#64748b", fontSize: 10, fontFamily: "JetBrains Mono" }}
          tickLine={false} axisLine={false}
          interval={Math.floor(visible.length / 8)}
        />
        <YAxis
          domain={[minP - pad, maxP + pad]}
          tick={{ fill: "#64748b", fontSize: 10, fontFamily: "JetBrains Mono" }}
          tickLine={false} axisLine={false} width={72}
          tickFormatter={(v) => v >= 1000 ? `$${(v / 1000).toFixed(0)}k` : `$${v.toFixed(2)}`}
        />
        <Tooltip content={<CustomTooltip />} />

        {/* BB band fill */}
        <Area dataKey="bbUpper" stroke="#7c3aed" strokeWidth={1} strokeDasharray="4 3"
          fill="url(#bbFill)" dot={false} activeDot={false} isAnimationActive={false} />
        <Area dataKey="bbLower" stroke="#a855f7" strokeWidth={1} strokeDasharray="4 3"
          fill="transparent" dot={false} activeDot={false} isAnimationActive={false} />

        {/* BB mid */}
        <Line dataKey="bbMid" stroke="#64748b" strokeWidth={1} strokeDasharray="6 4"
          dot={false} activeDot={false} isAnimationActive={false} />

        {/* Price line */}
        <Area dataKey="close" stroke="#6366f1" strokeWidth={2}
          fill="url(#priceGrad)" dot={false}
          activeDot={{ r: 4, fill: "#818cf8" }} isAnimationActive={false} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
