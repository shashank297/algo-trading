"""Unit tests verifying pre-strategy-factory foundation hardening."""

from datetime import datetime, timezone, timedelta
import pytest
import pandas as pd

from data_platform.universe import (
    PointInTimeConstituent,
    PointInTimeUniverseManager,
    PITCertificationStatus,
    PITCertificationService,
)
from data_platform.lineage import (
    DatasetLineageManifest,
    DatasetLineageVerifier,
)
from risk.factory import load_canonical_risk_policy
from risk.models import CanonicalRiskPolicy
from ai_research.workflow import ResearchWorkflow, NonExecutableResearchContext
from trading_stack.approval import (
    ExternalApprovalEvidence,
    ApprovalAuthorityType,
    ApprovalStatus,
    ExternalApprovalVerifier,
)
from trading_stack.foundation_certification import (
    FoundationCertificationRegistry,
    build_foundation_certification,
    verify_foundation_artifact_integrity,
)
from trading_stack.promotion import PromotionEngine
from storage.duckdb_manager import DuckDBManager


# ---------------------------------------------------------------------------
# 1. Workstream 1: Authoritative PIT Data Contract & Identity
# ---------------------------------------------------------------------------

def test_pit_constituent_rejects_symbol_derived_fallback_when_authoritative():
    # Non-authoritative allows fallback
    c_non_auth = PointInTimeConstituent(
        universe_name="NIFTY200",
        symbol="TCS",
        effective_from="2020-01-01",
        effective_until="2021-01-01",
        is_authoritative=False,
    )
    assert c_non_auth.instrument_id == "NSE:TCS:EQ"

    # Authoritative strictly rejects fallback
    with pytest.raises(ValueError, match="Authoritative PIT constituent requires an explicit durable instrument identity"):
        PointInTimeConstituent(
            universe_name="NIFTY200",
            symbol="TCS",
            effective_from="2020-01-01",
            effective_until="2021-01-01",
            is_authoritative=True,
        )

    # Authoritative with explicit durable instrument_id (e.g. ISIN or security ID) succeeds
    c_auth = PointInTimeConstituent(
        universe_name="NIFTY200",
        symbol="TCS",
        instrument_id="ISIN:INE467B01029",
        effective_from="2020-01-01",
        effective_until="2021-01-01",
        is_authoritative=True,
    )
    assert c_auth.instrument_id == "ISIN:INE467B01029"


def test_bulk_insert_constituents_preserves_known_at(tmp_path):
    db_path = str(tmp_path / "pit_test.duckdb")
    db = DuckDBManager(db_path)

    df = pd.DataFrame([
        {
            "universe_name": "NIFTY200",
            "symbol": "INFY",
            "instrument_id": "ISIN:INE009A01021",
            "effective_from": "2020-01-01T00:00:00Z",
            "effective_until": "2020-12-31T23:59:59Z",
            "known_from": "2019-12-25T00:00:00Z",
            "known_at": "2019-12-25T12:00:00Z",
        }
    ])
    inserted = PointInTimeUniverseManager.bulk_insert_constituents(
        db.conn, df, require_authoritative_identity=True
    )
    assert inserted == 1

    row = db.conn.execute(
        "SELECT instrument_id, known_at FROM index_constituent_knowledge WHERE instrument_id = 'ISIN:INE009A01021'"
    ).fetchone()
    assert row is not None
    assert row[0] == "ISIN:INE009A01021"
    assert row[1] is not None


def test_pit_certification_service_reports_blocked_on_gap(tmp_path):
    from datetime import date
    db_path = str(tmp_path / "pit_cert.duckdb")
    db = DuckDBManager(db_path)
    cert = PITCertificationService(db.conn).certify_universe(
        universe_name="NIFTY200",
        start_date=date(2020, 1, 1),
        end_date=date(2024, 12, 31),
        min_required_constituents=50,
    )
    assert cert.status == PITCertificationStatus.BLOCKED_EXTERNAL_DATA
    assert any("unpopulated or insufficient" in r for r in cert.reasons)



