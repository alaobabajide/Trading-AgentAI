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

interface Props {
  data: EquityPoint[];
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

export function EquityChart({ data }: Props) {
  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-[220px] text-slate-500 text-sm font-mono">
        Connecting to Alpaca…
      </div>
    );
  }

  const formatted = data.map((d) => ({
    ...d,
    label: format(new Date(d.time), "HH:mm"),
  }));

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
          interval="preserveStartEnd"
        />
        <YAxis
          tick={{ fill: "#64748b", fontSize: 11, fontFamily: "JetBrains Mono" }}
          tickLine={false}
          axisLine={false}
          width={70}
          tickFormatter={(v) => `$${(v / 1000).toFixed(0)}k`}
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
