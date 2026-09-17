# PIT calendar audit: verified defects, not full calendar certification

Status: INCOMPLETE. No trading, research run, broker call, or production database operation was performed.

Update 2026-09-15: the four staged documents below were merged into the v4 build. Six hash-bound overrides now cover those four dates, including the two intraday interruptions. A regression exposed and fixed interruption filtering for newly added special sessions. Date-only knowledge times now use the same repository calendar. The original findings below describe the pre-fix probe, not current behavior. The campaign calendar remains PARTIAL_NOT_CERTIFIED, with 3,611 sessions in v4 rather than 3,609.

Two additional first-party documents were downloaded successfully (HTTP 200) on 2026-09-15 and inspected, but are staged separately and **not included in v4**:

- `https://nsearchives.nseindia.com/content/circulars/CMTR65729.pdf`: February 1, 2025 normal market 09:15-15:30 IST; SHA-256 `84d12e29654e75f77baa0b9064a26f6d0e4c3ff58e64df14e01247a0c15a91be`.
- `https://nsearchives.nseindia.com/content/circulars/CMTR59124.pdf`: November 12, 2023 Muhurat normal market 18:15-19:15 IST; SHA-256 `09f80430f3ec95aeaeeb98938124273892abccc38a7aaa440b38a6426b428c21`.

Staging catalogue: `artifacts/calendar_acquisition_20260915/data/raw/nifty200_pit_public_sources/source_catalogue.json`. Apply through the existing overrides with regression tests, then rebuild; do not count these as resolved in v4.

Additional read-only API probe on 2026-09-15 reproduced two remaining calendar defects (`reports/nifty200_pit_calendar_api_probe_20260915.json`): January 22, 2024 correctly returns `is_trading_day=false`, but `expected_minute_index` still returns 375 minutes; March 2, 2024 at 10:30 IST incorrectly returns `is_session_open=true` during the evidenced interruption. The v4 PIT decision-date list excludes January 22 correctly, but the broader calendar API is not yet internally consistent. Fix with focused regressions before claiming calendar closure.

The builder calls the repository's `trading_stack.calendars.build_nse_calendar`, backed by installed `pandas-market-calendars-5.4.0`, without any `SessionOverride` entries. A direct read-only probe returned:

| Date | Provider says trading day | Evidence-backed finding |
| --- | --- | --- |
| 2024-01-20 | False | NSE Clearing's CMPT60343 explicitly records executed trades and revised settlement for this special live session. |
| 2024-01-22 | True | NSE CMTR60338 explicitly declares this a trading holiday. |
| 2024-03-02 | False | NSE MSD60677 explicitly schedules live CM trading, 09:15–10:00 and 11:30–12:30 IST. |
| 2024-05-18 | False | NSE MSD61893 explicitly schedules live CM trading, 09:15–10:00 and 11:30–12:30 IST. |
| 2023-11-12 | False | Candidate Muhurat-session discrepancy; official timing evidence not yet acquired in this audit. |
| 2025-02-01 | False | Candidate Budget-session discrepancy; official timing evidence not yet acquired in this audit. |

## Acquired official evidence

These sources are in a separate staging catalogue to avoid concurrent writes while the main PIT builder is running:
`artifacts/calendar_acquisition_20260912/data/raw/nifty200_pit_public_sources/source_catalogue.json`.

| Source | SHA-256 |
| --- | --- |
| https://nsearchives.nseindia.com/content/circulars/CMTR60338.zip (member CMTR60338.pdf) | c70a96e353be65fa1905057300ddd0cb8823fb8398bb3b9e13d95fbe166888b2 |
| https://nsearchives.nseindia.com/content/circulars/CMPT60343.pdf | 9236595e1d85a2c58abaa9d6a8e2d148f8ca7fdd696faa20407e91b233840361 |
| https://nsearchives.nseindia.com/content/circulars/MSD60677.pdf | 04b67f39314bae95672d86497c28cbed6cea698ad6f029ba47ef74feb9f6da91 |
| https://nsearchives.nseindia.com/content/circulars/MSD61893.pdf | 2483f60d67c34231d6fd25024cf5767c031b234196a7a475535d434cd4e758c8 |

Failed direct paths: CMTR60338.pdf, CMTR60340.pdf, CMTR60340.zip returned HTTP 404. The broker bulletin was used only to discover the working first-party CMTR60338.zip URL; its statements are not the certification source.

## Required next correction

Use the existing repository SessionOverride mechanism with locally hash-verified exchange evidence; preserve interruptions between the two live sessions. Audit all campaign years for exceptional closures, Budget sessions, Muhurat sessions, and other weekend live sessions. Do not label the current 3,609-session validation as a fully certified NSE decision-session audit. Session membership validation and date-only known_at derivation must use the same audited calendar. Independent QA remains NOT_ASSERTED.
