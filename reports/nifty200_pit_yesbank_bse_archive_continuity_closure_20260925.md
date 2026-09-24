# NIFTY-200 PIT YESBANK BSE archive continuity closure

Date: 2026-09-25  
Repository: `C:\Python projects\algo trading-authoritative-evidence`  
Branch: `codex/nifty200-pit-authoritative-evidence`  
Starting HEAD: `8b330acabd3e0099011ab3284d60642acebc4346`  
Scoped data commit: `2769cfd` (`data(pit): add yesbank bse archived identity evidence`)

## Decision

The two specified official BSE archive responses are valid, complete PDF bytes and are admissible A1 first-party issuer evidence. Under the existing `DOCUMENTED_STOCK_SPLIT_CONTINUITY` governance rule, the multi-source chain proves the requested YESBANK durable-identity continuity `INE528G01027 -> INE528G01035`:

1. FY2019-20 supplies the dated causal corporate action: on PDF page 106, Management Discussion and Analysis, “On March 13, 2020, the Government of India notified the Yes Bank Ltd. Reconstruction Scheme, 2020,” and records the reconstruction-scheme equity issue.
2. FY2020-21 supplies the explicit issuer identity assertion: on PDF page 134 (printed page 131), General Shareholders Information, “Domestic Listing - New ISIN INE528G01035 | Old ISIN-INE528G01027 (Equity).”
3. Existing dated NSE identity observations supply the period-valid endpoints: `INE528G01027` on 2020-02-28 and `INE528G01035` on 2020-03-19.

This uses the same governance applied to GRASIM. No synthetic membership event, direct-site substitute, NSDL substitute, or exception was used.

## BSE source validation

| Period | Official source | Preserved bytes | SHA-256 | PDF pages | Page/section assertion |
|---|---|---:|---|---:|---|
| FY2019-20 | [BSE YESBANK annual report](https://www.bseindia.com/bseplus/AnnualReport/532648/5326480320.pdf) | 14,441,184 | `3ad2f51f9660d3415e0a9bb1a8cc61aac16c0b0f1a894fdacdd68aa754ad7e16` | 359 | p.106, Management Discussion and Analysis - Equity Capital and Reserve and surplus: dated Reconstruction Scheme 2020 and reconstruction-scheme equity issue |
| FY2020-21 | [BSE YESBANK annual report](https://www.bseindia.com/bseplus/AnnualReport/532648/69137532648.pdf) | 7,314,802 | `b292add537db526e808a6831885468ebb6fbdbc551596d858c1650a8edfcf204` | 256 | p.134 / printed p.131, General Shareholders Information - Listing on Stock Exchanges, ISIN & Stock Code: explicit new/old ISIN pair |

Both responses returned HTTP 200, MIME `application/pdf`, and parsed successfully with `pypdf`. Retrieval timestamps are recorded in `reports/nifty200_pit_yesbank_bse_archive_continuity_sources_20260925/source_manifest.json` and the local source catalogue.

## Existing NSE endpoint evidence

| Role | Date/source | SHA-256 |
|---|---|---|
| Pre-transition | NSE dated identity row, 2020-02-28, `YESBANK`, `INE528G01027` | `2c5b8348dec6e64e0064bb8a77abe5811a2cc4eb1f720ac001ff923d6ae86b33` |
| Transition corroboration | NSE Circular INSP43833, dated 2020-03-15 | `c8d17de1f2d3e805d0776fc3cfd5d748cabb8a258d57e5eb27abd8138cf808e9` |
| Post-transition | NSE dated identity row, 2020-03-19, `YESBANK`, `INE528G01035` | `9c590311f613e0c1f33d07ab52a3ba4426bd867ac3a258f7dce38748d6db55b7` |

The source/edge registration is present in the local ignored source catalogue and in `artifacts/nifty200_pit_v1/identity_continuity_evidence.json`. The registered edge contains the FY2019-20 BSE causal source, FY2020-21 BSE identity-support source, and both NSE endpoint hashes. It leaves the accepted March 2020 DROP and September 2020 ADD events unchanged.

## Scoped replay

The read-only replay was rerun over 75 checkpoints and 74 suffix intervals. The raw-ID diagnostic was `8/74` exact before and `8/74` after; the edge changes the projected namespace after the September 2020 ADD but does not alter the raw-string diagnostic. Under the existing GRASIM-adjusted certification-grade accounting, the result remains `68/74` exact and `6/74` economic divergences before and after.

The six unchanged economic intervals are:

- 2020-02-28 -> 2020-03-31
- 2020-03-31 -> 2020-04-30
- 2020-04-30 -> 2020-05-29
- 2020-05-29 -> 2020-06-30
- 2020-06-30 -> 2020-07-31
- 2020-07-31 -> 2020-08-31

The carried strict replay seed remains `NSE-ISIN:INE528G01019`; the accepted 2020-03-19 DROP targets `NSE-ISIN:INE528G01035`. Therefore the new `027 -> 035` edge closes the requested durable-identity relationship but does not resolve the separate carried `019 -> 027` namespace/action-state gap. The one membership-affecting YESBANK conflict remains an unresolved `MISSING_PRIOR_ADD` / absent-DROP evidence gap. The prior 26 representation-only intervals remain 26, and no new production defect is established.

## Governance and safety

```text
DATA EVIDENCE BLOCKED
INDEPENDENT PIT/DATA QA: NOT ASSERTED
IMPORT APPROVAL: NOT GRANTED
CAMPAIGN STAGE A: BLOCKED
```

Production DuckDB/WAL were untouched. No Stage A, research/backtest, broker, trading, push, or merge operation was performed. Unrelated pre-existing dirty reports and untracked temporary directories were preserved.

## Verification

- 69 focused PIT tests passed.
- Ruff passed for `tools/nifty200_pit/build_public_dataset.py`.
- Mypy passed for all 21 files in `tools/nifty200_pit`.
- `compileall` passed for `tools/nifty200_pit`.
- `git diff --check` passed.
- BSE PDFs were hash-verified, parsed, and page-level assertions captured.

## Exact remaining requirement

The BSE closure is complete for `INE528G01027 -> INE528G01035`. Campaign certification remains blocked until the carried `INE528G01019 -> INE528G01027` identity/action-state gap is closed with admissible period-valid first-party evidence, followed by a fresh full replay and independent PIT/data QA. No such evidence was fabricated or inferred here.
