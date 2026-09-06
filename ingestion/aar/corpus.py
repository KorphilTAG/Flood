"""Build portable LangChain FAISS artifacts from validated source documents."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from langchain_core.documents import Document

from .embeddings import DEFAULT_MODEL, DEFAULT_PROVIDER, EmbeddingProvider, load_embedder
from .manifest import validate_manifest
from .models import ANALYTIC_FIELDS, CORPUS_SCHEMA_VERSION, Chunk
from .pdf import chunks_for_document


def chunk_document(chunk: Chunk) -> Document:
    """Build a controlled LangChain document from the canonical chunk record."""
    metadata = {field: getattr(chunk, field) for field in ANALYTIC_FIELDS}
    metadata.update({
        "chunk_id": chunk.chunk_id,
        "citation_document_id": chunk.citation.document_id,
        "citation_page_start": chunk.citation.page_start,
        "citation_page_end": chunk.citation.page_end,
    })
    return Document(page_content=chunk.text, metadata=metadata)


def _write_jsonl(path: Path, chunks: list[Chunk]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for chunk in chunks:
            handle.write(json.dumps(chunk.to_dict(), sort_keys=True) + "\n")


def _langchain_dependencies():
    try:
        import faiss
        from langchain_community.vectorstores import FAISS
        from langchain_community.vectorstores.utils import DistanceStrategy
    except ImportError as exc:  # pragma: no cover - installation configuration
        raise RuntimeError(
            "langchain-community and faiss-cpu are required to build an AAR corpus"
        ) from exc
    return faiss, FAISS, DistanceStrategy


def build_corpus(
    manifest_path: str | Path,
    output_dir: str | Path,
    *,
    embedding_provider: EmbeddingProvider = DEFAULT_PROVIDER,
    model_id: str = DEFAULT_MODEL,
    embedder=None,
    embedder_factory: Callable[[EmbeddingProvider, str], object] = load_embedder,
    page_loader_factory: Callable[..., object] | None = None,
) -> dict:
    """Validate, chunk, embed, and atomically publish a complete local corpus.

    Validation is intentionally the first executable operation. Consequently no
    loader, splitter, embedding provider, or vector store is constructed for an
    incomplete or unverified source manifest.
    """
    manifest = validate_manifest(manifest_path, require_complete=True)
    chunks: list[Chunk] = []
    for document in manifest.documents:
        chunks.extend(chunks_for_document(document, loader_factory=page_loader_factory))
    if len({chunk.chunk_id for chunk in chunks}) != len(chunks):
        raise ValueError("Chunk ID collision; corpus was not written")

    encoder = embedder or embedder_factory(embedding_provider, model_id)
    documents = [chunk_document(chunk) for chunk in chunks]
    faiss, FAISS, DistanceStrategy = _langchain_dependencies()
    try:
        store = FAISS.from_documents(
            documents,
            encoder,
            ids=[chunk.chunk_id for chunk in chunks],
            normalize_L2=True,
            distance_strategy=DistanceStrategy.MAX_INNER_PRODUCT,
        )
    except Exception as exc:
        raise RuntimeError(f"Could not build LangChain FAISS corpus: {exc}") from exc
    if store.index.ntotal != len(chunks):
        raise RuntimeError("LangChain FAISS index count does not match canonical chunks")
    row_map = {str(row): chunk_id for row, chunk_id in sorted(store.index_to_docstore_id.items())}
    if set(row_map.values()) != {chunk.chunk_id for chunk in chunks} or len(row_map) != len(chunks):
        raise RuntimeError("LangChain FAISS row mapping does not match canonical chunks")

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    build_manifest = {
        "schema_version": CORPUS_SCHEMA_VERSION,
        "embedding_provider": embedding_provider,
        "embedding_model": model_id,
        "vector_dimension": int(store.index.d),
        "chunk_count": len(chunks),
        "sources": [
            {"document_id": document.document_id, "sha256": document.sha256}
            for document in manifest.documents
        ],
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    # Avoid LangChain's pickle save/load format. All portable artifacts are
    # completed in a sibling temporary directory before replacing destinations.
    with tempfile.TemporaryDirectory(prefix=".aar-build-", dir=output.parent) as temporary:
        temporary_path = Path(temporary)
        faiss.write_index(store.index, str(temporary_path / "index.faiss"))
        _write_jsonl(temporary_path / "chunks.jsonl", chunks)
        (temporary_path / "index-map.json").write_text(
            json.dumps(row_map, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (temporary_path / "corpus-manifest.json").write_text(
            json.dumps(build_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        # Publish the manifest last; it is the completion marker for readers.
        for name in ("index.faiss", "index-map.json", "chunks.jsonl", "corpus-manifest.json"):
            os.replace(temporary_path / name, output / name)
    return build_manifest