def _sample_manifest(**overrides) -> DatasetLineageManifest:
    base = {
        "manifest_id": "man_001",
        "dataset_id": "NIFTY200_1D",
        "dataset_version": "1.0.0",
        "provider": "NSE",
        "source_reference": "https://archives.nseindia.com/content/historical/EQUITIES",
        "retrieved_at": "2026-09-06T00:00:00Z",
        "coverage_start": "2020-01-01T00:00:00Z",
        "coverage_end": "2024-12-31T23:59:59Z",
        "frequency": "1D",
        "timezone": "Asia/Kolkata",
        "calendar": "NSE",
        "universe": "NIFTY200",
        "raw_artifact_hash": "a" * 64,
        "canonical_artifact_hash": "b" * 64,
        "transformation_version": "v1.0",
        "transformation_hash": "c" * 64,
        "corporate_action_policy": "SPLIT_AND_BONUS_ADJUSTED",
        "missing_data_policy": "FAIL_CLOSED",
        "status": "CERTIFIED",
    }
    base.update(overrides)
    return DatasetLineageManifest(**base)


def test_lineage_manifest_validation():
    # Valid manifest passes validation
    manifest = _sample_manifest()
    DatasetLineageVerifier.validate_manifest(manifest)
    assert len(manifest.compute_hash()) == 64

    # Malformed raw_artifact_hash raises ValueError
    bad_hash_manifest = _sample_manifest(raw_artifact_hash="short_hash")
    with pytest.raises(ValueError, match="is not a valid 64-character SHA-256 hex string"):
        DatasetLineageVerifier.validate_manifest(bad_hash_manifest)

    # Missing mandatory field raises ValueError
    bad_source_manifest = _sample_manifest(source_reference="")
    with pytest.raises(ValueError, match="Incomplete dataset lineage manifest: missing source_reference"):
        DatasetLineageVerifier.validate_manifest(bad_source_manifest)

    # Inverted coverage dates raise ValueError
    inverted_dates_manifest = _sample_manifest(coverage_start="2025-01-01", coverage_end="2020-01-01")
    with pytest.raises(ValueError, match="Invalid coverage range in lineage manifest"):
        DatasetLineageVerifier.validate_manifest(inverted_dates_manifest)


def test_lineage_verifier_duckdb_roundtrip(tmp_path):
    db_path = str(tmp_path / "lineage.duckdb")
    db = DuckDBManager(db_path)
    manifest = _sample_manifest(manifest_id="man_roundtrip")
    DatasetLineageVerifier.record_manifest(db.conn, manifest)

    row = db.conn.execute(
        "SELECT manifest_id, dataset_id, raw_artifact_hash, status FROM dataset_lineage_manifests WHERE manifest_id = 'man_roundtrip'"
    ).fetchone()
    assert row is not None
    assert row[0] == "man_roundtrip"
    assert row[1] == "NIFTY200_1D"
    assert row[2] == "a" * 64
    assert row[3] == "CERTIFIED"


# ---------------------------------------------------------------------------
# 3. Workstream 3 & 4: Canonical Risk Policy & Implicit Fallback Removal
# ---------------------------------------------------------------------------

def test_canonical_risk_policy_load_and_validation():
    policy = load_canonical_risk_policy()
    assert isinstance(policy, CanonicalRiskPolicy)
    assert policy.allow_permissive_defaults is False
    assert policy.max_position_pct == 0.05
    assert policy.max_gross_exposure_pct == 0.20
    assert policy.max_daily_loss_pct == 0.01
    assert policy.max_drawdown_pct == 0.05
    assert policy.max_sector_exposure_pct == 0.20
    assert policy.max_open_positions == 20
    assert len(policy.policy_hash) == 64


