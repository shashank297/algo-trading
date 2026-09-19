# NIFTY-200 PIT Monthly Checkpoint Governance Recommendation

The strict monthly checkpoint gate remains in force. No missing checkpoint is
converted into a synthetic snapshot, and no non-200 result is silently accepted
as a complete historical constituent list.

Non-passing monthly checkpoint periods: 68.
The period denominator is one row per campaign month; it is distinct from
the underlying evidence-gap record denominator (176 records).

## Monthly checkpoint periods

| Period status | Monthly periods | Required evidence/action |
| --- | ---: | --- |
| PASS | 108 | No action for this gate |
| A: no snapshot evidence | 62 | Retrieve an official checkpoint or retain an evidence gap |
| E1: corrupt/incomplete download | 1 | Retrieve valid archive bytes or a verified Wayback copy |
| E2: source present but zero NIFTY-200 rows | 5 | Obtain an official NIFTY-200 member checkpoint; do not substitute another index |

## Underlying evidence-gap records

These counts describe source/archive/member records and must not be added to the monthly-period count.
| Evidence-gap classification | Records | Required evidence/action |
| --- | ---: | --- |
| A: no snapshot evidence | 161 | Retrieve an official checkpoint or retain an evidence gap |
| B: candidate/zero-row extraction | 9 | Inspect archive member/table and parser output |
| C: wrong table/parser | 0 | Add parser coverage only after source inspection |
| D: documented non-200 methodology | 0 | Obtain the official exception/methodology document |
| E1: corrupt/incomplete download | 1 | Retrieve valid archive bytes or a verified Wayback copy |
| E2: official archive has no NIFTY-200 member file | 5 | Obtain an official NIFTY-200 member checkpoint; do not treat other index files as a substitute |

The May 2012 archive response remains an HTML download failure. The May 2012
press release is event evidence, not a full historical checkpoint. The five
later May archives are valid official archives, but their members are for other
indices and do not contain a NIFTY-200 constituent file.
The current evidence does not justify governance Model B or an override.
Keep validation BLOCKED until the anchor and checkpoint chain is closed.
