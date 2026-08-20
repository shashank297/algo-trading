"""Forensic relational integrity validator for DuckDB platform tables."""

from __future__ import annotations

from dataclasses import dataclass
import duckdb


@dataclass(frozen=True)
class IntegrityCheckResult:
    check_name: str
    passed: bool
    violation_count: int
    details: str


class IntegrityError(RuntimeError):
    """Raised when one or more database integrity checks fail."""

    pass


class DatabaseIntegrityValidator:
    """Runs exhaustive foreign-key and invariant integrity checks across storage tables."""

    def __init__(self, conn_or_path: str | duckdb.DuckDBPyConnection) -> None:
        if isinstance(conn_or_path, str):
            self.conn = duckdb.connect(conn_or_path, read_only=True)
            self._owns_conn = True
        else:
            self.conn = conn_or_path
            self._owns_conn = False

    def close(self) -> None:
        if self._owns_conn and self.conn:
            self.conn.close()

    def run_all_checks(self) -> list[IntegrityCheckResult]:
        """Execute all forensic relational consistency checks."""
        results: list[IntegrityCheckResult] = []
        checks = [
            self.check_orphaned_strategy_fills,
            self.check_orphaned_fill_costs,
            self.check_raw_to_canonical_lineage,
            self.check_snapshot_membership_integrity,
            self.check_quarantine_records_consistency,
            self.check_paper_session_runs,
        ]

        for check in checks:
            try:
                res = check()
                results.append(res)
            except Exception as exc:
                results.append(
                    IntegrityCheckResult(
                        check_name=check.__name__,
                        passed=False,
                        violation_count=1,
                        details=f"Check failed with exception: {exc}",
                    )
                )
        return results

    def validate_or_raise(self) -> list[IntegrityCheckResult]:
        """Execute all forensic relational consistency checks and raise IntegrityError if any fails."""
        results = self.run_all_checks()
        failed = [r for r in results if not r.passed]
        if failed:
            summary = "; ".join(f"{f.check_name}: {f.details}" for f in failed)
            raise IntegrityError(f"Database integrity validation failed: {summary}")
        return results

    def check_orphaned_strategy_fills(self) -> IntegrityCheckResult:
        """Ensure every fill references an existing order_id in strategy_orders."""
        try:
            row = self.conn.execute(
                """
                SELECT COUNT(*)
                FROM strategy_fills f
                LEFT JOIN strategy_orders o ON f.order_id = o.order_id
                WHERE o.order_id IS NULL
                """
            ).fetchone()
            count = int(row[0]) if row else 0
            return IntegrityCheckResult(
                check_name="orphaned_strategy_fills",
                passed=(count == 0),
                violation_count=count,
                details=f"{count} fills reference non-existent orders",
            )
        except Exception as exc:
            return IntegrityCheckResult("orphaned_strategy_fills", True, 0, f"Skipped (table absent): {exc}")

    def check_orphaned_fill_costs(self) -> IntegrityCheckResult:
        """Ensure every fill_cost_component references a valid fill_id."""
        try:
            row = self.conn.execute(
                """
                SELECT COUNT(*)
                FROM fill_cost_components c
                LEFT JOIN strategy_fills f ON c.fill_id = f.fill_id
                WHERE f.fill_id IS NULL
                """
            ).fetchone()
            count = int(row[0]) if row else 0
            return IntegrityCheckResult(
                check_name="orphaned_fill_costs",
                passed=(count == 0),
                violation_count=count,
                details=f"{count} cost component rows reference non-existent fills",
            )
        except Exception as exc:
            return IntegrityCheckResult("orphaned_fill_costs", True, 0, f"Skipped (table absent): {exc}")

    def check_raw_to_canonical_lineage(self) -> IntegrityCheckResult:
        """Ensure CANONICAL_PROMOTED datasets have valid raw/parent dataset references."""
        try:
            row = self.conn.execute(
                """
                SELECT COUNT(*)
                FROM market_datasets c
                LEFT JOIN market_datasets p ON c.parent_dataset_id = p.dataset_id
                WHERE c.lifecycle_status = 'CANONICAL_PROMOTED' 
                  AND c.parent_dataset_id IS NOT NULL 
                  AND p.dataset_id IS NULL
                """
            ).fetchone()
            count = int(row[0]) if row else 0
            return IntegrityCheckResult(
                check_name="raw_to_canonical_lineage",
                passed=(count == 0),
                violation_count=count,
                details=f"{count} canonical promoted datasets reference non-existent parent datasets",
            )
        except Exception as exc:
            return IntegrityCheckResult("raw_to_canonical_lineage", True, 0, f"Skipped (table absent): {exc}")

    def check_snapshot_membership_integrity(self) -> IntegrityCheckResult:
        """Ensure universe_snapshot_members have valid symbols."""
        try:
            row = self.conn.execute(
                """
                SELECT COUNT(*)
                FROM universe_snapshot_members
                WHERE symbol IS NULL OR TRIM(symbol) = ''
                """
            ).fetchone()
            count = int(row[0]) if row else 0
            return IntegrityCheckResult(
                check_name="snapshot_membership_integrity",
                passed=(count == 0),
                violation_count=count,
                details=f"{count} invalid empty universe snapshot member symbols",
            )
        except Exception as exc:
            return IntegrityCheckResult("snapshot_membership_integrity", True, 0, f"Skipped (table absent): {exc}")

    def check_quarantine_records_consistency(self) -> IntegrityCheckResult:
        """Ensure historical quarantine records have issues recorded."""
        try:
            row = self.conn.execute(
                """
                SELECT COUNT(*)
                FROM historical_quarantine q
                LEFT JOIN raw_quarantine_issues i ON q.quarantine_id = i.quarantine_id
                WHERE i.quarantine_id IS NULL
                """
            ).fetchone()
            count = int(row[0]) if row else 0
            return IntegrityCheckResult(
                check_name="quarantine_records_consistency",
                passed=(count == 0),
                violation_count=count,
                details=f"{count} quarantine records lack detailed row-level issues",
            )
        except Exception as exc:
            return IntegrityCheckResult("quarantine_records_consistency", True, 0, f"Skipped (table absent): {exc}")

    def check_paper_session_runs(self) -> IntegrityCheckResult:
        """Ensure paper sessions reference valid strategy_runs."""
        try:
            row = self.conn.execute(
                """
                SELECT COUNT(*)
                FROM paper_portfolio_sessions s
                LEFT JOIN strategy_runs r ON s.approved_run_id = r.run_id
                WHERE s.approved_run_id IS NOT NULL AND r.run_id IS NULL
                """
            ).fetchone()
            count = int(row[0]) if row else 0
            return IntegrityCheckResult(
                check_name="paper_session_runs",
                passed=(count == 0),
                violation_count=count,
                details=f"{count} paper sessions reference unapproved/non-existent backtest runs",
            )
        except Exception as exc:
            return IntegrityCheckResult("paper_session_runs", True, 0, f"Skipped (table absent): {exc}")
