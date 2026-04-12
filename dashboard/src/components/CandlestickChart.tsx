import {
  ComposedChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import type { Candle } from "../lib/marketMock";

interface Props {
  candles: Candle[];
  height?: number;
}

/** Custom candlestick body rendered as SVG rect */
const CandleBody = (props: any) => {
  const { x, y, width, height, open, close } = props;
  if (!width || !height) return null;
  const bullish = close >= open;
  const color   = bullish ? "#10b981" : "#ef4444";
  return <rect x={x} y={y} width={width} height={Math.max(1, Math.abs(height))} fill={color} rx={1} />;
};

/** Transform candles into Recharts-friendly data with wick coords */
function transform(candles: Candle[]) {
  return candles.map((c) => {
    const bullish  = c.close >= c.open;
    const bodyLow  = Math.min(c.open, c.close);
    const bodyHigh = Math.max(c.open, c.close);
    return {
      ...c,
      bullish,
      bodyLow,
      bodyHigh,
      bodyHeight: bodyHigh - bodyLow,
      wickHigh: c.high,
      wickLow:  c.low,
    };
  });
}

const CustomTooltip = ({ active, payload }: any) => {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;
  const bullish = d.close >= d.open;
  return (
    <div className="glass rounded-xl px-3 py-2.5 text-xs font-mono space-y-1 min-w-[140px]">
      <div className="text-slate-400 mb-1">{d.time}</div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
        <span className="text-slate-500">O</span><span>{d.open.toLocaleString()}</span>
        <span className="text-slate-500">H</span><span className="text-emerald-400">{d.high.toLocaleString()}</span>
        <span className="text-slate-500">L</span><span className="text-red-400">{d.low.toLocaleString()}</span>
        <span className="text-slate-500">C</span><span className={bullish ? "text-emerald-400" : "text-red-400"}>{d.close.toLocaleString()}</span>
        <span className="text-slate-500">Vol</span><span>{(d.volume / 1e6).toFixed(1)}M</span>
      </div>
    </div>
  );
};

export function CandlestickChart({ candles, height = 300 }: Props) {
  if (!candles.length) return null;

  const prices  = candles.flatMap((c) => [c.high, c.low]);
  const minP    = Math.min(...prices);
  const maxP    = Math.max(...prices);
  const pad     = (maxP - minP) * 0.05;
  const yDomain: [number, number] = [minP - pad, maxP + pad];

  const data = transform(candles);
  const visible = data.slice(-60);

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={visible} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1a1e35" vertical={false} />
        <XAxis
          dataKey="time"
          tick={{ fill: "#64748b", fontSize: 10, fontFamily: "JetBrains Mono" }}
          tickLine={false} axisLine={false}
          interval={Math.floor(visible.length / 8)}
        />
        <YAxis
          domain={yDomain}
          tick={{ fill: "#64748b", fontSize: 10, fontFamily: "JetBrains Mono" }}
          tickLine={false} axisLine={false}
          width={72}
          tickFormatter={(v) =>
            v >= 1000 ? `$${(v / 1000).toFixed(0)}k` : `$${v.toFixed(2)}`
          }
        />
        <Tooltip content={<CustomTooltip />} />

        {/* Wick: low → high */}
        <Bar dataKey="wickHigh" stackId="wick" fill="transparent" isAnimationActive={false} minPointSize={0}>
          {visible.map((entry, i) => (
            <Cell key={i} fill={entry.bullish ? "#10b981" : "#ef4444"} />
          ))}
        </Bar>

        {/* Body: open ↔ close */}
        <Bar
          dataKey="bodyHeight"
          stackId="body"
          shape={<CandleBody />}
          isAnimationActive={false}
          minPointSize={1}
        >
          {visible.map((entry, i) => (
            <Cell key={i} fill={entry.bullish ? "#10b981" : "#ef4444"} />
          ))}
        </Bar>
      </ComposedChart>
    </ResponsiveContainer>
  );
}
