# Phase 0 Research: Technical Decisions & Architectural Analysis

## 1. Approval Cryptographic Authenticity & Binding

### Decision
Use standard Ed25519 asymmetric signature verification (`cryptography.hazmat.primitives.asymmetric.ed25519`).
The canonical payload is constructed as a deterministic JSON string with sorted keys and UTF-8 encoding.
The signed payload includes:
- `run_id`
- `strategy_name`
- `stage`
- `foundation_cert_id`
- `risk_policy_hash`
- `code_sha`
- `evidence_hash`
- `scope`
- `subject_type`
- `approved_by`
- `approved_by_type`
- `approved_at`
- `expires_at`

Excluded from the signed payload:
- `signature` (cannot sign its own signature)
- `issuer_key_id` (identifier pointing to the verification key)

### Rationale
- Ed25519 is fast, immune to timing side-channels, and produces compact 64-byte signatures.
- Standard in modern security architectures for non-repudiation of board/human sign-offs.
- `PromotionEngine.assert_paper_authorized()` will enforce that all 9 required context values match the payload exactly, failing closed if any value is absent or mismatched.

### Alternatives Considered
- Plain allowlist of human names: Insecure against spoofing/impersonation.
- Symmetric HMAC: Requires sharing secret keys between verifier and approver, creating secret exposure risks in deployment.

---

## 2. Date-Valid Alias Research Join

### Decision
In `trading_stack/datasets.py` (and relevant candle-join points), when candles do not match directly by `instrument_id`:
1. Check alias mappings tied to the instrument.
2. An alias match is valid IF AND ONLY IF `valid_from <= candle_date < valid_until` (or open-ended upper bound).
3. Do NOT match outside this validity window.

### Rationale
- Tickers like `ADANIGAS` became `ATGL`, `L&TFH` became `LTF`, `INFRATEL` became `INDUSTOWER`.
- If an alias mapping is global across all time, older trades or candles can be misassigned to unrelated corporate entities that reused symbols or before the rename occurred.

---

## 3. AMTEKAUTO Zero-Length Interval RCA

### Decision
Inspect canonical events and interval generation in `tools/nifty200_pit/intervals.py`.
When an inclusion and exclusion occur on the exact same date or are processed as a same-day zero-duration slice (`effective_from == effective_until`), the interval builder must handle it gracefully:
- Either identify if duplicate announcement dates were interpreted as effective dates, or
- Ensure interval end dates represent open interval upper bounds `[from, to)` or contiguous valid calendar dates.
- Never emit intervals where `effective_from >= effective_until`.

---

## 4. Porting Strategy from `009-platform-audit-remediation` & PR #27

### Decision
Port verified semantic fixes file by file onto the fresh `codex/platform-audit-remediation-clean` branch based on current `origin/main` (`a8f3831`).
Exclude all generated Parquet snapshots, OCR PNGs, and temporary CSV blocker ledgers.
Maintain clean commit hygiene with descriptive commit messages.
