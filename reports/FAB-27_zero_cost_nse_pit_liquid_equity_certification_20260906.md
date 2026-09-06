# FAB-27 — Zero-cost NSE PIT liquid equity universe

Disposition: **BLOCKED**

Decision token: `BLOCKED`

## Scope and boundary

This is a distinct candidate universe, `NSE_PIT_LIQUID_EQUITY_ZERO_COST_V1`, for
2012-01-02 through 2026-08-20. It is not the NIFTY 200, does not backfill current
constituents, and does not alter FAB-17, FAB-26, FAB-23 policy, the database/WAL, or safety gates.
No strategy, backtest, paper session, broker API, credential, order, live endpoint, paid data,
or capital was used.

## Evidence inventory

Only public first-party NSE/NSE Indices material is admissible: the official security master/listing
and suspension/delisting notices, dated index/market reports where used as cross-checks, and official
corporate-action or index-review notices. The package preserves downloaded bytes under
`data/raw/nifty200_pit_public_sources/` with `source_manifest.csv` SHA-256 entries. The existing
download set is useful discovery evidence, but it is NIFTY 200-oriented and is not evidence that a
liquid-equity universe was historically eligible.

FACT: the current package extraction reports unresolved coverage and is explicitly candidate-only.
FACT: no complete, independently reconciled PIT security-master plus turnover observations for the
full required horizon are present in the package.
UNKNOWN: historical symbol/ISIN mappings, suspensions, listing dates, and turnover completeness for
every rebalance date.

## Rules

Include only NSE-listed ordinary equity with verified ISIN, a proven effective interval, no
suspension/delisting at the decision date, and complete pre-decision turnover observations.
Exclude ETFs, REITs, InvITs, debt, preference shares, warrants, mutual funds, and any row with an
unresolved security type or identity. Use a fixed, pre-announced rolling window (recommended:
252 exchange sessions) and thresholds recorded in the run manifest; this report does not invent a
threshold without an approved experiment specification.

Identity is ISIN-primary. `symbol_at_event` is retained for audit, with effective-dated aliases;
symbol-only joins are prohibited. Missing ISIN, conflicting alias intervals, or an unexplained
corporate action fails closed.

## PIT and survivorship controls

Membership at date *t* may use only sources published/available by the rebalance decision time and
observations ending before that time. No today's constituents, future delistings, future prices, or
future corporate actions may enter an earlier interval. Every membership mutation requires a
first-party source URL, retrieval timestamp, source SHA-256, parser version, effective date, and
reconciliation status. Unresolved intervals remain `UNRESOLVED_GAP` and are excluded from any
research universe.

## Coverage and rebalance comparison

| Horizon | Required evidence | Status |
|---|---|---|
| 2012-01-02–2013-12-31 | historical security identity + listing/turnover observations | UNRESOLVED_GAP |
| 2014-01-01–2020-12-31 | effective-dated identity, suspensions, turnover, rebalance snapshots | UNRESOLVED_GAP |
| 2021-01-01–2026-08-20 | same, including latest available official notices | UNRESOLVED_GAP |

Rebalance comparison must report additions, removals, unchanged members, unresolved identities,
missing observations, and source hashes for each event. It has not been certified because the
required PIT inputs are incomplete.

## Candidate output and reproducibility

The candidate schema is `candidate_output_schema.json`; pure controls are in
`liquid_universe_spec.py`. Re-run deterministic checks with:

```powershell
.\venv\Scripts\python.exe -m pytest nifty200_zero_cost_pit_package/test_liquid_universe_spec.py -q
```

The expected certification result is `BLOCKED` until the evidence matrix is complete and reviewed
by Independent QA/Risk. The package's raw manifest and derived files must be retained unchanged;
rebuilds must record command, Python/dependency versions, parser version, input hashes, and output
hashes.

## Board decision matrix

| Decision | Evidence condition | Current result |
|---|---|---|
| Board review candidate | full horizon coverage, zero material identity gaps, PIT liquidity completeness, QA/Risk sign-off | Not met |
| Continue evidence acquisition | first-party sources can close named gaps reproducibly | Required |
| Reject for research use | any look-ahead, survivorship contamination, paid/non-first-party dependency, or failed replay | Fail-closed if found |

QA/Risk owner: Independent QA / Risk Lead. Unblock action: acquire and independently reconcile the
missing first-party PIT identity, listing/status, and turnover evidence, then rerun this bundle.
