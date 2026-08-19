# Experiments

Single-symbol compatibility:

```bash
python research.py --command experiment --strategy trend_following --symbol RELIANCE-EQ --timeframe 1d --mode event-driven
```

Cross-sectional portfolio replay:

```bash
python research.py --command portfolio-experiment --strategy cross_sectional_momentum --universe RELIANCE-EQ,TCS-EQ,HDFCBANK-EQ,INFY-EQ,ICICIBANK-EQ
```

Resumable mixed-scope research:

```bash
python research.py --command mass-research --strategies trend_following,cross_sectional_momentum,low_volatility --universe RELIANCE-EQ,TCS-EQ,HDFCBANK-EQ,INFY-EQ,ICICIBANK-EQ
```

Import an immutable official NIFTY 200 snapshot with `python tools/import_nifty200.py --effective-date YYYY-MM-DD`. The importer requires exactly 200 unique constituents, stores the source hash, resolves Angel aliases, and flags unresolved tokens as not paper-eligible. Current constituents disclose survivorship bias.

Mass jobs are resumable by deterministic key and record expanding walk-forward folds plus source revision.
