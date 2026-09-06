# FAB-26 — Public NSE NIFTY 200 PIT Reconstruction & Evidence Build

**Disposition: BLOCKED — incomplete first-party historical evidence**  
**Requested period:** 2012-01-02 through 2026-08-20  
**Scope:** public, zero-cost, first-party NSE/NSE Indices evidence only  
**Run date:** 2026-09-06 (Asia/Kolkata)

## Executive finding

The requested point-in-time NIFTY 200 reconstruction cannot be certified from the
currently available first-party public artifacts. NSE/NSE Indices provide a current
constituent CSV, current factsheet, methodology, and dated daily report access, but no
complete public, dated constituent/event archive was located for the full requested
period. The current CSV must not be projected backward. No membership interval,
announcement date, effective date, delisting event, or historical identity mapping is
inferred in this package.

The protected `market_data.duckdb` and `market_data.duckdb.wal` were not opened,
modified, checkpointed, repaired, or deleted. No strategy, backtest, broker, order, or
live endpoint was used.

## Evidence classification

- **FACT:** The official NIFTY 200 factsheet states launch date 2011-07-19, 200 constituents,
  semi-annual rebalancing, and that NIFTY 200 combines NIFTY 100 and NIFTY Midcap 100.
- **FACT:** The official methodology states that inclusion/exclusion changes in NIFTY 100
  and NIFTY Midcap 100 flow into NIFTY 200, with a four-week notice period.
- **FACT:** The repository's `config/universes/nifty_200.yaml` and
  `tools/import_nifty200.py` describe a manually versioned *current* snapshot and
  explicitly warn that it is not point-in-time or survivorship-free.
- **FACT:** `reports/FAB-17_pit_readiness_20260906.md` records that the local DuckDB/WAL
  could not be read and that current PIT coverage could not be independently certified.
- **INFERENCE:** A semi-annual schedule and current constituent file are insufficient to
  reconstruct the actual historical membership set, announcement timestamps, and
  effective dates without the underlying dated notices/snapshots.
- **ASSUMPTION:** “Public NSE/NSE Indices evidence” excludes vendor-derived historical
  constituent datasets and any current-list backward projection.
- **UNKNOWN:** Complete dated membership, corporate-event, delisting, symbol-history,
  and knowledge-time records for every interval in 2012-01-02 through 2026-08-20.

## Source manifest

| ID | First-party source | Role | Retrieved/checked | Hash/status |
|---|---|---|---|---|
| S01 | https://www.nseindia.com/static/products-services/indices-nifty200-index | Official NIFTY 200 landing page and current CSV link | 2026-09-06 | URL evidence; raw CSV not persisted in this run |
| S02 | https://nsearchives.nseindia.com/content/indices/ind_nifty200list.csv | Current constituent snapshot endpoint | 2026-09-06 | CSV endpoint; no historical effective date; not used backward |
| S03 | https://archives.nseindia.com/content/indices/ind_nifty_200.pdf | Official factsheet | 2026-09-06 | PDF endpoint; not persisted in this run |
| S04 | https://archives.nseindia.com/content/indices/Method_NIFTY_Equity_Indices.pdf | Official methodology | 2026-09-06 | PDF endpoint; endpoint timed out during this run; search extract retained as source lead only |
| S05 | https://www.nseindia.com/all-reports/ | Official dated reports/download index | 2026-09-06 | Page evidence; historical constituent-event archive not located |
| S06 | `data/corporate_actions_nifty200.json` | Existing local event-like artifact | local | SHA-256 `0C76D5F6BDC1FAC629015E21F7829FF6C89F4025662369E3AB77B1FDC38BB84F`; provenance/raw NSE documents absent, therefore not certified |

Raw NSE artifacts were not silently transformed. Because the historical raw corpus is
missing, no raw-artifact directory, source hash set, or derived authoritative ledger is
claimed as complete.

## Required control outputs and status

| Control/output | Status | Reason |
|---|---|---|
| Source manifest | PARTIAL | First-party URLs and local artifact hash recorded; raw historical corpus absent |
| Event ledger | BLOCKED | No complete dated NSE/NSE Indices event/notice corpus |
| Membership intervals | BLOCKED | Cannot derive intervals from current constituents or schedule alone |
| Known/effective-date controls | BLOCKED | Announcement/knowledge timestamps unavailable for historical changes |
| Official snapshot reconciliation | BLOCKED | Only current snapshot endpoint identified; dated historical snapshots unavailable |
| Coverage matrix | COMPLETE AS GAP REPORT | All requested years are unverified; no interval is certified |
| Identity validation | BLOCKED | Historical symbol/name/ISIN continuity source corpus unavailable |
| Deterministic outputs | PARTIAL | This report and source inventory are deterministic; no PIT dataset emitted |

## Coverage matrix

| Period | Official dated membership evidence | Event evidence | PIT interval output | Disposition |
|---|---:|---:|---:|---|
| 2012-01-02–2014-12-31 | 0 | 0 | 0 | BLOCKED |
| 2015-01-01–2017-12-31 | 0 | 0 | 0 | BLOCKED |
| 2018-01-01–2020-12-31 | 0 | 0 | 0 | BLOCKED |
| 2021-01-01–2023-12-31 | 0 | 0 | 0 | BLOCKED |
| 2024-01-01–2026-08-20 | 0 | 0 | 0 | BLOCKED |

Zero means “not certified from an eligible dated first-party raw artifact,” not that no
index changes occurred.

## Reproducibility instructions

From `C:\Python projects\algo trading`:

```powershell
Get-FileHash data\corporate_actions_nifty200.json -Algorithm SHA256
Get-Content config\universes\nifty_200.yaml
Get-Content tools\import_nifty200.py
Get-Content reports\FAB-17_pit_readiness_20260906.md
```

For an unblock attempt, an independent data/recovery owner must supply immutable,
first-party dated NSE/NSE Indices raw artifacts for every membership change and event,
with retrieval timestamps and hashes. Then a separate QA/Risk reviewer must rerun the
interval, knowledge-time, identity, reconciliation, and coverage controls without
touching the protected database files.

## Escalation

**Unblock owner:** Data/Recovery owner, to recover a readable immutable local database
copy and source corpus.  
**Required action:** provide the missing dated first-party membership/event artifacts;
generate the complete manifest, ledger, intervals, and controls; submit to Independent
QA/Risk.  
**QA/Risk disposition:** required before any use in strategy research. No profitability,
validation, or live-trading conclusion is authorized by this report.
