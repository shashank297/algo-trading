# NIFTY-200 PIT actionable blocker closure

Date: 2026-09-21  
Repository: `shashank297/algo-trading`  
Worktree: `C:\Python projects\algo trading-authoritative-evidence`  
Branch: `codex/nifty200-pit-authoritative-evidence`  
HEAD: `2c3f89db280398787e4221dd151273332c95d5a5`

## Scope

This is the task-scoped closure record for the actionable blockers in the latest
full real-data build. It does not continue the broad 2012 anchor search, change
the 68 monthly checkpoint blockers, promote B1 evidence, infer an ISIN, merge
predecessor/successor instruments, weaken validation, or touch the production
DuckDB/WAL.

The separate anchor investigation report was committed first as:

`2c3f89d docs(pit): record 2012 anchor investigation`

The pre-existing modified anchor reports and pre-existing untracked reports
were preserved and were not included in that commit.

## Current measured build

| Measure | Value |
| --- | ---: |
| Source records | 597 |
| A1 / A2 / B1 sources | 590 / 6 / 1 |
| Source hash failures | 0 |
| Event observations | 1,544 |
| Canonical events | 671 |
| ADD / DROP events | 327 / 344 |
| Snapshot rows / dates | 21,650 / 108 |
| Valid 200-member checkpoints | 58 |
| Missing or non-200 checkpoints | 68 |
| Current security-master rows | 2,578 |
| Historical identity rows | 230,784 |
| Unique historical instruments | 4,933 |
| Durable-ID / ISIN resolution | 45.7902% / 45.7902% |
| Unresolved identity cases | 15 |
| Constituent intervals | 325 |
| Campaign sessions checked | 3,613 |
| Minimum / maximum active constituents | 0 / 119 |
| Sessions not at expected count | 3,613 |
| known_at unresolved | 0 |
| Total / HIGH / CRITICAL conflicts | 137 / 1 / 136 |
| Anchor status | `NOT_ESTABLISHED` |
| Calendar status | `PARTIAL_NOT_CERTIFIED` |
| Validation | `BLOCKED` |

Before and after this closure pass are identical. No admissible new source was
added and no canonical event or identity row was changed, so a second build was
not justified. The existing full build remains the measured result.

## Exact unresolved durable-identity cases

All 15 rows remain `HIGH / UNRESOLVED` in
`artifacts/nifty200_pit_v1/blocker_ledger.csv`. The triggering A1 source for
the first 14 rows is the official inclusion/exclusion workbook
`https://archives.nseindia.com/content/indices/IndexInclExcl.xls`, SHA-256
`8869bb7c4df67403131a494a8cc65509e80828f9438bc150b506cdbf55378046`. That
workbook supplies the index event and company name but not a durable symbol/ISIN
pair. The final row is an A1 press-release assertion with SHA-256
`6607e06189839f749758147d8f21d9fdf6696ba4a32472992f007f96c34ed3b7`.

