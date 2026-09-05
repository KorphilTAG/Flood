"""Validated cosine-similarity retrieval over portable LangChain FAISS artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from langchain_community.docstore.in_memory import InMemoryDocstore
from langchain_community.vectorstores import FAISS
from langchain_community.vectorstores.utils import DistanceStrategy

from .corpus import chunk_document
from .embeddings import EmbeddingProvider, load_embedder
from .models import ANALYTIC_FIELDS, CORPUS_SCHEMA_VERSION, Chunk, Citation, IndexError


_ARTIFACTS = ("index.faiss", "index-map.json", "chunks.jsonl", "corpus-manifest.json")


def _read_manifest(path: Path) -> dict:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IndexError(f"Invalid corpus manifest JSON: {exc}") from exc
    if not isinstance(manifest, dict):
        raise IndexError("Corpus manifest must be a JSON object")
    if manifest.get("schema_version") != CORPUS_SCHEMA_VERSION:
        if manifest.get("schema_version") == "1.0":
            raise IndexError(
                "This is a v1 raw-FAISS corpus. Rebuild it with `python -m aar build` "
                "using the verified source manifest; v1 artifacts cannot be searched."
            )
        raise IndexError("Corpus schema version is missing or incompatible; rebuild with `python -m aar build`")
    provider = manifest.get("embedding_provider")
    model = manifest.get("embedding_model")
    dimension = manifest.get("vector_dimension")
    count = manifest.get("chunk_count")
    if provider not in {"huggingface", "openai"}:
        raise IndexError("Corpus manifest has an unsupported embedding provider")
    if not isinstance(model, str) or not model or not isinstance(dimension, int) or dimension < 1:
        raise IndexError("Corpus manifest has invalid embedding model or vector dimension")
    if not isinstance(count, int) or count < 1:
        raise IndexError("Corpus manifest has invalid chunk count")
    sources = manifest.get("sources")
    if not isinstance(sources, list) or any(
        not isinstance(source, dict) or not isinstance(source.get("document_id"), str)
        or not isinstance(source.get("sha256"), str) for source in sources
    ):
        raise IndexError("Corpus manifest has invalid source document checksums")
    return manifest


def _parse_chunk(raw: object, line_number: int) -> Chunk:
    if not isinstance(raw, dict):
        raise IndexError(f"Invalid chunk record at line {line_number}")
    chunk_id, text, citation_raw = raw.get("chunk_id"), raw.get("text"), raw.get("citation")
    if not isinstance(chunk_id, str) or not chunk_id or not isinstance(text, str) or not text.strip():
        raise IndexError(f"Invalid chunk record at line {line_number}")
    if not isinstance(citation_raw, dict):
        raise IndexError(f"Chunk citation is incomplete at line {line_number}")
    fields = ("document_id", "title", "publisher", "canonical_url", "pdf_sha256")
    if any(not isinstance(citation_raw.get(field), str) or not citation_raw[field] for field in fields):
        raise IndexError(f"Chunk citation is incomplete at line {line_number}")
    start, end = citation_raw.get("page_start"), citation_raw.get("page_end")
    if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or start < 1 or start != end:
        raise IndexError(f"Chunk citation is incomplete at line {line_number}")
    values = {}
    for field in ANALYTIC_FIELDS:
        value = raw.get(field)
        if value is not None and not isinstance(value, str):
            raise IndexError(f"Invalid analytic field {field!r} at line {line_number}")
        values[field] = value
    return Chunk(
        chunk_id=chunk_id,
        text=text,
        citation=Citation(
            document_id=citation_raw["document_id"], title=citation_raw["title"],
            publisher=citation_raw["publisher"], canonical_url=citation_raw["canonical_url"],
            pdf_sha256=citation_raw["pdf_sha256"], page_start=start, page_end=end,
        ),
        **values,
    )


def _read_chunks(path: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    try:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                raise IndexError(f"Invalid blank chunk record at line {line_number}")
            chunks.append(_parse_chunk(json.loads(line), line_number))
    except json.JSONDecodeError as exc:
        raise IndexError(f"Invalid chunks JSONL: {exc}") from exc
    if not chunks or len({chunk.chunk_id for chunk in chunks}) != len(chunks):
        raise IndexError("Chunk store is empty or contains duplicate chunk IDs")
    return chunks


def _read_row_map(path: Path, chunks: list[Chunk]) -> dict[int, str]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise IndexError(f"Invalid index-map JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise IndexError("index-map.json must be a JSON object mapping FAISS rows to chunk IDs")
    row_map: dict[int, str] = {}
    for raw_row, chunk_id in raw.items():
        try:
            row = int(raw_row)
        except (TypeError, ValueError) as exc:
            raise IndexError("index-map.json contains a non-integer FAISS row ID") from exc
        if str(row) != raw_row or row < 0 or not isinstance(chunk_id, str) or not chunk_id:
            raise IndexError("index-map.json contains an invalid row mapping")
        if row in row_map:
            raise IndexError("index-map.json contains duplicate FAISS row IDs")
        row_map[row] = chunk_id
    expected_rows = set(range(len(chunks)))
    if set(row_map) != expected_rows or len(set(row_map.values())) != len(chunks):
        raise IndexError("index-map.json does not contain exactly one mapping for every FAISS row")
    if set(row_map.values()) != {chunk.chunk_id for chunk in chunks}:
        raise IndexError("index-map.json chunk IDs do not match canonical chunks.jsonl")
    return row_map


def _load_index(index_dir: str | Path):
    directory = Path(index_dir)
    manifest_path = directory / "corpus-manifest.json"
    if not manifest_path.is_file():
        raise IndexError("Index directory is missing required artifacts: corpus-manifest.json")
    # Read the schema before requiring v2-only files so a normal legacy v1
    # directory (which has no index-map.json) gets the actionable rebuild hint.
    manifest = _read_manifest(manifest_path)
    missing = [name for name in _ARTIFACTS if name != "corpus-manifest.json" and not (directory / name).is_file()]
    if missing:
        raise IndexError("Index directory is missing required artifacts: " + ", ".join(missing))
    chunks = _read_chunks(directory / "chunks.jsonl")
    if len(chunks) != manifest["chunk_count"]:
        raise IndexError("Canonical chunks.jsonl count does not match corpus manifest")
    row_map = _read_row_map(directory / "index-map.json", chunks)
    try:
        import faiss
    except ImportError as exc:  # pragma: no cover - installation configuration
        raise RuntimeError("faiss-cpu is required to search an AAR corpus") from exc
    try:
        index = faiss.read_index(str(directory / "index.faiss"))
    except Exception as exc:
        raise IndexError(f"Could not read index.faiss: {exc}") from exc
    if index.d != manifest["vector_dimension"] or index.ntotal != len(chunks):
        raise IndexError("FAISS artifacts do not match the recorded corpus dimension or chunk count")
    if index.metric_type != faiss.METRIC_INNER_PRODUCT:
        raise IndexError("FAISS index metric is incompatible; rebuild with `python -m aar build`")
    return manifest, chunks, index, row_map


def search_index(
    index_dir: str | Path,
    query: str,
    *,
    hazard: str | None = None,
    phase: str | None = None,
    limit: int = 10,
    embedder=None,
    embedder_factory: Callable[[EmbeddingProvider, str], object] = load_embedder,
) -> list[dict]:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be non-empty")
    if limit < 1:
        raise ValueError("limit must be at least 1")
    manifest, chunks, index, row_map = _load_index(index_dir)
    encoder = embedder or embedder_factory(manifest["embedding_provider"], manifest["embedding_model"])
    try:
        query_vector = encoder.embed_query(query)
    except Exception as exc:
        raise RuntimeError(f"Could not embed AAR search query: {exc}") from exc
    if not isinstance(query_vector, (list, tuple)):
        # numpy arrays are intentionally accepted without importing numpy.
        try:
            query_vector = list(query_vector)
        except TypeError as exc:
            raise IndexError("Query embedder returned an invalid vector") from exc
    if len(query_vector) != manifest["vector_dimension"]:
        raise IndexError("Query embedder vector dimension does not match the corpus manifest")

    canonical = {chunk.chunk_id: chunk for chunk in chunks}
    docstore = InMemoryDocstore({chunk.chunk_id: chunk_document(chunk) for chunk in chunks})
    store = FAISS(
        embedding_function=encoder,
        index=index,
        docstore=docstore,
        index_to_docstore_id=row_map,
        distance_strategy=DistanceStrategy.MAX_INNER_PRODUCT,
        normalize_L2=True,
    )
    # Fetch all candidates before applying metadata filters, then rehydrate only
    # canonical JSONL records so public citations never depend on docstore data.
    try:
        candidates = store.similarity_search_with_score_by_vector(query_vector, k=len(chunks))
    except Exception as exc:
        raise IndexError(f"Could not query LangChain FAISS corpus: {exc}") from exc
    results: list[dict] = []
    for document, score in candidates:
        chunk_id = document.metadata.get("chunk_id")
        chunk = canonical.get(chunk_id)
        if chunk is None:
            raise IndexError("LangChain FAISS docstore returned a chunk absent from canonical chunks.jsonl")
        if hazard is not None and chunk.hazard != hazard:
            continue
        if phase is not None and chunk.phase != phase:
            continue
        result = {
            "chunk_id": chunk.chunk_id,
            "score": float(score),
            "excerpt": chunk.text[:500],
            "citation": chunk.citation.to_dict(),
        }
        result.update({field: getattr(chunk, field) for field in ANALYTIC_FIELDS})
        results.append(result)
        if len(results) == limit:
            break
    return results
