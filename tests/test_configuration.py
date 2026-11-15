from __future__ import annotations

import copy
import unittest
from pathlib import Path

import yaml

from main import validate_config


class ConfigurationSafetyTests(unittest.TestCase):
    def test_risk_policy_is_required_and_canonical(self) -> None:
        path = Path(__file__).resolve().parents[1] / "config" / "config.example.yaml"
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        config = copy.deepcopy(config)
        config["smartapi"].update({
            "api_key": "test", "client_code": "test", "pin": "test", "totp_secret": "test",
        })
        config["research"].pop("risk")

        with self.assertRaisesRegex(RuntimeError, "research.risk"):
            validate_config(config)

    def test_risk_policy_rejects_permissive_liquidity_and_sector_values(self) -> None:
        path = Path(__file__).resolve().parents[1] / "config" / "config.example.yaml"
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        config = copy.deepcopy(config)
        config["smartapi"].update({
            "api_key": "test", "client_code": "test", "pin": "test", "totp_secret": "test",
        })
        config["research"]["risk"]["max_sector_exposure_pct"] = 0.40

        with self.assertRaisesRegex(RuntimeError, "max_sector_exposure_pct"):
            validate_config(config)

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

    def test_active_config_yaml_matches_canonical_policy(self) -> None:
        """Verify that active config/config.yaml strictly conforms to the canonical risk policy."""
        from main import load_yaml
        from risk.factory import AUTHORITATIVE_RISK_FIELDS, build_risk_policy, load_canonical_risk_policy
        from trading_stack.economic import economic_contract_hash
        import run_pipeline

        path = Path(__file__).resolve().parents[1] / "config" / "config.yaml"
        if not path.is_file():
            self.skipTest("Requires the local active configuration, which is excluded from Git")

        cfg = load_yaml(str(path))
        # 1. validate_config must succeed without error
        validate_config(cfg)

        canonical = load_canonical_risk_policy()
        canonical_rp = canonical.to_risk_policy()
        configured_risk = cfg["research"]["risk"]

        # 2. Every AUTHORITATIVE_RISK_FIELD must match canonical policy
        for field in sorted(AUTHORITATIVE_RISK_FIELDS):
            self.assertIn(field, configured_risk, f"Missing authoritative risk field {field} in config.yaml")
            self.assertEqual(
                configured_risk[field],
                getattr(canonical_rp, field),
                f"Field {field} in config.yaml does not match canonical policy value",
            )

        # 3. Configured risk policy hash must equal canonical policy hash
        configured_rp = build_risk_policy(cfg)
        configured_hash = economic_contract_hash(configured_rp.model_dump())
        self.assertEqual(
            configured_hash,
            canonical.policy_hash,
            "Configured risk-policy hash must equal canonical FAB-31 policy hash",
        )

        # 4. CAMPAIGN_FROZEN_RESEARCH_CONFIG_HASH in run_pipeline.py must match
        self.assertEqual(
            run_pipeline.CAMPAIGN_FROZEN_RESEARCH_CONFIG_HASH,
            economic_contract_hash(cfg["research"]),
            "CAMPAIGN_FROZEN_RESEARCH_CONFIG_HASH in run_pipeline.py must match active research config hash",
        )


if __name__ == "__main__":
    unittest.main()
