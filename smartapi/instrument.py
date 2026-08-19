"""Instrument master caching and lookup utilities."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from loguru import logger

from utils.timezone import IST


class InstrumentMaster:
    """Download, cache, and query the SmartAPI instrument master."""

    REQUIRED_COLUMNS = [
        "token",
        "symbol",
        "name",
        "expiry",
        "strike",
        "lotsize",
        "instrumenttype",
        "exch_seg",
        "tick_size",
    ]

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize the instrument master client.

        Args:
            config: Full application configuration dictionary.
        """

        self.config = config
        self.instrument_master_url: str = config["smartapi"]["instrument_master_url"]
        self.refresh_hours: int = int(config["data"]["instrument_master_refresh_hours"])
        self.local_path = Path(__file__).resolve().parent.parent / "data" / "instrument_master.json"
        self.local_path.parent.mkdir(parents=True, exist_ok=True)
        self._df = pd.DataFrame(columns=self.REQUIRED_COLUMNS)

    def download_instrument_master(self, force: bool = False) -> bool:
        """Download or reuse the cached instrument master.

        Args:
            force: If True, bypass local disk cache and force a fresh download.

        Returns:
            bool: True when the instrument master is loaded successfully.

        Raises:
            RuntimeError: If the download or parsing fails.
        """

        try:
            raw_payload: list[dict[str, Any]]
            if not force and self._is_cache_fresh():
                try:
                    raw_payload = self._load_local_file()
                    logger.info("📦 Reusing cached instrument master from {}", self.local_path)
                except (OSError, ValueError, TypeError) as exc:
                    logger.warning("Ignoring invalid instrument cache and downloading a fresh copy: {}", exc)
                    raw_payload = self._download_remote_file()
                    self._write_local_file(raw_payload)
            else:
                raw_payload = self._download_remote_file()
                self._write_local_file(raw_payload)

            frame = pd.DataFrame(raw_payload)
            self._df = frame.reindex(columns=self.REQUIRED_COLUMNS).copy()
            if self._df.empty or self._df[["token", "symbol", "exch_seg"]].isna().any().any():
                raise RuntimeError("Instrument master is missing required instrument identifiers.")
            self._df["token"] = self._df["token"].astype(str)
            self._df = self._df.drop_duplicates(subset=["token", "exch_seg"]).reset_index(drop=True)
            logger.info("📦 Instrument master loaded: {} instruments", len(self._df))
            return True
        except Exception as exc:
            logger.exception("Failed to load instrument master: {}", exc)
            raise RuntimeError("Instrument master load failed.") from exc

    def get_token(self, symbol: str, exchange: str) -> str | None:
        """Return the token for a symbol and exchange pair."""

        try:
            result = self._df.loc[
                (self._df["symbol"] == symbol) & (self._df["exch_seg"] == exchange),
                "token",
            ]
            if result.empty:
                return None
            return str(result.iloc[0])
        except Exception as exc:
            logger.exception("Token lookup failed for {} {}: {}", symbol, exchange, exc)
            return None

    def get_symbol(self, token: str, exchange: str) -> str | None:
        """Return the symbol for a token and exchange pair."""

        try:
            result = self._df.loc[
                (self._df["token"] == str(token)) & (self._df["exch_seg"] == exchange),
                "symbol",
            ]
            if result.empty:
                return None
            return str(result.iloc[0])
        except Exception as exc:
            logger.exception("Symbol lookup failed for {} {}: {}", token, exchange, exc)
            return None

    def get_instrument_info(self, token: str, exchange: str) -> dict[str, Any] | None:
        """Return the full instrument row for a token and exchange pair."""

        try:
            rows = self._df.loc[
                (self._df["token"] == str(token)) & (self._df["exch_seg"] == exchange),
                self.REQUIRED_COLUMNS,
            ]
            if rows.empty:
                return None
            return rows.iloc[0].to_dict()
        except Exception as exc:
            logger.exception("Instrument info lookup failed for {} {}: {}", token, exchange, exc)
            return None

    def search_symbol(
        self,
        query: str,
        exchange: str | None = None,
    ) -> pd.DataFrame:
        """Search the instrument master by symbol.

        Args:
            query: Case-insensitive partial symbol search text.
            exchange: Optional exchange filter.

        Returns:
            pd.DataFrame: Matching instrument rows.
        """

        try:
            mask = self._df["symbol"].astype(str).str.contains(query, case=False, na=False)
            results = self._df.loc[mask, self.REQUIRED_COLUMNS]
            if exchange is not None:
                results = results.loc[results["exch_seg"] == exchange]
            return results.reset_index(drop=True)
        except Exception as exc:
            logger.exception("Instrument symbol search failed for {}: {}", query, exc)
            return pd.DataFrame(columns=self.REQUIRED_COLUMNS)

    def _is_cache_fresh(self) -> bool:
        """Return whether the local instrument cache is fresh enough to reuse."""

        if not self.local_path.exists():
            return False
        modified_at = datetime.fromtimestamp(self.local_path.stat().st_mtime, tz=IST)
        return datetime.now(tz=IST) - modified_at < timedelta(hours=self.refresh_hours)

    def _load_local_file(self) -> list[dict[str, Any]]:
        """Load the cached instrument master file."""

        payload = json.loads(self.local_path.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or not all(isinstance(row, dict) for row in payload):
            raise ValueError("Instrument cache must contain a list of objects.")
        return payload

    def _download_remote_file(self) -> list[dict[str, Any]]:
        """Download the instrument master from the configured URL."""

        response = requests.get(self.instrument_master_url, timeout=30)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError("Instrument master payload is not a JSON list.")
        return payload

    def _write_local_file(self, payload: list[dict[str, Any]]) -> None:
        """Write the instrument master file atomically."""

        temp_path = self.local_path.with_name(f"{self.local_path.name}.{os.getpid()}.tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        temp_path.replace(self.local_path)
