import clsx from "clsx";
import { Position } from "../lib/types";
import { ETF_LIST } from "../lib/marketMock";

function assetClass(p: Position): "etf" | "stock" | "crypto" {
  if (p.asset_class === "crypto") return "crypto";
  if (ETF_LIST.includes(p.symbol))  return "etf";
  return "stock";
}

const CLASS_BADGE: Record<string, string> = {
  stock:  "bg-blue-500/15 text-blue-400",
  etf:    "bg-violet-500/15 text-violet-400",
  crypto: "bg-orange-500/15 text-orange-400",
};

function Row({ p }: { p: Position }) {
  const cls = assetClass(p);
  const bullish = p.unrealized_pnl >= 0;
  return (
    <tr className="border-b border-white/[0.03] hover:bg-white/[0.02] transition-colors">
      <td className="py-3 pr-4 font-mono font-semibold">{p.symbol}</td>
      <td className="py-3 pr-4">
        <span className={clsx("text-[10px] px-1.5 py-0.5 rounded uppercase font-medium", CLASS_BADGE[cls])}>
          {cls}
        </span>
      </td>
      <td className="py-3 pr-4 font-mono text-slate-300">{p.qty}</td>
      <td className="py-3 pr-4 font-mono text-slate-400">
        ${p.avg_entry_price.toLocaleString("en-US", { minimumFractionDigits: 2 })}
      </td>
      <td className="py-3 pr-4 font-mono">
        ${p.current_price.toLocaleString("en-US", { minimumFractionDigits: 2 })}
      </td>
      <td className="py-3 pr-4 font-mono">
        ${p.market_value.toLocaleString("en-US", { minimumFractionDigits: 2 })}
      </td>
      <td className="py-3 pr-4">
        <span className={clsx("font-mono text-sm", bullish ? "text-emerald-400" : "text-red-400")}>
          {bullish ? "+" : ""}${p.unrealized_pnl.toLocaleString("en-US", { minimumFractionDigits: 2 })}
          <span className="text-xs ml-1 opacity-70">
            ({bullish ? "+" : ""}{p.unrealized_pnl_pct.toFixed(2)}%)
          </span>
        </span>
      </td>
    </tr>
  );
}

const GROUP_ORDER: Array<"stock" | "etf" | "crypto"> = ["stock", "etf", "crypto"];
const GROUP_LABEL: Record<string, string> = { stock: "Equities", etf: "ETFs", crypto: "Crypto" };

export function PositionsTable({ positions }: { positions: Position[] }) {
  const groups = GROUP_ORDER.map((cls) => ({
    cls,
    items: positions.filter((p) => assetClass(p) === cls),
  })).filter((g) => g.items.length > 0);

  const totalPnl    = positions.reduce((s, p) => s + p.unrealized_pnl, 0);
  const totalValue  = positions.reduce((s, p) => s + p.market_value, 0);

  return (
    <div className="space-y-1 overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-[10px] text-slate-500 uppercase tracking-widest border-b border-white/5">
            {["Symbol", "Class", "Qty", "Avg Cost", "Price", "Value", "Unrealised P&L"].map((h) => (
              <th key={h} className="pb-2 pr-4 font-medium">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {groups.map(({ cls, items }) => (
            <>
              <tr key={`group-${cls}`}>
                <td colSpan={7} className="pt-3 pb-1 pr-4">
                  <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-500">
                    {GROUP_LABEL[cls]}
                    <span className="ml-2 font-mono text-slate-600">
                      ${items.reduce((s, p) => s + p.market_value, 0).toLocaleString("en-US", { maximumFractionDigits: 0 })}
                    </span>
                  </span>
                </td>
              </tr>
              {items.map((p) => <Row key={p.symbol} p={p} />)}
            </>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t border-white/10">
            <td colSpan={5} className="pt-3 text-xs text-slate-500 font-mono">
              {positions.length} positions · Total value ${totalValue.toLocaleString("en-US", { maximumFractionDigits: 0 })}
            </td>
            <td colSpan={2} className="pt-3 text-right">
              <span className={clsx("text-sm font-mono font-semibold",
                totalPnl >= 0 ? "text-emerald-400" : "text-red-400")}>
                {totalPnl >= 0 ? "+" : ""}${totalPnl.toLocaleString("en-US", { minimumFractionDigits: 2 })} unrealised
              </span>
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
