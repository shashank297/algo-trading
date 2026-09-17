# NIFTY-200 archived identity evidence closure

The following free archived NSE CSV captures were acquired and incorporated as
A2 evidence:

- `https://web.archive.org/web/20140122091713id_/http%3A%2F%2Fnseindia.com%2Fcontent%2Findices%2Find_cnx200list.csv`
- `https://web.archive.org/web/20140709091522id_/http%3A%2F%2Fnseindia.com%2Fcontent%2Findices%2Find_cnx200list.csv`
- `https://web.archive.org/web/20150325063347id_/http%3A%2F%2Fnseindia.com%2Fcontent%2Findices%2Find_cnx200list.csv`

| Capture date | Content SHA-256 | Parsed rows | Unique symbols | Unique ISINs |
| --- | --- | ---: | ---: | ---: |
| 2014-01-13 | `840b495e70121b6e3c3323f78b33e7b62018abd8f459263418dbf07403786084` | 200 | 200 | 200 |
| 2014-07-09 | `383297fe23f076462158a65fe149196f8f1492c9a522ceb94f00626bc9d13b2a` | 200 | 200 | 200 |
| 2015-03-25 | `6ca9abaec1c3f2f7d50e92d36c80c9727e64d570f0d5de1f62c67b18b29267d6` | 200 | 200 | 200 |

All three rows use provenance `A2`, `ARCHIVED_INDEX_SNAPSHOT_DATE_ONLY`.

The source is identity evidence for its own dated snapshot. It is not used to
infer the 2012-01-02 membership set, reconstruct missing events, or promote the
B1 challenger dataset. The post-acquisition build measured:

- source count: 572 (`A1=565`, `A2=6`, `B1=1`)
- historical identity rows: 23,324
- unresolved event identities: 17, down from 32
- durable-ID/ISIN resolution: 98.5774%
- validation: `BLOCKED`

The remaining anchor, membership-history, checkpoint, and calendar blockers are
unchanged because the earliest available capture is 2014-01-13 and cannot
certify the campaign's 2012-01-02 initial state. The new captures did not alter
the authoritative replay result: 0 checkpoint matches and 108 mismatches.
