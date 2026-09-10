"""Small, serialisable data contracts for the NIFTY-200 PIT pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any


class Action(StrEnum):
    ADD = "ADD"
    DROP = "DROP"
    INITIAL_MEMBER = "INITIAL_MEMBER"


class Confidence(StrEnum):
    CERTIFIED = "CERTIFIED"
    PROVISIONAL = "PROVISIONAL"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    UNRESOLVED = "UNRESOLVED"


class EvidenceStatus(StrEnum):
    PASS = "PASS"
    BLOCKED = "BLOCKED"


class ReviewStatus(StrEnum):
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, slots=True)
class SourceRecord:
    source_url: str
    local_path: str
    source_sha256: str
    retrieved_at: str
    content_type: str = ""
    status: str = "downloaded"
    archive_url: str | None = None
    original_url: str | None = None
    document_date: str | None = None
    source_tier: str = "A1"
    http_status: int | None = None
    etag: str | None = None
    last_modified: str | None = None
    file_size: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Observation:
    """One source assertion; observations are never silently rewritten."""

    index_id: str = "NIFTY_200"
    source_index_name: str = "NIFTY 200"
    instrument_id: str | None = None
    isin: str | None = None
    symbol: str | None = None
    company_name: str | None = None
    announcement_date: date | None = None
    known_at: datetime | None = None
    known_at_basis: str | None = None
    effective_date: date | None = None
    action: Action | str | None = None
    reason: str | None = None
    source_url: str = ""
    archive_url: str | None = None
    source_sha256: str = ""
    source_page: int | None = None
    source_tier: str = "A1"
    extraction_method: str = "MANUAL"
    extractor_version: str = ""
    confidence: Confidence | str = Confidence.UNRESOLVED
    review_status: ReviewStatus | str = ReviewStatus.UNRESOLVED
    observation_id: str = ""
    supersedes_observation_id: str | None = None
    synthetic: bool = False
    raw_text: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("announcement_date", "effective_date", "known_at"):
            if value[key] is not None:
                value[key] = value[key].isoformat()
        for key in ("action", "confidence", "review_status"):
            if value[key] is not None and hasattr(value[key], "value"):
                value[key] = value[key].value
        return value


@dataclass(frozen=True, slots=True)
class CanonicalEvent:
    index_id: str
    instrument_id: str
    isin: str | None
    symbol: str
    company_name: str | None
    announcement_date: date
    known_at: datetime
    known_at_basis: str
    effective_date: date
    action: Action
    reason: str | None
    source_url: str
    archive_url: str | None
    source_sha256: str
    source_page: int | None
    source_tier: str
    extraction_method: str
    extractor_version: str
    confidence: Confidence
    review_status: ReviewStatus
    event_hash: str
    observation_id: str = ""
    synthetic: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        for key in ("announcement_date", "effective_date", "known_at"):
            value[key] = value[key].isoformat()
        value["action"] = self.action.value
        value["confidence"] = self.confidence.value
        value["review_status"] = self.review_status.value
        return value


@dataclass(frozen=True, slots=True)
class ConstituentInterval:
    interval_id: str
    index_id: str
    instrument_id: str
    symbol_at_entry: str
    isin_at_entry: str | None
    company_name: str | None
    effective_from: date
    effective_until: date | None
    known_from: date
    known_at: datetime
    reason: str | None
    entry_event_hash: str
    exit_event_hash: str | None
    confidence: Confidence
    dataset_version: str = "NIFTY200_PIT_V1"
    synthetic: bool = False

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["effective_from"] = self.effective_from.isoformat()
        value["effective_until"] = self.effective_until.isoformat() if self.effective_until else None
        value["known_from"] = self.known_from.isoformat()
        value["known_at"] = self.known_at.isoformat()
        value["confidence"] = self.confidence.value
        return value


@dataclass(frozen=True, slots=True)
class Conflict:
    conflict_id: str
    date: date | None
    severity: str
    conflict_type: str
    message: str
    observation_ids: list[str] = field(default_factory=list)
    source_urls: list[str] = field(default_factory=list)
    required_action: str = "MANUAL_REVIEW"

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["date"] = self.date.isoformat() if self.date else None
        return value


@dataclass(frozen=True, slots=True)
class ValidationReport:
    status: EvidenceStatus
    reasons: list[str]
    metrics: dict[str, Any]
    generated_at: str

    @property
    def passed(self) -> bool:
        return self.status == EvidenceStatus.PASS

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"status": self.status.value, "passed": self.passed}
