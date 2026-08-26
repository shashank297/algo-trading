import { useState, useEffect, useMemo, Fragment } from 'react'
import {
  LayoutDashboard, ChevronRight, ArrowLeft, Search, X,
  Activity, BarChart3, TrendingUp, TrendingDown, Target,
  BookOpen, Lightbulb, Shield, Clock, Zap, AlertCircle,
  CheckCircle2, Filter,
} from 'lucide-react'
import { PaperReconciliationTab } from './components/PaperReconciliationTab'
import { AnalyticsTab } from './components/AnalyticsTab'
import { getStrategyInfo, type StrategyInfo } from './lib/strategyKnowledge'

const API_BASE = (window as any).__API_BASE__ || (import.meta as any).env?.VITE_API_URL || 'http://localhost:8000/api'

// ── Types ─────────────────────────────────────────────────────────────────────

interface StrategyAggregate {
  strategy_name: string
  total_runs: number
  total_stocks: number
  avg_return: number
  avg_win_rate: number
  avg_sharpe: number
  avg_max_drawdown: number
  avg_profit_factor: number
}

interface StrategyStockSummary {
  symbol: string
  run_id: string
  mode: string
  total_return: number
  win_rate: number
  max_drawdown: number
  sharpe: number
  total_trades: number
  net_pnl: number
  has_trades: boolean
}

// ── Nav State ─────────────────────────────────────────────────────────────────

type NavState =
  | { level: 'strategies' }
  | { level: 'strategy-detail'; strategyName: string }
  | { level: 'stock-analytics'; strategyName: string; symbol: string; runId: string }

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmtPct = (v: number, dec = 2) => `${(v * 100).toFixed(dec)}%`
const fmtRupee = (v: number) =>
  (v >= 0 ? '+₹' : '-₹') + Math.abs(v).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

const RISK_COLOR: Record<string, string> = {
  Low:    'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
  Medium: 'text-amber-400   bg-amber-500/10   border-amber-500/20',
  High:   'text-rose-400    bg-rose-500/10    border-rose-500/20',
}

const CAT_COLOR: Record<string, string> = {
  'Momentum':         'bg-violet-500/20 text-violet-300 border-violet-500/30',
  'Mean Reversion':   'bg-blue-500/20   text-blue-300   border-blue-500/30',
  'Breakout':         'bg-amber-500/20  text-amber-300  border-amber-500/30',
  'Trend Following':  'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
  'Factor':           'bg-pink-500/20   text-pink-300   border-pink-500/30',
  'Volatility':       'bg-cyan-500/20   text-cyan-300   border-cyan-500/30',
}

// ── Breadcrumb ────────────────────────────────────────────────────────────────

function Breadcrumb({ items }: { items: { label: string; onClick: () => void }[] }) {
  return (
    <nav className="flex items-center gap-1 text-sm text-slate-400 flex-wrap mb-4">
      {items.map((item, i) => (
        <Fragment key={i}>
          {i > 0 && <ChevronRight className="w-3.5 h-3.5 text-slate-600 flex-shrink-0" />}
          <button
            onClick={item.onClick}
            className={`px-1.5 py-0.5 rounded hover:text-white transition-colors ${
              i === items.length - 1 ? 'text-white font-semibold' : 'hover:underline'
            }`}
          >
            {item.label}
          </button>
        </Fragment>
      ))}
    </nav>
  )
}

// ── Level 1: Strategy Cards ────────────────────────────────────────────────────

