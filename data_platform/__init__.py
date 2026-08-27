"""Provider-neutral market data contracts and persistence services."""

from data_platform.adjustments import PriceAdjustmentEngine, TotalReturnEngine
from data_platform.contracts import BarRequest, DataProvenance, DatasetSnapshot, Instrument, PriceAdjustment
from data_platform.dq_derived import DerivedBarDQCertifier, DerivedDQReport
from data_platform.provider_verification import (
    CrossProviderVerifier,
    ProviderDataVerificationError,
    ProviderDataVerificationWarning,
    ProviderReconciliationResult,
    ProviderVerificationReport,
    VerificationSeverity,
)
from data_platform.providers import AngelOneProvider, DuckDBCacheProvider, MarketDataProvider, OpenBBHttpProvider, ProviderRegistry
from data_platform.resampling import (
    DerivedDatasetCertification,
    ResampledBar,
    SessionBarResampler,
    compute_derived_content_hash,
)
from data_platform.service import DataPlatform
from data_platform.source_semantics import (
    AmbiguousSourceBasisError,
    BasisDetectionResult,
    BasisEvidenceCode,
    CorporateActionBasisWarning,
    CorporateActionEvidenceInsufficientError,
    InvalidCorporateActionError,
    SourceBarSemantics,
    SourceBasisDetection,
    SourceSemanticsAdapter,
    SourceSemanticsPolicy,
    SourceValidationStatus,
    UnsupportedAdjustmentConversion,
    VolumeAdjustment,
    compose_same_day_corporate_actions,
    compose_same_day_share_actions,
)

__all__ = [
    # Phase 2.2 — Multi-timeframe resampling
    "SessionBarResampler",
    "ResampledBar",
    "DerivedDatasetCertification",
    "compute_derived_content_hash",
    # Phase 2.2 — DQ certification
    "DerivedBarDQCertifier",
    "DerivedDQReport",
    # Phase 2.2 — Cross-provider verification
    "CrossProviderVerifier",
    "ProviderVerificationReport",
    "ProviderReconciliationResult",
    "VerificationSeverity",
    "ProviderDataVerificationWarning",
    "ProviderDataVerificationError",
    # Existing
    "AmbiguousSourceBasisError",
    "AngelOneProvider",
    "BarRequest",
    "BasisDetectionResult",
    "BasisEvidenceCode",
    "CorporateActionBasisWarning",
    "CorporateActionEvidenceInsufficientError",
    "DataPlatform",
    "DataProvenance",
    "DatasetSnapshot",
    "DuckDBCacheProvider",
    "Instrument",
    "InvalidCorporateActionError",
    "MarketDataProvider",
    "OpenBBHttpProvider",
    "PriceAdjustment",
    "PriceAdjustmentEngine",
    "ProviderRegistry",
    "SourceBarSemantics",
    "SourceBasisDetection",
    "SourceSemanticsAdapter",
    "SourceSemanticsPolicy",
    "SourceValidationStatus",
    "TotalReturnEngine",
    "UnsupportedAdjustmentConversion",
    "VolumeAdjustment",
    "compose_same_day_corporate_actions",
    "compose_same_day_share_actions",
]

