import subprocess
import sys
import os
import argparse

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def run_step(command: list[str], description: str) -> None:
    print(f"\n{'='*60}")
    print(f">> STAGE: {description}")
    print(f"{'='*60}")
    
    # Run the subprocess and stream output directly to the console
    result = subprocess.run(command, env=os.environ.copy())
    
    if result.returncode != 0:
        print(f"\n[FATAL ERROR] Stage failed: {description}")
        print("Pipeline aborted.")
        sys.exit(result.returncode)
        
    print(f"\n[OK] {description} completed.")

def main():
    parser = argparse.ArgumentParser(description="End-to-End Orchestrator for Algo Trading Pipeline")
    parser.add_argument(
        "--universe-snapshot", 
        type=str, 
        default="NIFTY200_2026_08_17", 
        help="The universe snapshot ID to run the pipeline against"
    )
    parser.add_argument(
        "--skip-api",
        action="store_true",
        help="If set, the pipeline will complete after research and will not start the Dashboard API."
    )
    args = parser.parse_args()

    python_exe = sys.executable

    # Stage 1: Incremental Data Backfill
    run_step(
        [python_exe, "tools/backfill_market_history.py", "--universe-snapshot", args.universe_snapshot],
        "Incremental Market Data Backfill"
    )

    # Stage 2: Data Quality & Session Integrity
    run_step(
        [
            python_exe,
            "tools/refresh_session_quality.py",
            "--universe-snapshot",
            args.universe_snapshot,
            "--timeframe",
            "1d",
        ],
        "Data Quality & Session Guardrails"
    )


    # Stage 3: Event-Driven Mass Research
    run_step(
        [python_exe, "research.py", "--command", "mass-research", "--universe-snapshot", args.universe_snapshot],
        "Mass Strategy Backtesting & Evaluation"
    )

    print(f"\n{'='*60}")
    print("[DONE] PIPELINE COMPLETED SUCCESSFULLY")
    print(f"{'='*60}")


    # Stage 4: Launch API
    if not args.skip_api:
        print("\nStarting Dashboard API on http://127.0.0.1:8000 ... (Press Ctrl+C to quit)")
        try:
            subprocess.run(
                [python_exe, "-m", "uvicorn", "tools.dashboard.api.main:app", "--host", "127.0.0.1", "--port", "8000"],
                env=os.environ.copy()
            )
        except KeyboardInterrupt:
            print("\nShutting down API server. Goodbye!")

if __name__ == "__main__":
    main()
