"""Retrieval-then-generation orchestration for the historical critic.

Retrieval is always a direct, in-process Python call into
`aar.search.search_index` (imported at module load) -- never a subprocess or
shell-out to `python -m aar search`.
"""
from __future__ import annotations

from typing import Callable

from aar.search import search_index

from .facts import ImpactFacts, ImpactFactsError
from .llm import Generator, generate_critique
from .prompts import build_correction_message
from .schemas import (
    CritiqueAlternative,
    CritiqueObjection,
    CritiqueRequest,
    CritiqueResponse,
    RetrievedChunk,
    build_structured_response_schema,
)
from .settings import Settings
from .validator import CitationViolation, find_citation_violations

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


def _build_query(request: CritiqueRequest, impact: ImpactFacts | None) -> str:
    """Retrieval query: the plan, plus whatever context narrows it.

    The rendered impact facts join the query so retrieval is steered by the actual
    situation (PRD 6.6: retrieval "by semantic similarity to the current impact JSON
    and/or the trainee's proposed plan"), not by the plan text alone.
    """
    parts = [p for p in (request.situation, impact.render() if impact else None) if p]
    parts.append(request.plan)
    return "\n\n".join(parts)


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

    After each generation attempt, the independent rule-checker
    (`validator.py::find_citation_violations`) re-verifies that every cited
    `chunk_id` -- structured and inline-bracketed -- was actually retrieved
    for this request. A failure triggers a bounded regenerate-with-correction
    loop (up to `settings.max_regeneration_attempts` additional attempts);
    if every attempt still fails validation, `CritiqueGenerationError` is
    raised -- the request still fails closed, never returning a fabricated
    citation, but only after regeneration was actually attempted.
    """
    impact = ImpactFacts(request.impact) if request.impact is not None else None
    query = _build_query(request, impact)
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

    retrieved_ids = {hit["chunk_id"] for hit in hits}
    # The citable set is the union of retrieved AAR chunks and this request's own
    # flood facts. The validator and the structured-output enum are both built from
    # it, so a feature ID is exactly as unfakeable as a chunk ID (PRD 6.6).
    feature_ids = impact.feature_ids() if impact else set()
    citable_ids = [hit["chunk_id"] for hit in hits] + sorted(feature_ids)
    valid_ids = retrieved_ids | feature_ids
    response_schema = build_structured_response_schema(citable_ids)

    attempt = 0
    correction: str | None = None
    last_violations: list[CitationViolation] = []
    objections: list[CritiqueObjection] = []
    alternatives: list[CritiqueAlternative] = []

    while attempt <= settings.max_regeneration_attempts:
        try:
            structured = generate_critique(
                request.plan,
                request.situation,
                request.decision_point,
                hits,
                response_schema,
                generator=generator,
                settings=settings,
                correction=correction,
                impact_text=impact.render() if impact else None,
            )
            objections_raw = [
                {"text": item.text, "chunk_ids": [cid.value for cid in item.chunk_ids]}
                for item in structured.objections
            ]
            alternatives_raw = [
                {"text": item.text, "chunk_ids": [cid.value for cid in item.chunk_ids]}
                for item in structured.alternatives
            ]
        except CritiqueGenerationError:
            raise
        except Exception as exc:
            raise CritiqueGenerationError(
                f"Historical critique generation failed: {exc}"
            ) from exc

        last_violations = find_citation_violations(objections_raw, alternatives_raw, valid_ids)
        if not last_violations:
            objections = [CritiqueObjection(**item) for item in objections_raw]
            alternatives = [CritiqueAlternative(**item) for item in alternatives_raw]
            break

        correction = build_correction_message(last_violations, valid_ids)
        attempt += 1
    else:
        raise CritiqueGenerationError(
            "Historical critique still referenced non-existent IDs after "
            f"{settings.max_regeneration_attempts + 1} attempts: {last_violations}"
        )

    citations = [RetrievedChunk(**hit) for hit in hits]
    cited = {cid for item in (*objections, *alternatives) for cid in item.chunk_ids}
    return CritiqueResponse(
        objections=objections,
        alternatives=alternatives,
        citations=citations,
        feature_citations=sorted(cited & feature_ids),
        decision_point=request.decision_point,
        model=settings.openai_model,
    )
