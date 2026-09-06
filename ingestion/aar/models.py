"""Shared data shapes for the local AAR corpus."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Source manifests are curator-owned evidence records. Their version is kept
# independent from the derived, rebuildable corpus artifact format.
SOURCE_MANIFEST_SCHEMA_VERSION = "1.0"
CORPUS_SCHEMA_VERSION = "2.0"
# Compatibility alias for callers that import the old manifest constant.
SCHEMA_VERSION = SOURCE_MANIFEST_SCHEMA_VERSION
REQUIRED_SOURCE_CATEGORIES = (
    "tx_house_senate_committee",
    "kerr_hmp_2024",
    "kerr_eop",
    "nws_service_assessment",
    "usgs_post_flood_report",
    "fema_ipaws_records",
    "wimberley_2015_aar",
    "houston_2016_aar",
    "llano_2018_aar",
)
ANALYTIC_FIELDS = ("hazard", "phase", "tactic", "resources", "outcome", "lesson")


class ManifestError(ValueError):
    """Raised when manually curated corpus inputs are not safe to process."""


class ExtractionError(ValueError):
    """Raised when a PDF cannot supply page-bounded extractable text."""


class IndexError(ValueError):
    """Raised when an on-disk corpus index is inconsistent or incomplete."""


@dataclass(frozen=True)
class Annotation:
    page_start: int
    page_end: int
    values: dict[str, str | None]


@dataclass(frozen=True)
class SourceDocument:
    document_id: str
    source_category: str
    title: str
    publisher: str
    canonical_url: str
    local_pdf_path: Path
    sha256: str
    status: str
    verified_by: str
    verified_at: str
    verification_note: str
    annotations: tuple[Annotation, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SourceManifest:
    path: Path
    schema_version: str
    documents: tuple[SourceDocument, ...]


@dataclass(frozen=True)
class Citation:
    document_id: str
    title: str
    publisher: str
    canonical_url: str
    pdf_sha256: str
    page_start: int
    page_end: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "title": self.title,
            "publisher": self.publisher,
            "canonical_url": self.canonical_url,
            "pdf_sha256": self.pdf_sha256,
            "page_start": self.page_start,
            "page_end": self.page_end,
        }


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    hazard: str | None
    phase: str | None
    tactic: str | None
    resources: str | None
    outcome: str | None
    lesson: str | None
    text: str
    citation: Citation

    def to_dict(self) -> dict[str, Any]:
        data = {field: getattr(self, field) for field in ANALYTIC_FIELDS}
        data.update({"chunk_id": self.chunk_id, "text": self.text, "citation": self.citation.to_dict()})
        return data
