/** Horizontal stacked bar showing Buy / Hold / Sell analyst counts. */
interface Props {
  buy: number;
  hold: number;
  sell: number;
}

export function AnalystBar({ buy, hold, sell }: Props) {
  const total = buy + hold + sell || 1;
  const buyW  = (buy  / total) * 100;
  const holdW = (hold / total) * 100;
  const sellW = (sell / total) * 100;

  return (
    <div className="space-y-2">
      <div className="flex rounded-full overflow-hidden h-3">
        <div style={{ width: `${buyW}%` }}  className="bg-emerald-500 transition-all duration-500" />
        <div style={{ width: `${holdW}%` }} className="bg-yellow-500 mx-px transition-all duration-500" />
        <div style={{ width: `${sellW}%` }} className="bg-red-500 transition-all duration-500" />
      </div>
      <div className="flex justify-between text-[10px] font-mono">
        <span><span className="text-emerald-400 font-semibold">{buy}</span> <span className="text-slate-500">Buy</span></span>
        <span><span className="text-yellow-400 font-semibold">{hold}</span> <span className="text-slate-500">Hold</span></span>
        <span><span className="text-red-400 font-semibold">{sell}</span> <span className="text-slate-500">Sell</span></span>
      </div>
    </div>
  );
}
