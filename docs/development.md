# Development

Install dependencies with `pip install -r requirements.txt`, then run the suite with:

```bash
python -m pytest tests -q
```

Use `main.py` for ingestion and `research.py` for research workflows. Add tests with every provider, strategy, risk, orchestration, or schema change. Preserve `historical_candles` compatibility and avoid unrelated refactors.
