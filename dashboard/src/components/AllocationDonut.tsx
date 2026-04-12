import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from "recharts";
import { Position } from "../lib/types";
import { ETF_LIST } from "../lib/marketMock";

interface Props {
  positions: Position[];
  equity: number;
  cash: number;
}

const COLORS = ["#6366f1", "#a855f7", "#f97316", "#22c55e"];

export function AllocationDonut({ positions, equity, cash }: Props) {
  const stockMv = positions
    .filter((p) => p.asset_class !== "crypto" && !ETF_LIST.includes(p.symbol))
    .reduce((s, p) => s + p.market_value, 0);
  const etfMv = positions
    .filter((p) => ETF_LIST.includes(p.symbol))
    .reduce((s, p) => s + p.market_value, 0);
  const cryptoMv = positions
    .filter((p) => p.asset_class === "crypto")
    .reduce((s, p) => s + p.market_value, 0);

  const data = [
    { name: "Stocks", value: Math.round((stockMv  / equity) * 100) },
    { name: "ETFs",   value: Math.round((etfMv    / equity) * 100) },
    { name: "Crypto", value: Math.round((cryptoMv / equity) * 100) },
    { name: "Cash",   value: Math.round((cash     / equity) * 100) },
  ].filter((d) => d.value > 0);

  return (
    <div className="flex items-center gap-6">
      <ResponsiveContainer width={100} height={100}>
        <PieChart>
          <Pie data={data} cx="50%" cy="50%" innerRadius={30} outerRadius={46}
            paddingAngle={3} dataKey="value" strokeWidth={0}>
            {data.map((_, i) => <Cell key={i} fill={COLORS[i]} />)}
          </Pie>
          <Tooltip
            formatter={(v) => `${v}%`}
            contentStyle={{
              background: "#131629", border: "1px solid rgba(255,255,255,0.05)",
              borderRadius: 12, fontSize: 11, fontFamily: "JetBrains Mono",
            }}
          />
        </PieChart>
      </ResponsiveContainer>
      <div className="space-y-1.5">
        {data.map((d, i) => (
          <div key={d.name} className="flex items-center gap-2 text-xs">
            <span className="w-2 h-2 rounded-full" style={{ background: COLORS[i] }} />
            <span className="text-slate-400 w-12">{d.name}</span>
            <span className="font-mono font-medium">{d.value}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}
