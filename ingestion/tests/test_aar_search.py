import hashlib
import json
import sys
from types import SimpleNamespace

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from aar.corpus import build_corpus
from aar.embeddings import load_embedder
from aar.models import IndexError, REQUIRED_SOURCE_CATEGORIES
from aar.search import search_index


class FakeEmbeddings(Embeddings):
    """Deterministic offline LangChain Embeddings fixture."""

    def _vector(self, text):
        return [1.0, 0.0] if "alpha" in text.lower() else [0.0, 1.0]

    def embed_documents(self, texts):
        return [self._vector(text) for text in texts]

    def embed_query(self, text):
        return self._vector(text)


def _manifest_path(tmp_path):
    documents = []
    for category in REQUIRED_SOURCE_CATEGORIES:
        pdf = tmp_path / f"{category}.pdf"
        pdf.write_bytes(category.encode())
        entry = {
            "document_id": f"synthetic-{category}", "source_category": category,
            "title": "Synthetic title", "publisher": "Synthetic publisher",
            "canonical_url": f"https://example.invalid/{category}", "local_pdf_path": str(pdf),
            "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(), "status": "verified",
            "verified_by": "fixture curator", "verified_at": "2026-01-01T00:00:00Z",
            "verification_note": "Synthetic metadata for offline test.",
        }
        if category == REQUIRED_SOURCE_CATEGORIES[0]:
            entry["annotations"] = [{"page_start": 1, "page_end": 1, "hazard": "synthetic", "phase": "response"}]
        documents.append(entry)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"schema_version": "1.0", "documents": documents}))
    return manifest


def _loader(path, *, mode, extract_images):
    text = "alpha synthetic response" if REQUIRED_SOURCE_CATEGORIES[0] in path else "bravo synthetic report"
    return SimpleNamespace(load=lambda: [Document(page_content=text, metadata={"page": 0})])


def _build(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    output = tmp_path / "library"
    built = build_corpus(
        _manifest_path(tmp_path), output, model_id="fake-local", embedder=FakeEmbeddings(),
        page_loader_factory=_loader,
    )
    return output, built


def test_build_and_search_are_offline_filterable_and_citation_preserving(tmp_path):
    output, built = _build(tmp_path)
    hits = search_index(output, "alpha", limit=3, embedder=FakeEmbeddings())
    filtered = search_index(output, "alpha", hazard="synthetic", phase="response", limit=3, embedder=FakeEmbeddings())

    assert {path.name for path in output.iterdir()} == {
        "index.faiss", "index-map.json", "chunks.jsonl", "corpus-manifest.json",
    }
    assert built["schema_version"] == "2.0"
    assert built["embedding_provider"] == "huggingface"
    assert built["embedding_model"] == "fake-local"
    assert built["vector_dimension"] == 2
    assert hits == sorted(hits, key=lambda hit: hit["score"], reverse=True)
    assert hits[0]["citation"]["page_start"] == hits[0]["citation"]["page_end"] == 1
    assert len(filtered) == 1 and filtered[0]["hazard"] == "synthetic"


@pytest.mark.parametrize("artifact", ["index-map.json", "chunks.jsonl"])
def test_search_rejects_missing_safe_artifacts(tmp_path, artifact):
    output, _ = _build(tmp_path)
    (output / artifact).unlink()

    with pytest.raises(IndexError, match="missing required artifacts"):
        search_index(output, "alpha", embedder=FakeEmbeddings())


def test_search_rejects_mismatched_map_and_dimension(tmp_path):
    output, _ = _build(tmp_path)
    row_map = json.loads((output / "index-map.json").read_text())
    row_map["0"] = "missing-chunk"
    (output / "index-map.json").write_text(json.dumps(row_map))
    with pytest.raises(IndexError, match="do not match canonical"):
        search_index(output, "alpha", embedder=FakeEmbeddings())

    output, _ = _build(tmp_path / "second")
    metadata = json.loads((output / "corpus-manifest.json").read_text())
    metadata["vector_dimension"] = 9
    (output / "corpus-manifest.json").write_text(json.dumps(metadata))
    with pytest.raises(IndexError, match="FAISS artifacts"):
        search_index(output, "alpha", embedder=FakeEmbeddings())


def test_search_rejects_v1_artifacts_with_rebuild_instruction(tmp_path):
    output = tmp_path / "old-library"
    output.mkdir()
    for name in ("index.faiss", "chunks.jsonl"):
        (output / name).write_text("{}")
    (output / "corpus-manifest.json").write_text(json.dumps({"schema_version": "1.0"}))

    with pytest.raises(IndexError, match=r"v1 raw-FAISS corpus.*python -m aar build"):
        search_index(output, "alpha", embedder=FakeEmbeddings())


def test_embedding_provider_factory_is_explicit_and_openai_needs_a_key(monkeypatch):
    calls = []

    class Local:
        def __init__(self, model_name):
            calls.append(("huggingface", model_name))

    monkeypatch.setitem(sys.modules, "langchain_huggingface", SimpleNamespace(HuggingFaceEmbeddings=Local))
    load_embedder("huggingface", "local-model")
    assert calls == [("huggingface", "local-model")]

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        load_embedder("openai", "text-embedding-3-small")

    class Remote:
        def __init__(self, model):
            calls.append(("openai", model))

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setitem(sys.modules, "langchain_openai", SimpleNamespace(OpenAIEmbeddings=Remote))
    load_embedder("openai", "text-embedding-3-small")
    assert calls[-1] == ("openai", "text-embedding-3-small")
