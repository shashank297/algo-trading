# NIFTY-200 PIT checkpoint requirement audit

Conclusion: `PERIODIC_CHECKPOINT_SUFFICIENT_PENDING_GOVERNANCE_APPROVAL`

The official launch notice describes CNX 200 periodic review as semi-annual, not a
monthly constituent-publication obligation. The public corpus nevertheless contains
many monthly weightage files, and the current validator requires a 200-member monthly
checkpoint. Those are different claims: the first is index methodology evidence; the
second is this repository's conservative acceptance control. This task does not weaken
that control or silently treat a missing month as PASS.

The 50 checkpoints from April 2016 through May 2020 were inspected at row level. Each
contains 201 unique constituent symbols in the extracted official PDF, with no duplicate
symbol or parser-created header row. Their status remains manual-review because the
repository acceptance rule expects exactly 200 and the source semantics/count discrepancy
cannot be resolved by deleting an apparently valid constituent.

Required governance decision: confirm whether periodic official checkpoints plus complete
causal event lineage are acceptable for the campaign, or retain the monthly/200-member
rule. Until that decision and the 2012-01-02 anchor are supplied, automated validation
remains blocked.

Official methodology reference: <https://niftyindices.com/Press_Release/ind_prs18072011.pdf>
