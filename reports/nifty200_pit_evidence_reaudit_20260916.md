# NIFTY-200 PIT evidence re-audit

Audit date: 2026-09-16

## Findings

- The official NSE Indices press archive was rechecked. The 2012 CNX 200 notices for April 27, May 21, and September 28 are already present in the local source catalogue (`ind_prs14032012.pdf`, `ind_prs16052012.pdf`, and `ind_prs16082012.pdf`). The 2013 CNX 200 notices used for the later replay are also already present.
- The official September 2022 monthly archive ZIP was inspected directly. Its members are `NIFTY_50_Sep2022.pdf`, `NIFTY_Bank_Sep2022.pdf`, `NIFTY_Financial_Services_Sep2022.pdf`, `NIFTY_Midcap_Select_Sep2022.pdf`, and `NIFTY_IT_Sep2022.pdf`; it contains no NIFTY-200 constituent table. This confirms the existing `NO_NIFTY200_CHECKPOINT` classification for this archive family.
- A retry of the official press-archive discovery endpoint timed out before any catalogue write. The working tree confirms that no partial acquisition was created.

## Consequence

This re-audit produced no new first-party evidence that can close the current blockers. The strict build therefore remains fail-closed with one missing 2012-01-02 anchor, 68 missing/unusable monthly NIFTY-200 checkpoints, and 123 exact membership-history gaps. The required next evidence is still a complete authoritative initial list, the missing checkpoint lists, and first-party predecessor ADD records.

References:

- https://niftyindices.com/press-release
- https://niftyindices.com/Press_Release/ind_prs14032012.pdf
- https://niftyindices.com/Press_Release/ind_prs16052012.pdf
- https://niftyindices.com/Press_Release/ind_prs16082012.pdf
- https://www.niftyindices.com/offerings/data-subscription
