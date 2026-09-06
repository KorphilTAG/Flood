"""Request/response contracts and the per-request structured-output schema
builder for the historical critic.

`CritiqueRequest`/`CritiqueResponse` are the stable HTTP contract. The
`build_structured_response_schema` function below is different: it builds a
fresh Pydantic model *per request*, with the citation fields constrained to
an `Enum` of exactly that request's retrieved `chunk_id`s, so the LLM's
structured output cannot represent a chunk ID it was not just handed as
context (spec.md Approach, item 6; Design Principle 3: every LLM claim
cites a real ID).
"""
from __future__ import annotations

from enum import Enum
from typing import Sequence

from pydantic import BaseModel, Field, create_model, field_validator


class CritiqueRequest(BaseModel):
    plan: str
    situation: str | None = None
    decision_point: str | None = None
    hazard: str | None = None
    phase: str | None = None
    top_k: int | None = None

    @field_validator("plan")
    @classmethod
    def _plan_must_be_non_empty(cls, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("plan must be a non-empty, non-whitespace string")
        return value

    @field_validator("top_k")
    @classmethod
    def _top_k_must_be_positive(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("top_k must be at least 1")
        return value


class CitationDetail(BaseModel):
    document_id: str
    title: str
    publisher: str
    canonical_url: str
    pdf_sha256: str
    page_start: int
    page_end: int


class RetrievedChunk(BaseModel):
    """The full retrieved chunk record, as produced by `aar.search.search_index`,
    so a caller can render/verify a citation without a second search call.
    """

    chunk_id: str
    score: float
    excerpt: str
    citation: CitationDetail
    hazard: str | None = None
    phase: str | None = None
    tactic: str | None = None
    resources: str | None = None
    outcome: str | None = None
    lesson: str | None = None


class CritiqueObjection(BaseModel):
    text: str
    chunk_ids: list[str]


class CritiqueAlternative(BaseModel):
    text: str
    chunk_ids: list[str]


class CritiqueResponse(BaseModel):
    objections: list[CritiqueObjection]
    alternatives: list[CritiqueAlternative]
    citations: list[RetrievedChunk]
    decision_point: str | None = None
    model: str


def build_structured_response_schema(chunk_ids: Sequence[str]) -> type[BaseModel]:
    """Build a structured-output schema whose `chunk_ids` fields are an
    `Enum` of exactly the given retrieved chunk IDs. Built fresh per request
    because the valid ID set changes with every retrieval; a schema built
    this way cannot represent an invented chunk ID at all -- it is a JSON
    Schema constraint, not a post-hoc filter (see spec.md Approach, "Why a
    schema-constrained enum, not a post-hoc filter").
    """
    if not chunk_ids:
        raise ValueError("build_structured_response_schema requires at least one chunk id")

    chunk_id_enum = Enum("ChunkIdEnum", {chunk_id: chunk_id for chunk_id in chunk_ids})

    objection_model = create_model(
        "CritiqueObjectionSchema",
        text=(str, ...),
        chunk_ids=(list[chunk_id_enum], Field(..., min_length=1)),
    )
    alternative_model = create_model(
        "CritiqueAlternativeSchema",
        text=(str, ...),
        chunk_ids=(list[chunk_id_enum], Field(..., min_length=1)),
    )
    structured_critique_model = create_model(
        "StructuredCritiqueSchema",
        objections=(list[objection_model], ...),
        alternatives=(list[alternative_model], ...),
    )
    return structured_critique_model
