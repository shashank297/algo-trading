# NIFTY 200 Zero-Cost PIT Reconstruction Package

Purpose: build a provenance-preserving candidate point-in-time NIFTY 200 membership history for
2012-01-02 through 2026-08-20 using only freely accessible first-party NSE / NSE Indices evidence.

This package is intentionally fail-closed. It does not run strategies, backtests, paper trading,
broker APIs, or modify `market_data.duckdb` / `market_data.duckdb.wal`.

## Evidence strategy

1. Bootstrap from an official monthly NIFTY 200 constituent snapshot (April 2013 or nearest available).
2. Reconstruct backwards to 2012-01-02 using official inclusion/exclusion events.
3. Use monthly NSE Indices market-cap/weightage archives (April 2013 through March 2022) as independent checkpoints.
4. From March 2022 forward, replay official NSE Indices press-release events.
5. Preserve original source bytes, SHA-256, source URL, retrieval timestamp, and parser version.
6. Never infer a historical membership from today's NIFTY 200 constituent list.
7. If an event/date/identity cannot be proven from first-party evidence, mark the interval UNRESOLVED_GAP.

## Main official sources

- NSE/NSE Indices historical inclusion/exclusion workbook:
  https://archives.nseindia.com/content/indices/IndexInclExcl.xls
- NSE Indices monthly reports:
  https://www.niftyindices.com/reports/monthly-reports
- NSE Indices historical-data archive:
  https://www.niftyindices.com/reports/historical-data
- NSE Indices press-release archive:
  https://www.niftyindices.com/press-release
- NIFTY 200 official page:
  https://www.nseindia.com/static/products-services/indices-nifty200-index
- NIFTY equity-index methodology:
  https://archives.nseindia.com/content/indices/Method_NIFTY_Equity_Indices.pdf

Known monthly ZIP pattern:
https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataMar2022.zip

The acquisition script tests the analogous month URLs from Apr-2013 through Mar-2022 rather than
assuming all URLs exist.

## Run

Use a clean Python environment on the machine that has internet access:

    python -m pip install -r requirements.txt
    python acquire_sources.py --root "C:\Python projects\algo trading"
    python extract_candidate_evidence.py --root "C:\Python projects\algo trading"

The scripts create their own NIFTY 200 evidence directories and do not touch the trading database.

## Outputs

Under the supplied root:

    data/raw/nifty200_pit_public_sources/
    data/derived/nifty200_pit/
    reports/

The acquisition step creates a SHA-256 manifest. The extraction step creates:
- press_release_candidates.csv
- monthly_snapshot_candidates.csv
- coverage_matrix_seed.csv

These are candidate evidence, NOT certification.

## Required QA rule

Do not resolve FAB-17's `NIFTY200_HISTORICAL_PIT_DATA` blocker unless Independent QA/Risk accepts
the completed reconstruction and all material gaps are closed.
