import {
  ComposedChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer,
} from "recharts";

export type Candle = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

interface Props {
  candles: Candle[];
  height?: number;
  maxCandles?: number;
}

const CustomTooltip = ({ active, payload }: { active?: boolean; payload?: { payload: Candle }[] }) => {
  if (!active || !payload?.length) return null;
  const d = payload[0]?.payload;
  if (!d) return null;
  const bullish = d.close >= d.open;
  return (
    <div className="glass rounded-xl px-3 py-2.5 text-xs font-mono space-y-1 min-w-[140px]">
      <div className="text-slate-400 mb-1">{d.time}</div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5">
        <span className="text-slate-500">O</span>
        <span>{d.open.toLocaleString()}</span>
        <span className="text-slate-500">H</span>
        <span className="text-emerald-400">{d.high.toLocaleString()}</span>
        <span className="text-slate-500">L</span>
        <span className="text-red-400">{d.low.toLocaleString()}</span>
        <span className="text-slate-500">C</span>
        <span className={bullish ? "text-emerald-400" : "text-red-400"}>
          {d.close.toLocaleString()}
        </span>
        <span className="text-slate-500">Vol</span>
        <span>{(d.volume / 1e6).toFixed(1)}M</span>
      </div>
    </div>
  );
};

export function CandlestickChart({ candles, height = 300, maxCandles }: Props) {
  if (!candles.length) return null;

  const visible = maxCandles ? candles.slice(-maxCandles) : candles;

  const prices = visible.flatMap((c) => [c.high, c.low]);
  const minP   = Math.min(...prices);
  const maxP   = Math.max(...prices);
  const pad    = (maxP - minP) * 0.05;
  const yDomain: [number, number] = [minP - pad, maxP + pad];

  // Single custom shape that draws wick + body as SVG in one pass.
  // Recharts passes the full data payload as props alongside bar geometry:
  //   x, width — horizontal position and bar width
  //   y         — pixel coordinate of the `high` price (top of the bar)
  //   height    — pixel height from yDomain[0] up to `high`
  // From these we interpolate every price level into pixel coordinates.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const CandleShape = (props: any) => {
    const { x, y, width, height: barH, open, high, low, close } = props as {
      x: number; y: number; width: number; height: number;
      open: number; high: number; low: number; close: number;
    };

    if (!width || barH <= 0 || high <= yDomain[0]) return null;

    const bullish = close >= open;
    const color   = bullish ? "#10b981" : "#ef4444";

    // Map a price to its pixel y-coordinate.
    // y corresponds to `high`; y + barH corresponds to yDomain[0].
    const pxPerUnit = barH / (high - yDomain[0]);
    const yOf = (p: number) => y + (high - p) * pxPerUnit;

    const yHigh      = y;                        // pixel for high (wick top)
    const yLow       = yOf(low);                 // pixel for low (wick bottom)
    const bodyTop    = Math.min(yOf(open), yOf(close));
    const bodyBottom = Math.max(yOf(open), yOf(close));
    const bodyH      = Math.max(1, bodyBottom - bodyTop);
    const cx         = x + width / 2;            // horizontal centre
    const bodyW      = Math.max(2, width - 2);   // body slightly narrower than bar slot

    return (
      <g>
        {/* Upper wick: from high down to top of body */}
        <line x1={cx} y1={yHigh}      x2={cx} y2={bodyTop}    stroke={color} strokeWidth={1} />
        {/* Lower wick: from bottom of body down to low */}
        <line x1={cx} y1={bodyBottom} x2={cx} y2={yLow}       stroke={color} strokeWidth={1} />
        {/* Candle body */}
        <rect
          x={x + (width - bodyW) / 2}
          y={bodyTop}
          width={bodyW}
          height={bodyH}
          fill={color}
          rx={1}
        />
      </g>
    );
  };

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={visible} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1a1e35" vertical={false} />
        <XAxis
          dataKey="time"
          tick={{ fill: "#64748b", fontSize: 10, fontFamily: "JetBrains Mono" }}
          tickLine={false}
          axisLine={false}
          interval={Math.floor(visible.length / 8)}
        />
        <YAxis
          domain={yDomain}
          tick={{ fill: "#64748b", fontSize: 10, fontFamily: "JetBrains Mono" }}
          tickLine={false}
          axisLine={false}
          width={72}
          tickFormatter={(v) =>
            v >= 1000 ? `$${(v / 1000).toFixed(0)}k` : `$${v.toFixed(2)}`
          }
        />
        <Tooltip content={<CustomTooltip />} />

        {/* Single bar per candle — CandleShape draws wick + body itself */}
        <Bar
          dataKey="high"
          shape={<CandleShape />}
          isAnimationActive={false}
          minPointSize={0}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
