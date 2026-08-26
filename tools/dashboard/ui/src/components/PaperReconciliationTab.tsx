import { ShieldCheck, AlertTriangle } from 'lucide-react';

interface PaperRecon {
  trade_date: string;
  expected_orders: number;
  submitted_orders: number;
  filled_orders: number;
  rejected_orders: number;
  pnl: number;
  drift: number;
}

interface Props {
  data: PaperRecon[];
  loading: boolean;
}

export function PaperReconciliationTab({ data, loading }: Props) {
  if (loading) {
    return (
      <div className="glass-panel p-6 h-[400px] flex items-center justify-center">
        <div className="animate-pulse flex flex-col items-center gap-4">
          <div className="w-8 h-8 border-4 border-accent border-t-transparent rounded-full animate-spin"></div>
          <span className="text-muted">Loading paper trading health...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="glass-panel overflow-hidden">
      <div className="p-5 border-b border-white/10 flex justify-between items-center bg-white/5">
        <h2 className="text-xl font-bold flex items-center gap-2">
          <ShieldCheck className="text-emerald-400" />
          Paper Trading Health & Reconciliations
        </h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-black/20 text-muted text-sm uppercase tracking-wider">
              <th className="p-4 font-medium">Trade Date</th>
              <th className="p-4 font-medium text-right">Expected</th>
              <th className="p-4 font-medium text-right">Submitted</th>
              <th className="p-4 font-medium text-right">Filled</th>
              <th className="p-4 font-medium text-right">Rejected</th>
              <th className="p-4 font-medium text-right">PnL</th>
              <th className="p-4 font-medium text-right">Drift</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5 text-sm">
            {data.length === 0 && (
              <tr>
                <td colSpan={7} className="p-8 text-center text-muted">
                  No paper trading sessions found.
                </td>
              </tr>
            )}
            {data.map(recon => (
              <tr key={recon.trade_date} className="hover:bg-white/5 transition-colors">
                <td className="p-4 font-medium text-white">{recon.trade_date}</td>
                <td className="p-4 text-right">{recon.expected_orders}</td>
                <td className="p-4 text-right">{recon.submitted_orders}</td>
                <td className="p-4 text-right">{recon.filled_orders}</td>
                <td className="p-4 text-right">
                  {recon.rejected_orders > 0 ? (
                    <span className="flex items-center justify-end gap-1 text-rose-400 font-bold">
                      <AlertTriangle className="w-3 h-3" />
                      {recon.rejected_orders}
                    </span>
                  ) : (
                    <span className="text-emerald-400">0</span>
                  )}
                </td>
                <td className={`p-4 text-right font-medium ${recon.pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  ${recon.pnl.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}
                </td>
                <td className="p-4 text-right text-slate-300">
                  {recon.drift !== 0 ? `$${recon.drift.toFixed(2)}` : '-'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
