# Campaign 1 Historical PIT Data Readiness

Date: 2026-09-03
Branch: `main`
Main SHA: `196df4206f5c20e4d2edab434d679c9a7e9dd570`

## Verdict

`CAMPAIGN 1 DATA READINESS BLOCKED`

Blockers:

1. `DATABASE_RECOVERY_REQUIRED`: the original database cannot be opened with
   DuckDB 1.5.5 while its matching WAL is present.
2. `EXTERNAL HISTORICAL CONSTITUENT DATA REQUIRED`: no authoritative historical
   NIFTY 200 membership evidence is present in any readable local candidate.
3. PIT completeness, market-data intersection, and authoritative certification
   cannot be established without that evidence.

No Campaign experiment, trial reservation, strategy run, Stage A/B/C/D/E/F
execution, or paper session was started.

## Frozen Campaign Contract

| Field | Value |
| --- | --- |
| Campaign ID | `campaign-1-2d653914799e` |
| Research configuration hash | `ec50bff064bed0d2b4ff59a97961467d2225a4e3511ac8155f8555b8f66a1357` |
| RiskPolicy hash | `8330bb013ffd1d22acb2c60d715066a43b239cd35b382e772c4a7d47c7d72a3c` |
| Cost identity | `52e6a43699be4daee483c7503742b033235b0e47d918782ce74cf811aae8e79f` |
| Feature version | `features-v1` |
| Economic semantics | `current_mark_to_market_equity_v1/floor_whole_share_v1` |
| Execution mode | `event-driven` |
| Starting capital | `100000.0` |
| Benchmark | `NIFTY200` |
| Live trading | `false` |
| Strategy library count | `20` |
| Strategy library hash | `ef5e1492b81c4e76f4f1e9c6fae4d54de4597b8eabb1af223fc4eee8174742d8` |
| Selector blob | `d9bc13fc7d7e7c3f486c4223c03eb03254bc98d5` |

The preflight also reported the date-effective cost schedule sequence from
2010-01-01, 2016-06-01, 2024-10-01, and 2026-04-01. These identities were not
changed.

## Database And Recovery Evidence

DuckDB version: `1.5.5`

| Candidate | Size | Result |
| --- | ---: | --- |
| `market_data.duckdb` plus matching WAL | 9,860,820,992 bytes plus 2,396 bytes | Read-only open fails during WAL replay |
| `recovery/campaign1-20260902/base-only/market_data.duckdb` | 9,860,820,992 bytes | Readable forensic candidate; not authoritative because WAL was excluded |
| `backups/market_data-20260818.duckdb` | 4,053,020,672 bytes | Readable backup candidate; not authoritative PIT evidence |

Original file hashes, retained from the recovery report:

- Database: `BE513B6E5D0E8ED7C0E70F3EFD58406565DE2CE554F493B81E9B421C409FED0E`
- WAL: `CA4E2221286E0F16E7BFBB1FB7050118F0CA883FED28A5BEDB7E1CA7154356DF`
- Backup: `498DEAE820657C27992D3B623B76581D5394A838C311CB5B758068508DD812E9`

The original database and WAL were not overwritten, deleted, or checkpointed.

## PIT Inventory

The base-only candidate has 75 tables, 62,372,402 historical candles, and
4,874 market datasets. It contains:

- `index_constituents_pit`: `0` rows;
- `index_constituent_knowledge`: no authoritative membership records;
- one snapshot, `NIFTY200_2026_08_17`, with 200 current members;
- snapshot metadata `survivorship_bias=true`, `active_from=2026-08-17`, and no
  historical `active_to` intervals;
- `research_frame_certifications`: `0` rows;
- `data_quality_certifications`: `0` rows.

The backup contains 48 tables and no `index_constituents_pit` table. Neither
candidate provides additions, removals, former constituents, delistings,
knowledge-time fields, source certification, or a PIT completeness manifest.
The current snapshot is therefore rejected and was not relabeled or mutated.

## Market Data

The readable base-only candidate has NSE daily coverage from `2012-01-02` to
`2026-08-20` for 201 symbols, but this does not establish PIT eligibility.
Because historical membership intervals and identity mappings are absent,
complete/partial/missing former-member coverage and the campaign-safe
intersection cannot be calculated. The campaign-safe date range is `NONE`.

## Readiness Command

Command:

```text
.\\venv\\Scripts\\python.exe run_pipeline.py --universe-snapshot NIFTY200_2026_08_17 --preflight-only --database-path market_data.duckdb
```

Result: `PIPELINE PREFLIGHT BLOCKED`, with `DATABASE_RECOVERY_REQUIRED` and
`PIT_UNIVERSE_NOT_READY`. The command opened the database read-only and did not
mutate Campaign experiment state.

## External Source Gap

NSE's NIFTY 200 page provides a current constituent CSV and methodology, while
NSE Indices describes historical constituent data as a subscription data
product. A current snapshot is not sufficient for the required historical
point-in-time intervals. An authoritative historical source with effective and
knowledge-time evidence must be obtained before import and certification.

Required next input: licensed or otherwise authoritative historical NIFTY 200
constituent records covering the proposed Campaign interval, including source
provenance, membership events, instrument identity mapping, and causally valid
`known_at` timestamps.

`EXTERNAL HISTORICAL CONSTITUENT DATA REQUIRED`

`CAMPAIGN 1 DATA READINESS BLOCKED`
