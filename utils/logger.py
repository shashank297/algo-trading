"""Loguru logger configuration for the AlgoTrading project."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
import uuid
from typing import Any

from loguru import logger


class LoggerSetup:
    """Configure Loguru sinks for console and rotating file logging."""

    @staticmethod
    def setup(
        config: dict[str, Any],
        *,
        component: str = "application",
        command: str | None = None,
        operation_id: str | None = None,
    ) -> Any:
        """Configure and return the project logger.

        Args:
            config: Full application configuration dictionary.

        Returns:
            Any: Configured Loguru logger instance.
        """

        logging_config = config["logging"]
        log_path = Path(logging_config["path"])
        log_path.mkdir(parents=True, exist_ok=True)

        logger.remove()
        context = {
            "component": component,
            "command": command or component,
            "operation_id": operation_id or str(uuid.uuid4()),
        }
        logger.configure(extra=context)

        logger.add(
            sink=sys.stderr,
            level=logging_config["level"],
            colorize=True,
            backtrace=False,
            diagnose=False,
            format=logging_config.get(
                "format",
                "{time:YYYY-MM-DD HH:mm:ss} | {level} | {name} | {message}",
            ),
        )

        file_name = f"algotrading_{datetime.now().strftime('%Y-%m-%d')}.log"
        logger.add(
            sink=str(log_path / file_name),
            level=logging_config["level"],
            rotation=logging_config["rotation"],
            retention=logging_config["retention"],
            format=logging_config.get(
                "format",
                "{time:YYYY-MM-DD HH:mm:ss} | {level} | {name} | {message}",
            ),
            enqueue=False,
            encoding="utf-8",
            backtrace=False,
            diagnose=False,
        )

        structured_name = f"events_{datetime.now().strftime('%Y-%m-%d')}.jsonl"
        logger.add(
            sink=str(log_path / structured_name),
            level=logging_config["level"],
            rotation=logging_config["rotation"],
            retention=logging_config["retention"],
            serialize=True,
            enqueue=False,
            encoding="utf-8",
            backtrace=False,
            diagnose=False,
        )

        return logger
