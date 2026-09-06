# FAB-10 candidate strategy evidence package

## Recommendation

**Candidate:** long-only 200-session trend filter: hold the index/asset when the close is above its causal 200-session simple moving average; otherwise hold cash.

**Recommendation:** admit this as a *paper-only research candidate* for the next validation stage, not as a validated strategy and not for live routing. The local diagnostic is reproducible and leakage-controlled, but the source database fails the project’s PIT-universe gate, so no claim about a tradable Indian-equity portfolio is supported.

## Evidence labels

- **FACT:** `recovery/campaign1-20260902/base-only/market_data.duckdb` opens read-only and contains 62,372,402 historical candles, including 3,628 daily `NIFTY200` observations from 2012-01-02 through 2026-08-20.
- **FACT:** the queried candles are `SPLIT_ADJUSTED`; the database reports provider `angel_one` and two dataset IDs for `NIFTY200`.
- **FACT:** `index_constituents_pit` contains zero rows, and the available snapshot is marked survivorship-biased in `reports/campaign1_data_readiness_recovery_20260902.md`.
- **FACT:** the deterministic diagnostic uses the close at session *t*, shifts the resulting position to session *t+1*, and executes at the next row’s open. It never uses the current close to execute.
- **FACT:** the academic motivation is time-series momentum/trend persistence; Moskowitz, Ooi, and Pedersen document time-series momentum across 58 liquid futures instruments: <https://fairmodel.econ.yale.edu/ec439/mosk.pdf>.
- **INFERENCE:** a slow trend filter is a reasonable low-turnover candidate for paper validation because it has an auditable causal rule and a modest number of state transitions; this is a hypothesis, not evidence of alpha in Indian equities.
- **ASSUMPTION:** percentage-only round-trip drag is modeled as 2 bps spread + 3 bps slippage + 10 bps STT per side. Fixed brokerage and DP charges are explicitly excluded from this diagnostic and must be added in the next validation run.
- **UNKNOWN:** whether the split-adjusted series has complete corporate-action, delisting, symbol-history, and point-in-time membership treatment. This is why the result is diagnostic-only.

## Deterministic result

Artifact: `reports/candidate_trend_backtest_20260906.json`.

| Metric | Result |
|---|---:|
| Evaluation period | 2012-10-15 to 2026-08-20 |
| Observations | 3,429 |
| Total return, net diagnostic costs | 110.14% |
| Annualized return | 5.51% |
| Annualized volatility | 11.49% |
| Sharpe (0% risk-free, diagnostic) | 0.53 |
| Maximum drawdown | -25.55% |
| Trade events | 113 |
| Exposure | 75.15% |
| Gross return | 149.02% |
| Modeled cost drag | 16.95 percentage points (simple summed daily drag measure) |

The return statistics are **not a portfolio recommendation**: they are one index-series diagnostic, use a non-PIT source, omit fixed charges, and have no independent QA approval.

## PIT, leakage, and robustness checks

- **PIT check: FAIL.** No historical constituent membership rows are available. A future validation must use dated membership with `known_from` controls, not today’s NIFTY 200 list.
- **Look-ahead check: PASS for this diagnostic.** Rolling features are formed only from current/prior rows; target position is shifted one row; execution uses the next row open.
- **Data integrity: PARTIAL.** Daily coverage and adjustment labels are present, but certification rows are absent in the base-only recovery candidate and provider provenance is not sufficient to establish PIT completeness.
- **Robustness: NOT RUN.** Required next tests are walk-forward splits, 100/150/200/250-day windows, cost stress, missing-bar checks, and a historical constituent panel. No parameter-selection claim is made.

## Reproduction

From the repository root, with the checked-in virtual environment:

```powershell
.\venv\Scripts\python.exe tools\run_candidate_trend_backtest.py
```

The script is read-only against DuckDB and writes only `reports/candidate_trend_backtest_20260906.json`. To rerun against another read-only database:

```powershell
.\venv\Scripts\python.exe tools\run_candidate_trend_backtest.py --db <path> --symbol NIFTY200 --window 200 --output reports/candidate_trend_backtest_custom.json
```

## Open questions / escalation

1. Data Engineering/QA must restore authoritative historical PIT constituents and certification evidence.
2. QA/Risk must independently reproduce the script and review cost assumptions before any paper session.
3. The next experiment must test investable constituents, delisted names, corporate-action semantics, and fixed brokerage/DP costs.
4. Live endpoints, credentials, and live order routing remain out of scope.
