import hashlib
import json

import pytest
from langchain_core.documents import Document

from aar.corpus import build_corpus
from aar.manifest import validate_manifest
from aar.models import ExtractionError, ManifestError, REQUIRED_SOURCE_CATEGORIES
from aar.pdf import chunks_for_document, read_pdf_pages


def _source_manifest(tmp_path, *, annotations=None):
    documents = []
    for category in REQUIRED_SOURCE_CATEGORIES:
        path = tmp_path / f"{category}.pdf"
        path.write_bytes(category.encode())
        entry = {
            "document_id": f"synthetic-{category}", "source_category": category,
            "title": "Synthetic title", "publisher": "Synthetic publisher",
            "canonical_url": f"https://example.invalid/{category}", "local_pdf_path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "status": "verified",
            "verified_by": "fixture curator", "verified_at": "2026-01-01T00:00:00Z",
            "verification_note": "Synthetic metadata for offline test.",
        }
        if category == REQUIRED_SOURCE_CATEGORIES[0] and annotations is not None:
            entry["annotations"] = annotations
        documents.append(entry)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"schema_version": "1.0", "documents": documents}))
    return path


class MultiPageLoader:
    calls = []

    def __init__(self, path, *, mode, extract_images):
        self.path, self.mode, self.extract_images = path, mode, extract_images
        self.calls.append((path, mode, extract_images))

    def load(self):
        return [
            Document(page_content="page one alpha " * 100, metadata={"page": 0, "source": "untrusted"}),
            Document(page_content="page two bravo " * 100, metadata={"page": 1, "source": "untrusted"}),
        ]


def test_page_loader_recursive_splits_are_bounded_stable_and_annotated(tmp_path):
    manifest = validate_manifest(_source_manifest(tmp_path, annotations=[{
        "page_start": 2, "page_end": 2, "hazard": "synthetic hazard", "phase": "response",
    }]))
    document = manifest.documents[0]
    MultiPageLoader.calls.clear()

    pages = read_pdf_pages(document.local_pdf_path, MultiPageLoader)
    first = chunks_for_document(document, page_documents=pages)
    rebuilt = chunks_for_document(document, page_documents=pages)

    assert MultiPageLoader.calls == [(str(document.local_pdf_path), "page", False)]
    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in rebuilt]
    assert all(chunk.text for chunk in first)
    assert all(chunk.citation.page_start == chunk.citation.page_end for chunk in first)
    assert all("page two" not in chunk.text for chunk in first if chunk.citation.page_start == 1)
    assert all("page one" not in chunk.text for chunk in first if chunk.citation.page_start == 2)
    assert all(chunk.hazard is None for chunk in first if chunk.citation.page_start == 1)
    assert all(chunk.hazard == "synthetic hazard" and chunk.phase == "response"
               for chunk in first if chunk.citation.page_start == 2)


def test_conflicting_annotation_overlap_is_rejected(tmp_path):
    with pytest.raises(ManifestError, match="overlapping annotations conflict"):
        validate_manifest(_source_manifest(tmp_path, annotations=[
            {"page_start": 1, "page_end": 2, "hazard": "one"},
            {"page_start": 2, "page_end": 3, "hazard": "two"},
        ]))


def test_non_extractable_pdf_fails_with_human_follow_up(tmp_path):
    document = validate_manifest(_source_manifest(tmp_path)).documents[0]
    with pytest.raises(ExtractionError, match="human-prepared text/OCR follow-up"):
        chunks_for_document(document, page_documents=[
            Document(page_content="", metadata={"page": 0}),
            Document(page_content="   ", metadata={"page": 1}),
        ])


def test_invalid_manifest_never_constructs_a_pdf_loader_or_artifacts(tmp_path):
    manifest = _source_manifest(tmp_path)
    raw = json.loads(manifest.read_text())
    raw["documents"] = raw["documents"][:1]
    manifest.write_text(json.dumps(raw))
    output = tmp_path / "library"
    calls = []

    def loader(*args, **kwargs):
        calls.append((args, kwargs))
        return MultiPageLoader(*args, **kwargs)

    with pytest.raises(ManifestError, match="missing verified source category"):
        build_corpus(manifest, output, page_loader_factory=loader)

    assert calls == []
    assert not output.exists()