| Blocker ID | Effective date | Company / symbol | Why it remains open | Evidence needed to close |
| --- | --- | --- | --- | --- |
| `9ccf6d88a0832631cd232179f1c91ddaa16f80a40266046d0ca19ee3e5368cdc` | 2012-04-27 | Gujarat NRE Coke Ltd. | Index workbook is company-only; exact period-valid equity symbol/ISIN linkage is not established by the available admissible evidence. | Dated official NSE security master, bhavcopy containing an independently linked company name, or an official symbol/ISIN/corporate-action document valid on or before 2012-04-27. |
| `f8454f928217b964140a9f80157b8a8d0ef11b658beb6b2577bc54f6923503be` | 2012-09-28 | Fortis Healthcare Ltd. | Current and later historical observations do not by themselves prove the exact 2012 index assertion; a current filing cannot be backdated. | Period-valid official NSE identity evidence for Fortis at the event date. |
| `cdaea287793adfb17b0e5ef2143363816c2eefb14b2f5e0cf6cc4262425179d7` | 2012-09-28 | Jammu & Kashmir Bank Ltd. | Same company-only index assertion; later identity observations are insufficient to certify the event-date relationship. | Period-valid official NSE identity evidence for the ordinary equity instrument at the event date. |
| `201892061e32568273e6d3b53b91e25bf1257ca924914bf2555a93d22388d0d3` | 2012-09-28 | Shree Cement Ltd. | Same company-only index assertion; no exact event-date A1/A2 identity row has been admitted. | Period-valid official NSE identity evidence for the ordinary equity instrument at the event date. |
| `41afd83eb951ad0ebc9c413a5dd88280b7c584b069f49fbef3670de781f2d44d` | 2013-04-17 | Future Retail Ltd. | The current identity is not evidence of the historical event-date identity, especially given later corporate distress and successor questions. | Dated official NSE identity or corporate-action evidence valid on or before 2013-04-17. |
| `e17a370f89faf4da4aa0aae695e0aeaea2bf380a612d8ff2961597ed4ffd2b0c` | 2013-09-27 | GVK Power & Infrastructures Ltd. | Company-only index assertion lacks an admitted period-valid symbol/ISIN linkage. | Dated official NSE security master or identity/corporate-action document covering 2013-09-27. |
| `90da867472de290bfe9ea910b1a90f361791f424255f4763ea45f9920e9b57fd` | 2015-05-29 | Alstom T&D India Ltd. | Historical corporate/name changes make current `GECALSTHOM` evidence insufficient to backdate the Alstom T&D instrument. | Official dated symbol/name/ISIN change or corporate-action chain proving the exact instrument. |
| `e8ee69b9a443f85142f02ca9139952df6b36a6b5133a70e197fbc3ba4683c701` | 2015-09-28 | Ajanta Pharmaceuticals Ltd. | The available historical/current rows do not constitute an admitted identity observation for the index event itself. | Dated official NSE identity evidence valid on or before 2015-09-28. |
| `d527b405bb2dd2aee45d4d037aad0f67888168b0bcc2eec890d9964c00370074` | 2016-04-01 | Alstom T&D India Ltd. | Same unresolved predecessor/name-change chain as the 2015 case. | Official dated symbol/name/ISIN change or corporate-action chain proving the exact instrument. |
| `ce7fbd24119453afcd3b3cf805385d2cc58b405d8b2c2f90dfadbf7eca4a1976` | 2016-04-01 | Jain Irrigation Systems Ltd. | Ordinary equity versus DVR and historical symbol/ISIN identity must be proven for the event date; a name-only match is insufficient. | Official dated NSE identity evidence for the ordinary equity instrument. |
| `b7cbaf38329e5ceb547d7b61f20acd8fe12de2caae54b8c34d2829835a712ba3` | 2016-04-01 | National Buildings Construction Corporation Ltd. | The index row is company-only; no admissible event-date identity row has been incorporated. | Dated official NSE identity evidence valid on or before 2016-04-01. |
| `e7af7af8c98e626f7afe0cc8a9f77ddc7e046364d53224316405f3428969e226` | 2018-09-28 | HDFC Standard Life Insurance Company Ltd. | Later renamed HDFC Life evidence cannot be silently backdated to the original event assertion. | Official dated name/symbol/ISIN change chain covering the event date. |
| `938ad5a93cdc1d7580242c13239bf8e8c5558015c4042910bbe176db78d11844` | 2019-09-27 | Reliance Nippon Life Asset Management Ltd. | The company-name assertion lacks an admitted event-date durable identity row. | Dated official NSE identity evidence valid on or before 2019-09-27. |
| `fd7d78a3c1f856b71006d67ec361a7d5686fcb277274bba8ad8b24378c76d510` | 2020-06-26 | Adani Gas Ltd. | The later official name/symbol change to Adani Total Gas does not prove the pre-change event-date identity without a complete dated chain. | Official dated identity/name-change evidence covering the ordinary equity instrument at 2020-06-26. |
| `96ac40604ad4b399816a834cd20b8eb94897ae1ec7f001c1d6a7dc8a6166f7a9` | 2013-11-15 | `IBULHSGFIN` / Indiabulls Housing Finance Limited | The press release supplies a symbol but the available admissible identity path does not prove the durable ISIN relationship for this event date. | Official NSE security master or listing/corporate-action document explicitly linking `IBULHSGFIN` to its ISIN on or before 2013-11-15. |

Exact-date NSE bhavcopies were checked for several affected dates. They provide
`SYMBOL` and `ISIN`, but not the company name. Joining a company-only index row
to one of those rows by current or fuzzy company name would be an inference, so
none was promoted.

## Duplicate-event forensics

The two current critical conflicts remain visible in
`artifacts/nifty200_pit_v1/duplicate_event_forensics.csv`:

