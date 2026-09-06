"""Strict validation for curator-supplied AAR source manifests."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .models import (
    ANALYTIC_FIELDS,
    REQUIRED_SOURCE_CATEGORIES,
    SOURCE_MANIFEST_SCHEMA_VERSION,
    Annotation,
    ManifestError,
    SourceDocument,
    SourceManifest,
)

_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
# A chunk ID is composed as `aar:<document_id>.p<page>.c<sequence>.<digest16>` and must
# satisfy the shared feature_ref grammar (common.schema.json#/$defs/aar_ref), whose
# source_id half allows [A-Za-z0-9_.-] and at most 64 characters. The suffix costs at
# most len(".p9999.c999.") + 16 == 28 for a 9999-page document with 999 chunks on a
# page, leaving 36 for the document_id. `pdf.py` re-checks the composed ID, so this
# bound is a clear early error rather than the thing the invariant rests on.
_MAX_SOURCE_ID = 64
_MAX_CHUNK_SUFFIX = len(".p9999.c999.") + 16
_MAX_DOCUMENT_ID = _MAX_SOURCE_ID - _MAX_CHUNK_SUFFIX  # 36
_DOCUMENT_ID = re.compile(rf"^[A-Za-z0-9][A-Za-z0-9_.-]{{0,{_MAX_DOCUMENT_ID - 1}}}$")
_REQUIRED_DOCUMENT_FIELDS = (
    "document_id", "source_category", "title", "publisher", "canonical_url",
    "local_pdf_path", "sha256", "verified_by", "verified_at", "verification_note",
)


def _error_list(errors: list[str]) -> ManifestError:
    return ManifestError("Manifest validation failed:\n- " + "\n- ".join(errors))


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _valid_timestamp(value: Any) -> bool:
    if not _nonempty(value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ManifestError(f"Manifest file does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"Manifest is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError("Manifest root must be a JSON object")
    return data


def _parse_annotations(raw: Any, document_id: str, errors: list[str]) -> tuple[Annotation, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        errors.append(f"document {document_id}: annotations must be a list")
        return ()
    annotations: list[Annotation] = []
    for position, item in enumerate(raw, start=1):
        label = f"document {document_id} annotation {position}"
        if not isinstance(item, dict):
            errors.append(f"{label}: must be an object")
            continue
        start, end = item.get("page_start"), item.get("page_end")
        if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
            errors.append(f"{label}: page_start/page_end must be positive ordered integers")
            continue
        unknown = set(item) - {"page_start", "page_end", *ANALYTIC_FIELDS}
        if unknown:
            errors.append(f"{label}: unknown fields {', '.join(sorted(unknown))}")
        values: dict[str, str | None] = {}
        for field in ANALYTIC_FIELDS:
            value = item.get(field)
            if value is not None and not _nonempty(value):
                errors.append(f"{label}: {field} must be a non-empty string or null")
            values[field] = value.strip() if isinstance(value, str) else None
        annotations.append(Annotation(start, end, values))
    for left_index, left in enumerate(annotations):
        for right in annotations[left_index + 1:]:
            if max(left.page_start, right.page_start) > min(left.page_end, right.page_end):
                continue
            for field in ANALYTIC_FIELDS:
                if left.values[field] and right.values[field] and left.values[field] != right.values[field]:
                    errors.append(
                        f"document {document_id}: overlapping annotations conflict for {field}"
                    )
    return tuple(annotations)


def _absolute_pdf_path(value: str, manifest_path: Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (manifest_path.parent / path).resolve()


def _is_verified(entry: dict[str, Any]) -> bool:
    # ``status`` is the documented field. Supporting the boolean spelling makes
    # hand-authored manifests no less strict while retaining the same gate.
    return entry.get("status") == "verified" or entry.get("verified") is True


def validate_manifest(manifest_path: str | Path, *, require_complete: bool = True) -> SourceManifest:
    """Validate a manually curated manifest and every referenced local file.

    All detected errors are reported together so a curator can fix an incomplete
    source set in one pass. No PDF is eligible for processing until this succeeds.
    """
    path = Path(manifest_path).resolve()
    data = _load_json(path)
    errors: list[str] = []
    schema_version = data.get("schema_version")
    if schema_version != SOURCE_MANIFEST_SCHEMA_VERSION:
        errors.append(f"schema_version must be {SOURCE_MANIFEST_SCHEMA_VERSION!r}")
    entries = data.get("documents")
    if not isinstance(entries, list):
        raise _error_list([*errors, "documents must be a list"])

    seen_ids: set[str] = set()
    verified_categories: set[str] = set()
    documents: list[SourceDocument] = []
    for position, entry in enumerate(entries, start=1):
        label = f"document entry {position}"
        if not isinstance(entry, dict):
            errors.append(f"{label}: must be an object")
            continue
        document_id = entry.get("document_id")
        if not _nonempty(document_id):
            errors.append(f"{label}: missing document_id")
            document_id = f"<entry {position}>"
        elif not _DOCUMENT_ID.fullmatch(str(document_id)):
            errors.append(
                f"document {document_id}: document_id must match {_DOCUMENT_ID.pattern} "
                "so its composed aar: citation ID stays a valid feature reference"
            )
        elif document_id in seen_ids:
            errors.append(f"duplicate document_id: {document_id}")
        seen_ids.add(document_id)
        for field in _REQUIRED_DOCUMENT_FIELDS:
            if not _nonempty(entry.get(field)):
                errors.append(f"document {document_id}: missing {field}")
        category = entry.get("source_category")
        if category not in REQUIRED_SOURCE_CATEGORIES:
            errors.append(f"document {document_id}: invalid source_category {category!r}")
        if not _is_verified(entry):
            errors.append(f"document {document_id}: status must be 'verified'")
        if not _valid_timestamp(entry.get("verified_at")):
            errors.append(f"document {document_id}: verified_at must be ISO-8601")
        canonical_url = entry.get("canonical_url", "")
        parsed_url = urlparse(canonical_url) if isinstance(canonical_url, str) else None
        if not parsed_url or parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            errors.append(f"document {document_id}: canonical_url must be an http(s) URL")
        checksum = entry.get("sha256", "")
        if not isinstance(checksum, str) or not _SHA256.fullmatch(checksum):
            errors.append(f"document {document_id}: sha256 must be a 64-character hexadecimal checksum")
        local_path_value = entry.get("local_pdf_path", "")
        pdf_path = _absolute_pdf_path(local_path_value, path) if _nonempty(local_path_value) else path.parent / "<missing>"
        if not pdf_path.is_file():
            errors.append(f"document {document_id}: local PDF file is missing: {pdf_path}")
        elif _SHA256.fullmatch(str(checksum)):
            actual_checksum = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
            if actual_checksum.lower() != checksum.lower():
                errors.append(f"document {document_id}: SHA-256 checksum mismatch")
        annotations = _parse_annotations(entry.get("annotations"), document_id, errors)
        if category in REQUIRED_SOURCE_CATEGORIES and _is_verified(entry):
            verified_categories.add(category)
        if all(_nonempty(entry.get(field)) for field in _REQUIRED_DOCUMENT_FIELDS):
            documents.append(SourceDocument(
                document_id=document_id,
                source_category=category,
                title=entry["title"].strip(),
                publisher=entry["publisher"].strip(),
                canonical_url=canonical_url.strip(),
                local_pdf_path=pdf_path,
                sha256=checksum.lower() if isinstance(checksum, str) else "",
                status="verified" if _is_verified(entry) else str(entry.get("status", "")),
                verified_by=entry["verified_by"].strip(),
                verified_at=entry["verified_at"].strip(),
                verification_note=entry["verification_note"].strip(),
                annotations=annotations,
            ))
    if require_complete:
        for category in REQUIRED_SOURCE_CATEGORIES:
            if category not in verified_categories:
                errors.append(f"missing verified source category: {category}")
    if errors:
        raise _error_list(errors)
    return SourceManifest(path=path, schema_version=schema_version, documents=tuple(documents))
