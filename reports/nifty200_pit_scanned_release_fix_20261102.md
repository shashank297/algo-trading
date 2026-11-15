# Scanned-release extraction remediation

Decision: **BOUNDED_PIT_VALIDATION_BLOCKED**. This is a parser remediation record, not a bounded membership certificate.

Worktree: `C:/Python projects/algo trading`  
Branch: `codex/nifty200-pit-residual-evidence`  
Starting HEAD: `02dc80e9f931750f8ec37c9e658a8d219c2c6e6e`  
Bounded data scope: 2016-01-29 through 2022-03-31.

## Defect and implementation

The registered release `data/raw/nifty200_pit_public_sources/press_releases/candidates/ind_prs23082021.pdf` has SHA-256 `c9b9feef248ca89f7d8c8f12009e3d5c409eb4d6c793eee061fb93bf0af1231e`. Its bytes match the catalogue and the authoritative worktree copy. Both native extractors tested returned blank text for its NIFTY 200 page. A local rendering of page 14 visibly contains the six exclusions and six inclusions missing from residual observations.

`tools/nifty200_pit/ocr.py` now provides a local OCR page extractor with stable geometric ordering of table cells. `parse_press_releases` invokes it for PDFs with wholly blank native text. OCR rows preserve source URL/hash, event text, and page attribution and remain `UNRESOLVED` / `MANUAL_REVIEW`. Missing OCR dependencies, unrecognized headings, and unreadable event tables produce source-bound unresolved diagnostic observations. Ambiguous OCR page attribution remains unresolved with no guessed page.

The identity resolver previously promoted a date-complete manual-review observation to `CERTIFIED` / `ACCEPTED` when identity resolution succeeded. A failing regression reproduced that path; the resolver now preserves the manual-review veto. The regression follows resolution through reconciliation and asserts that no canonical event is created.

