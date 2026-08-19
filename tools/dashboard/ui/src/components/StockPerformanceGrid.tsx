import React from 'react';
import { BarChart3 } from 'lucide-react';

interface StockPerf {
  symbol: string;
  pnl: number;
  trade_count: number;
  win_rate: number;
}

interface Props {
  data: StockPerf[];
  loading: boolean;
  onSelectStock?: (symbol: string) => void;
}

export function StockPerformanceGrid({ data, loading, onSelectStock }: Props) {
  if (loading) {
    return (
      <div className="glass-panel p-6 min-h-[300px] flex items-center justify-center mt-6">
        <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin"></div>
      </div>
    );
  }

  if (!data || data.length === 0) {
    return null;
  }

  return (
    <div className="glass-panel overflow-hidden mt-6">
      <div className="p-5 border-b border-white/10 flex justify-between items-center bg-white/5">
        <h3 className="text-lg font-bold flex items-center gap-2">
          <BarChart3 className="text-accent" />
          Stock-wise Attribution
        </h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-black/20 text-muted text-sm uppercase tracking-wider">
              <th className="p-4 font-medium">Symbol</th>
              <th className="p-4 font-medium text-right">PnL</th>
              <th className="p-4 font-medium text-right">Trades</th>
              <th className="p-4 font-medium text-right">Win Rate</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5 text-sm">
            {data.map(stock => (
              <tr 
                key={stock.symbol} 
                className={`transition-colors ${onSelectStock ? 'cursor-pointer hover:bg-white/10' : 'hover:bg-white/5'}`}
                onClick={() => onSelectStock && onSelectStock(stock.symbol)}
              >
                <td className="p-4 font-semibold text-white">{stock.symbol}</td>
                <td className={`p-4 text-right font-medium ${stock.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  ${stock.pnl.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}
                </td>
                <td className="p-4 text-right text-slate-300">{stock.trade_count}</td>
                <td className="p-4 text-right text-slate-300">
                  {(stock.win_rate * 100).toFixed(1)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
