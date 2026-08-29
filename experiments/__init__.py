"""Reproducible experiment specifications and execution management."""

from experiments.manager import ExperimentManager
from experiments.models import ExperimentSpec, MassExperimentSpec
from experiments.mass import MassExperimentManager
from experiments.trials import (
    ExperimentFamilySpec,
    ResearchCausalityError,
    ResearchCertificationError,
    ResearchIntegrityError,
    ResearchLineageError,
    ResearchTrial,
    TrialStatus,
)

from experiments.robustness import (
    CostStressResult,
    ExecutionStressResult,
    NestedFoldEvidence,
    NestedWalkForwardSplitter,
    ParameterRobustnessCandidate,
    ParameterRobustnessSelector,
    RobustnessBundle,
    RobustnessEvaluator,
    RobustnessPolicy,
    StressScenarioEngine,
)

from experiments.statistical_tests import (
    BootstrapConfidenceIntervals,
    DSRResult,
    EvidenceStatus,
    MonteCarloRobustnessResult,
    PSRResult,
    compute_bootstrap_confidence_intervals,
    compute_dsr,
    compute_monte_carlo_robustness,
    compute_psr,
)

__all__ = [
    "BootstrapConfidenceIntervals",
    "CostStressResult",
    "DSRResult",
    "EvidenceStatus",
    "ExecutionStressResult",
    "ExperimentFamilySpec",
    "ExperimentManager",
    "ExperimentSpec",
    "MassExperimentManager",
    "MassExperimentSpec",
    "MonteCarloRobustnessResult",
    "NestedFoldEvidence",
    "NestedWalkForwardSplitter",
    "PSRResult",
    "ParameterRobustnessCandidate",
    "ParameterRobustnessSelector",
    "ResearchCausalityError",
    "ResearchCertificationError",
    "ResearchIntegrityError",
    "ResearchLineageError",
    "ResearchTrial",
    "RobustnessBundle",
    "RobustnessEvaluator",
    "RobustnessPolicy",
    "StressScenarioEngine",
    "TrialStatus",
    "compute_bootstrap_confidence_intervals",
    "compute_dsr",
    "compute_monte_carlo_robustness",

    "compute_psr",
]

