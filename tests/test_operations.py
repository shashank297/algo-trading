from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from operations import DatabaseBackupService
from storage import DuckDBManager


class DatabaseRecoveryTests(unittest.TestCase):
    def test_backup_verify_and_atomic_restore_preserve_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "source.duckdb"
            backup = root / "backups" / "source.duckdb"
            restored = root / "restored.duckdb"
            db = DuckDBManager(str(database))
            try:
                db.conn.execute("INSERT INTO market_data_state VALUES (2, 7, CURRENT_TIMESTAMP)")
            finally:
                db.close()
            service = DatabaseBackupService()
            manifest = service.backup(database, backup)
            result = service.restore(backup, restored)
            restored_db = DuckDBManager(str(restored))
            try:
                revision = restored_db.conn.execute(
                    "SELECT revision FROM market_data_state WHERE state_id = 2"
                ).fetchone()[0]
            finally:
                restored_db.close()
            self.assertEqual(manifest["sha256"], service._sha256(backup))
            self.assertGreater(result["table_count"], 0)
            self.assertEqual(revision, 7)

    def test_restore_rejects_tampered_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "source.duckdb"
            backup = root / "source.backup.duckdb"
            db = DuckDBManager(str(database))
            db.close()
            service = DatabaseBackupService()
            service.backup(database, backup)
            with backup.open("ab") as handle:
                handle.write(b"tampered")
            with self.assertRaisesRegex(ValueError, "hash"):
                service.restore(backup, root / "restored.duckdb")


if __name__ == "__main__":
    unittest.main()
