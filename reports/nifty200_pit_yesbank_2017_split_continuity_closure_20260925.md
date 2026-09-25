# NIFTY-200 PIT YESBANK 2017 subdivision continuity closure

Date: 2026-09-25
Repository: `C:\Python projects\algo trading-authoritative-evidence`
Branch: `codex/nifty200-pit-authoritative-evidence`
Starting HEAD: `d795d5c4e0e8635113780f32eeac61c693c20cf0`

## Decision

The requested first-party YES BANK source was not validated, so the carried durable-identity edge `INE528G01019 -> INE528G01027` was not registered. The NIFTY-200 PIT evidence state remains blocked and the existing baseline is retained without replay.

## Exact requested source

```text
https://www.yesbank.in/content/published/api/v1.1/assets/CONT581D68AA77CF4A7187C0168949CAB68F/native/intimation_of_sub_division_of_each_equity_pdf.pdf?channelToken=21f7ccfa2fc3401091938f541a6f8f2a&download=false
```

The bounded retrieval followed the exact URL. The first-party host returned `301 Moved Permanently` to the corresponding `yes.bank.in` URL. The redirected host returned `404 Not Found`, `Content-Type: text/html; charset=UTF-8`, and `Content-Length: 11255`; no PDF bytes were written or admitted. The server response date was `Fri, 25 Sep 2026 10:16:41 GMT` (`2026-09-25 15:46:41 IST`). No alternate source was acquired or substituted.

Status: `YESBANK_2017_SPLIT_SOURCE_NOT_VALIDATED`.

There is therefore no admissible PDF SHA-256, page number, section, or explicit assertion to record for the requested document. The source must return valid PDF bytes containing the dated subdivision/corporate-action assertion, the 2017-09-22 effective date, the 10-to-5 face-value change, and the explicit old/new ISIN relationship `INE528G01019 -> INE528G01027` before registration can be reconsidered.

## Existing endpoint observations

The available pre-side diagnostic source is an archived NSE equity master, SHA-256 `c1b9cb0b8404070bee7a01a4824972d5913bb348cf082aff8344de1513a32067`, archived/document date `2011-10-30`, containing `YESBANK` with `INE528G01019`. It is not a period-valid 2017 first-party corporate-action assertion and is not sufficient to prove the requested continuity edge.

The available post-side period-valid observation is the official NSE dated identity row for `YESBANK`, `INE528G01027`, on `2017-09-29`, identity-source SHA-256 `02c7a906d55e08a0d3fde86d440577b23a47f21cd09581ef953e90ccc79f752e`, from:

```text
https://archives.nseindia.com/content/historical/EQUITIES/2017/SEP/cm29SEP2017bhav.csv.zip
```

These observations establish neither the dated corporate action nor the missing old/new assertion. `YESBANK_019_027_CONTINUITY_INSUFFICIENT` and `YESBANK_019_027_DURABLE_IDENTITY_CONTINUITY_NOT_PROVEN` remain the operative statuses.

## Existing admitted suffix evidence

The already-admitted `INE528G01027 -> INE528G01035` edge was not reopened or changed. Its BSE causal and identity-support source hashes remain `3ad2f51f9660d3415e0a9bb1a8cc61aac16c0b0f1a894fdacdd68aa754ad7e16` and `b292add537db526e808a6831885468ebb6fbdbc551596d858c1650a8edfcf204`, with NSE endpoint hashes `2c5b8348dec6e64e0064bb8a77abe5811a2cc4eb1f720ac001ff923d6ae86b33` and `9c590311f613e0c1f33d07ab52a3ba4426bd867ac3a258f7dce38748d6db55b7`.

The strict carried chain remains `INE528G01019 -> INE528G01027 -> INE528G01035`, broken only at the unresolved first link. No synthetic membership event, reconstructed evidence, direct-site substitute, NSDL substitute, or exception was used.

## Replay and governance state

No replay was run because no new evidence was admitted. The retained baseline is 75 checkpoints, 74 suffix intervals, 15,050/15,050 identities, 68/74 certification-grade exact, 6/74 economic divergences, 26 representation-only intervals, and 1 membership-affecting unresolved YESBANK conflict. The existing continuity machinery is not a production defect; it correctly refused to add an unverified edge.

No Stage A, research/backtest, broker/API, trading, production DuckDB/WAL, push, or merge operation was performed. Existing unrelated dirty reports and untracked temporary directories were preserved.

## Exact residual requirement

Preserve valid PDF bytes returned by the specified YES BANK first-party URL, or obtain an explicitly authorized exact official replacement, then hash-verify and page-review the document for the dated 2017-09-22 subdivision, 10-to-5 face-value change, and explicit old/new ISIN assertions. Only after that evidence is admitted may the `019 -> 027` edge be registered and the full 75-checkpoint replay plus independent PIT/data QA be rerun.

```text
DATA EVIDENCE BLOCKED
INDEPENDENT PIT/DATA QA: NOT ASSERTED
IMPORT APPROVAL: NOT GRANTED
CAMPAIGN STAGE A: BLOCKED
```

## Verification

- Exact source retrieval was bounded and response-validated; the response was rejected as HTML/404 rather than treated as a PDF.
- Temporary curl/probe files were removed.
- No authoritative source catalogue, identity-continuity artifact, production database, or runtime dataset was modified.
- `git diff --check` is required after the report files are added.
