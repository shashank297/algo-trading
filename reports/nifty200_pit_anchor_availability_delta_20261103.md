# NIFTY 200 Starting-Anchor Availability Review

**Review date:** 2026-11-03  
**Repository:** `C:\Python projects\algo trading`  
**Branch:** `codex/nifty200-pit-residual-evidence`  
**Starting HEAD:** `02dc80e9f931750f8ec37c9e658a8d219c2c6e6e`  
**Ending HEAD:** `02dc80e9f931750f8ec37c9e658a8d219c2c6e6e`  
**Requested anchor:** NIFTY 200 membership available before the 2016-01-29 NSE session open (09:15 IST).

## Decision

**BLOCKED — the opening anchor is not established by the currently available evidence.** This review narrows the blocker and tests a forward-seed route. It does not change the existing certification, blocker ledger, validation rules, or historical reports.

The December and January official monthly files independently parse to the same 200 unique symbols. The January file was created after the 2016-01-29 session opened, and the December file has no verified public-availability timestamp. An earlier Wayback capture is recorded, but its CSV payload is absent and could not be retrieved in this environment. Therefore there is no verified pre-open roster from which to certify the opening population.

## Repository and safety

- Starting and ending branch/HEAD are recorded above; no commit was made.
- Existing local changes were preserved. No tracked source code, certified artifact, production database, or WAL was modified for this review.
- New files from this review are this delta report, its CSV, and investigation scratch under `.arena/pit-anchor-closure-20261103/`.
- No backtest, production import, trading command, or test suite was run. No validator or certification status was changed.

## Artifact and hash checks

SHA-256 was recomputed for the source catalogue, source manifest, December and January ZIPs, the unversioned NSE inclusion/exclusion workbook, and the relevant local first-party press-release PDFs. Each listed ZIP, workbook, and press-release hash matched its row in both `source_catalogue.json` and `source_manifest.csv`.

| Input | SHA-256 | Relevant metadata/result |
|---|---|---|
| `data/raw/nifty200_pit_public_sources/source_catalogue.json` | `07ea0f01c4672128a5a76aed613731f698568772c7fc530128f82adbdc31828a` | Catalog records have `retrieved_at` in 2026; monthly ZIP `document_date` is month-only and `last_modified` is null. |
| `data/raw/nifty200_pit_public_sources/source_manifest.csv` | `8176c44ec1d9d1e8b1af7f06a81372313901f64a08af866f3ef6ad48462ad278` | File hashes agree with the manifest rows. |
| `monthly_weightage/indices_dataDec2015.zip` | `ee21d99b90cd5634725d95ebd84f2488db4fa6f4bd4f151e11cb0a60706308e9` | `nifty200_Dec2015.pdf`: 200 rows, 200 unique symbols; PDF creation metadata `2015-12-31 19:24:49 +05:30`. |
| `monthly_weightage/indices_dataJan2016.zip` | `e433e6f2f94f9a94d150f2fbdc178d6a63ee3d3771d2d1c7e3794db9b6d00535` | `nifty200_Jan2016.pdf`: 200 rows, 200 unique symbols; PDF creation metadata `2016-01-29 17:17:21 +05:30`, 8 hours 2 minutes 21 seconds after the 09:15 open. |
| `index_inclusion_exclusion/IndexInclExcl.xls` | `8869bb7c4df67403131a494a8cc65509e80828f9438bc150b506cdbf55378046` | Retrieved `2026-09-06`; catalogue has no document date or last-modified value. Corroborative event history only. |

The two parsed symbol sets are identical. This is useful corroboration of the month-end state; it does not establish when that state became public or prove that the January close roster was available at the January open.

## Candidate forward-seed event chain

The local first-party notices and the current official IISL media index identify the following direct CNX/NIFTY 200 changes between the March 2015 archive capture and the requested start. The release files listed below have hashes matching both local source registries.

