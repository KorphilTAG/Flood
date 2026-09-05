import hashlib
import json

import pytest

from aar.manifest import validate_manifest
from aar.models import CORPUS_SCHEMA_VERSION, REQUIRED_SOURCE_CATEGORIES, ManifestError


def _entry(category, path):
    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
    return {
        "document_id": f"synthetic-{category}",
        "source_category": category,
        "title": "Synthetic document",
        "publisher": "Synthetic publisher",
        "canonical_url": f"https://example.invalid/{category}",
        "local_pdf_path": str(path),
        "sha256": checksum,
        "status": "verified",
        "verified_by": "synthetic curator",
        "verified_at": "2026-01-01T00:00:00Z",
        "verification_note": "Synthetic fixture manually marked verified for unit testing.",
    }


def _complete_manifest(tmp_path):
    documents = []
    for category in REQUIRED_SOURCE_CATEGORIES:
        path = tmp_path / f"{category}.pdf"
        path.write_bytes(f"synthetic {category}".encode())
        documents.append(_entry(category, path))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": "1.0", "documents": documents}))
    return manifest, documents


def test_complete_synthetic_manifest_is_accepted(tmp_path):
    manifest, documents = _complete_manifest(tmp_path)

    validated = validate_manifest(manifest)

    assert [document.document_id for document in validated.documents] == [entry["document_id"] for entry in documents]


def test_validation_reports_each_missing_category_and_bad_provenance(tmp_path):
    manifest, documents = _complete_manifest(tmp_path)
    documents = documents[:1]
    documents[0]["status"] = "pending"
    documents[0]["sha256"] = "not-a-checksum"
    documents.append({**documents[0], "document_id": documents[0]["document_id"]})
    manifest.write_text(json.dumps({"schema_version": "1.0", "documents": documents}))

    with pytest.raises(ManifestError) as raised:
        validate_manifest(manifest)

    message = str(raised.value)
    assert "duplicate document_id" in message
    assert "status must be 'verified'" in message
    assert "64-character hexadecimal" in message
    for category in REQUIRED_SOURCE_CATEGORIES[1:]:
        assert f"missing verified source category: {category}" in message


def test_checksum_mismatch_and_missing_file_are_rejected(tmp_path):
    manifest, documents = _complete_manifest(tmp_path)
    documents[0]["sha256"] = "a" * 64
    documents[1]["local_pdf_path"] = str(tmp_path / "missing.pdf")
    manifest.write_text(json.dumps({"schema_version": "1.0", "documents": documents}))

    with pytest.raises(ManifestError) as raised:
        validate_manifest(manifest)

    assert "checksum mismatch" in str(raised.value)
    assert "local PDF file is missing" in str(raised.value)


def test_source_changed_after_verification_fails_checksum_gate(tmp_path):
    manifest, documents = _complete_manifest(tmp_path)
    validate_manifest(manifest)
    source = tmp_path / f"{REQUIRED_SOURCE_CATEGORIES[0]}.pdf"
    source.write_bytes(b"changed synthetic source")

    with pytest.raises(ManifestError, match="checksum mismatch"):
        validate_manifest(manifest)


def test_source_manifest_v1_remains_valid_when_corpus_schema_is_v2(tmp_path):
    manifest, _ = _complete_manifest(tmp_path)

    validated = validate_manifest(manifest)

    assert validated.schema_version == "1.0"
    assert CORPUS_SCHEMA_VERSION == "2.0"
