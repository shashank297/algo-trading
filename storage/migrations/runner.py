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

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def run_migrations(self) -> list[str]:
        """Discover and apply all unapplied migration scripts."""
        conn = duckdb.connect(self.db_path)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR NOT NULL PRIMARY KEY,
                    applied_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    checksum VARCHAR NOT NULL
                );
            """)
            applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()}
            sql_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
            applied_now = []

            for sql_file in sql_files:
                version = sql_file.stem
                if version in applied:
                    continue
                logger.info("Applying migration {}", version)
                sql_content = sql_file.read_text(encoding="utf-8")
                conn.execute(sql_content)
                checksum = hashlib.sha256(sql_content.encode()).hexdigest()
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at, checksum) VALUES (?, ?, ?)",
                    [version, datetime.now(timezone.utc), checksum],
                )
                applied_now.append(version)
            return applied_now
        finally:
            conn.close()
