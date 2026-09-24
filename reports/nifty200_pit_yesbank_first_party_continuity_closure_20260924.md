# NIFTY-200 PIT YESBANK first-party continuity closure

Date: 2026-09-24
Repository: `C:\Python projects\algo trading-authoritative-evidence`
Branch: `codex/nifty200-pit-authoritative-evidence`
Scope: only YESBANK durable-identity continuity `INE528G01027 -> INE528G01035`.

## Decision

`YESBANK_MULTISOURCE_CONTINUITY_INSUFFICIENT`

`YESBANK_DURABLE_IDENTITY_CONTINUITY_NOT_PROVEN`

The existing GRASIM governance was applied without a YESBANK-specific exception. It permits a mutually consistent, first-party, hash-verified multi-source chain; it does not require one document to contain both ISINs. The available NSE circular is valid and preserved, but the required YES BANK first-party PDFs could not be validated from current official-origin responses. The chain therefore remains insufficient.

## Existing governance rule

The already-applied rule is `DOCUMENTED_STOCK_SPLIT_CONTINUITY`. Its admitted GRASIM chain required:

1. a first-party, period-valid observation of the old durable identity;
2. a first-party issuer filing explicitly documenting the causal corporate action;
3. a first-party, period-valid observation of the new durable identity; and
4. preserved bytes, SHA-256 validation, temporal bounds, and exact company/symbol/ISIN consistency.

The GRASIM adjudication expressly states that no single-document old/new ISIN sentence is required when separately period-valid first-party observations and a same-issuer dated causal filing form the complete chain. This same standard was applied here.

## Source acquisition and validation

### YES BANK FY2019-20 annual report

Official source attempted:

`https://www.yesbank.in/content/published/api/v1.1/assets/CONTBD330CE6A3224A7EA5BCC44ABAFE0AFB/native/annual_report_2019_2020_pdf.pdf?channelToken=21f7ccfa2fc3401091938f541a6f8f2a&download=false`

Result: `YESBANK_2019_20_REPORT_NOT_VALIDATED`.

The exact official URL returned HTTP 404 through bounded PowerShell retrieval. The same asset path without the query returned a 11,255-byte HTML Oracle/YES BANK site shell beginning with `<!DOCTYPE html>`, not a PDF. No PDF bytes, page, MIME, complete-document validation, or SHA-256 were admitted.

The official search index exposes listing text consistent with `New ISIN INE528G01035` and `Old ISIN INE528G01027`, but that extracted text is not preserved source evidence.

### YES BANK annual return

Official FY2021-22 annual-return source attempted:

`https://www.yesbank.in/content/published/api/v1.1/assets/CONTC3D5352CA29B4123BD2A51B6CF6078B8/native/mgt7_extract_of_annual_return_march_31_2022_pdf.pdf?channelToken=21f7ccfa2fc3401091938f541a6f8f2a&download=false`

Result: `YESBANK_ANNUAL_RETURN_NOT_VALIDATED`.

The exact official URL returned HTTP 404 through bounded PowerShell retrieval. The same asset path without the query returned the same 11,255-byte HTML site shell, not a PDF. The annual-return statement that both ISINs exist and pledged shares remained under the old ISIN is therefore not admitted from search-index text.

### NSE reconstruction circular

Result: `NSE_RECONSTRUCTION_CIRCULAR_VALIDATED`.

- Official URL: `https://nsearchives.nseindia.com/content/circulars/INSP43833.pdf`
- Identifier: `NSE/CML/43833`
- Date: 2020-03-15
- Raw path: `reports/nifty200_pit_yesbank_first_party_continuity_sources_20260924/nse_INSP43833.pdf`
- Bytes: `498374`
- SHA-256: `c8d17de1f2d3e805d0776fc3cfd5d748cabb8a258d57e5eb27abd8138cf808e9`
- MIME: `application/pdf`
- Structure: valid PDF, 2 pages, parseable with `pypdf`
- Page 1 assertion: under the Yes Bank Limited Reconstruction Scheme, dealing in the shares is permitted in new ISIN `INE528G01035` from March 16, 2020.

The circular does not itself state the old ISIN `INE528G01027`; it supplies the dated reconstruction/new-ISIN leg only.

## Existing dated identity evidence

