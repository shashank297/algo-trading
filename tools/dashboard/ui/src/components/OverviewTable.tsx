import { Activity, Clock, CheckCircle2, XCircle } from 'lucide-react';

interface RunSummary {
  run_id: string;
  strategy_name: string;
  mode: string;
  started_at: string;
  status: string;
  total_return: number;
  max_drawdown: number;
  sharpe_ratio: number;
  win_rate: number;
}

interface Props {
  runs: RunSummary[];
  selectedRunId: string | null;
  onSelectRun: (id: string) => void;
}

export function OverviewTable({ runs, selectedRunId, onSelectRun }: Props) {
  const getStatusIcon = (status: string) => {
    switch(status) {
      case 'COMPLETED': return <CheckCircle2 className="w-4 h-4 text-emerald-400" />;
      case 'FAILED': return <XCircle className="w-4 h-4 text-rose-400" />;
      default: return <Activity className="w-4 h-4 text-primary" />;
    }
  };

  return (
    <div className="glass-panel overflow-hidden">
      <div className="p-5 border-b border-white/10 flex justify-between items-center bg-white/5">
        <h2 className="text-xl font-bold flex items-center gap-2">
          <Activity className="text-accent" />
          Strategy Executions
        </h2>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left border-collapse">
          <thead>
            <tr className="bg-black/20 text-muted text-sm uppercase tracking-wider">
              <th className="p-4 font-medium">Strategy</th>
              <th className="p-4 font-medium">Mode</th>
              <th className="p-4 font-medium">Status</th>
              <th className="p-4 font-medium text-right">Return</th>
              <th className="p-4 font-medium text-right">Sharpe</th>
              <th className="p-4 font-medium text-right">Max DD</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5 text-sm">
            {runs.length === 0 && (
              <tr>
                <td colSpan={6} className="p-8 text-center text-muted">
                  No strategy runs found. Start a backtest to see results.
                </td>
              </tr>
            )}
            {runs.map(run => (
              <tr 
                key={run.run_id} 
                onClick={() => onSelectRun(run.run_id)}
                className={`cursor-pointer transition-all duration-200 hover:bg-white/5 ${selectedRunId === run.run_id ? 'bg-primary/20 border-l-2 border-primary' : ''}`}
              >
                <td className="p-4">
                  <div className="font-semibold text-white">{run.strategy_name}</div>
                  <div className="text-xs text-muted flex items-center gap-1 mt-1">
                    <Clock className="w-3 h-3" />
                    {new Date(run.started_at).toLocaleString()}
                  </div>
                </td>
                <td className="p-4">
                  <span className={`px-2 py-1 text-xs rounded-full font-medium ${
                    run.mode === 'PAPER' ? 'bg-accent/20 text-accent' : 'bg-primary/20 text-primary'
                  }`}>
                    {run.mode}
                  </span>
                </td>
                <td className="p-4">
                  <div className="flex items-center gap-2">
                    {getStatusIcon(run.status)}
                    <span className="capitalize">{run.status.toLowerCase()}</span>
                  </div>
                </td>
                <td className={`p-4 text-right font-medium ${run.total_return >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                  {(run.total_return * 100).toFixed(2)}%
                </td>
                <td className="p-4 text-right font-medium text-slate-300">
                  {run.sharpe_ratio.toFixed(2)}
                </td>
                <td className="p-4 text-right font-medium text-rose-400">
                  {(run.max_drawdown * 100).toFixed(2)}%
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
