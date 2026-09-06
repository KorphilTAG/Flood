"""Retrieval-then-generation orchestration for the historical critic.

Retrieval is always a direct, in-process Python call into
`aar.search.search_index` (imported at module load) -- never a subprocess or
shell-out to `python -m aar search`.
"""
from __future__ import annotations

from typing import Callable

from aar.search import search_index

from .llm import Generator, generate_critique
from .schemas import (
    CritiqueAlternative,
    CritiqueObjection,
    CritiqueRequest,
    CritiqueResponse,
    RetrievedChunk,
    build_structured_response_schema,
)
from .settings import Settings

SearchFn = Callable[..., list[dict]]


class NoHistoricalContextError(Exception):
    """Raised when retrieval returns zero chunks to ground a critique in.

    The LLM is never called in this case (spec.md Approach, item 4 / item 6).
    """


class CritiqueGenerationError(Exception):
    """Raised when the LLM call fails or its structured output cannot be
    trusted (an OpenAI/LangChain failure, or a schema-validation failure).
    Never passed through as if it were a valid critique.
    """


def _build_query(request: CritiqueRequest) -> str:
    if request.situation:
        return f"{request.situation}\n\n{request.plan}"
    return request.plan


def run_critique(
    request: CritiqueRequest,
    settings: Settings,
    *,
    search: SearchFn = search_index,
    generator: Generator | None = None,
) -> CritiqueResponse:
    """Retrieve grounded AAR context for `request.plan`, then call the LLM
    to produce a structured, cited critique. Raises `NoHistoricalContextError`
    if retrieval finds nothing; lets `aar.models.IndexError`/`RuntimeError`
    from retrieval propagate as-is (service-configuration failures, not user
    input errors); wraps any generation/schema failure in
    `CritiqueGenerationError`.
    """
    query = _build_query(request)
    top_k = request.top_k if request.top_k is not None else settings.default_top_k

    hits = search(
        settings.aar_index_dir,
        query,
        hazard=request.hazard,
        phase=request.phase,
        limit=top_k,
    )
    if not hits:
        raise NoHistoricalContextError(
            "No historical AAR context matched this plan/filters; refusing to "
            "generate an ungrounded critique. Try broadening the hazard/phase "
            "filters or top_k."
        )

    response_schema = build_structured_response_schema([hit["chunk_id"] for hit in hits])

    try:
        structured = generate_critique(
            request.plan,
            request.situation,
            request.decision_point,
            hits,
            response_schema,
            generator=generator,
            settings=settings,
        )
        objections = [
            CritiqueObjection(text=item.text, chunk_ids=[cid.value for cid in item.chunk_ids])
            for item in structured.objections
        ]
        alternatives = [
            CritiqueAlternative(text=item.text, chunk_ids=[cid.value for cid in item.chunk_ids])
            for item in structured.alternatives
        ]
    except CritiqueGenerationError:
        raise
    except Exception as exc:
        raise CritiqueGenerationError(
            f"Historical critique generation failed: {exc}"
        ) from exc

    citations = [RetrievedChunk(**hit) for hit in hits]
    return CritiqueResponse(
        objections=objections,
        alternatives=alternatives,
        citations=citations,
        decision_point=request.decision_point,
        model=settings.openai_model,
    )
