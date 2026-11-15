# Campaign 1 PIT verification for five selected stocks

Scope is the NIFTY 200 campaign, 2016-01-29 through 2022-03-31 inclusive, using the package’s Asia/Kolkata session calendar. Branch `codex/nifty200-pit-residual-evidence` started and ended at `02dc80e9f931750f8ec37c9e658a8d219c2c6e6e`. There were 35 tracked changes before and after the audit. Each of five workers was launched with `gpt-6-luna` and reasoning effort `high`.

## Findings by stock

| Stock | NSE EQ observations | Dated checkpoint matches | Candidate identity evidence | Verified finding |
|---|---:|---:|---:|---|
| HDFCBANK | 1,528 / 1,528 | 75 / 75 | 75 / 1,528 sessions | Old ISIN INE040A01026 through 2019-09-19 (899 sessions), new INE040A01034 from 2019-09-20 (629 sessions). Staged split continuity evidence for review. |
| ICICIBANK | 1,528 / 1,528 | 75 / 75 | 75 / 1,528 sessions | INE090A01021 throughout the campaign. Verified the pre-campaign NSE EQ switch from INE090A01013 on 2014-12-05 using the 3, 4, and 5 December files. |
| RELIANCE | 1,528 / 1,528 | 75 / 75 | 75 / 1,528 sessions | INE002A01018 throughout. The 1:1 bonus went ex on 2017-09-07. RELIANCEPP (E1, IN9002A01024) first appears on 2020-06-15 and is absent from candidate membership. |
| BHARTIARTL | 1,528 / 1,528 | 75 / 75 | 75 / 1,528 sessions | INE397D01024 throughout. Verified 2021-11-02 as first trading date for AIRTELPP (E1, IN9397D01014), correcting the dossier's 23 November date. The partly paid line is absent from candidate membership. |
| LT | 1,528 / 1,528 | 75 / 75 | 75 / 1,528 sessions | INE018A01030 throughout. The issuer confirms a 1:2 bonus, post-bonus pricing from 2017-07-13, and a 2017-07-14 record date. Month-end prices do not establish the adjustment factor. |

All 1,528 dated source ZIPs were read and hash-checked against the registered A1 daily corpus. The resulting 7,640 ordinary EQ observations and their source paths, ZIP member names, hashes, and CSV row numbers are in [daily observations](../artifacts/campaign1_top5_verified_20261115/daily_observations.jsonl). [Coverage JSON](../artifacts/campaign1_top5_verified_20261115/coverage.json) lists the 1,453 uncovered candidate identity sessions per stock. The audit verified that the candidate and the authoritative reference both contain zero in-window ADD/DROP events for these symbols. Checkpoint membership and raw trading observations were evaluated against their specific dates. All five seed intervals still have unresolved availability, so complete membership replay and certified price data are NOT_EVALUABLE.

