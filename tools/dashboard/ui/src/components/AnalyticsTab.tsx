import React, { useState, useEffect, useMemo, useCallback } from 'react';
import {
  Target, BarChart2, List, IndianRupee, TrendingUp, TrendingDown,
  Award, AlertTriangle, Download, ChevronLeft, ChevronRight,
  ChevronUp, ChevronDown, ChevronsUpDown, Filter,
} from 'lucide-react';
import { YearlyReturnsChart } from './YearlyReturnsChart';

const API_BASE = (window as any).__API_BASE__ || (import.meta as any).env?.VITE_API_URL || 'http://localhost:8000/api';

// ── Types ────────────────────────────────────────────────────────────────────

interface TradeStats {
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  base_investment_profit: number;
  avg_profit_per_win: number;
  avg_loss_per_loss: number;
  profit_factor: number;
  max_drawdown: number;
}

interface MonthlyReturn {
  year: number;
  month: number;
  return_pct: number;
}

interface TradeLedgerEntry {
  trade_id: string;
  symbol: string;
  entry_timestamp: string;
  exit_timestamp: string;
  quantity: number;
  entry_price: number;
  exit_price: number;
  gross_pnl: number;
  fees: number;
  net_pnl: number;
  holding_period_days: number;
  entry_reason: string;
  exit_reason: string;
}

type SortKey = keyof TradeLedgerEntry;
type SortDir = 'asc' | 'desc';

