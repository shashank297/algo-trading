"""Database migrations runner for DuckDB schema evolution."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import duckdb
from loguru import logger


MIGRATIONS_DIR = Path(__file__).parent


class MigrationRunner:
    """Applies ordered SQL migration scripts to DuckDB fail-closed."""

    def __init__(self, conn_or_path: str | duckdb.DuckDBPyConnection) -> None:
        if isinstance(conn_or_path, str):
            self.conn = duckdb.connect(conn_or_path)
            self._owns_conn = True
        else:
            self.conn = conn_or_path
            self._owns_conn = False

    def run_migrations(self) -> list[str]:
        """Discover and apply all unapplied migration scripts with checksum validation."""
        try:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR NOT NULL PRIMARY KEY,
                    applied_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    checksum VARCHAR NOT NULL
                );
            """)
            applied_rows = self.conn.execute("SELECT version, checksum FROM schema_migrations").fetchall()
            applied_map = {row[0]: row[1] for row in applied_rows}
            sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
            applied_now = []

            for sql_file in sql_files:
                version = sql_file.stem
                sql_content = sql_file.read_text(encoding="utf-8")
                checksum = hashlib.sha256(sql_content.encode()).hexdigest()

                if version in applied_map:
                    # Validate checksum integrity against tampering
                    recorded_checksum = applied_map[version]
                    if recorded_checksum != checksum:
                        raise RuntimeError(
                            f"Migration integrity violation: {version} checksum mismatch! "
                            f"Recorded: {recorded_checksum}, Current: {checksum}. Migrations are immutable."
                        )
                    continue

                logger.info("Applying migration {}", version)
                try:
                    self.conn.execute("BEGIN TRANSACTION;")
                    self.conn.execute(sql_content)
                    self.conn.execute(
                        "INSERT INTO schema_migrations (version, applied_at, checksum) VALUES (?, ?, ?)",
                        [version, datetime.now(timezone.utc), checksum],
                    )
                    self.conn.execute("COMMIT;")
                    applied_now.append(version)
                except Exception as exc:
                    try:
                        self.conn.execute("ROLLBACK;")
                    except Exception:
                        pass
                    logger.error("Failed to apply migration {}: {}", version, exc)
                    raise RuntimeError(f"Failed to apply migration {version}: {exc}") from exc
            return applied_now
        finally:
            if self._owns_conn:
                self.conn.close()
