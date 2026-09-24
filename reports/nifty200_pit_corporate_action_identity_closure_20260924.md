# NIFTY-200 PIT corporate-action identity continuity closure

Date: 2026-09-24
Repository: `C:\Python projects\algo trading-authoritative-evidence`
Branch: `codex/nifty200-pit-authoritative-evidence`
Scope: final two-source identity continuity check for YESBANK and GRASIM only.

## 1. Executive decision

`SUFFIX_MEMBERSHIP_REPLAY_BLOCKED`.

The two requested identity edges were not admitted to the authoritative identity map:

| Company | Requested edge | Closure result | Reason |
|---|---|---|---|
| YESBANK | `INE528G01027 -> INE528G01035` | `NOT_PROVEN` | The NSDL primary and corroborating PDFs could not be retrieved as validated bytes, so their explicit old/new assertion could not receive a SHA-256, retrieval record, or pipeline registration. |
| GRASIM | `INE047A01013 -> INE047A01021` | `NOT_PROVEN` | The retrieved company filing proves the share subdivision, but does not explicitly state the old and new ISIN pair; the NIFTY 200 release contains no GRASIM membership action. |

No synthetic ADD, alias, continuity edge, or backdated membership event was created.

## 2. Repository state and preservation boundary

- Starting HEAD: `30f02654140cf5df7e52e57b6f3e8c7a77b87107`.
- Branch: `codex/nifty200-pit-authoritative-evidence`.
- The worktree was already dirty before this closure. Pre-existing modified and untracked report files were preserved and were not staged.
- No production DuckDB/WAL, broker API, research run, backtest, paper session, live order, push, or merge was used.
- No calendar work, 2015 frontier extension, broad membership research, or Stage A work was started.

## 3. Source acquisition and byte validation

### YESBANK / NSDL

The requested NSDL URLs were attempted with a standard HTTPS client and a minimal browser user-agent. The primary 0033 endpoint returned a repeated HTTP 301 self-redirect from the encoded-comma filename to the comma-form filename. The 0029 endpoint also entered a redirect loop. No validated PDF bytes were returned for 0033, 0029, or 0034; therefore no SHA-256 was computed or registered for any NSDL source.

The NSDL search-result text is explicit about the old/new relationship, but search-result text is not an admissible substitute for preserved source bytes. The existing local YESBANK dated identity corpus remains identity evidence only:

- `INE528G01027` is present through the 2020-02-28 dated row.
- `INE528G01035` begins at the 2020-03-19 dated row.
- The existing accepted March DROP and September ADD remain unchanged.
- No `027 -> 035` edge was added to `instrument_aliases.parquet` or `identity_continuity_evidence.json`.

YESBANK result: `YESBANK_DURABLE_IDENTITY_CONTINUITY_NOT_PROVEN`.

### GRASIM / company split source