| Notice date | Effective date | CNX/NIFTY 200 change |
|---|---|---|
| 2015-02-20 | 2015-03-27, close of 2015-03-26 | 7 exclusions and 7 inclusions. |
| 2015-03-18 | 2015-03-27, close of 2015-03-26 | CMC out; Cox & Kings in. |
| 2015-04-29 | 2015-05-29, close of 2015-05-28 | 2 exclusions and 2 inclusions. |
| 2015-08-12 | 2015-09-28, close of 2015-09-24 | 9 exclusions and 9 inclusions. |
| 2015-08-24 | 2015-09-28, close of 2015-09-24 | 2 corporate-action exclusions and 2 inclusions. |
| 2015-09-18 | 2015-10-19, close of 2015-10-16 | Aditya Birla Nuvo out; Gateway Distriparks in. |
| 2016-01-11 | 2016-01-18 | The notice covers Nifty Alpha 50, High Beta 50, Low Volatility 50, Nifty 500, and Nifty Smallcap 100; it does not list a NIFTY/CNX 200 change. |

The official release PDFs are [2015-02-20](https://www.niftyindices.com/Press_Release/ind_prs20022015.pdf), [2015-03-18](https://www.niftyindices.com/Press_Release/ind_prs18032015_2.pdf), [2015-04-29](https://www.niftyindices.com/Press_Release/ind_prs29042015.pdf), [2015-08-12](https://www.niftyindices.com/Press_Release/ind_prs12082015.pdf), [2015-08-24](https://www.niftyindices.com/Press_Release/ind_prs24082015.pdf), [2015-09-18](https://www.niftyindices.com/Press_Release/ind_prs18092015.pdf), and [2016-01-11](https://www.niftyindices.com/Press_Release/ind_prs11012016.pdf). The current [official IISL media index](https://www.niftyindices.com/media) lists these releases and the other index notices in the period.

This chain is a viable reconstruction hypothesis, not a completed replay. The capture occurred on 2015-03-25 at 06:33:47 UTC (12:03:47 IST), before the March 27 changes took effect. Without its captured member list, the replay cannot establish the starting set or prove that applying all intervening events produces the observed January 2016 symbols. The 2026-retrieved workbook is not contemporaneous availability evidence, and the current media listing alone is not a substitute for verifying the captured payload and full source chain.

## Archive payload status

The existing `.arena/pit-assembly-20261103/archive_probe.json` records this Wayback CDX entry for `http://nseindia.com/content/indices/ind_cnx200list.csv`:

- capture time `2015-03-25 06:33:47 UTC`;
- HTTP status `200`, MIME type `application/csv`, length `4663` bytes;
- CDX digest `AHGIMTDBZSU5QAUTJ65MOJTEFT3IOXSF`.

The workspace has the CDX metadata but no CSV bytes. The archive replay URL was blocked in the browser and inaccessible through the web research interface; an availability API request returned HTTP 429. No payload SHA-256 or digest comparison could be performed. The CDX digest and length do not establish the roster contents.

## Remaining blocker and closure criteria

**Exact blocker:** no retrievable, verified pre-start membership payload is available to anchor the candidate event replay. The 2016-01-29 monthly PDF is post-open; the December PDF has only internal creation metadata and a month-level catalogue date, not evidence of when it was publicly available.

To close this blocker without relaxing the PIT contract:

1. Obtain the raw 2015-03-25 archived CSV bytes (or another admissible official roster with proven availability before 2016-01-29 09:15 IST). If the Wayback payload remains inaccessible, NSE Indices lists historical data and constituent-level data as subscription offerings and directs requests to its licensing contact; this is a possible official acquisition route, but this page does not establish that the records are free or state a price ([NSE Indices data subscription](https://www.nse.in/static/nse-indices/index-data-subscription)).
2. Preserve the original bytes, compute SHA-256, and verify the 4663-byte capture against the recorded Wayback digest where the archive format permits.
3. Parse and independently validate the exact starting member set and durable identities.
4. Replay all official dated CNX/NIFTY 200 changes through 2016-01-28, verify event `known_at` values and identity continuity, and compare the result with the January/December 200-symbol set.
5. Re-run the actual authoritative PIT validator on the complete bounded evidence before considering backtesting.

Until those steps pass, retain **BACKTEST_BLOCKED**. Independent PIT/data QA remains **NOT ASSERTED**; import approval remains **NOT GRANTED**; Campaign Stage A remains **BLOCKED**.

## Reproducible review scratch

- `.arena/pit-anchor-closure-20261103/verify_anchor_inputs.py` recomputes source hashes and checks the two monthly roster sets.
- `.arena/pit-anchor-closure-20261103/verified_anchor_inputs.json` records the machine-readable hash and roster results.
- `.arena/pit-anchor-closure-20261103/scan_anchor_releases.py` scans the local first-party candidate releases in the relevant date interval.
