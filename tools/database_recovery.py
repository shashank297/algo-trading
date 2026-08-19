"""Create, verify, or restore a canonical DuckDB backup."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from operations import DatabaseBackupService


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup = subparsers.add_parser("backup")
    backup.add_argument("--database", default="market_data.duckdb")
    backup.add_argument("--output", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--backup", required=True)
    restore = subparsers.add_parser("restore")
    restore.add_argument("--backup", required=True)
    restore.add_argument("--database", required=True)
    restore.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    service = DatabaseBackupService()
    if args.command == "backup":
        result = service.backup(args.database, args.output)
    elif args.command == "verify":
        result = service.verify(args.backup)
    else:
        result = service.restore(args.backup, args.database, overwrite=args.overwrite)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
