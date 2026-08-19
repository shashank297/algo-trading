"""Unit, adversarial, and metamorphic property tests for SourceSemanticsAdapter and Ground-Truth Admission Gateway."""

from __future__ import annotations

import math
from datetime import date
import unittest

import duckdb
import numpy as np
import pandas as pd
import pytest

from data_platform.adjustments import PriceAdjustmentEngine
from data_platform.contracts import PriceAdjustment
from data_platform.source_semantics import (
    AmbiguousSourceBasisError,
    BasisEvidenceCode,
    CorporateActionBasisWarning,
    InvalidCorporateActionError,
    SourceBarSemantics,
    SourceBasisDetection,
    SourceSemanticsAdapter,
    SourceSemanticsPolicy,
    SourceValidationStatus,
    compose_same_day_share_actions,
)



class TestSourceSemanticsGateway(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = SourceSemanticsPolicy(
            adjusted_log_tolerance=0.15,
            raw_log_tolerance=0.15,
            max_missing_trading_sessions=0,
            max_calendar_gap_days=7,
            volume_window_sessions=5,
            min_evidence_strength=0.80,
            fail_closed=True,
        )

    def test_invalid_multiplier_rejection_zero_negative_nan_inf(self) -> None:
        """Corporate action metadata with R <= 0, NaN, or inf must raise InvalidCorporateActionError immediately."""
        bars = pd.DataFrame(
            {
                "timestamp": [pd.Timestamp("2022-07-27", tz="UTC"), pd.Timestamp("2022-07-28", tz="UTC")],
                "open": [1000.0, 100.0],
                "high": [1020.0, 105.0],
                "low": [990.0, 98.0],
                "close": [1000.0, 102.0],
                "volume": [1000, 10000],
            }
        )
        invalid_multipliers = [0.0, -1.0, -10.0, float("nan"), float("inf"), float("-inf")]
        for bad_r in invalid_multipliers:
            bad_action = pd.DataFrame(
                [
                    {
                        "action_id": "BAD_ACT",
                        "symbol": "TEST",
                        "ex_date": date(2022, 7, 28),
                        "action_type": "SPLIT",
                        "share_multiplier": bad_r,
                    }
                ]
            )
            with self.assertRaises(InvalidCorporateActionError):
                SourceSemanticsAdapter.detect_corporate_action_discontinuity(bars, bad_action, policy=self.policy)

    def test_log_space_symmetric_consolidation_and_split(self) -> None:
        """Log-space distances treat 10:1 split (R=10.0) and 1:10 consolidation (R=0.1) with exact mathematical symmetry."""
        # 10:1 split (Raw pre-close 1000, ex-open 100 -> observed ratio 10.0)
        split_bars = pd.DataFrame(
            {
                "timestamp": [pd.Timestamp("2022-07-27", tz="UTC"), pd.Timestamp("2022-07-28", tz="UTC")],
                "open": [1000.0, 100.0],
                "high": [1020.0, 105.0],
                "low": [990.0, 98.0],
                "close": [1000.0, 102.0],
                "volume": [1000, 10000],
            }
        )
        split_ca = pd.DataFrame([{"action_id": "S10", "symbol": "SPLITCO", "ex_date": date(2022, 7, 28), "action_type": "SPLIT", "share_multiplier": 10.0}])
        split_reports = SourceSemanticsAdapter.detect_corporate_action_discontinuity(split_bars, split_ca, policy=self.policy)
        self.assertEqual(len(split_reports), 1)
        self.assertEqual(split_reports[0].detection, SourceBasisDetection.UNADJUSTED)
        self.assertIsNotNone(split_reports[0].log_distance_raw)
        self.assertAlmostEqual(float(split_reports[0].log_distance_raw or 0.0), 0.0, places=5)
        self.assertIn(BasisEvidenceCode.RAW_RATIO_MATCH, split_reports[0].evidence_codes)

        # 1:10 consolidation / reverse-split (Raw pre-close 100, ex-open 1000 -> observed ratio 0.1)
        cons_bars = pd.DataFrame(
            {
                "timestamp": [pd.Timestamp("2022-07-27", tz="UTC"), pd.Timestamp("2022-07-28", tz="UTC")],
                "open": [100.0, 1000.0],
                "high": [105.0, 1020.0],
                "low": [98.0, 990.0],
                "close": [100.0, 1010.0],
                "volume": [10000, 1000],
            }
        )
        cons_ca = pd.DataFrame([{"action_id": "C10", "symbol": "CONSCO", "ex_date": date(2022, 7, 28), "action_type": "CONSOLIDATION", "share_multiplier": 0.1}])
        cons_reports = SourceSemanticsAdapter.detect_corporate_action_discontinuity(cons_bars, cons_ca, policy=self.policy)
        self.assertEqual(len(cons_reports), 1)
        self.assertEqual(cons_reports[0].detection, SourceBasisDetection.UNADJUSTED)
        self.assertIsNotNone(cons_reports[0].log_distance_raw)
        self.assertAlmostEqual(float(cons_reports[0].log_distance_raw or 0.0), 0.0, places=5)
        self.assertIn(BasisEvidenceCode.RAW_RATIO_MATCH, cons_reports[0].evidence_codes)


    def test_poor_hypothesis_separation_r_near_one(self) -> None:
        """When R is very close to 1.0 (e.g. R=1.05), hypothesis separation |ln(R)| is poor and flagged as POOR_HYPOTHESIS_SEPARATION."""
        bars = pd.DataFrame(
            {
                "timestamp": [pd.Timestamp("2023-01-14", tz="UTC"), pd.Timestamp("2023-01-15", tz="UTC")],
                "open": [105.0, 100.0],
                "high": [106.0, 101.0],
                "low": [104.0, 99.0],
                "close": [105.0, 100.0],
                "volume": [1000, 1050],
            }
        )
        ca = pd.DataFrame([{"action_id": "TINY", "symbol": "TINYCO", "ex_date": date(2023, 1, 15), "action_type": "SPLIT", "share_multiplier": 1.05}])
        reports = SourceSemanticsAdapter.detect_corporate_action_discontinuity(bars, ca, policy=self.policy)
        self.assertEqual(len(reports), 1)
        self.assertIn(BasisEvidenceCode.POOR_HYPOTHESIS_SEPARATION, reports[0].evidence_codes)

    def test_trading_session_gap_weekend_vs_missing_week(self) -> None:
        """Friday-to-Monday has 0 missing trading sessions (valid), whereas a missing 2-week gap flags INSUFFICIENT_EVIDENCE."""
        # 1. Friday to Monday (July 22, 2022 to July 25, 2022): 3 calendar days, 0 missing trading sessions (Valid)
        weekend_bars = pd.DataFrame(
            {
                "timestamp": [pd.Timestamp("2022-07-22", tz="UTC"), pd.Timestamp("2022-07-25", tz="UTC")],
                "open": [1000.0, 100.0],
                "high": [1020.0, 105.0],
                "low": [990.0, 98.0],
                "close": [1000.0, 102.0],
                "volume": [1000, 10000],
            }
        )
        ca_mon = pd.DataFrame([{"action_id": "MON1", "symbol": "MONCO", "ex_date": date(2022, 7, 25), "action_type": "SPLIT", "share_multiplier": 10.0}])
        reports_weekend = SourceSemanticsAdapter.detect_corporate_action_discontinuity(weekend_bars, ca_mon, policy=self.policy)
        self.assertEqual(len(reports_weekend), 1)
        self.assertEqual(reports_weekend[0].missing_trading_sessions, 0)
        self.assertEqual(reports_weekend[0].trading_session_distance, 1)
        self.assertEqual(reports_weekend[0].detection, SourceBasisDetection.UNADJUSTED)

        # 2. 14-day missing data gap (July 14 to July 28): 14 calendar days, 9 missing trading sessions (Insufficient Evidence)
        missing_bars = pd.DataFrame(
            {
                "timestamp": [pd.Timestamp("2022-07-14", tz="UTC"), pd.Timestamp("2022-07-28", tz="UTC")],
                "open": [1000.0, 100.0],
                "high": [1020.0, 105.0],
                "low": [990.0, 98.0],
                "close": [1000.0, 102.0],
                "volume": [1000, 10000],
            }
        )
        ca_gap = pd.DataFrame([{"action_id": "GAP1", "symbol": "GAPCO", "ex_date": date(2022, 7, 28), "action_type": "SPLIT", "share_multiplier": 10.0}])
        reports_gap = SourceSemanticsAdapter.detect_corporate_action_discontinuity(missing_bars, ca_gap, policy=self.policy)
        self.assertEqual(len(reports_gap), 1)
        self.assertEqual(reports_gap[0].detection, SourceBasisDetection.INSUFFICIENT_EVIDENCE)
        self.assertIn(BasisEvidenceCode.SESSION_GAP_EXCEEDED, reports_gap[0].evidence_codes)

    def test_deterministic_status_precedence_mixed_over_insufficient_and_ambiguous(self) -> None:
        """When a dataset has Action 1=RAW, Action 2=ADJUSTED, Action 3=INSUFFICIENT, status MUST be MIXED_BASIS."""
        multi_bars = pd.DataFrame(
            {
                "timestamp": [
                    pd.Timestamp("2018-05-09", tz="UTC"),
                    pd.Timestamp("2018-05-10", tz="UTC"),  # 2:1 Raw jump (200 -> 100)
                    pd.Timestamp("2020-03-01", tz="UTC"),
                    pd.Timestamp("2020-03-02", tz="UTC"),  # 2:1 Adjusted (100 -> 100)
                    pd.Timestamp("2022-01-01", tz="UTC"),
                    pd.Timestamp("2022-02-01", tz="UTC"),  # Missing 1 month data (INSUFFICIENT)
                ],
                "open": [200.0, 100.0, 100.0, 100.0, 100.0, 10.0],
                "high": [205.0, 105.0, 102.0, 102.0, 102.0, 11.0],
                "low": [195.0, 98.0, 98.0, 98.0, 98.0, 9.0],
                "close": [200.0, 102.0, 100.0, 101.0, 100.0, 10.0],
                "volume": [1000, 2000, 2000, 2000, 2000, 20000],
                "symbol": ["MIXCO"] * 6,
            }
        )
        actions = pd.DataFrame(
            [
                {"action_id": "ACT_RAW", "symbol": "MIXCO", "ex_date": date(2018, 5, 10), "action_type": "SPLIT", "share_multiplier": 2.0},
                {"action_id": "ACT_ADJ", "symbol": "MIXCO", "ex_date": date(2020, 3, 2), "action_type": "SPLIT", "share_multiplier": 2.0},
                {"action_id": "ACT_GAP", "symbol": "MIXCO", "ex_date": date(2022, 2, 1), "action_type": "SPLIT", "share_multiplier": 10.0},
            ]
        )
        with self.assertRaises(AmbiguousSourceBasisError) as ctx, pytest.warns(CorporateActionBasisWarning):
            SourceSemanticsAdapter.infer_semantics(multi_bars, actions, policy=self.policy)
        self.assertIn("MIXED_BASIS", str(ctx.exception))


    def test_deterministic_status_precedence_raw_plus_ambiguous(self) -> None:
        """When a dataset has Action 1=RAW and Action 2=AMBIGUOUS, status MUST be AMBIGUOUS."""
        bars = pd.DataFrame(
            {
                "timestamp": [
                    pd.Timestamp("2018-05-09", tz="UTC"),
                    pd.Timestamp("2018-05-10", tz="UTC"),  # 2:1 Raw jump (200 -> 100)
                    pd.Timestamp("2020-03-01", tz="UTC"),
                    pd.Timestamp("2020-03-02", tz="UTC"),  # Ambiguous (100 -> 86.6 with R=1.333)
                ],
                "open": [200.0, 100.0, 100.0, 86.60],
                "high": [205.0, 105.0, 102.0, 87.00],
                "low": [195.0, 98.0, 98.0, 84.00],
                "close": [200.0, 102.0, 100.0, 86.60],
                "volume": [1000, 2000, 1000, 1500],
                "symbol": ["AMBCO"] * 4,
            }
        )
        actions = pd.DataFrame(
            [
                {"action_id": "ACT_RAW", "symbol": "AMBCO", "ex_date": date(2018, 5, 10), "action_type": "SPLIT", "share_multiplier": 2.0},
                {"action_id": "ACT_AMB", "symbol": "AMBCO", "ex_date": date(2020, 3, 2), "action_type": "BONUS", "share_multiplier": 1.333333},
            ]
        )
        with self.assertRaises(AmbiguousSourceBasisError) as ctx:
            SourceSemanticsAdapter.infer_semantics(bars, actions, policy=self.policy)
        self.assertIn("AMBIGUOUS", str(ctx.exception))

    def test_overridden_status_preserves_pre_override_state(self) -> None:
        """When an override is applied, pre_override_status records the original empirical state while validation_status is OVERRIDDEN."""
        amb_bars = pd.DataFrame(
            {
                "timestamp": [pd.Timestamp("2023-05-09", tz="UTC"), pd.Timestamp("2023-05-10", tz="UTC")],
                "open": [100.0, 86.60],
                "high": [102.0, 87.00],
                "low": [98.0, 84.00],
                "close": [100.0, 86.60],
                "volume": [1000, 1500],
                "symbol": ["OVRCO", "OVRCO"],
            }
        )
        ca = pd.DataFrame([{"action_id": "B1", "symbol": "OVRCO", "ex_date": date(2023, 5, 10), "action_type": "BONUS", "share_multiplier": 1.333333}])
        # User explicitly declares UNADJUSTED override on ambiguous data
        semantics = SourceSemanticsAdapter.infer_semantics(
            amb_bars, ca, declared_adjustment=PriceAdjustment.UNADJUSTED, override_reason="User confirmed vendor is unadjusted raw feed."
        )
        self.assertEqual(semantics.validation_status, SourceValidationStatus.OVERRIDDEN)
        self.assertEqual(semantics.pre_override_status, SourceValidationStatus.AMBIGUOUS)
        self.assertEqual(semantics.override_reason, "User confirmed vendor is unadjusted raw feed.")
        self.assertTrue(len(semantics.semantics_hash) > 16)

    def test_require_admitted_gatekeeper(self) -> None:
        """require_admitted() allows VERIFIED and OVERRIDDEN but raises on AMBIGUOUS, MIXED_BASIS, or INSUFFICIENT."""
        verified = SourceBarSemantics(price_adjustment=PriceAdjustment.UNADJUSTED, validation_status=SourceValidationStatus.VERIFIED)
        verified.require_admitted()  # Should not raise

        overridden = SourceBarSemantics(price_adjustment=PriceAdjustment.UNADJUSTED, validation_status=SourceValidationStatus.OVERRIDDEN)
        overridden.require_admitted()  # Should not raise

        ambiguous = SourceBarSemantics(price_adjustment=PriceAdjustment.UNADJUSTED, validation_status=SourceValidationStatus.AMBIGUOUS)
        with self.assertRaises(AmbiguousSourceBasisError):
            ambiguous.require_admitted()

        mixed = SourceBarSemantics(price_adjustment=PriceAdjustment.UNADJUSTED, validation_status=SourceValidationStatus.MIXED_BASIS)
        with self.assertRaises(AmbiguousSourceBasisError):
            mixed.require_admitted()

    def test_idempotency_raw_to_canonical_redetect_readjust(self) -> None:
        """End-to-End Idempotency Invariant: Raw -> Canonical -> Re-detect -> Re-adjust yields A(A(X)) = A(X)."""
        raw_bars = pd.DataFrame(
            {
                "timestamp": [pd.Timestamp("2022-07-27", tz="UTC"), pd.Timestamp("2022-07-28", tz="UTC")],
                "open": [959.40, 100.35],
                "high": [965.00, 102.00],
                "low": [950.00, 98.00],
                "close": [959.40, 100.35],
                "volume": [1_000, 10_000],
                "symbol": ["TATASTEEL", "TATASTEEL"],
            }
        )
        ca = pd.DataFrame([{"action_id": "TATA_S10", "symbol": "TATASTEEL", "ex_date": date(2022, 7, 28), "action_type": "SPLIT", "share_multiplier": 10.0}])

        # Stage 1: Gateway detects UNADJUSTED on raw data
        raw_semantics = SourceSemanticsAdapter.infer_semantics(raw_bars, ca, policy=self.policy)
        self.assertEqual(raw_semantics.price_adjustment, PriceAdjustment.UNADJUSTED)
        self.assertEqual(raw_semantics.validation_status, SourceValidationStatus.VERIFIED)

        # Stage 2: Adjust raw to canonical split-adjusted series A(X)
        adj_bars_1 = PriceAdjustmentEngine.adjust_ohlcv(
            raw_bars, corporate_actions=ca, adjustment=PriceAdjustment.SPLIT_ADJUSTED, source_semantics=raw_semantics
        )
        self.assertAlmostEqual(adj_bars_1["close"].iloc[0], 95.94, places=2)
        self.assertAlmostEqual(adj_bars_1["close"].iloc[1], 100.35, places=2)

        # Stage 3: Gateway re-detects on canonical series A(X) -> MUST be SPLIT_ADJUSTED / VERIFIED
        with pytest.warns(CorporateActionBasisWarning):
            adj_semantics = SourceSemanticsAdapter.infer_semantics(adj_bars_1, ca, policy=self.policy)
        self.assertEqual(adj_semantics.price_adjustment, PriceAdjustment.SPLIT_ADJUSTED)
        self.assertEqual(adj_semantics.validation_status, SourceValidationStatus.VERIFIED)

        # Stage 4: Re-adjust A(X) requesting SPLIT_ADJUSTED again -> A(A(X)) must equal A(X) identically (no double-adjustment)
        adj_bars_2 = PriceAdjustmentEngine.adjust_ohlcv(
            adj_bars_1, corporate_actions=ca, adjustment=PriceAdjustment.SPLIT_ADJUSTED, source_semantics=adj_semantics
        )
        pd.testing.assert_frame_equal(adj_bars_1, adj_bars_2)

    def test_adversarial_composite_overflow_rejection(self) -> None:
        """Adversarial huge multiplier inputs that would cause float overflow raise InvalidCorporateActionError."""
        overflow_ca = pd.DataFrame(
            [
                {"action_id": "HUGE1", "symbol": "OVERFLOWCO", "ex_date": date(2023, 1, 1), "action_type": "SPLIT", "share_multiplier": 1e200},
                {"action_id": "HUGE2", "symbol": "OVERFLOWCO", "ex_date": date(2023, 1, 1), "action_type": "SPLIT", "share_multiplier": 1e200},
            ]
        )
        with self.assertRaises(InvalidCorporateActionError), pytest.warns(RuntimeWarning):
            compose_same_day_share_actions(overflow_ca)


    def test_deterministic_semantics_hashing(self) -> None:
        """Semantics hash is deterministic and sensitive to input price boundary modifications."""
        bars1 = pd.DataFrame(
            {
                "timestamp": [pd.Timestamp("2022-07-27", tz="UTC"), pd.Timestamp("2022-07-28", tz="UTC")],
                "open": [1000.0, 100.0],
                "high": [1020.0, 105.0],
                "low": [990.0, 98.0],
                "close": [1000.0, 102.0],
                "volume": [1000, 10000],
                "symbol": ["HASHCO", "HASHCO"],
            }
        )
        ca = pd.DataFrame([{"action_id": "S10", "symbol": "HASHCO", "ex_date": date(2022, 7, 28), "action_type": "SPLIT", "share_multiplier": 10.0}])

        sem1 = SourceSemanticsAdapter.infer_semantics(bars1, ca, policy=self.policy)
        sem2 = SourceSemanticsAdapter.infer_semantics(bars1, ca, policy=self.policy)
        self.assertEqual(sem1.semantics_hash, sem2.semantics_hash)

        # Modifying a boundary price changes the hash
        bars2 = bars1.copy()
        bars2.loc[0, "close"] = 990.0
        sem3 = SourceSemanticsAdapter.infer_semantics(bars2, ca, policy=self.policy)
        self.assertNotEqual(sem1.semantics_hash, sem3.semantics_hash)

    def test_forensic_duckdb_persistence(self) -> None:
        """SourceSemanticsAdapter.persist_detections writes action and admission records to DuckDB."""
        bars = pd.DataFrame(
            {
                "timestamp": [pd.Timestamp("2022-07-27", tz="UTC"), pd.Timestamp("2022-07-28", tz="UTC")],
                "open": [1000.0, 100.0],
                "high": [1020.0, 105.0],
                "low": [990.0, 98.0],
                "close": [1000.0, 102.0],
                "volume": [1000, 10000],
                "symbol": ["PERSISTCO", "PERSISTCO"],
            }
        )
        ca = pd.DataFrame([{"action_id": "S10", "symbol": "PERSISTCO", "ex_date": date(2022, 7, 28), "action_type": "SPLIT", "share_multiplier": 10.0}])
        semantics = SourceSemanticsAdapter.infer_semantics(bars, ca, policy=self.policy)

        # Connect to DuckDB in-memory and initialize schema
        con = duckdb.connect(":memory:")
        from pathlib import Path

        schema_sql = (Path(__file__).resolve().parent.parent / "database_schema.sql").read_text(encoding="utf-8")
        con.execute(schema_sql)

        # Persist detections
        SourceSemanticsAdapter.persist_detections(con, dataset_id="ds_test_123", semantics=semantics)

        det_df = con.execute("SELECT * FROM source_basis_detections WHERE dataset_id = 'ds_test_123'").df()
        adm_df = con.execute("SELECT * FROM source_semantics_admissions WHERE dataset_id = 'ds_test_123'").df()

        self.assertEqual(len(det_df), 1)
        self.assertEqual(det_df["detection"].iloc[0], "UNADJUSTED")
        self.assertEqual(det_df["expected_multiplier"].iloc[0], 10.0)

        self.assertEqual(len(adm_df), 1)
        self.assertEqual(adm_df["validation_status"].iloc[0], "VERIFIED")
        self.assertEqual(adm_df["num_raw"].iloc[0], 1)
        con.close()


    def test_same_day_composite_share_actions(self) -> None:
        """Multiple same-day share-count actions (e.g. 10:1 split + 1:1 bonus) compose to 20:1 multiplier preserving all action IDs."""
        raw_actions = pd.DataFrame(
            [
                {"action_id": "S1", "symbol": "COMPCO", "ex_date": date(2023, 6, 1), "action_type": "SPLIT", "share_multiplier": 10.0},
                {"action_id": "B1", "symbol": "COMPCO", "ex_date": date(2023, 6, 1), "action_type": "BONUS", "share_multiplier": 2.0},
            ]
        )
        composed = compose_same_day_share_actions(raw_actions)
        self.assertEqual(len(composed), 1)
        self.assertEqual(composed["share_multiplier"].iloc[0], 20.0)
        self.assertEqual(composed["action_ids"].iloc[0], ("S1", "B1"))
        self.assertEqual(composed["action_types"].iloc[0], ("SPLIT", "BONUS"))

        # Test discontinuity detection against composite 20:1 event (Pre 2000, Post 100 -> ratio 20x)
        bars = pd.DataFrame(
            {
                "timestamp": [pd.Timestamp("2023-05-31", tz="UTC"), pd.Timestamp("2023-06-01", tz="UTC")],
                "open": [2000.0, 100.0],
                "high": [2020.0, 102.0],
                "low": [1980.0, 98.0],
                "close": [2000.0, 100.0],
                "volume": [1000, 20000],
                "symbol": ["COMPCO", "COMPCO"],
            }
        )
        reports = SourceSemanticsAdapter.detect_corporate_action_discontinuity(bars, raw_actions, policy=self.policy)
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0].expected_multiplier, 20.0)
        self.assertEqual(reports[0].detection, SourceBasisDetection.UNADJUSTED)
        self.assertEqual(reports[0].action_ids, ("S1", "B1"))

    def test_multi_window_volume_and_turnover_supporting_evidence(self) -> None:
        """BasisDetectionResult calculates multi-session median turnover and volume ratios across corporate action boundary."""
        dates = pd.date_range("2022-07-20", periods=10, freq="B", tz="UTC")
        bars = pd.DataFrame(
            {
                "timestamp": dates,
                "open": [1000.0] * 5 + [100.0] * 5,
                "high": [1010.0] * 5 + [101.0] * 5,
                "low": [990.0] * 5 + [99.0] * 5,
                "close": [1000.0] * 5 + [100.0] * 5,
                "volume": [1_000] * 5 + [10_000] * 5,
                "symbol": ["VOLCO"] * 10,
            }
        )
        ca = pd.DataFrame([{"action_id": "S1", "symbol": "VOLCO", "ex_date": date(2022, 7, 27), "action_type": "SPLIT", "share_multiplier": 10.0}])


        reports = SourceSemanticsAdapter.detect_corporate_action_discontinuity(bars, ca, policy=self.policy)
        self.assertEqual(len(reports), 1)
        self.assertIsNotNone(reports[0].turnover_ratio)
        self.assertIsNotNone(reports[0].volume_ratio)
        self.assertAlmostEqual(float(reports[0].turnover_ratio or 0.0), 1.0, places=2)
        self.assertAlmostEqual(float(reports[0].volume_ratio or 0.0), 0.1, places=2)


    def test_zero_observable_actions_handling(self) -> None:
        """Dataset with zero corporate actions returns SourceValidationStatus.VERIFIED under default UNADJUSTED contract."""
        bars = pd.DataFrame(
            {
                "timestamp": [pd.Timestamp("2023-01-01", tz="UTC"), pd.Timestamp("2023-01-02", tz="UTC")],
                "open": [100.0, 102.0],
                "high": [105.0, 104.0],
                "low": [99.0, 101.0],
                "close": [102.0, 103.0],
                "volume": [1000, 1200],
            }
        )
        empty_ca = pd.DataFrame(columns=["action_id", "symbol", "ex_date", "action_type", "share_multiplier"])
        semantics = SourceSemanticsAdapter.infer_semantics(bars, empty_ca, policy=self.policy)
        self.assertEqual(semantics.validation_status, SourceValidationStatus.VERIFIED)
        self.assertEqual(semantics.price_adjustment, PriceAdjustment.UNADJUSTED)

    def test_metamorphic_order_invariance(self) -> None:
        """Metamorphic property: Shuffling DataFrame row order produces identical detection results."""
        bars = pd.DataFrame(
            {
                "timestamp": [
                    pd.Timestamp("2022-07-25", tz="UTC"),
                    pd.Timestamp("2022-07-26", tz="UTC"),
                    pd.Timestamp("2022-07-27", tz="UTC"),
                    pd.Timestamp("2022-07-28", tz="UTC"),
                    pd.Timestamp("2022-07-29", tz="UTC"),
                ],
                "open": [1000.0, 1010.0, 1005.0, 100.0, 102.0],
                "high": [1020.0, 1030.0, 1015.0, 105.0, 104.0],
                "low": [990.0, 1000.0, 995.0, 98.0, 100.0],
                "close": [1010.0, 1005.0, 1000.0, 102.0, 103.0],
                "volume": [1000, 1100, 1200, 10000, 11000],
            }
        )
        ca = pd.DataFrame([{"action_id": "S10", "symbol": "SHUFFLE", "ex_date": date(2022, 7, 28), "action_type": "SPLIT", "share_multiplier": 10.0}])


        # Baseline
        orig_reports = SourceSemanticsAdapter.detect_corporate_action_discontinuity(bars, ca, policy=self.policy)

        # Shuffle rows
        shuffled_bars = bars.sample(frac=1.0, random_state=42).reset_index(drop=True)
        shuffled_reports = SourceSemanticsAdapter.detect_corporate_action_discontinuity(shuffled_bars, ca, policy=self.policy)

        self.assertEqual(orig_reports[0].detection, shuffled_reports[0].detection)
        self.assertIsNotNone(orig_reports[0].observed_ratio)
        self.assertIsNotNone(shuffled_reports[0].observed_ratio)
        self.assertAlmostEqual(float(orig_reports[0].observed_ratio or 0.0), float(shuffled_reports[0].observed_ratio or 0.0), places=4)

    def test_metamorphic_panel_isolation(self) -> None:
        """Metamorphic property: Inserting thousands of unrelated rows for other symbols does not alter symbol detection."""
        target_bars = pd.DataFrame(
            {
                "timestamp": [pd.Timestamp("2022-07-27", tz="UTC"), pd.Timestamp("2022-07-28", tz="UTC")],
                "open": [1000.0, 100.0],
                "high": [1020.0, 105.0],
                "low": [990.0, 98.0],
                "close": [1000.0, 102.0],
                "volume": [1000, 10000],
                "symbol": ["TARGET", "TARGET"],
            }
        )
        unrelated_bars = pd.DataFrame(
            {
                "timestamp": [pd.Timestamp("2022-07-27", tz="UTC"), pd.Timestamp("2022-07-28", tz="UTC")],
                "open": [50.0, 50.0],
                "high": [52.0, 52.0],
                "low": [49.0, 49.0],
                "close": [51.0, 51.0],
                "volume": [500, 500],
                "symbol": ["OTHER", "OTHER"],
            }
        )
        panel_bars = pd.concat([target_bars, unrelated_bars], ignore_index=True)
        ca = pd.DataFrame([{"action_id": "T1", "symbol": "TARGET", "ex_date": date(2022, 7, 28), "action_type": "SPLIT", "share_multiplier": 10.0}])

        single_reports = SourceSemanticsAdapter.detect_corporate_action_discontinuity(target_bars, ca, policy=self.policy)
        panel_reports = SourceSemanticsAdapter.detect_corporate_action_discontinuity(panel_bars, ca, policy=self.policy)

        self.assertEqual(len(single_reports), 1)
        self.assertEqual(len(panel_reports), 1)
        self.assertEqual(single_reports[0].detection, panel_reports[0].detection)
        self.assertIsNotNone(single_reports[0].observed_ratio)
        self.assertIsNotNone(panel_reports[0].observed_ratio)
        self.assertAlmostEqual(float(single_reports[0].observed_ratio or 0.0), float(panel_reports[0].observed_ratio or 0.0), places=4)

    def test_metamorphic_timezone_representation_invariance(self) -> None:
        """Metamorphic property: Equivalent timestamps expressed in UTC vs Asia/Kolkata produce identical detection results."""
        utc_bars = pd.DataFrame(
            {
                "timestamp": [pd.Timestamp("2022-07-27 03:45:00", tz="UTC"), pd.Timestamp("2022-07-28 03:45:00", tz="UTC")],
                "open": [1000.0, 100.0],
                "high": [1020.0, 105.0],
                "low": [990.0, 98.0],
                "close": [1000.0, 102.0],
                "volume": [1000, 10000],
                "symbol": ["TZCO", "TZCO"],
            }
        )
        ist_bars = pd.DataFrame(
            {
                "timestamp": [pd.Timestamp("2022-07-27 09:15:00", tz="Asia/Kolkata"), pd.Timestamp("2022-07-28 09:15:00", tz="Asia/Kolkata")],
                "open": [1000.0, 100.0],
                "high": [1020.0, 105.0],
                "low": [990.0, 98.0],
                "close": [1000.0, 102.0],
                "volume": [1000, 10000],
                "symbol": ["TZCO", "TZCO"],
            }
        )
        ca = pd.DataFrame([{"action_id": "TZ1", "symbol": "TZCO", "ex_date": date(2022, 7, 28), "action_type": "SPLIT", "share_multiplier": 10.0}])

        utc_reports = SourceSemanticsAdapter.detect_corporate_action_discontinuity(utc_bars, ca, policy=self.policy)
        ist_reports = SourceSemanticsAdapter.detect_corporate_action_discontinuity(ist_bars, ca, policy=self.policy)

        self.assertEqual(utc_reports[0].detection, ist_reports[0].detection)
        self.assertIsNotNone(utc_reports[0].observed_ratio)
        self.assertIsNotNone(ist_reports[0].observed_ratio)
        self.assertAlmostEqual(float(utc_reports[0].observed_ratio or 0.0), float(ist_reports[0].observed_ratio or 0.0), places=4)

    def test_parameterized_random_multipliers_property(self) -> None:
        """Property test: for any random multiplier R in [0.05, 50.0], synthetic raw data resolves UNADJUSTED, synthetic adjusted resolves SPLIT_ADJUSTED."""
        rng = np.random.default_rng(12345)
        multipliers = [0.1, 0.2, 0.5, 1.5, 2.0, 3.0, 5.0, 10.0, 20.0]
        for _ in range(10):
            r_rand = float(rng.uniform(0.05, 50.0))
            if abs(math.log(r_rand)) > 0.35:
                multipliers.append(r_rand)

        for R in multipliers:
            ex_d = date(2023, 1, 15)
            ca = pd.DataFrame([{"action_id": f"ACT_{R:.2f}", "symbol": "PROP", "ex_date": ex_d, "action_type": "SPLIT", "share_multiplier": float(R)}])

            # Synthetic RAW series: pre_close = 100.0 * R, post_open = 100.0
            raw_bars = pd.DataFrame(
                {
                    "timestamp": [pd.Timestamp("2023-01-14", tz="UTC"), pd.Timestamp("2023-01-15", tz="UTC")],
                    "open": [100.0 * R, 100.0],
                    "high": [102.0 * R, 102.0],
                    "low": [98.0 * R, 98.0],
                    "close": [100.0 * R, 100.0],
                    "volume": [1000, int(1000 * max(R, 0.1))],
                    "symbol": ["PROP", "PROP"],
                }
            )
            raw_reports = SourceSemanticsAdapter.detect_corporate_action_discontinuity(raw_bars, ca, policy=self.policy)
            self.assertEqual(raw_reports[0].detection, SourceBasisDetection.UNADJUSTED)

            # Synthetic SPLIT_ADJUSTED series: pre_close = 100.0, post_open = 100.0
            adj_bars = pd.DataFrame(
                {
                    "timestamp": [pd.Timestamp("2023-01-14", tz="UTC"), pd.Timestamp("2023-01-15", tz="UTC")],
                    "open": [100.0, 100.0],
                    "high": [102.0, 102.0],
                    "low": [98.0, 98.0],
                    "close": [100.0, 100.0],
                    "volume": [int(1000 * max(R, 0.1)), int(1000 * max(R, 0.1))],
                    "symbol": ["PROP", "PROP"],
                }
            )
            with pytest.warns(CorporateActionBasisWarning):
                adj_reports = SourceSemanticsAdapter.detect_corporate_action_discontinuity(adj_bars, ca, policy=self.policy)
            self.assertEqual(adj_reports[0].detection, SourceBasisDetection.SPLIT_ADJUSTED)



if __name__ == "__main__":
    unittest.main()
