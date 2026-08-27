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

__all__ = [
    "ExperimentManager",
    "ExperimentFamilySpec",
    "ExperimentSpec",
    "MassExperimentManager",
    "MassExperimentSpec",
    "ResearchCausalityError",
    "ResearchCertificationError",
    "ResearchIntegrityError",
    "ResearchLineageError",
    "ResearchTrial",
    "TrialStatus",
]