Optional extraction dependencies are listed in `requirements-pit-ocr.txt`. Local package/model provenance and source/output hashes are saved in `.arena/pit-evidence-closure-20261102/scanned_release_verification.json`. The local OCR package used is pinned for this reproduction; its upstream documentation describes the migration to the newer RapidOCR package: [official installation guide](https://rapidai.github.io/RapidOCRDocs/main/en/install_usage/rapidocr/install/). No paid service or remote OCR submission was used.

## Verification

- Regression failures were reproduced before fixes for silent scanned-source omission, manual-review promotion, OCR source loss, page misattribution, and backend-order-dependent OCR line grouping.
- Focused parser/identity/certification/OCR tests: 43 passed; complete PIT-specific suite: **147 passed**.
- PIT MyPy: 20 source files, no issues.
- Ruff on changed source and tests: passed.
- Compilation of PIT tools and tests: passed.
- Repository-wide MyPy: 43 errors in 11 other files, matching the previous recorded count; none in the changed PIT package.
- Repository-wide Ruff traverses old scratch exports and denied temporary directories; its nonzero result is separate from the clean changed-file result.
- Final real-PDF reproduction recovered exactly the expected 12 keys, all attributed to page 14 and kept in manual review. Two final extractions are byte-identical: SHA-256 `11e1d17c70abe052c1036b2e8d77da7e4f270bec44fd9e8510065dce975afdcb`. An earlier output hash changed when the explicit OCR adapter version was added; that cross-revision comparison was not counted as deterministic reproduction.
- Final source/test/requirements hashes are recorded in `.arena/pit-evidence-closure-20261102/ocr_source_hashes.json`; HEAD remains `02dc80e9f931750f8ec37c9e658a8d219c2c6e6e`.
- Broader regression run: **1,040 passed, 3 warnings**, exit 0, 803.03 seconds. One final OCR permutation test was added after this run began; it passed in the final 147-test PIT run. Collection after all changes reports 1,041 tests. This combined verification covers the full collected set, although the broad run itself did not use a frozen commit.

## Validator and remaining evidence

### Source disposition recheck — 2026-11-02

- **Bounded membership evidence:** the later authoritative YESBANK continuity closure (`reports/nifty200_pit_yesbank_msei_2017_continuity_closure_20260926.md` in the authoritative worktree) records 75 checkpoints, 74 intervals, 15,050/15,050 checkpoint identities, 74/74 certification-grade exact replay, zero economic divergences, and zero membership-affecting conflicts. The older 2013 start-anchor audit is a wider-history issue; it does not invalidate the bounded 2016-01-29 seed by itself. The executable CLI still has no hash-bound bounded-anchor input, so it cannot consume that seed as a validated artifact.
- **Calendar evidence:** the prior authoritative calendar certification records 310 events and 310/310 chronology, known_at, and effective-session checks. I independently hashed all seven preserved NSE CM circular PDFs; every SHA-256 matches the certification report: 2016 `bf33e9aade8773908fc5d6de105cc731e93bf063cd1564a82fe1998c5aaf6432`; 2017 `2fd7ee17432434df26154bbdb9de549d3e4a7acd4cf567843513457e9c98fbce`; 2018 `d80ac64d32806f9ada629bc96ba91c6d85546dfde405f4468bbfcb194fdb22fb`; 2019 `3fe8f7356085b75a14efec16e765216d09b99be6f00ff2305d813a864394ab88`; 2020 `635535e35ddc37e79b188d9f21409210cfdef00f44cde1cb980c4f64ed005eaf`; 2021 `3c922e234ad2cbe8320cc34507e281477e0ce273ba9ee39d73da2a49d5629add`; 2022 `731a4f0f3b3633e53ff344ffda23dab0277c4a6608f5a6da8874f931c9be4ead`. The existing validator accepts no certificate/session artifact, so runtime calendar evaluation remains NOT_EVALUABLE; this does not reopen the prior calendar certification.
- **Residual event identity:** 27 bounded observations still lack separately admissible dated identity segments. Event-date raw NSE observations corroborate symbols and ISINs for 26 EQ rows and a BE row for TRIDENT, but they do not close competing open-ended historical identity intervals. The persisted 310-row artifact's ISIN fields are outputs and are not admissible resolver inputs.
- **Scanned release:** the 12 observations recovered from official release page 14 remain `MANUAL_REVIEW`; OCR recovery alone does not certify event attribution or identity. The output is deterministic for the pinned local OCR path, but a source-linked adjudication and integrated rebuild are still required.
- **Duplicate event:** the residual canonical population has a critical `DUPLICATE_ADD` for ABBOTINDIA on 2022-03-31 from the official 2022-02-24 release. The February checkpoint omits ABBOTINDIA and the March checkpoint includes it, supporting the announced transition, but the existing replay says the instrument was already active. The prior active-state source/event path has not been reconciled; retain the conflict.
- **Current generated population:** the isolated rebuild reports 271 bounded canonical events versus the prior certified 310-event component, 81 bounded HIGH/CRITICAL conflicts (45 missing durable identity, 35 absent-member removals, 1 duplicate add), and zero sessions checked by the validator. The 12 OCR observations and 27 identity cases are not yet integrated as certified events. Do not combine metrics from stale `data/derived` outputs and `.arena/.../rebuild-full` as if they were one build.
- **Independent review:** the requested quick Arena tournament was initialized but did not complete because child agents hit the account usage limit. It produced no winner or independent adjudication; the local source checks above are not represented as an Arena result.

The smallest safe tooling change remains an evidence-bound bounded validator input for the certified first checkpoint and certified NSE session/calendar artifact, with source-hash, range, exact-set, provenance, and replay checks. Separately, the current rebuild needs admissible identity rows for the 27 cases, human/source review of the 12 OCR observations, and resolution of every in-scope removal/duplicate conflict. A CLI boolean asserting that an anchor/calendar is certified would not close these gaps.

The actual CLI was rerun against the existing isolated rebuild at `.arena/pit-evidence-closure-20261102/rebuild-full`, using `validate --campaign-from 2016-01-29 --campaign-to 2022-03-31 --require-member-count 200`. It exited 2 with `BLOCKED`, zero sessions checked, uncertified calendar, missing anchor, and 273 unresolved global conflicts. This invocation used the existing rebuild; it did not regenerate a complete package from the new OCR code. It is not evidence of an integrated package pass.

The twelve recovered observations still require extraction review and admissible event-date identity evidence before canonical admission. Their recovery does not resolve the other 27 identity gaps, complete calendar/anchor inputs, executable economic replay, package determinism, frozen baseline, or formal approvals. The source-backed identity review is recorded in `.arena/pit-evidence-closure-20261102/identity_handoff.md`; asserted ISINs in existing reports were not copied into resolver inputs.

Per-event identity triage is in `.arena/pit-evidence-closure-20261102/identity_disposition.csv`. It records dated raw source checks and competing ISIN histories for the 27 events. Old snapshot-only observations without proven segment ends still prevent certification under the existing resolver contract. TRIDENT also has an event-date raw reference in series BE that is not represented as a qualifying dated master segment. Economic continuity projections in the stored historical master must not be confused with pre-resolution identity inputs or treated as permission to discard competing history. These cases remain unresolved; the current reports do not prove the missing temporal dispositions.

Existing dirty work was preserved. No authoritative-worktree source, historical report, production database/WAL, campaign, backtest, trading service, or broker integration was changed or invoked. No commit, push, or merge was made.

Ending HEAD: `02dc80e9f931750f8ec37c9e658a8d219c2c6e6e`. The fix is confined to the residual checkout and has not been integrated into the authoritative evidence worktree. No complete bounded package was regenerated or certified by this remediation. Remaining actions are extraction review of the 12 OCR candidates, admissible temporal disposition of the 27 competing identity histories, evidence-bound anchor/calendar validator inputs, complete replay/conflict closure, deterministic integrated-package reproduction, and verification of the frozen intended source before independent QA and import approval.

INDEPENDENT PIT/DATA QA: NOT ASSERTED  
IMPORT APPROVAL: NOT GRANTED  
CAMPAIGN STAGE A: BLOCKED