def test_research_workflow_rejects_missing_authoritative_risk(tmp_path):
    db = DuckDBManager(str(tmp_path / "research_test.duckdb"))
    workflow = ResearchWorkflow(db=db, llm=None, risk_engine=None)
    assert isinstance(workflow.context, NonExecutableResearchContext)
    assert workflow.context.is_executable is False
    assert workflow.context.reason == "NON_EXECUTABLE_RESEARCH_CONTEXT_MISSING_AUTHORITATIVE_RISK"


# ---------------------------------------------------------------------------
# 4. Workstream 5: Risk Override Governance
# ---------------------------------------------------------------------------

def test_promotion_engine_rejects_override_and_diagnostic_runs(tmp_path):
    db_path = str(tmp_path / "promo.duckdb")
    db = DuckDBManager(db_path)
    db.conn.execute("""
        INSERT INTO strategy_runs (
            run_id, strategy_name, asset_class, symbol, timeframe, mode,
            parameters_json, data_hash, status, started_at, notes, frame_certification_id
        ) VALUES (
            'run_diag_1', 'momentum', 'EQUITY', 'RELIANCE', '1d', 'NON_EXECUTABLE_DIAGNOSTIC',
            '{}', 'h1', 'COMPLETED', CURRENT_TIMESTAMP, '{}', 'f1'
        )
    """)
    promo = PromotionEngine(db)
    result = promo.review("run_diag_1")
    assert result["stage"] == "NOT_PROMOTABLE"
    assert result["decision"] == "REJECT"
    assert "RUN_USES_RISK_OVERRIDE_OR_DIAGNOSTIC_MODE_NOT_PROMOTABLE" in result["reasons"]


# ---------------------------------------------------------------------------
# 5. Workstream 6: External Human / Board Approval Contract
# ---------------------------------------------------------------------------

def test_external_approval_verifier_fails_closed():
    now = datetime.now(timezone.utc)
    evidence = ExternalApprovalEvidence(
        approval_id="app_001",
        approval_type="PAPER_TRADING_AUTHORIZATION",
        subject_type="STRATEGY_RUN",
        run_id="run_100",
        strategy_name="trend_following",
        requested_stage="PAPER_CANDIDATE",
        approved_stage="PAPER_CANDIDATE",
        approved_by_type=ApprovalAuthorityType.HUMAN,
        approved_by_identifier="ChiefRiskOfficer_JaneDoe",
        approved_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=30),
        scope="PAPER_SESSION",
        status=ApprovalStatus.ACTIVE,
        foundation_certification_id="cert_fab25",
        risk_policy_id="canonical-risk-policy-v1",
        risk_policy_hash="d" * 64,
        code_sha="e" * 40,
        evidence_hash="f" * 64,
    )

    # Genuine approval passes verification
    ExternalApprovalVerifier.verify_approval(
        evidence,
        expected_run_id="run_100",
        expected_strategy_name="trend_following",
        expected_stage="PAPER_CANDIDATE",
        expected_foundation_cert_id="cert_fab25",
        expected_risk_policy_hash="d" * 64,
    )

    # 1. AI identifier is rejected
    ai_evidence = ExternalApprovalEvidence(
        **{**evidence.to_dict(), "approved_by_identifier": "auto-agent-model"}
    )
    with pytest.raises(PermissionError, match="Approval cannot be issued by an automated agent"):
        ExternalApprovalVerifier.verify_approval(
            ai_evidence,
            expected_run_id="run_100",
            expected_strategy_name="trend_following",
        )

    # 2. Expired approval is rejected
    expired_evidence = ExternalApprovalEvidence(
        **{**evidence.to_dict(), "expires_at": now - timedelta(hours=1)}
    )
    with pytest.raises(PermissionError, match="Approval expired"):
        ExternalApprovalVerifier.verify_approval(
            expired_evidence,
            expected_run_id="run_100",
            expected_strategy_name="trend_following",
        )

    # 3. Mismatched run_id is rejected
    with pytest.raises(PermissionError, match="Approval run_id 'run_100' does not match expected 'run_999'"):
        ExternalApprovalVerifier.verify_approval(
            evidence,
            expected_run_id="run_999",
            expected_strategy_name="trend_following",
        )