Sources for stock-specific claims:
- HDFCBANK [MSE listing circular 8106](https://www.msei.in/SX-Content/Circulars/2019/September/Circular-8106.pdf), [NSE F&O circular 42168](https://archives.nseindia.com/content/circulars/FAOP42168.pdf), [NSE Clearing circular 42091](https://nsearchives.nseindia.com/content/circulars/CMPT42091.pdf).
- ICICIBANK [2014-12-03 file](https://nsearchives.nseindia.com/content/historical/EQUITIES/2014/DEC/cm03DEC2014bhav.csv.zip), [2014-12-04 file](https://nsearchives.nseindia.com/content/historical/EQUITIES/2014/DEC/cm04DEC2014bhav.csv.zip), [2014-12-05 file](https://nsearchives.nseindia.com/content/historical/EQUITIES/2014/DEC/cm05DEC2014bhav.csv.zip). Dec 4 is recorded as the ex-date. Dec 5 is the reported record date and independently observed first new cash EQ ISIN.
- RELIANCE [MSE corporate actions](https://www.msei.in/corporates/corporate-securities-information/corporate-update/default?symbol=RELIANCE&type=4&vmode=vm), [NSE listing circular](https://archives.nseindia.com/content/circulars/CML44626.pdf).
- BHARTIARTL [NSE listing circular, pages 1–2](https://archives.nseindia.com/content/circulars/CML50161.pdf), [issuer listing notice](https://nsearchives.nseindia.com/corporate/BHARTIARTL_01112021105319_STXIntimationBasisOfAllotment.pdf). Exclusion as a separate member instrument is distinct from the index's economic rights adjustment.
- LT [issuer record-date notice](https://investors.larsentoubro.com/upload/Announcements/ANRecord%20date%20advertisement.pdf), [issuer post-bonus price table](https://investors.larsentoubro.com/PDF/Annexures_to_Board_Report-FY17-18.pdf).

## HDFC Bank continuity

MSE 8106 is dated 2019-09-11. NSE FAOP 42168 is dated 2019-09-18 and applies the derivatives adjustment from the 2019-09-19 ex-date. NSE Clearing 42091 is dated 2019-09-09 and gives 2019-09-20 as the record date with specific early pay-in rules. The verified NSE EQ files show the old ISIN on 18 and 19 September and the new ISIN on 20 and 23 September. The circulars distinguish venues, derivatives, and clearing mechanics. An admissible cash-equity publication or explicit date-only rule is still needed before assigning a PIT `known_at` to the observed NSE EQ transition.

The baseline open interval retains the old ISIN at the 2019-09-30 checkpoint, which records the new ISIN. This mismatch is reproduced directly from the two hash-bound artifacts. The producer needs a raw continuity input before any allowlist entry can emit a link. The [review record](../artifacts/campaign1_top5_verified_20261115/hdfcbank_continuity_review.json) carries the four boundary observations with exact row references, three verified circular PDFs and their full digests, and the checkpoint comparison. The new package includes this raw row and registered sources under MANUAL_REVIEW, with null accepted effective date and knowledge timestamp. A production admission or resolver change still requires admissible causal evidence and integration of accepted daily identity records.

## Coordinator review and verification

The coordinator sent follow-up feedback to all five Luna workers after the daily scan. HDFCBANK reconciled the conflicting market dates. ICICIBANK separated its ex-date from its record and first-new-ISIN date, and the coordinator retrieved the missing ZIPs. RELIANCE and BHARTIARTL verified ordinary and rights share separation. BHARTIARTL identified that its pre-existing test reads a different candidate and includes synthetic filtering tests. This audit added a direct candidate and primary-source check. LT removed the inference about price adjustment from comparing month-end prices. The baseline report's payload hash table listed eight stale hashes. All nine files matched the actual baseline manifest. [Full hash comparison](../artifacts/campaign1_top5_verified_20261115/comparison.json)

- Baseline manifest SHA‑256 `ee68c27734f2546cd5b6378c684671ea7074146303c875be9fa3c9b3a41eb116`.
- New paired manifest SHA‑256 `961d61e68ac03f3fd66594692f26464240fd2454f585a44915c902d38409be03`. All nine payloads, the manifest, and the identity-transition boundary audit match byte for byte across the two builds. Continuity, source catalogue and manifest differ from the baseline.
- Both bounded validator invocations returned exit 2 with `bounded_input:evidence_not_accepted`. The top-level opening anchor is still UNRESOLVED / MANUAL_REVIEW and both bounded input evaluability and actual campaign replay are false. [New validator output](../artifacts/campaign1_top5_verified_20261115/validator_after.json)
- The first assembly attempt correctly rejected an anchor input still pointing to the original ledger path. Rebinding the isolated copy to the verified byte-identical ledger resolved the assembly error. Both successful builds used the normal `assemble-bounded-package` entry point with the copied authority inputs, the rebound anchor evidence and registered count inputs. Existing project code was sufficient to carry the unapproved continuity record.
- Focused Windows pytest run completed **109 passed** in 214.63 seconds. Files were `test_nifty200_pit_bounded_validation.py`, `test_nifty200_pit_bounded_producer.py`, `test_nifty200_pit_identity_transitions.py` and `test_bhartiartl_pit_continuity.py`. The exact focused command is below.

```powershell
.\venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp artifacts/campaign1_top5_verified_20261115/pytest tests/test_nifty200_pit_bounded_validation.py tests/test_nifty200_pit_bounded_producer.py tests/test_nifty200_pit_identity_transitions.py tests/test_bhartiartl_pit_continuity.py
```

Validator command from the workspace root for the rebuilt candidate:

```powershell
.\venv\Scripts\python.exe -B -m tools.nifty200_pit.cli --root . validate --campaign-from 2016-01-29 --campaign-to 2022-03-31 --evidence-package artifacts/campaign1_top5_verified_20261115/candidate_a/package.json
```

Three stocks have verified timeline corrections in this audit. Zero stock gaps were formally closed in the production evidence package. All five still have daily identity admission and shared anchor gaps. Zero stocks passed end to end. Campaign 1 remains BACKTEST_BLOCKED.