interface Props {
  selectedRunId: string | null;
  selectedSymbol?: string | null;
  onClearSymbol?: () => void;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const fmt = (n: number, dec = 2) =>
  n.toLocaleString('en-IN', { minimumFractionDigits: dec, maximumFractionDigits: dec });

const fmtRupee = (n: number) => (n >= 0 ? '+' : '-') + '₹' + fmt(Math.abs(n));

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const PAGE_SIZE = 25;

// ── CSV export ────────────────────────────────────────────────────────────────

function exportCSV(rows: TradeLedgerEntry[], filename: string) {
  const headers = [
    '#', 'Symbol', 'Entry Date', 'Exit Date', 'Hold (days)',
    'Entry ₹', 'Exit ₹', 'Qty', 'Gross PnL', 'Fees', 'Net PnL', 'Exit Reason',
  ];
  const lines = rows.map((t, i) => [
    i + 1,
    t.symbol,
    new Date(t.entry_timestamp).toLocaleDateString('en-IN'),
    new Date(t.exit_timestamp).toLocaleDateString('en-IN'),
    t.holding_period_days.toFixed(1),
    t.entry_price.toFixed(2),
    t.exit_price.toFixed(2),
    t.quantity.toFixed(4),
    t.gross_pnl.toFixed(2),
    t.fees.toFixed(2),
    t.net_pnl.toFixed(2),
    t.exit_reason,
  ].join(','));
  const csv = [headers.join(','), ...lines].join('\n');
  const blob = new Blob([csv], { type: 'text/csv' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

// ── KPI Card ─────────────────────────────────────────────────────────────────

interface KpiProps {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  accent?: 'blue' | 'violet' | 'emerald' | 'rose' | 'amber';
  icon?: React.ReactNode;
  wide?: boolean;
}

function KpiCard({ label, value, sub, accent = 'blue', icon, wide }: KpiProps) {
  const glows: Record<string, string> = {
    blue:    'bg-blue-500/10',
    violet:  'bg-violet-500/10',
    emerald: 'bg-emerald-500/10',
    rose:    'bg-rose-500/10',
    amber:   'bg-amber-500/10',
  };
  return (
    <div className={`glass-panel p-5 relative overflow-hidden group${wide ? ' md:col-span-2' : ''}`}>
      <div className={`absolute top-0 right-0 w-28 h-28 ${glows[accent]} rounded-full blur-2xl -mr-12 -mt-12 transition-transform group-hover:scale-150`} />
      <div className="text-muted text-xs font-medium uppercase tracking-wider mb-2">{label}</div>
      <div className="text-2xl font-bold text-white leading-tight">{value}</div>
      {sub && <div className="mt-1 text-xs text-slate-400">{sub}</div>}
      {icon && <div className="absolute bottom-4 right-4 opacity-20">{icon}</div>}
    </div>
  );
}

// ── Sort icon ─────────────────────────────────────────────────────────────────

function SortIcon({ col, sortKey, sortDir }: { col: SortKey; sortKey: SortKey; sortDir: SortDir }) {
  if (col !== sortKey) return <ChevronsUpDown className="w-3 h-3 opacity-30" />;
  return sortDir === 'asc'
    ? <ChevronUp className="w-3 h-3 text-violet-400" />
    : <ChevronDown className="w-3 h-3 text-violet-400" />;
}

// ── Main component ────────────────────────────────────────────────────────────

export function AnalyticsTab({ selectedRunId, selectedSymbol, onClearSymbol }: Props) {
  const [stats,   setStats]   = useState<TradeStats | null>(null);
  const [monthly, setMonthly] = useState<MonthlyReturn[]>([]);
  const [ledger,  setLedger]  = useState<TradeLedgerEntry[]>([]);
  const [loading, setLoading] = useState(false);

  // year filter
  const [selectedYear, setSelectedYear] = useState<number | null>(null);
  const [yearStats,    setYearStats]    = useState<TradeStats | null>(null);
  const [yearLoading,  setYearLoading]  = useState(false);

  // ledger
  const [page,    setPage]    = useState(1);
  const [sortKey, setSortKey] = useState<SortKey>('exit_timestamp');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  // Fetch base data whenever run or symbol changes
  useEffect(() => {
    if (!selectedRunId) return;
    setLoading(true);
    setSelectedYear(null);
    setYearStats(null);
    setPage(1);

    const sym = selectedSymbol ? `?symbol=${encodeURIComponent(selectedSymbol)}` : '';
    Promise.all([
      fetch(`${API_BASE}/runs/${selectedRunId}/analytics/stats${sym}`).then(r => r.json()),
      fetch(`${API_BASE}/runs/${selectedRunId}/analytics/monthly${sym}`).then(r => r.json()),
      fetch(`${API_BASE}/runs/${selectedRunId}/analytics/ledger${sym}`).then(r => r.json()),
    ]).then(([s, m, l]) => {
      setStats(s);
      setMonthly(m);
      setLedger(l);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [selectedRunId, selectedSymbol]);

  // Fetch year-specific stats
  useEffect(() => {
    if (!selectedRunId || !selectedYear) { setYearStats(null); return; }
    setYearLoading(true);
    const sym  = selectedSymbol ? `&symbol=${encodeURIComponent(selectedSymbol)}` : '';
    fetch(`${API_BASE}/runs/${selectedRunId}/analytics/stats?year=${selectedYear}${sym}`)
      .then(r => r.json())
      .then(s => { setYearStats(s); setYearLoading(false); })
      .catch(() => setYearLoading(false));
  }, [selectedRunId, selectedYear, selectedSymbol]);

  // Derived display stats
  const displayStats = selectedYear ? yearStats : stats;

  // Build monthly matrix
  const matrixByYear = useMemo<Record<number, number[]>>(() => {
    const m: Record<number, number[]> = {};
    monthly.forEach(({ year, month, return_pct }) => {
      if (!m[year]) m[year] = Array(12).fill(null);
      m[year][month - 1] = return_pct;
    });
    return m;
  }, [monthly]);

  // Years for filter dropdown
  const allYears = useMemo(() => Object.keys(matrixByYear).map(Number).sort((a, b) => b - a), [matrixByYear]);

  // Yearly totals for bar chart
  const yearlyData = useMemo(() =>
    allYears.map(year => ({
      year,
      total_pnl: (matrixByYear[year] || [])
        .filter(v => v !== null)
        .reduce((sum, v) => sum + v * 100_000, 0),
    })), [matrixByYear, allYears]);

  // Filtered matrix rows
  const matrixRows = useMemo(() =>
    selectedYear
      ? allYears.filter(y => y === selectedYear)
      : allYears,
    [allYears, selectedYear]);

  // Sorted + paginated ledger
  const sortedLedger = useMemo(() => {
    const filtered = selectedYear
      ? ledger.filter(t => new Date(t.exit_timestamp).getFullYear() === selectedYear)
      : ledger;
    return [...filtered].sort((a, b) => {
      const av = a[sortKey], bv = b[sortKey];
      if (typeof av === 'number' && typeof bv === 'number')
        return sortDir === 'asc' ? av - bv : bv - av;
      return sortDir === 'asc'
        ? String(av).localeCompare(String(bv))
        : String(bv).localeCompare(String(av));
    });
  }, [ledger, sortKey, sortDir, selectedYear]);

  const totalPages  = Math.max(1, Math.ceil(sortedLedger.length / PAGE_SIZE));
  const pagedLedger = sortedLedger.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const handleSort = useCallback((key: SortKey) => {
    if (key === sortKey) setSortDir(d => d === 'asc' ? 'desc' : 'asc');
    else { setSortKey(key); setSortDir('desc'); }
    setPage(1);
  }, [sortKey]);

  // ── Render: empty states ──
  if (!selectedRunId) {
    return (
      <div className="glass-panel p-6 min-h-[400px] flex items-center justify-center">
        <div className="text-center space-y-3">
          <BarChart2 className="w-12 h-12 text-slate-600 mx-auto" />
          <p className="text-muted">Select a strategy from the Overview to view analytics</p>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="glass-panel p-6 min-h-[400px] flex items-center justify-center">
        <div className="animate-pulse flex flex-col items-center gap-4">
          <div className="w-8 h-8 border-4 border-violet-500 border-t-transparent rounded-full animate-spin" />
          <span className="text-muted">Loading deep dive analytics…</span>
        </div>
      </div>
    );
  }

  const winPct  = displayStats ? (displayStats.win_rate * 100).toFixed(1) : '0.0';
  const totalTr = displayStats?.total_trades ?? 0;

  return (
    <div className="space-y-6">

      {/* ── Symbol Filter Banner ── */}
      {selectedSymbol && (
        <div className="bg-blue-500/10 border border-blue-500/20 rounded-xl p-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="bg-blue-500 text-white px-3 py-1 rounded-full text-xs font-bold tracking-wider">
              STOCK FILTER ACTIVE
            </div>
            <div className="text-white font-medium">
              Showing analytics specifically for{' '}
              <span className="text-blue-400 font-bold">{selectedSymbol}</span>
            </div>
          </div>
          <button
            onClick={onClearSymbol}
            className="text-sm font-medium text-muted hover:text-white bg-white/5 hover:bg-white/10 px-4 py-2 rounded-lg transition-colors"
          >
            Clear Filter
          </button>
        </div>
      )}

      {/* ── Year Filter ── */}
      <div className="flex items-center gap-3 flex-wrap">
        <Filter className="w-4 h-4 text-slate-400" />
        <span className="text-sm text-slate-400 font-medium">Year:</span>
        <button
          onClick={() => { setSelectedYear(null); setPage(1); }}
          className={`px-4 py-1.5 rounded-full text-sm font-medium transition-all ${
            !selectedYear
              ? 'bg-violet-600 text-white shadow-lg shadow-violet-500/20'
              : 'bg-white/5 text-slate-400 hover:bg-white/10 hover:text-white'
          }`}
        >
          All Years
        </button>
        {allYears.map(y => (
          <button
            key={y}
            onClick={() => { setSelectedYear(y); setPage(1); }}
            className={`px-4 py-1.5 rounded-full text-sm font-medium transition-all ${
              selectedYear === y
                ? 'bg-violet-600 text-white shadow-lg shadow-violet-500/20'
                : 'bg-white/5 text-slate-400 hover:bg-white/10 hover:text-white'
            }`}
          >
            {y}
          </button>
        ))}
        {selectedYear && yearLoading && (
          <div className="w-4 h-4 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
        )}
      </div>

      {/* ── 8 KPI Cards ── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard
          label="Total Trades"
          value={totalTr.toLocaleString()}
          sub={selectedYear ? `Filtered to ${selectedYear}` : 'All time'}
          accent="blue"
          icon={<BarChart2 className="w-10 h-10" />}
        />

        <KpiCard
          label="Profitable Trades"
          value={
            <span className="text-emerald-400">
              {displayStats?.winning_trades ?? 0}
            </span>
          }
          sub={totalTr > 0 ? `${((displayStats?.winning_trades ?? 0) / totalTr * 100).toFixed(1)}% of total` : '—'}
          accent="emerald"
          icon={<TrendingUp className="w-10 h-10 text-emerald-500" />}
        />

        <KpiCard
          label="Losing Trades"
          value={
            <span className="text-rose-400">
              {displayStats?.losing_trades ?? 0}
            </span>
          }
          sub={totalTr > 0 ? `${((displayStats?.losing_trades ?? 0) / totalTr * 100).toFixed(1)}% of total` : '—'}
          accent="rose"
          icon={<TrendingDown className="w-10 h-10 text-rose-500" />}
        />

        <KpiCard
          label="Win Rate"
          value={`${winPct}%`}
          sub={
            <div className="w-full bg-white/10 rounded-full h-1 mt-2">
              <div
                className="bg-gradient-to-r from-violet-500 to-emerald-500 h-1 rounded-full transition-all"
                style={{ width: `${winPct}%` }}
              />
            </div>
          }
          accent="violet"
          icon={<Target className="w-10 h-10 text-violet-500" />}
        />

        <KpiCard
          label="Profit on ₹1,00,000 Base"
          value={
            <span className={(displayStats?.base_investment_profit ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}>
              <span className="inline-flex items-center gap-1">
                <IndianRupee className="w-6 h-6" />
                {fmt(Math.abs(displayStats?.base_investment_profit ?? 0))}
              </span>
            </span>
          }
          sub={(displayStats?.base_investment_profit ?? 0) >= 0 ? '▲ Profit' : '▼ Loss'}
          accent={(displayStats?.base_investment_profit ?? 0) >= 0 ? 'emerald' : 'rose'}
          wide
        />

        <KpiCard
          label="Avg Profit / Win"
          value={
            <span className="text-emerald-400">
              +₹{fmt(displayStats?.avg_profit_per_win ?? 0)}
            </span>
          }
          sub="Average winning trade"
          accent="emerald"
          icon={<Award className="w-10 h-10 text-emerald-500" />}
        />

        <KpiCard
          label="Avg Loss / Loss"
          value={
            <span className="text-rose-400">
              -₹{fmt(Math.abs(displayStats?.avg_loss_per_loss ?? 0))}
            </span>
          }
          sub="Average losing trade"
          accent="rose"
          icon={<AlertTriangle className="w-10 h-10 text-rose-500" />}
        />

        <KpiCard
          label="Profit Factor"
          value={
            <span className={(displayStats?.profit_factor ?? 0) >= 1 ? 'text-emerald-400' : 'text-rose-400'}>
              {(displayStats?.profit_factor ?? 0).toFixed(2)}×
            </span>
          }
          sub="Win PnL ÷ Loss PnL"
          accent={(displayStats?.profit_factor ?? 0) >= 1 ? 'emerald' : 'rose'}
        />
      </div>

      {/* ── Yearly Returns Bar Chart ── */}
      {yearlyData.length > 0 && (
        <div className="glass-panel overflow-hidden">
          <div className="p-5 border-b border-white/10 flex justify-between items-center bg-white/5">
            <h2 className="text-lg font-bold flex items-center gap-2">
              <BarChart2 className="text-amber-400 w-5 h-5" />
              Yearly Returns — Net PnL in ₹
            </h2>
          </div>
          <div className="p-5">
            <YearlyReturnsChart data={yearlyData} />
          </div>
        </div>
      )}

      {/* ── Monthly Returns Matrix ── */}
      <div className="glass-panel overflow-hidden">
        <div className="p-5 border-b border-white/10 flex justify-between items-center bg-white/5">
          <h2 className="text-lg font-bold flex items-center gap-2">
            <BarChart2 className="text-violet-400 w-5 h-5" />
            Monthly Returns Matrix
            {selectedYear && (
              <span className="ml-2 text-sm font-normal text-violet-400 bg-violet-500/10 px-2 py-0.5 rounded-full">
                {selectedYear}
              </span>
            )}
          </h2>
        </div>
        <div className="p-5 overflow-x-auto">
          <table className="w-full text-center border-collapse text-sm">
            <thead>
              <tr className="text-muted text-xs uppercase tracking-wide">
                <th className="p-2 text-left">Year</th>
                {MONTHS.map(m => <th key={m} className="p-2 min-w-[56px]">{m}</th>)}
                <th className="p-2 text-right">Annual</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {matrixRows.length === 0 && (
                <tr>
                  <td colSpan={14} className="p-8 text-center text-muted">
                    No time-series data available.
                  </td>
                </tr>
              )}
              {matrixRows.map(year => {
                const months  = matrixByYear[year] || Array(12).fill(null);
                const annual  = months.filter(v => v !== null).reduce((s, v) => s + v, 0);
                return (
                  <tr key={year} className="hover:bg-white/[0.02] transition-colors">
                    <td
                      className="p-2 font-bold text-left text-slate-300 cursor-pointer hover:text-violet-400"
                      onClick={() => { setSelectedYear(year === selectedYear ? null : year); setPage(1); }}
                    >
                      {year}
                    </td>
                    {months.map((ret, i) => {
                      const pct  = ret !== null ? ret * 100 : null;
                      const bg   = pct === null ? ''
                        : pct > 0
                          ? `rgba(52,211,153,${Math.min(0.08 + Math.abs(pct) * 0.04, 0.6)})`
                          : `rgba(248,113,113,${Math.min(0.08 + Math.abs(pct) * 0.04, 0.6)})`;
                      return (
                        <td key={i} className="p-1">
                          <div
                            className={`p-1.5 rounded text-xs font-semibold ${
                              pct === null ? 'text-slate-600'
                                : pct > 0   ? 'text-emerald-400'
                                : 'text-rose-400'
                            }`}
                            style={{ backgroundColor: bg || 'transparent' }}
                          >
                            {pct === null ? '—' : `${pct > 0 ? '+' : ''}${pct.toFixed(1)}%`}
                          </div>
                        </td>
                      );
                    })}
                    <td className={`p-2 text-right font-bold text-sm ${
                      annual > 0 ? 'text-emerald-400' : annual < 0 ? 'text-rose-400' : 'text-slate-500'
                    }`}>
                      {annual > 0 ? '+' : ''}{(annual * 100).toFixed(1)}%
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── RCA Ledger ── */}
      <div className="glass-panel overflow-hidden">
        <div className="p-5 border-b border-white/10 flex justify-between items-center bg-white/5 flex-wrap gap-3">
          <h2 className="text-lg font-bold flex items-center gap-2">
            <List className="text-blue-400 w-5 h-5" />
            Trade RCA Ledger
            <span className="text-sm font-normal text-slate-400">
              ({sortedLedger.length} trades)
            </span>
          </h2>
          <button
            onClick={() => exportCSV(sortedLedger, `rca-${selectedRunId?.split(':')[0] ?? 'trades'}.csv`)}
            className="flex items-center gap-2 px-4 py-2 bg-white/5 hover:bg-white/10 text-sm text-slate-300 hover:text-white rounded-lg transition-colors border border-white/10"
          >
            <Download className="w-4 h-4" />
            Export CSV
          </button>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-sm">
            <thead className="sticky top-0 bg-[#111c2b] z-10">
              <tr className="text-muted text-xs uppercase tracking-wider border-b border-white/10">
                {([
                  ['#',                  null],
                  ['Symbol',             'symbol'],
                  ['Entry Date',         'entry_timestamp'],
                  ['Exit Date',          'exit_timestamp'],
                  ['Hold (d)',           'holding_period_days'],
                  ['Entry ₹',            'entry_price'],
                  ['Exit ₹',             'exit_price'],
                  ['Qty',                'quantity'],
                  ['Gross PnL',          'gross_pnl'],
                  ['Fees',               'fees'],
                  ['Net PnL ₹',          'net_pnl'],
                  ['Exit Reason',        'exit_reason'],
                ] as [string, SortKey | null][]).map(([label, key]) => (
                  <th
                    key={label}
                    className={`px-4 py-3 font-medium whitespace-nowrap ${key ? 'cursor-pointer hover:text-white select-none' : ''}`}
                    onClick={() => key && handleSort(key)}
                  >
                    <span className="flex items-center gap-1">
                      {label}
                      {key && <SortIcon col={key} sortKey={sortKey} sortDir={sortDir} />}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {pagedLedger.length === 0 && (
                <tr>
                  <td colSpan={12} className="p-8 text-center text-muted">
                    No trade ledger data available.
                  </td>
                </tr>
              )}
              {pagedLedger.map((trade, idx) => (
                <tr
                  key={trade.trade_id}
                  className={`hover:bg-white/[0.04] transition-colors ${
                    trade.net_pnl > 0 ? 'bg-emerald-500/[0.02]' : trade.net_pnl < 0 ? 'bg-rose-500/[0.02]' : ''
                  }`}
                >
                  <td className="px-4 py-3 text-slate-500 text-xs">{(page - 1) * PAGE_SIZE + idx + 1}</td>
                  <td className="px-4 py-3 font-semibold text-white">{trade.symbol}</td>
                  <td className="px-4 py-3 text-slate-300 whitespace-nowrap">
                    {new Date(trade.entry_timestamp).toLocaleDateString('en-IN')}
                  </td>
                  <td className="px-4 py-3 text-slate-300 whitespace-nowrap">
                    {new Date(trade.exit_timestamp).toLocaleDateString('en-IN')}
                  </td>
                  <td className="px-4 py-3 text-slate-400 text-right">
                    {trade.holding_period_days.toFixed(0)}
                  </td>
                  <td className="px-4 py-3 text-slate-300 text-right">
                    ₹{fmt(trade.entry_price)}
                  </td>
                  <td className="px-4 py-3 text-slate-300 text-right">
                    ₹{fmt(trade.exit_price)}
                  </td>
                  <td className="px-4 py-3 text-slate-400 text-right">
                    {trade.quantity.toFixed(2)}
                  </td>
                  <td className={`px-4 py-3 text-right ${trade.gross_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {fmtRupee(trade.gross_pnl)}
                  </td>
                  <td className="px-4 py-3 text-slate-500 text-right text-xs">
                    ₹{fmt(trade.fees)}
                  </td>
                  <td className={`px-4 py-3 text-right font-bold ${trade.net_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {fmtRupee(trade.net_pnl)}
                  </td>
                  <td className="px-4 py-3">
                    <span className="px-2 py-0.5 text-xs rounded-full bg-white/10 text-slate-300 whitespace-nowrap">
                      {trade.exit_reason || '—'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div className="px-5 py-4 border-t border-white/10 flex items-center justify-between text-sm text-slate-400">
          <span>
            Showing {Math.min((page - 1) * PAGE_SIZE + 1, sortedLedger.length)}–
            {Math.min(page * PAGE_SIZE, sortedLedger.length)} of {sortedLedger.length} trades
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
              className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span className="px-3 py-1 bg-white/5 rounded-lg font-medium text-white">
              {page} / {totalPages}
            </span>
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
              className="p-1.5 rounded-lg bg-white/5 hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

    </div>
  );
}
