# NIFTY-200 PIT initial-anchor audit

Status: `BLOCKED_NO_CERTIFIABLE_2012_01_02_ANCHOR`

The earliest acquired official checkpoint is 2013-04-18 with 200 unique candidate rows. These rows are retained in `initial_anchor_20120102.parquet` only as forward-checkpoint evidence; none is asserted to have been a member on 2012-01-02 and none is eligible for replay. No synthetic membership, predecessor, successor, ISIN, or announcement date was created.

Required closure evidence: an authoritative historical CNX/NIFTY-200 membership anchor effective on or before 2012-01-02, with durable identity and source hash for every member, or a complete first-party event chain that proves the anchor.

The official CNX 200 launch notice is methodology evidence, not a dated constituent list: <https://niftyindices.com/Press_Release/ind_prs18072011.pdf>
