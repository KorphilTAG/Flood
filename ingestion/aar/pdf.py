"""Page-bounded LangChain PDF extraction and deterministic chunking."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Callable, Iterable

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from .models import ANALYTIC_FIELDS, Chunk, Citation, ExtractionError, SourceDocument

TARGET_CHARS = 900
OVERLAP_CHARS = 150


# Contract convention: an AAR citation is a feature_ref in the reserved `aar` layer, so
# the critic's validator and any downstream consumer treat chunk IDs and feature IDs
# under one grammar (contracts/README.md "Feature IDs"; common.schema.json aar_ref).
# Separators inside the source_id are dots, because the grammar allows one colon only.
_AAR_REF = re.compile(r"^aar:[A-Za-z0-9_.-]{1,64}$")


def _chunk_id(document_id: str, page_number: int, sequence: int, digest: str) -> str:
    """Compose a citation ID and prove it is citable before it reaches the index.

    `manifest.py` bounds `document_id` so this cannot normally fail; asserting here
    makes the invariant hold by construction rather than by that arithmetic, because
    a chunk whose ID fails the grammar would be silently uncitable downstream.
    """
    chunk_id = f"aar:{document_id}.p{page_number}.c{sequence}.{digest}"
    if not _AAR_REF.fullmatch(chunk_id):
        raise ExtractionError(
            f"composed chunk id {chunk_id!r} is not a valid aar citation reference; "
            "shorten the document_id in the source manifest"
        )
    return chunk_id


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def read_pdf_pages(
    pdf_path: str | Path,
    loader_factory: Callable[..., object] | None = None,
) -> list[Document]:
    """Load each parsed PDF page in LangChain's page mode.

    Loader metadata is used solely for a parsed page offset. No loader source
    metadata is carried forward as corpus evidence.
    """
    if loader_factory is None:
        try:
            from langchain_community.document_loaders import PyPDFLoader
        except ImportError as exc:  # pragma: no cover - installation configuration
            raise ExtractionError("langchain-community and pypdf are required for AAR PDF extraction") from exc
        loader_factory = PyPDFLoader
    try:
        loader = loader_factory(str(pdf_path), mode="page", extract_images=False)
        loaded = loader.load()
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(f"Could not read PDF {pdf_path}: {exc}") from exc
    pages: list[Document] = []
    for position, page in enumerate(loaded, start=1):
        metadata = getattr(page, "metadata", None)
        page_offset = metadata.get("page") if isinstance(metadata, dict) else None
        if isinstance(page_offset, bool) or not isinstance(page_offset, int) or page_offset < 0:
            raise ExtractionError(
                f"PDF {pdf_path}: PyPDFLoader page {position} has no valid zero-based 'page' metadata"
            )
        content = getattr(page, "page_content", None)
        if not isinstance(content, str):
            raise ExtractionError(f"PDF {pdf_path}: PyPDFLoader page {position} has invalid text content")
        # Fresh, controlled documents ensure loader metadata never becomes evidence.
        pages.append(Document(page_content=content, metadata={"page": page_offset}))
    return pages


def _annotation_values(document: SourceDocument, page_number: int) -> dict[str, str | None]:
    values: dict[str, str | None] = {field: None for field in ANALYTIC_FIELDS}
    for annotation in document.annotations:
        if annotation.page_start <= page_number <= annotation.page_end:
            for field, value in annotation.values.items():
                if value is not None:
                    values[field] = value
    return values


def chunks_for_document(
    document: SourceDocument,
    *,
    page_documents: Iterable[Document] | None = None,
    loader_factory: Callable[..., object] | None = None,
) -> list[Chunk]:
    """Make provenance-bearing chunks that cannot cross parsed PDF pages."""
    pages = list(page_documents) if page_documents is not None else read_pdf_pages(document.local_pdf_path, loader_factory)
    parsed_page_numbers: list[int] = []
    for position, page in enumerate(pages, start=1):
        offset = page.metadata.get("page") if isinstance(page.metadata, dict) else None
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ExtractionError(
                f"document {document.document_id}: page {position} has no valid zero-based page metadata"
            )
        parsed_page_numbers.append(offset + 1)
    if parsed_page_numbers and max(parsed_page_numbers) > len(pages):
        raise ExtractionError(f"document {document.document_id}: loader page metadata is not a parsed PDF page sequence")
    for annotation in document.annotations:
        if annotation.page_end > len(pages):
            raise ExtractionError(
                f"document {document.document_id}: annotation page range {annotation.page_start}-{annotation.page_end} "
                f"extends beyond the PDF's {len(pages)} parsed pages"
            )

    splitter = RecursiveCharacterTextSplitter(chunk_size=TARGET_CHARS, chunk_overlap=OVERLAP_CHARS)
    chunks: list[Chunk] = []
    for page, page_number in zip(pages, parsed_page_numbers):
        normalized = normalize_text(page.page_content)
        # The splitter is invoked separately for every page by design.
        page_splits = [normalize_text(text) for text in splitter.split_text(normalized)] if normalized else []
        for sequence, text in enumerate((text for text in page_splits if text), start=1):
            digest = hashlib.sha256(
                f"{document.document_id}|{page_number}|{sequence}|{text}".encode("utf-8")
            ).hexdigest()[:16]
            values = _annotation_values(document, page_number)
            chunks.append(Chunk(
                # Contract convention: an AAR citation is a feature_ref in the
                # reserved `aar` layer, so the critic's validator and any
                # downstream consumer can treat chunk IDs and feature IDs under
                # one grammar (contracts/README.md "Feature IDs";
                # common.schema.json#/$defs/aar_ref). Separators inside the
                # source_id are dots, because the grammar allows exactly one colon.
                chunk_id=_chunk_id(document.document_id, page_number, sequence, digest),
                text=text,
                citation=Citation(
                    document_id=document.document_id,
                    title=document.title,
                    publisher=document.publisher,
                    canonical_url=document.canonical_url,
                    pdf_sha256=document.sha256,
                    page_start=page_number,
                    page_end=page_number,
                ),
                **values,
            ))
    if not chunks:
        raise ExtractionError(
            f"PDF {document.local_pdf_path} has no extractable text; it needs a human-prepared text/OCR follow-up before verification."
        )
    return chunks
