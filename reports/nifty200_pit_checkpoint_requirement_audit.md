# NIFTY-200 PIT checkpoint requirement audit

Conclusion: `HISTORICAL_DVR_COUNT_RESOLVED_MONTHLY_EVIDENCE_GAPS_REMAIN`

The official launch notice describes CNX 200 periodic review as semi-annual, not a
monthly constituent-publication obligation. The public corpus nevertheless contains
many monthly weightage files, and the validator requires an official monthly
checkpoint. Those are different claims: the first is index methodology evidence; the
second is this repository's conservative acceptance control. This task does not weaken
that control or silently treat a missing month as PASS.

The 50 checkpoints from April 2016 through May 2020 were inspected at row level. Each
contains 201 unique constituent symbols including TATAMTRDVR. The 2016-02-22 release
explicitly establishes 201 securities from 2016-04-01. The 2020-06-10 release removes
TATAMTRDVR with ten exclusions and nine inclusions effective 2020-06-26. The validator
now applies that documented period-specific count and preserves all source rows.

Required governance decision: confirm whether periodic official checkpoints plus complete
causal event lineage are acceptable for the campaign, or retain the monthly-checkpoint
rule. Until that decision and the 2012-01-02 anchor are supplied, automated validation
remains blocked.

Official methodology reference: <https://niftyindices.com/Press_Release/ind_prs18072011.pdf>
Additional-security rule: <https://www.niftyindices.com/Press_Release/ind_prs22022016_2.pdf>
DVR removal: <https://www.niftyindices.com/Press_Release/ind_prs10062020.pdf>
