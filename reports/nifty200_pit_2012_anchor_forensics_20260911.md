# NIFTY-200 PIT 2012 anchor forensics

## Decision

The 2012-01-02 anchor is not defensibly established. This diagnostic reverse replay is not authoritative and is not used by the normal interval builder or validator.

## Evidence options checked

- A: the official `IndexInclExcl.xls` `Nifty 200` sheet is a dated inclusion/exclusion change log; its earliest NIFTY-200 row is 2011-11-22, not a 2012-01-02 membership list.
- B: the official CNX 200 launch notice establishes methodology and launch context, but contains no 200-member list.
- C: the nearest acquired official monthly checkpoint is used as a forward anchor only.
- D: reversing the currently canonical, certified event chain gives a diagnostic candidate; unresolved official observations are not promoted and B1 rows are not used as authority.

## Measured result

- Forward checkpoint: 2013-04-18; rows: 200; source SHA-256: 4942c0f021abcd6ed9702c343c2696ec44cfa8022c7e37448f8a78c075c4a16d.
- Reverse canonical events: 12; candidate initial rows: 205.
- NSE sessions replayed: 3609; exact-200 sessions: 37; non-200 sessions: 3572.
- First count divergence: 2012-01-02 at 204 members; event rows applied that day: none; cause is the unproven initial set, not a fabricated event.
- Valid official checkpoints compared: 58; set matches: 0; set mismatches: 58; first mismatch: 2013-04-18.

## Interpretation

A candidate that matches a later checkpoint cannot prove the starting membership when the intervening official event chain has unresolved observations and missing publication/effective-date linkage. Remaining closure evidence must be first-party historical membership or event evidence with durable identity and causality.
