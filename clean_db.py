import duckdb

def main():
    conn = duckdb.connect('market_data.duckdb', read_only=False)
    tables_to_clear = [
        "strategy_runs",
        "strategy_metrics",
        "strategy_orders",
        "strategy_fills",
        "trade_attribution",
        "trade_round_trips",
        "fill_cost_components",
        "portfolio_positions",
        "portfolio_rebalances",
        "strategy_equity_curve",
        "experiment_jobs",
        "walk_forward_folds",
        "strategy_correlations",
        "promotion_reviews",
    ]

    
    print("Clearing corrupted backtest artifacts...")
    for table in tables_to_clear:
        try:
            conn.execute(f"DELETE FROM {table}")
            print(f"Cleared {table}")
        except Exception as e:
            print(f"Skipped {table}: {e}")
            
    print("Database cleaned.")
    conn.close()

if __name__ == "__main__":
    main()
