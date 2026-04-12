/**
 * Two-panel chart for ETF pages:
 *   Left  — horizontal bar chart of top holdings by weight
 *   Right — pie/donut of sector allocation
 */
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell, PieChart, Pie,
} from "recharts";
import type { EtfHolding } from "../lib/marketMock";

interface HoldingsProps {
  holdings: EtfHolding[];
  height?: number;
}

const SECTOR_COLORS = [
  "#6366f1","#10b981","#f59e0b","#ef4444","#3b82f6",
  "#a855f7","#ec4899","#14b8a6","#f97316","#84cc16",
];

const HoldingTooltip = ({ active, payload }: any) => {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload as EtfHolding;
  return (
    <div className="glass rounded-xl px-3 py-2 text-xs font-mono space-y-0.5">
      <div className="text-slate-200 font-semibold">{d.ticker}</div>
      <div className="text-slate-400">{d.name}</div>
      <div className="text-brand-400">{d.weight.toFixed(2)}%</div>
    </div>
  );
};

export function EtfHoldingsChart({ holdings, height = 220 }: HoldingsProps) {
  const data = [...holdings].sort((a, b) => b.weight - a.weight);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 0, right: 8, left: 8, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1a1e35" horizontal={false} />
        <XAxis type="number" tick={{ fill: "#64748b", fontSize: 10, fontFamily: "JetBrains Mono" }}
          tickLine={false} axisLine={false} tickFormatter={(v) => `${v}%`} />
        <YAxis type="category" dataKey="ticker" width={60}
          tick={{ fill: "#94a3b8", fontSize: 11, fontFamily: "JetBrains Mono" }}
          tickLine={false} axisLine={false} />
        <Tooltip content={<HoldingTooltip />} />
        <Bar dataKey="weight" radius={[0, 4, 4, 0]} maxBarSize={18}>
          {data.map((_, i) => (
            <Cell key={i} fill={SECTOR_COLORS[i % SECTOR_COLORS.length]} fillOpacity={0.85} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// ── Sector Donut ──────────────────────────────────────────────────────────────

interface SectorProps {
  sectors: { sector: string; weight: number }[];
}

const SectorTooltip = ({ active, payload }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="glass rounded-xl px-3 py-2 text-xs font-mono">
      <div className="text-slate-300">{payload[0]?.name}</div>
      <div className="text-brand-400">{payload[0]?.value?.toFixed(1)}%</div>
    </div>
  );
};

export function SectorDonut({ sectors }: SectorProps) {
  return (
    <div className="flex items-center gap-4">
      <ResponsiveContainer width={110} height={110}>
        <PieChart>
          <Pie data={sectors} dataKey="weight" nameKey="sector"
            cx="50%" cy="50%" innerRadius={32} outerRadius={50}
            paddingAngle={2} strokeWidth={0}>
            {sectors.map((_, i) => (
              <Cell key={i} fill={SECTOR_COLORS[i % SECTOR_COLORS.length]} />
            ))}
          </Pie>
          <Tooltip content={<SectorTooltip />} />
        </PieChart>
      </ResponsiveContainer>
      <div className="flex-1 grid grid-cols-1 gap-1">
        {sectors.map((s, i) => (
          <div key={s.sector} className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full shrink-0"
                style={{ background: SECTOR_COLORS[i % SECTOR_COLORS.length] }} />
              <span className="text-[11px] text-slate-400 truncate max-w-[110px]">{s.sector}</span>
            </div>
            <span className="text-[11px] font-mono text-slate-300">{s.weight.toFixed(1)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}
