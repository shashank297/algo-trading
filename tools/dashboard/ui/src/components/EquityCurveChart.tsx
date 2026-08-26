import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { TrendingUp } from 'lucide-react';

interface Point {
  timestamp: string;
  equity: number;
  drawdown: number;
}

interface Props {
  data: Point[];
  loading: boolean;
}

export function EquityCurveChart({ data, loading }: Props) {
  if (loading) {
    return (
      <div className="glass-panel p-6 h-[400px] flex items-center justify-center">
        <div className="animate-pulse flex flex-col items-center gap-4">
          <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin"></div>
          <span className="text-muted">Loading chart data...</span>
        </div>
      </div>
    );
  }

  if (!data || data.length === 0) {
    return (
      <div className="glass-panel p-6 h-[400px] flex items-center justify-center">
        <span className="text-muted">Select a strategy to view its equity curve</span>
      </div>
    );
  }

  // Format dates for the X-axis
  const formattedData = data.map(d => ({
    ...d,
    dateStr: new Date(d.timestamp).toLocaleDateString()
  }));

  return (
    <div className="glass-panel p-6 flex flex-col h-[400px]">
      <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
        <TrendingUp className="text-emerald-400" />
        Equity Curve
      </h3>
      <div className="flex-1 w-full min-h-0">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={formattedData} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="colorEquity" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.4}/>
                <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#ffffff15" vertical={false} />
            <XAxis 
              dataKey="dateStr" 
              stroke="#94a3b8" 
              fontSize={12} 
              tickLine={false}
              axisLine={false}
              minTickGap={30}
            />
            <YAxis 
              stroke="#94a3b8" 
              fontSize={12}
              tickLine={false}
              axisLine={false}
              domain={['auto', 'auto']}
              tickFormatter={(val) => `$${val.toLocaleString()}`}
            />
            <Tooltip 
              contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px', color: '#f8fafc' }}
              itemStyle={{ color: '#3b82f6' }}
              labelStyle={{ color: '#94a3b8', marginBottom: '4px' }}
            />
            <Area 
              type="monotone" 
              dataKey="equity" 
              stroke="#3b82f6" 
              strokeWidth={2}
              fillOpacity={1} 
              fill="url(#colorEquity)" 
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
