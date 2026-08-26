import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Cell, ResponsiveContainer, ReferenceLine,
} from 'recharts';

interface YearlyData {
  year: number;
  total_pnl: number;
}

interface Props {
  data: YearlyData[];
}

const formatRupee = (val: number) => {
  if (Math.abs(val) >= 100_000) return `₹${(val / 100_000).toFixed(1)}L`;
  if (Math.abs(val) >= 1_000)   return `₹${(val / 1_000).toFixed(1)}K`;
  return `₹${val.toFixed(0)}`;
};

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  const val = payload[0].value as number;
  return (
    <div className="bg-[#0f1923] border border-white/10 rounded-xl px-4 py-3 shadow-2xl text-sm">
      <div className="font-bold text-white mb-1">{label}</div>
      <div className={val >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
        {val >= 0 ? '+' : ''}₹{val.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
      </div>
      <div className="text-slate-400 text-xs">Annual Net PnL</div>
    </div>
  );
};

export function YearlyReturnsChart({ data }: Props) {
  if (!data.length) {
    return (
      <div className="flex items-center justify-center h-40 text-slate-500 text-sm">
        No yearly data available
      </div>
    );
  }

  const sorted = [...data].sort((a, b) => a.year - b.year);

  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={sorted} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
        <XAxis
          dataKey="year"
          tick={{ fill: '#64748b', fontSize: 12 }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          tickFormatter={formatRupee}
          tick={{ fill: '#64748b', fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          width={60}
        />
        <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
        <ReferenceLine y={0} stroke="rgba(255,255,255,0.15)" strokeWidth={1} />
        <Bar dataKey="total_pnl" radius={[4, 4, 0, 0]} maxBarSize={48}>
          {sorted.map((entry) => (
            <Cell
              key={entry.year}
              fill={entry.total_pnl >= 0 ? 'rgba(52,211,153,0.85)' : 'rgba(248,113,113,0.85)'}
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