The official [Grasim Q2 FY17 results PDF](https://www.grasim.com/Upload/PDF/Q2FY17_results.pdf) was retrieved successfully:

- HTTP/content validation: HTTP 200; PDF signature; 10 pages; 582,103 bytes.
- SHA-256: `b70a7d5d4d324de72c825c8262786fa8683ec96511e27e6c90a9552cba811db7`.
- Document date: 2016-10-28.
- Extracted assertion: one Rs10 fully paid equity share was subdivided into five Rs2 fully paid shares effective 2016-10-08.
- Preserved copy: `reports/nifty200_pit_corporate_action_identity_sources_20260924/b70a7d5d4d324de72c825c8262786fa8683ec96511e27e6c90a9552cba811db7.pdf`.

This proves the economic corporate action and its effective date. It does not explicitly join `INE047A01013` to `INE047A01021`, so it is not by itself an admissible ISIN-continuity edge.

### GRASIM / NIFTY 200 corroboration

The official [NIFTY Indices 12 Aug 2016 release](https://niftyindices.com/Press_Release/ind_prs12082016.pdf) was retrieved successfully:

- HTTP/content validation: HTTP 200; PDF signature; 15 pages; 286,768 bytes.
- SHA-256: `5a62ae30702b448323496a7099a40cef446941cabd1b1677af63d6ff2aef6742`.
- Publication date: 2016-08-12; changes effective 2016-09-30.
- Extracted NIFTY 200 lists: nine exclusions and nine inclusions; GRASIM appears in neither list.
- Preserved copy: `reports/nifty200_pit_corporate_action_identity_sources_20260924/5a62ae30702b448323496a7099a40cef446941cabd1b1677af63d6ff2aef6742.pdf`.

This is corroboration that the Sep 30 review was not the source of a GRASIM membership action. It is not an old/new ISIN mapping assertion.

The byte-level source manifest is at `reports/nifty200_pit_corporate_action_identity_sources_20260924/source_manifest.json`.

## 4. Identity and membership state checks

### YESBANK

- 2020-02-28 checkpoint: symbol `YESBANK`, `INE528G01027`, certified unique.
- 2020-03-19 accepted DROP: target `NSE-ISIN:INE528G01035`; the strict carried seed remains `NSE-ISIN:INE528G01019`.
- 2020-09-25 accepted ADD: target `NSE-ISIN:INE528G01035`.
- 2020-09-30 first checkpoint after the ADD: `YESBANK`, `INE528G01035`, certified unique.
- Conclusion: the observed old/new namespace transition is real, but the required durable continuity edge remains unproven and is not inferred from the symbol.

### GRASIM

- 2016-01-29 suffix seed and 2016-09-30 checkpoint: `GRASIM`, `INE047A01013`; exact target `INE047A01021` absent.
- 2016-10-24 and 2016-10-30 dated identity rows: `GRASIM`, `INE047A01021`.
- 2017-04-28 checkpoint: exact target `INE047A01021` present immediately before the accepted 2017-05-26 DROP.
- 2017-05-31 checkpoint: no GRASIM member row.
- Conclusion: the split explains a plausible economic identity transition, but no explicit first-party old/new ISIN edge or prior NIFTY-200 ADD was admitted. The existing `MISSING_PRIOR_ADD` state remains.

## 5. Replay reconciliation

No canonical event, identity artifact, replay output, or membership source row was changed. Consequently the before/after metrics are intentionally identical:

| Metric | Before | After |
|---|---:|---:|
| Checkpoints | 75 | 75 |
| Intervals | 74 | 74 |
| Checkpoint identity rows | 15,050 / 15,050 | 15,050 / 15,050 |
| Certification-grade exact intervals | 68 / 74 | 68 / 74 |
| Economic divergences | 6 / 74 | 6 / 74 |
| Representation-only intervals | 26 | 26 |
| Unresolved evidence-gap conflicts | 2 | 2 |
| Membership-affecting unresolved conflicts | 2 | 2 |
| Synthetic events introduced | 0 | 0 |

The six economic divergences remain the YESBANK identity-continuity family from 2020-02-28 through 2020-08-31. GRASIM remains an unresolved prior-membership/identity-continuity case; no missing ADD was fabricated.

## 6. Checks and governance

- Source files were independently rehashed after preservation; both hashes match the manifest.
- PDF signatures, page counts, and targeted text assertions were validated.
- CSV closure output has two unique records and matches the two requested identity targets.
- The existing accepted source hashes and replay metrics were read from the authoritative worktree; no production database or WAL was accessed.
- `git diff --check` is required after the report files are staged.

Global governance remains unchanged:

```text
NIFTY-200 PIT RECONSTRUCTION:
DATA EVIDENCE BLOCKED

INDEPENDENT PIT/DATA QA:
NOT ASSERTED

IMPORT APPROVAL:
NOT GRANTED

CAMPAIGN STAGE A:
BLOCKED
```

## 7. Required next evidence, narrowly bounded

1. Preserve and register the official NSDL YESBANK 0033/0029 source bytes with HTTP metadata and SHA-256, then admit the explicit `INE528G01027 -> INE528G01035` edge only through the existing continuity pipeline.
2. Locate one first-party GRASIM security-master/corporate-action record that explicitly joins `INE047A01013` and `INE047A01021`, or an authoritative NIFTY-200 membership history assertion that closes the prior-ADD window.

No calendar or broad membership work is authorized by this closure.