- Latest valid pre-transition observation: 2020-02-28, `YESBANK`, `INE528G01027`, source SHA-256 `2c5b8348dec6e64e0064bb8a77abe5811a2cc4eb1f720ac001ff923d6ae86b33`.
- Earliest valid post-transition observation: 2020-03-19, `YESBANK`, `INE528G01035`, source SHA-256 `9c590311f613e0c1f33d07ab52a3ba4426bd867ac3a258f7dce38748d6db55b7`.
- Internal `019 -> 027` history: no admitted period-valid continuity edge is present in the current accepted evidence. It is not needed to broaden this adjudication; the primary target remains `027 -> 035`.

## Provenance-chain adjudication

| chain leg | result |
|---|---|
| dated NSE pre-evidence: `027` | proven and already admitted |
| YES BANK FY2019-20 filing explicitly joining old/new ISINs | not validated; no PDF bytes |
| YES BANK annual-return pledged-share semantics | not validated; no PDF bytes |
| NSE reconstruction circular: new `035` from 2020-03-16 | proven and preserved |
| dated NSE post-evidence: `035` | proven and already admitted |

The missing semantic evidence is a preserved first-party YES BANK filing or equivalent first-party source that explicitly establishes the old/new YESBANK durable-identity relationship or the old shares’ continuity into the reconstruction context. The NSE circular alone establishes the new trading ISIN, not the old-to-new continuity.

Therefore: `YESBANK_MULTISOURCE_CONTINUITY_INSUFFICIENT`.

## Registration and replay

- The validated NSE circular was preserved in the scoped source folder, recorded in its manifest, and added to the local source catalogue as A1 evidence.
- The unavailable YES BANK documents were not registered.
- The continuity edge `INE528G01027 -> INE528G01035` was not registered in `identity_continuity_evidence.json`.
- No DROP/ADD event was created or altered. March 2020 DROP and September 2020 ADD remain unchanged.
- No production code change was needed or made.

The six intervals remain unchanged:

| interval | before | after | edge used |
|---|---|---|---|
| 2020-02-28 -> 2020-03-31 | STILL_DIVERGENT | STILL_DIVERGENT | none admitted |
| 2020-03-31 -> 2020-04-30 | STILL_DIVERGENT | STILL_DIVERGENT | none admitted |
| 2020-04-30 -> 2020-05-29 | STILL_DIVERGENT | STILL_DIVERGENT | none admitted |
| 2020-05-29 -> 2020-06-30 | STILL_DIVERGENT | STILL_DIVERGENT | none admitted |
| 2020-06-30 -> 2020-07-31 | STILL_DIVERGENT | STILL_DIVERGENT | none admitted |
| 2020-07-31 -> 2020-08-31 | STILL_DIVERGENT | STILL_DIVERGENT | none admitted |

Full suffix replay is unchanged: `CERTIFICATION_GRADE_EXACT = 68 / 74`, `ECONOMIC_DIVERGENCES = 6`, `REPRESENTATION_ONLY = 26`. The YESBANK conflict is `YESBANK_CONFLICT_UNRESOLVED`, and `MEMBERSHIP_AFFECTING_UNRESOLVED_CONFLICTS = 1`.

## Verification and boundaries

- NSE source hash was recomputed after preservation and matches the manifest and catalogue.
- PDF signature, byte length, page count, and page-1 assertion were validated.
- YES BANK responses were checked for PDF signature; the preserved 11,255-byte responses were HTML and rejected.
- Source manifest and source catalogue JSON parse successfully.
- Closure CSV validation passed: 5 rows, 5 unique record IDs, one validated NSE source, and all replay effects unchanged.
- Full pytest passed: `1020 passed, 3 warnings`.
- Ruff passed; compileall passed; focused Mypy on `tools/nifty200_pit` passed with no issues.
- Broad Mypy reported one unrelated pre-existing error at `utils/retry.py:128`; no task code caused it.
- Pyright reported `0 errors, 874 warnings`; warnings are pre-existing and unrelated to this source-only change.
- Deterministic certification replay was not recomputed because no YESBANK continuity edge was registered; the unchanged baseline remains `68/74`, `6`, and `26`.
- `git diff --check` passed.
- No production DuckDB/WAL, calendar, frontier, anchor, post-2022 governance, Stage A, research, backtest, broker, or trading work was performed.
- No push or merge occurred.

## Final decision

`SUFFIX_MEMBERSHIP_REPLAY_BLOCKED`

Exact remaining blocker: preserve and validate a first-party YES BANK document that supplies the missing old/new durable-identity continuity semantics for `INE528G01027 -> INE528G01035`; current official YES BANK asset URLs returned 404/HTML and cannot be replaced by search text.

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
