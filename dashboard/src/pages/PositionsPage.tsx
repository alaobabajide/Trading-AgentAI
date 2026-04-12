import { BarChart2 } from "lucide-react";
import { PositionsTable } from "../components/PositionsTable";
import { mockPortfolio } from "../lib/mock";

export function PositionsPage() {
  return (
    <div className="space-y-5">
      <h1 className="text-lg font-semibold flex items-center gap-2">
        <BarChart2 className="w-5 h-5 text-brand-400" />
        Open Positions
      </h1>
      <div className="glass rounded-2xl p-5">
        <PositionsTable positions={mockPortfolio.positions} />
      </div>
    </div>
  );
}