function StrategiesView({
  onDrill,
}: {
  onDrill: (name: string) => void
}) {
  const [strategies, setStrategies] = useState<StrategyAggregate[]>([])
  const [loading, setLoading]       = useState(true)
  const [search,  setSearch]        = useState('')
  const [cat,     setCat]           = useState('')

  useEffect(() => {
    fetch(`${API_BASE}/strategies`).then(r => r.json()).then(d => { setStrategies(d); setLoading(false) }).catch(() => setLoading(false))
  }, [])

  const filtered = useMemo(() => {
    const info = strategies.map(s => ({ ...s, _info: getStrategyInfo(s.strategy_name) }))
    return info.filter(s => {
      if (search && !s.strategy_name.toLowerCase().includes(search.toLowerCase()) && !s._info.displayName.toLowerCase().includes(search.toLowerCase())) return false
      if (cat && s._info.category !== cat) return false
      return true
    })
  }, [strategies, search, cat])

  const allCategories = useMemo(() => [...new Set(strategies.map(s => getStrategyInfo(s.strategy_name).category))].sort(), [strategies])

  if (loading) return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="animate-spin w-10 h-10 border-4 border-violet-500 border-t-transparent rounded-full" />
    </div>
  )

  return (
    <div className="space-y-6">
      {/* Filters */}
      <div className="glass-panel p-4 flex flex-wrap items-center gap-3">
        <Filter className="w-4 h-4 text-slate-400 flex-shrink-0" />
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
          <input
            type="text"
            placeholder="Search strategies…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="bg-white/5 border border-white/10 text-sm text-slate-300 rounded-lg pl-8 pr-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-violet-500 w-44"
          />
        </div>
        {allCategories.map(c => (
          <button
            key={c}
            onClick={() => setCat(cat === c ? '' : c)}
            className={`px-3 py-1.5 rounded-full text-xs font-medium border transition-all ${
              cat === c
                ? (CAT_COLOR[c] || 'bg-violet-500/20 text-violet-300 border-violet-500/30')
                : 'border-white/10 text-slate-400 hover:border-white/30 hover:text-white'
            }`}
          >
            {c}
          </button>
        ))}
        {(search || cat) && (
          <button onClick={() => { setSearch(''); setCat('') }} className="text-xs text-slate-500 hover:text-white flex items-center gap-1">
            <X className="w-3 h-3" /> Clear
          </button>
        )}
        <span className="ml-auto text-xs text-slate-500">{filtered.length} strategies</span>
      </div>

      {/* Cards grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
        {filtered.map(({ strategy_name, total_stocks, avg_return, avg_win_rate, avg_profit_factor, _info }) => (
          <button
            key={strategy_name}
            onClick={() => onDrill(strategy_name)}
            className="glass-panel p-5 text-left group hover:border-violet-500/40 transition-all duration-300 hover:shadow-lg hover:shadow-violet-500/10 relative overflow-hidden"
          >
            {/* Glow */}
            <div className="absolute top-0 right-0 w-32 h-32 bg-violet-500/5 rounded-full blur-3xl -mr-12 -mt-12 group-hover:bg-violet-500/15 transition-all" />

            {/* Header */}
            <div className="flex items-start justify-between mb-3">
              <div>
                <div className="flex items-center gap-2 mb-1 flex-wrap">
                  <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${CAT_COLOR[_info.category] || ''}`}>
                    {_info.category}
                  </span>
                  <span className={`text-xs px-2 py-0.5 rounded-full border font-medium ${RISK_COLOR[_info.riskProfile]}`}>
                    {_info.riskProfile} Risk
                  </span>
                </div>
                <h3 className="font-bold text-white text-base group-hover:text-violet-300 transition-colors">
                  {_info.displayName}
                </h3>
                <p className="text-slate-500 text-xs mt-0.5 leading-tight">{_info.tagline}</p>
              </div>
              <ChevronRight className="w-4 h-4 text-slate-600 group-hover:text-violet-400 group-hover:translate-x-1 transition-all flex-shrink-0 mt-1" />
            </div>

            {/* Metrics grid */}
            <div className="grid grid-cols-2 gap-2 mt-4">
              {[
                { label: 'Stocks Tested', value: total_stocks, suffix: '', color: 'text-white' },
                { label: 'Avg Return',    value: (avg_return * 100).toFixed(1), suffix: '%', color: avg_return >= 0 ? 'text-emerald-400' : 'text-rose-400' },
                { label: 'Avg Win Rate',  value: (avg_win_rate * 100).toFixed(1), suffix: '%', color: 'text-blue-400' },
                { label: 'Profit Factor', value: avg_profit_factor.toFixed(2), suffix: '×', color: avg_profit_factor >= 1 ? 'text-emerald-400' : 'text-rose-400' },
              ].map(m => (
                <div key={m.label} className="bg-white/[0.03] rounded-lg px-3 py-2">
                  <div className="text-slate-500 text-xs mb-0.5">{m.label}</div>
                  <div className={`font-bold text-sm ${m.color}`}>{m.value}{m.suffix}</div>
                </div>
              ))}
            </div>

            {/* Hold time pill */}
            <div className="mt-3 flex items-center gap-2 text-xs text-slate-500">
              <Clock className="w-3 h-3" />
              Hold: {_info.typicalHoldDays}
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Level 2: Strategy Detail (Overview + all stocks) ─────────────────────────

function StrategyDetailView({
  strategyName,
  onDrillStock,
  onBack,
}: {
  strategyName: string
  onDrillStock: (symbol: string, runId: string) => void
  onBack: () => void
}) {
  const [stocks,  setStocks]  = useState<StrategyStockSummary[]>([])
  const [loading, setLoading] = useState(true)
  const [search,  setSearch]  = useState('')
  const [showOnly, setShowOnly] = useState<'all' | 'with-trades' | 'profitable' | 'losing'>('all')
  const info: StrategyInfo = getStrategyInfo(strategyName)

  useEffect(() => {
    setLoading(true)
    fetch(`${API_BASE}/strategies/${strategyName}/stocks`)
      .then(r => r.json()).then(d => { setStocks(d); setLoading(false) }).catch(() => setLoading(false))
  }, [strategyName])

  const filtered = useMemo(() => {
    let base = stocks
    if (search) base = base.filter(s => s.symbol.toUpperCase().includes(search.toUpperCase()))
    if (showOnly === 'with-trades') base = base.filter(s => s.has_trades)
    if (showOnly === 'profitable')  base = base.filter(s => s.has_trades && s.total_return > 0)
    if (showOnly === 'losing')      base = base.filter(s => s.has_trades && s.total_return < 0)
    return base
  }, [stocks, search, showOnly])

  const profitable = stocks.filter(s => s.has_trades && s.total_return > 0).length
  const withTrades = stocks.filter(s => s.has_trades).length
  const avgReturn  = stocks.length ? stocks.reduce((s, r) => s + r.total_return, 0) / stocks.length : 0

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="flex items-center gap-1.5 text-sm text-slate-400 hover:text-white bg-white/5 hover:bg-white/10 px-3 py-1.5 rounded-lg transition-colors">
          <ArrowLeft className="w-4 h-4" /> Back
        </button>
        <Breadcrumb items={[
          { label: 'All Strategies', onClick: onBack },
          { label: info.displayName, onClick: () => {} },
        ]} />
      </div>

      {/* Strategy Overview Panel */}
      <div className="glass-panel overflow-hidden">
        <div className="p-6 border-b border-white/10 bg-gradient-to-r from-violet-500/10 to-blue-500/5">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <div className="flex items-center gap-3 mb-2 flex-wrap">
                <span className={`text-xs px-2.5 py-1 rounded-full border font-semibold ${CAT_COLOR[info.category] || ''}`}>{info.category}</span>
                <span className={`text-xs px-2.5 py-1 rounded-full border font-semibold ${RISK_COLOR[info.riskProfile]}`}>{info.riskProfile} Risk</span>
                <span className="text-xs px-2.5 py-1 rounded-full border border-white/10 text-slate-400 flex items-center gap-1">
                  <Clock className="w-3 h-3" /> Hold: {info.typicalHoldDays}
                </span>
              </div>
              <h2 className="text-2xl font-bold text-white">{info.displayName}</h2>
              <p className="text-slate-400 mt-1 text-sm italic">{info.tagline}</p>
            </div>
            <BookOpen className="w-8 h-8 text-violet-400 opacity-60" />
          </div>
        </div>

        <div className="grid md:grid-cols-2 gap-0 divide-y md:divide-y-0 md:divide-x divide-white/10">
          {/* Description + How it works */}
          <div className="p-6 space-y-5">
            <div>
              <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-2 flex items-center gap-2">
                <Lightbulb className="w-4 h-4 text-amber-400" /> Strategy Description
              </h3>
              <p className="text-slate-400 text-sm leading-relaxed">{info.description}</p>
            </div>

            <div>
              <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-2 flex items-center gap-2">
                <Zap className="w-4 h-4 text-violet-400" /> How It Works
              </h3>
              <ol className="space-y-1.5">
                {info.howItWorks.map((step, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-slate-400">
                    <span className="flex-shrink-0 w-5 h-5 bg-violet-500/20 text-violet-400 rounded-full flex items-center justify-center text-xs font-bold mt-0.5">{i + 1}</span>
                    {step}
                  </li>
                ))}
              </ol>
            </div>

            <div>
              <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-2 flex items-center gap-2">
                <Target className="w-4 h-4 text-blue-400" /> Best Market Conditions
              </h3>
              <p className="text-slate-400 text-sm leading-relaxed">{info.bestConditions}</p>
            </div>
          </div>

          {/* Signals + Params */}
          <div className="p-6 space-y-5">
            <div>
              <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-2 flex items-center gap-2">
                <TrendingUp className="w-4 h-4 text-emerald-400" /> Entry Signal
              </h3>
              <div className="bg-emerald-500/5 border border-emerald-500/20 rounded-xl px-4 py-3 font-mono text-xs text-emerald-300 leading-relaxed">
                {info.signals.buy}
              </div>
            </div>

            <div>
              <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-2 flex items-center gap-2">
                <TrendingDown className="w-4 h-4 text-rose-400" /> Exit Signal
              </h3>
              <div className="bg-rose-500/5 border border-rose-500/20 rounded-xl px-4 py-3 font-mono text-xs text-rose-300 leading-relaxed">
                {info.signals.sell}
              </div>
            </div>

            {info.keyParams.length > 0 && (
              <div>
                <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-2 flex items-center gap-2">
                  <Shield className="w-4 h-4 text-slate-400" /> Key Parameters
                </h3>
                <div className="space-y-2">
                  {info.keyParams.map(p => (
                    <div key={p.name} className="flex items-start justify-between gap-4 text-sm py-1.5 border-b border-white/5 last:border-0">
                      <span className="text-slate-300 font-medium flex-shrink-0">{p.name}</span>
                      <span className="text-slate-500 text-right">{p.description}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Aggregate stats */}
            <div>
              <h3 className="text-sm font-semibold text-slate-300 uppercase tracking-wider mb-3 flex items-center gap-2">
                <BarChart3 className="w-4 h-4 text-blue-400" /> Backtest Summary
              </h3>
              <div className="grid grid-cols-3 gap-2">
                {[
                  { l: 'Stocks Tested', v: stocks.length, c: 'text-white' },
                  { l: 'With Trades',   v: withTrades,    c: 'text-blue-400' },
                  { l: 'Profitable',    v: profitable,    c: 'text-emerald-400' },
                  { l: 'Avg Return',    v: fmtPct(avgReturn), c: avgReturn >= 0 ? 'text-emerald-400' : 'text-rose-400' },
                  { l: 'Win Rate',      v: stocks.length ? fmtPct(stocks.reduce((s,r) => s + r.win_rate,0) / stocks.length) : '—', c: 'text-blue-400' },
                  { l: 'Losing',        v: stocks.filter(s => s.has_trades && s.total_return < 0).length, c: 'text-rose-400' },
                ].map(m => (
                  <div key={m.l} className="bg-white/[0.03] rounded-lg p-2 text-center">
                    <div className="text-slate-500 text-xs mb-0.5">{m.l}</div>
                    <div className={`font-bold text-sm ${m.c}`}>{m.v}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Stock-wise table */}
      <div className="glass-panel overflow-hidden">
        <div className="p-5 border-b border-white/10 bg-white/5 flex flex-wrap items-center justify-between gap-3">
          <h3 className="text-lg font-bold flex items-center gap-2">
            <Activity className="text-blue-400 w-5 h-5" />
            Stock-wise Backtest Results
            <span className="text-sm font-normal text-slate-500">({filtered.length} / {stocks.length} stocks)</span>
          </h3>
          <div className="flex items-center gap-2 flex-wrap">
            {/* Quick filters */}
            {(['all', 'with-trades', 'profitable', 'losing'] as const).map(f => (
              <button
                key={f}
                onClick={() => setShowOnly(f)}
                className={`px-3 py-1 rounded-full text-xs font-medium transition-all ${
                  showOnly === f ? 'bg-violet-600 text-white' : 'bg-white/5 text-slate-400 hover:bg-white/10 hover:text-white'
                }`}
              >
                {f === 'all' ? 'All' : f === 'with-trades' ? 'Has Trades' : f === 'profitable' ? '▲ Profitable' : '▼ Losing'}
              </button>
            ))}
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500" />
              <input
                type="text"
                placeholder="Search stock…"
                value={search}
                onChange={e => setSearch(e.target.value)}
                className="bg-white/5 border border-white/10 text-sm text-slate-300 rounded-lg pl-8 pr-3 py-1.5 focus:outline-none focus:ring-1 focus:ring-violet-500 w-36"
              />
            </div>
          </div>
        </div>

        {loading ? (
          <div className="p-16 flex justify-center">
            <div className="w-10 h-10 border-4 border-violet-500 border-t-transparent rounded-full animate-spin" />
          </div>
        ) : (
          <div className="overflow-x-auto max-h-[560px] custom-scrollbar">
            <table className="w-full text-sm border-collapse">
              <thead className="sticky top-0 bg-[#111c2b] z-10 border-b border-white/10">
                <tr className="text-muted text-xs uppercase tracking-wider">
                  <th className="px-4 py-3 text-left">#</th>
                  <th className="px-4 py-3 text-left">Symbol</th>
                  <th className="px-4 py-3 text-right">Return</th>
                  <th className="px-4 py-3 text-right">Net PnL ₹</th>
                  <th className="px-4 py-3 text-right">Win Rate</th>
                  <th className="px-4 py-3 text-right">Trades</th>
                  <th className="px-4 py-3 text-right">Max DD</th>
                  <th className="px-4 py-3 text-center">Trades?</th>
                  <th className="px-4 py-3 text-right">PnL Bar</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                {filtered.length === 0 && (
                  <tr><td colSpan={9} className="p-8 text-center text-muted">No stocks match the current filter.</td></tr>
                )}
                {filtered.map((stock, i) => {
                  const maxAbs = Math.max(...filtered.map(s => Math.abs(s.total_return)), 0.001)
                  const barPct = Math.round((Math.abs(stock.total_return) / maxAbs) * 100)
                  return (
                    <tr
                      key={stock.symbol}
                      onClick={() => onDrillStock(stock.symbol, stock.run_id)}
                      className={`cursor-pointer hover:bg-white/[0.06] transition-colors group ${
                        !stock.has_trades ? 'opacity-50' : ''
                      }`}
                    >
                      <td className="px-4 py-3 text-slate-500 text-xs">{i + 1}</td>
                      <td className="px-4 py-3">
                        <span className="font-bold text-blue-400 group-hover:text-blue-300 group-hover:underline transition-colors font-mono">
                          {stock.symbol}
                        </span>
                      </td>
                      <td className={`px-4 py-3 text-right font-bold ${stock.total_return >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {fmtPct(stock.total_return)}
                      </td>
                      <td className={`px-4 py-3 text-right font-semibold ${stock.net_pnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {stock.has_trades ? fmtRupee(stock.net_pnl) : '—'}
                      </td>
                      <td className="px-4 py-3 text-right text-slate-300 font-mono">
                        {stock.has_trades ? fmtPct(stock.win_rate, 1) : '—'}
                      </td>
                      <td className="px-4 py-3 text-right text-slate-400">{stock.total_trades || '—'}</td>
                      <td className="px-4 py-3 text-right text-rose-400 font-mono text-xs">{fmtPct(stock.max_drawdown)}</td>
                      <td className="px-4 py-3 text-center">
                        {stock.has_trades
                          ? <CheckCircle2 className="w-4 h-4 text-emerald-400 mx-auto" />
                          : <AlertCircle className="w-4 h-4 text-slate-600 mx-auto" />}
                      </td>
                      <td className="px-4 py-3 w-28">
                        <div className="w-full bg-white/5 rounded-full h-2">
                          <div
                            className={`h-2 rounded-full transition-all ${stock.total_return >= 0 ? 'bg-emerald-500/70' : 'bg-rose-500/70'}`}
                            style={{ width: `${barPct}%` }}
                          />
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

// ── Main App ─────────────────────────────────────────────────────────────────

type MainTab = 'overview' | 'paper' | 'analytics'

function App() {
  const [activeTab, setActiveTab] = useState<MainTab>('overview')
  const [navState,  setNavState]  = useState<NavState>({ level: 'strategies' })
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)

  const [paperData, setPaperData]     = useState([])
  const [paperLoading, setPaperLoading] = useState(false)

  // Load paper data
  useEffect(() => {
    if (activeTab !== 'paper') return
    setPaperLoading(true)
    fetch(`${API_BASE}/paper/reconciliations`)
      .then(r => r.json()).then(d => { setPaperData(d); setPaperLoading(false) }).catch(() => setPaperLoading(false))
  }, [activeTab])

  // Nav handlers
  const drillStrategy = (strategyName: string) => {
    setNavState({ level: 'strategy-detail', strategyName })
  }

  const drillStock = async (strategyName: string, symbol: string, runId: string) => {
    // Try to find the most specific run for this strategy+symbol
    let resolvedRunId = runId
    try {
      const resp = await fetch(`${API_BASE}/strategies/${strategyName}/run-for-stock?symbol=${encodeURIComponent(symbol)}`)
      if (resp.ok) {
        const data = await resp.json()
        resolvedRunId = data.run_id
      }
    } catch { /* fall back to passed runId */ }
    setSelectedRunId(resolvedRunId)
    setNavState({ level: 'stock-analytics', strategyName, symbol, runId: resolvedRunId })
    setActiveTab('analytics')
  }

  const goToStrategies = () => {
    setNavState({ level: 'strategies' })
    setActiveTab('overview')
  }

  const goToStrategyDetail = () => {
    if (navState.level === 'stock-analytics') {
      setNavState({ level: 'strategy-detail', strategyName: navState.strategyName })
      setActiveTab('overview')
    }
  }

  const handleTabChange = (tab: MainTab) => {
    setActiveTab(tab)
    if (tab === 'overview') setNavState({ level: 'strategies' })
  }

  // Breadcrumb for analytics tab
  const analyticsBreadcrumb = navState.level === 'stock-analytics'
    ? [
        { label: 'All Strategies', onClick: goToStrategies },
        { label: getStrategyInfo(navState.strategyName).displayName, onClick: goToStrategyDetail },
        { label: navState.symbol, onClick: () => {} },
      ]
    : null

  return (
    <div className="min-h-screen p-6 md:p-8">
      <div className="max-w-7xl mx-auto space-y-2">

        {/* Header */}
        <header className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-6">
          <div>
            <h1
              className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-violet-400 flex items-center gap-3 cursor-pointer"
              onClick={goToStrategies}
            >
              <LayoutDashboard className="w-8 h-8 text-blue-400" />
              Trading Platform Dashboard
            </h1>
            <p className="text-slate-400 mt-1 text-sm">Quantitative strategy analytics — 21 strategies · 200+ stocks</p>
          </div>
          <div className="flex gap-2 bg-white/5 p-1 rounded-xl border border-white/10">
            <button
              onClick={() => handleTabChange('overview')}
              className={`px-4 py-2 rounded-lg font-medium text-sm transition-all ${activeTab === 'overview' ? 'bg-blue-600 text-white shadow-lg shadow-blue-500/20' : 'text-muted hover:text-white hover:bg-white/5'}`}
            >
              Strategy Overview
            </button>
            <button
              onClick={() => handleTabChange('paper')}
              className={`px-4 py-2 rounded-lg font-medium text-sm transition-all ${activeTab === 'paper' ? 'bg-amber-500 text-white shadow-lg shadow-amber-500/20' : 'text-muted hover:text-white hover:bg-white/5'}`}
            >
              Paper Trading
            </button>
            <button
              onClick={() => handleTabChange('analytics')}
              className={`px-4 py-2 rounded-lg font-medium text-sm transition-all ${activeTab === 'analytics' ? 'bg-violet-600 text-white shadow-lg shadow-violet-500/20' : 'text-muted hover:text-white hover:bg-white/5'}`}
            >
              Deep Dive Analytics
            </button>
          </div>
        </header>

        {/* Analytics breadcrumb */}
        {activeTab === 'analytics' && analyticsBreadcrumb && (
          <Breadcrumb items={analyticsBreadcrumb} />
        )}

        <main>
          {activeTab === 'paper' ? (
            <PaperReconciliationTab data={paperData} loading={paperLoading} />
          ) : activeTab === 'analytics' ? (
            <AnalyticsTab
              selectedRunId={selectedRunId}
              selectedSymbol={navState.level === 'stock-analytics' ? navState.symbol : null}
              onClearSymbol={() => {
                if (navState.level === 'stock-analytics') goToStrategyDetail()
                else setActiveTab('overview')
              }}
            />
          ) : (
            /* Overview — 2 levels */
            navState.level === 'strategies' ? (
              <StrategiesView onDrill={drillStrategy} />
            ) : navState.level === 'strategy-detail' ? (
              <StrategyDetailView
                strategyName={navState.strategyName}
                onDrillStock={(symbol, runId) => drillStock(navState.strategyName, symbol, runId)}
                onBack={goToStrategies}
              />
            ) : null
          )}
        </main>
      </div>
    </div>
  )
}

export default App
