# NIFTY-200 PIT live archive probe

Probe date: `2026-09-17`

## Findings

- The official NSE Indices historical-report interface at `https://www.niftyindices.com/reports?option1=Archives%20of%20Daily/%20Monthly%20Reports&option2=Daily%20Snapshot` returned `No Data Found` for `2012-01-02`.
- The same official interface returned `No Data Found` for `2022-09-30`.
- The official NIFTY-200 page exposes `https://www.niftyindices.com/IndexConstituent/ind_nifty200list.csv`, but it is a current constituent download and does not provide the requested historical dates.
- The official monthly-reports page exposes the current market-capitalisation/weightage archive, but the verified 2022-04 through 2026-08 ZIPs acquired through that route contain no NIFTY-200 member table; the other index tables are not a substitute.
- The official EOD Index File link routes to `https://www.connect2nse.com/iislNet/`, which requires an authenticated username, password, and captcha. It is not a free unauthenticated source for the missing historical constituent files.
- Wayback CDX search for that official constituent URL returned captures on 2017-11-13, 2018-03-15, 2019-02-02, and 2023-08-11; no capture predates the 2012-01-02 campaign anchor.
- The official CNX-200 launch notice confirms methodology and the 2011-07-19 launch, but contains no complete 200-member list.

## Closure impact

No new period-valid source was added to the corpus. The `2012-01-02` anchor and the missing historical checkpoints therefore remain unresolved; no synthetic membership or B1 promotion was performed.