def test_promotion_engine_assert_paper_authorized_requires_external_evidence(tmp_path):
    db_path = str(tmp_path / "promo_auth.duckdb")
    db = DuckDBManager(db_path)
    promo = PromotionEngine(db)

    # Setup promotion review with PASS and human_approved=True
    db.conn.execute("""
        INSERT INTO promotion_reviews (
            review_id, strategy_name, run_id, stage, decision, score, reasons_json, human_approved, reviewed_at
        ) VALUES (
            'rev_ok', 'trend_following', 'run_candidate', 'PAPER_CANDIDATE', 'PASS', 1.0, '[]', true, CURRENT_TIMESTAMP
        )
    """)

    # Fails closed because external approval evidence table has no record
    with pytest.raises(PermissionError, match="lacks authoritative external human/board approval evidence"):
        promo.assert_paper_authorized("run_candidate", "trend_following")

    # Now add valid external approval evidence
    now = datetime.now(timezone.utc)
    evidence = ExternalApprovalEvidence(
        approval_id="app_auth_ok",
        approval_type="PAPER_TRADING_AUTHORIZATION",
        subject_type="STRATEGY_RUN",
        run_id="run_candidate",
        strategy_name="trend_following",
        requested_stage="PAPER_CANDIDATE",
        approved_stage="PAPER_CANDIDATE",
        approved_by_type=ApprovalAuthorityType.BOARD,
        approved_by_identifier="InvestmentCommittee_Chair",
        approved_at=now - timedelta(hours=2),
        expires_at=now + timedelta(days=10),
        scope="PAPER_SESSION",
        status=ApprovalStatus.ACTIVE,
        foundation_certification_id="cert_v1",
        risk_policy_id="risk_v1",
        risk_policy_hash="h" * 64,
        code_sha="c" * 40,
        evidence_hash="e" * 64,
    )
    ExternalApprovalVerifier.record_approval(db.conn, evidence)

    # Now passes
    promo.assert_paper_authorized("run_candidate", "trend_following")


# ---------------------------------------------------------------------------
# 6. Workstream 7, 8, 10: Foundation Certification Registry & Integrity
# ---------------------------------------------------------------------------

def test_foundation_certification_registry_and_tamper_detection(tmp_path):
    gates = {
        name: {"status": "PASS", "reason": "verified"}
        for name in (
            "PIT", "LINEAGE", "TRANSACTION_COSTS", "ROBUSTNESS", "KPI",
            "RISK_CONFIGURATION", "INDEPENDENT_QA_RISK",
        )
    }
    artifact = build_foundation_certification(gates=gates, generated_at="2026-09-06T00:00:00Z")
    assert artifact["final_verdict"] == "PASS"
    assert artifact["derived_flags"]["CAN_DEPLOY_REAL_CAPITAL"] is False
    assert artifact["derived_flags"]["CAN_MARK_LIVE_CANDIDATE"] is False
    assert artifact["derived_flags"]["CAN_RUN_REAL_TIME_PAPER"] is True

    # Tampering with payload without updating sha256 raises PermissionError
    tampered = dict(artifact)
    tampered["final_verdict"] = "FAIL"
    with pytest.raises(PermissionError, match="Foundation certification checksum mismatch"):
        verify_foundation_artifact_integrity(tampered)

    # Register in DuckDB
    db_path = str(tmp_path / "cert_reg.duckdb")
    db = DuckDBManager(db_path)
    cid = FoundationCertificationRegistry.register_artifact(db.conn, artifact)
    assert cid.startswith("cert_")

    active = FoundationCertificationRegistry.get_active_certification(db.conn)
    assert active is not None
    assert active["artifact_sha256"] == artifact["artifact_sha256"]
