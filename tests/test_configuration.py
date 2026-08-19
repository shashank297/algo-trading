from __future__ import annotations

import copy
import unittest
from pathlib import Path

import yaml

from main import validate_config


class ConfigurationSafetyTests(unittest.TestCase):
    def test_live_trading_cannot_be_enabled(self) -> None:
        path = Path(__file__).resolve().parents[1] / "config" / "config.example.yaml"
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        config = copy.deepcopy(config)
        config["smartapi"].update({
            "api_key": "test", "client_code": "test", "pin": "test", "totp_secret": "test",
        })
        config["research"]["live_trading"] = True

        with self.assertRaisesRegex(RuntimeError, "must remain false"):
            validate_config(config)


if __name__ == "__main__":
    unittest.main()
