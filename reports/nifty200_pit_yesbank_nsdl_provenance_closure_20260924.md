# NIFTY-200 PIT YESBANK NSDL provenance closure

Date: 2026-09-24
Repository: `C:\Python projects\algo trading-authoritative-evidence`
Branch: `codex/nifty200-pit-authoritative-evidence`
Scope: the single remaining YESBANK durable-identity blocker, `INE528G01027 -> INE528G01035`.

## Decision

`YESBANK_DURABLE_IDENTITY_CONTINUITY_NOT_PROVEN`

The requested official NSDL evidence path was retried with bounded, browser-compatible HTTPS requests, but no validated PDF bytes were obtained. No source was admitted, no SHA-256 or MIME/size record can be registered, and the existing evidence pipeline was not changed. The PIT gate therefore remains closed.

The official NSDL pages remain the intended primary sources:

- [Circular 0029](https://nsdl.co.in/downloadables/pdf/2020-0029-Policy-Yes%20Bank%20Limited%20Reconstruction%20Scheme%202020.pdf), dated 2020-03-15, the priority source for the explicit old/new assertion.
- [Circular 0033](https://nsdl.co.in/downloadables/pdf/2020-0033-Policy-Yes%20Bank%20Limited%20Reconstruction%20Scheme%2C%202020.pdf), dated 2020-03-17, corroborating the reconstruction-scheme identity handling.
- [Circular 0034](https://nsdl.co.in/downloadables/pdf/2020-0034-Policy-Yes%20Bank%20Limited%20Reconstruction%20Scheme%2C%202020.pdf), dated 2020-03-18, corroborating suspension of the old ISIN.

Search-index text for Circular 0029 is consistent with the exact assertion that free balances under `INE528G01027` were debited and new shares under `INE528G01035` were issued. That text is not a preserved source file and is not evidence-corpus input.

## Source metadata outcome

| field | result |
|---|---|
| successful acquisition method | none; all bounded official-origin attempts failed before a usable response |
| source URL | official NSDL URLs listed above |
| final URL after redirects | unavailable; no validated response reached a final document URL |
| raw evidence path | none; no bytes were preserved in the repository |
| byte size | unavailable |
| MIME type | unavailable |
| SHA-256 | unavailable |
| circular metadata validation | `NO`; number, date, subject, and page content were not validated from bytes |
| old/new assertion | `NOT_ADMISSIBLE`; search-index wording cannot substitute for a source file |
| continuity edge | `NOT_REGISTERED` |

## Bounded acquisition record

All attempts were read-only with respect to the repository and used a `Mozilla/5.0` user agent, a 20-second timeout, and at most five redirects. The latest bounded retry was at `2026-09-24T23:06:43.6485572+05:30`. No retry loop or alternate mirror was used.

| source | request path | result | admissible bytes | reason |
|---|---|---|---|---|
| NSDL 0029 | official `https://nsdl.co.in/...2020-0029...pdf` | connection reset while following the official endpoint | no | no PDF, MIME, length, or hash |
| NSDL 0029 | official URL, no-follow header capture | connection reset before any response headers; captured header file was zero bytes | no | no HTTP status or `Location` header was available |
| NSDL 0029 | official `https://www.nsdl.co.in/...2020-0029...pdf` | connection reset | no | no PDF, MIME, length, or hash |
| NSDL 0033 | official `https://nsdl.co.in/...2020-0033...pdf` | connection reset | no | no PDF, MIME, length, or hash |
| NSDL 0034 | official `https://nsdl.co.in/...2020-0034...pdf` | connection reset | no | no PDF, MIME, length, or hash |
| NSDL 0029 | exact decoded filename probe | client URL parser rejected embedded spaces before an HTTP request | no | encoding probe produced no server evidence |

Earlier repository evidence also recorded a repeated self-redirect/redirect-loop response for Circular 0029. The new bounded attempts do not cure that acquisition gap. Temporary response paths, if any, were outside the repository and no response was accepted as a PDF.

## Existing YESBANK evidence and unresolved edge

The local first-party observations remain:

- 2020-02-28: `YESBANK`, `INE528G01027`, source SHA-256 `2c5b8348dec6e64e0064bb8a77abe5811a2cc4eb1f720ac001ff923d6ae86b33`.
- 2020-03-19: `YESBANK`, `INE528G01035`, source SHA-256 `9c590311f613e0c1f33d07ab52a3ba4426bd867ac3a258f7dce38748d6db55b7`.
- The carried suffix namespace includes internal `INE528G01019`; the accepted 2020-03-19 NIFTY-200 DROP targets `INE528G01035`.

The internal mapping is therefore preserved as historical representation: `019` is the carried suffix namespace, `027` is the dated pre-reconstruction YESBANK ISIN, and `035` is the dated post-reconstruction/event ISIN. The missing provenance-backed `027 -> 035` edge prevents collapsing those representations into one certified economic namespace.

These dated observations establish before/after identity labels but do not, by themselves, prove the corporate-action continuity edge or the prior membership state required for the March DROP. No synthetic ADD, DROP replacement, or index-membership event was created.

## Pipeline and replay status

- `artifacts/nifty200_pit_v1/identity_continuity_evidence.json` remains unchanged by this pass and contains no YESBANK link.
- No source catalogue entry was added because there are no preservable source bytes or hash.
- No production code, raw evidence corpus, production DuckDB/WAL, calendar, frontier, anchor, post-2022 governance, Stage A, strategy, research, backtest, broker, or trading material was touched.
- No push or merge occurred.

The existing deterministic baseline therefore remains:

| metric | current result |
|---|---:|
| checkpoints | 75 |
| intervals | 74 |
| checkpoint identity rows | 15,050 / 15,050 |
| certification-grade exact intervals | 68 / 74 |
| economic divergences | 6 / 74 |
| representation-only intervals | 26 |
| unresolved evidence-gap conflicts | 1 YESBANK membership-affecting conflict |
| synthetic events introduced | 0 |

The six remaining economic divergences are `2020-02-28 -> 2020-03-31`, `2020-03-31 -> 2020-04-30`, `2020-04-30 -> 2020-05-29`, `2020-05-29 -> 2020-06-30`, `2020-06-30 -> 2020-07-31`, and `2020-07-31 -> 2020-08-31`. Replay accounting is unchanged because the required authoritative continuity bytes were not acquired and consumed.

| interval | before | after | identity edge used |
|---|---|---|---|
| 2020-02-28 -> 2020-03-31 | STILL_DIVERGENT | STILL_DIVERGENT | none admitted |
| 2020-03-31 -> 2020-04-30 | STILL_DIVERGENT | STILL_DIVERGENT | none admitted |
| 2020-04-30 -> 2020-05-29 | STILL_DIVERGENT | STILL_DIVERGENT | none admitted |
| 2020-05-29 -> 2020-06-30 | STILL_DIVERGENT | STILL_DIVERGENT | none admitted |
| 2020-06-30 -> 2020-07-31 | STILL_DIVERGENT | STILL_DIVERGENT | none admitted |
| 2020-07-31 -> 2020-08-31 | STILL_DIVERGENT | STILL_DIVERGENT | none admitted |

## Closure decision

The YESBANK blocker is not closed. The exact remaining evidence gap is: preserve the actual official NSDL Circular 0029 PDF (or an equally authoritative dated source explicitly joining `INE528G01027` to `INE528G01035`), record final URL, retrieval timestamp, byte length, MIME, SHA-256, page-level assertion, and register/consume it through the existing provenance pipeline. Only then may the six-interval replay be rerun and independently verified.

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
