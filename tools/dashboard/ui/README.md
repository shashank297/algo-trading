# Algo Trading Web Dashboard UI

The Algo Trading Web Dashboard is an interactive analytics interface for visualizing backtest results, strategy performance metrics, equity curves, drawdown trajectories, fills, trade attribution, risk allocations, and data quality certification status.

---

## Features

- **Strategy Runs & Comparisons**: Browse and filter single-asset and cross-sectional portfolio strategy runs with Sharpe, Sortino, Calmar, Max Drawdown, and Win Rate metrics.
- **Interactive Equity Curves**: View marked-to-market daily portfolio equity curves, benchmark comparisons (NIFTY 200), and underwater drawdown plots.
- **Trade Attribution & Fills**: Detailed drill-down into executed orders, statutory cost drag breakdowns (STT, broker fees, exchange charges, stamp duty, DP charges), holding periods, and trade reasons.
- **Risk & Allocations**: Monitor daily sector exposures, portfolio gross exposures, and risk decisions.
- **Data Quality & Provenance**: Inspect dataset certification records, Point-in-Time universe snapshots, and historical session alignment status.

---

## Architecture & Technology Stack

- **Framework**: [React 19](https://react.dev/) + [TypeScript](https://www.typescriptlang.org/)
- **Build Tool**: [Vite](https://vite.dev/)
- **Styling**: TailwindCSS + Lucide Icons + Radix UI components
- **Charting**: Recharts / Canvas charting
- **Backend API**: FastAPI (`tools/dashboard/api/main.py`) serving read-only DuckDB data via REST endpoints.

---

## Development & Build

### Prerequisites
- Node.js `20+` and `npm`
- Running FastAPI backend on `http://localhost:8000`

### Start Development Server
```powershell
cd tools\dashboard\ui
npm install
npm run dev
```
The development server will start at `http://localhost:5173/` and proxy API requests to `http://localhost:8000`.

### Linting
```powershell
npm run lint
```

### Production Build
```powershell
npm run build
```
The compiled static assets will be output to the `dist/` directory.

---

## API Proxy Configuration

During development, Vite proxies all `/api` requests to the local backend:
- `VITE_API_BASE_URL` defaults to `http://localhost:8000` (configured in `vite.config.ts`).