| Date | Symbol | Conflict | Disposition |
| --- | --- | --- | --- |
| 2022-03-31 | `ABBOTINDIA` | ADD while the reconstructed interval is already active; A1 source `ind_prs24022022_1.pdf`, SHA `3091cf1c10b57bbae3b81645f5d91916a1af2bb7284902060f4640f7fb9fcd56`. Earlier A1 ADD 2020-06-26 and later A1 DROP 2023-09-29 are also present. | `UNRESOLVED_MANUAL_REVIEW`; raw observation retained; no event deleted or canonical event rewritten. |
| 2024-03-28 | `OFSS` | ADD while the reconstructed interval is already active; A1 source `ind_prs28022024.pdf`, SHA `5c70d043edde682a31fc5fa043a3b829a380fc9896de904bcb76d64b8319f698`. Earlier A1 DROP 2021-03-31 and ADD 2022-03-31 are present. | `UNRESOLVED_MANUAL_REVIEW`; raw observation retained; no event deleted or canonical event rewritten. |

The event-date snapshots show both instruments in the relevant checkpoint
chains. No first-party prior DROP or effective-date correction was found that
would justify automatically changing either event.

## May-2012 source failure

Blocker `24e473fdb484157e7595f87fdb60bf295a737a8535c8c1c729fb5a62c783d9b9`
remains `SOURCE_DOWNLOAD_FAILURE` for 2012-05-01. The official URL is:

`https://www.niftyindices.com/Indices_-_Market_Capitalisation_and_Weightage/indices_dataMay2012.zip`

The recorded response has SHA-256
`2e87473e6cabf210c1a9949f16dae74a8dddb2a90e3b1982f594fe31c778601d` but is
HTML, not a valid ZIP archive. Direct official retrieval and a Wayback CDX
lookup did not produce a verified May-2012 archive. A press release or an event
workbook is not a substitute for the missing full monthly NIFTY-200 checkpoint.

Status remains `E_HTML_RESPONSE_NOT_ARCHIVE`; the exact closure evidence is a
valid official May-2012 archive or a byte-verifiable Wayback copy of that same
archive.

## Calendar provenance

The build currently uses the repository’s NSE-oriented calendar implementation
with eight evidenced exceptions, but the audit remains
`PARTIAL_NOT_CERTIFIED`. The provenance string is
`nse-pandas-market-calendars-with-evidenced-exceptions`.

Official NSE pages checked include the current [Market Timings & Holidays
page](https://www.nseindia.com/resources/exchange-communication-holidays),
the [historical reports archive](https://www.nseindia.com/static/resources/historical-reports-capital-market-daily-monthly-archives),
and the [exchange data/reports documentation](https://www.nseindia.com/static/products-services/equity-market-data-reports-download).
These establish the existence and structure of NSE holiday/report facilities,
but no free, complete, date-addressable official holiday/session corpus for all
2012-01-02 through 2026-08-20 was admitted to the artifact package. The dynamic
current holiday page is not sufficient evidence for historical years.

The exact evidence needed is a complete official NSE Capital Market holiday and
special-session series, with dated source bytes and hashes, covering the full
campaign range. Until then, calendar certification must remain fail-closed.

## Monthly and anchor blockers

The 68 missing/non-200 monthly rows and 135 initial-anchor rows were not
modified in this task. They remain separate blockers and are not hidden behind
the actionable dispositions above. The 2012-01-02 authoritative full roster is
still not established.

## Evidence searches performed

The following official or official-archive locations were searched as candidate
evidence only:

- NSE/Nifty Indices press-release archives and the existing A1 press-release corpus.
- NSE historical reports and security-master documentation.
- NSE archived daily bhavcopies for exact affected dates.
- Official symbol/name-change and corporate-action circular locations.
- The official NSE holiday page and historical-report archive.
- Wayback URL/CDX lookup for the May-2012 monthly archive.

Search hits that were current-only, company-only, not date-valid, or lacked a
complete predecessor/successor chain were not admitted as historical identity
evidence. B1 remained a search index only.

## Safety and verification

- No Campaign Stage A, research, backtest, paper-trading, broker, or live-trading action was run.
- No production `market_data.duckdb` or `market_data.duckdb.wal` was touched.
- No import approval was granted.
- The dry-run importer remains refusal-by-design because validation is not PASS; `database_touched=false`.
- Independent QA remains `NOT_ASSERTED`.
- Existing verification: PIT tests `112 passed`; storage tests `9 passed`; full suite `1012 passed, 3 warnings`; Ruff passed; Mypy passed; Pyright exited 0 with 0 errors and 874 warnings; compileall passed; `git diff --check` passed.

## Final disposition

No blocker was closed in this pass because no newly contacted source met the
strict A1/A2 period-valid evidence rules. The correct outcome is to preserve
the evidence gaps and continue fail-closed.

```text
NIFTY-200 PIT RECONSTRUCTION:
DATA EVIDENCE BLOCKED

INDEPENDENT QA:
NOT ASSERTED

IMPORT APPROVAL:
NOT GRANTED

CAMPAIGN STAGE A:
BLOCKED
```
