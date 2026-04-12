import {
  ComposedChart, Bar, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import type { QuarterlyEarnings } from "../lib/marketMock";

interface Props { data: QuarterlyEarnings[]; height?: number }

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  const find = (k: string) => payload.find((p: any) => p.dataKey === k)?.value;
  const beat = (find("epsActual") ?? 0) >= (find("epsEst") ?? 0);
  return (
    <div className="glass rounded-xl px-3 py-2.5 text-xs font-mono space-y-1">
      <div className="text-slate-400 font-semibold mb-1">{label}</div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
        <span className="text-slate-500">EPS Est</span>
        <span>${find("epsEst")?.toFixed(2)}</span>
        <span className="text-slate-500">EPS Act</span>
        <span className={beat ? "text-emerald-400" : "text-red-400"}>
          ${find("epsActual")?.toFixed(2)} {beat ? "▲" : "▼"}
        </span>
        <span className="text-slate-500">Rev Est</span>
        <span>${find("revenueEst")?.toFixed(1)}B</span>
        <span className="text-slate-500">Rev Act</span>
        <span className={(find("revenueActual") ?? 0) >= (find("revenueEst") ?? 0) ? "text-emerald-400" : "text-red-400"}>
          ${find("revenueActual")?.toFixed(1)}B
        </span>
      </div>
    </div>
  );
};

export function EarningsChart({ data, height = 200 }: Props) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1a1e35" vertical={false} />
        <XAxis dataKey="quarter"
          tick={{ fill: "#64748b", fontSize: 11, fontFamily: "JetBrains Mono" }}
          tickLine={false} axisLine={false} />
        <YAxis yAxisId="eps" orientation="left" width={44}
          tick={{ fill: "#64748b", fontSize: 10, fontFamily: "JetBrains Mono" }}
          tickLine={false} axisLine={false}
          tickFormatter={(v) => `$${v.toFixed(1)}`} />
        <YAxis yAxisId="rev" orientation="right" width={44}
          tick={{ fill: "#64748b", fontSize: 10, fontFamily: "JetBrains Mono" }}
          tickLine={false} axisLine={false}
          tickFormatter={(v) => `$${v}B`} />
        <Tooltip content={<CustomTooltip />} />

        {/* Revenue bars */}
        <Bar yAxisId="rev" dataKey="revenueEst"    fill="#6366f1" fillOpacity={0.25} maxBarSize={28} radius={[4,4,0,0]} />
        <Bar yAxisId="rev" dataKey="revenueActual" maxBarSize={18} radius={[4,4,0,0]}>
          {data.map((d, i) => (
            <Cell key={i}
              fill={d.revenueActual >= d.revenueEst ? "#10b981" : "#ef4444"}
              fillOpacity={d.revenueActual === 0 ? 0.2 : 0.85} />
          ))}
        </Bar>

        {/* EPS lines */}
        <Line yAxisId="eps" dataKey="epsEst" stroke="#94a3b8" strokeWidth={1.5}
          strokeDasharray="5 4" dot={{ r: 3, fill: "#94a3b8" }} />
        <Line yAxisId="eps" dataKey="epsActual" stroke="#f59e0b" strokeWidth={2}
          dot={(props: any) => {
            if (props.payload.epsActual === 0) return <g key={props.key} />;
            const beat = props.payload.epsActual >= props.payload.epsEst;
            return (
              <circle key={props.key} cx={props.cx} cy={props.cy} r={5}
                fill={beat ? "#10b981" : "#ef4444"} stroke="#0d0f1a" strokeWidth={2} />
            );
          }} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
