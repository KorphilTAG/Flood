"""Offline tests for the critic's retrieval-to-generation orchestration.

No real `OPENAI_API_KEY`, no network call, and no real built FAISS corpus:
`search_index` and the LLM `generator` are always faked/monkeypatched.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from aar.models import IndexError as AarIndexError
from critic.schemas import CritiqueRequest
from critic.service import CritiqueGenerationError, NoHistoricalContextError, run_critique
from critic.settings import Settings


def _hit(chunk_id: str, **overrides) -> dict:
    hit = {
        "chunk_id": chunk_id,
        "score": 0.9,
        "excerpt": f"excerpt for {chunk_id}",
        "citation": {
            "document_id": "doc-1",
            "title": "Synthetic AAR",
            "publisher": "Synthetic publisher",
            "canonical_url": "https://example.invalid/doc-1",
            "pdf_sha256": "a" * 64,
            "page_start": 1,
            "page_end": 1,
        },
        "hazard": "flood",
        "phase": "response",
        "tactic": "shelter-in-place",
        "resources": "boats",
        "outcome": "no casualties",
        "lesson": "pre-position boats",
    }
    hit.update(overrides)
    return hit


class RecordingSearch:
    """Fake `search_index` replacement that records every call it receives."""

    def __init__(self, hits=None, exc=None):
        self.hits = hits if hits is not None else []
        self.exc = exc
        self.calls: list[dict] = []

    def __call__(self, index_dir, query, *, hazard=None, phase=None, limit=10):
        self.calls.append(
            {"index_dir": index_dir, "query": query, "hazard": hazard, "phase": phase, "limit": limit}
        )
        if self.exc is not None:
            raise self.exc
        return self.hits


class RecordingGenerator:
    """Fake LLM `generator` replacement that records every call it receives."""

    def __init__(self, response=None, exc=None):
        self._response = response
        self.exc = exc
        self.calls: list[dict] = []

    def __call__(self, plan, situation, decision_point, chunks, response_schema, *, settings):
        self.calls.append(
            {
                "plan": plan,
                "situation": situation,
                "decision_point": decision_point,
                "chunks": chunks,
                "response_schema": response_schema,
                "settings": settings,
            }
        )
        if self.exc is not None:
            raise self.exc
        return self._response


def _valid_structured_response(response_schema, chunk_id: str):
    return response_schema(
        objections=[{"text": "Consider evacuating low-water crossings earlier.", "chunk_ids": [chunk_id]}],
        alternatives=[{"text": "Pre-position boats upstream before the surge.", "chunk_ids": [chunk_id]}],
    )


def _settings() -> Settings:
    return Settings(aar_index_dir="unused/for/fakes", openai_model="test-model")


def test_run_critique_success_grounds_response_in_retrieved_chunks():
    hits = [_hit("chunk-1"), _hit("chunk-2")]
    search = RecordingSearch(hits=hits)
    generator = RecordingGenerator()

    def generator_call(plan, situation, decision_point, chunks, response_schema, *, settings):
        generator.calls.append(
            {
                "plan": plan,
                "situation": situation,
                "decision_point": decision_point,
                "chunks": chunks,
                "response_schema": response_schema,
                "settings": settings,
            }
        )
        return _valid_structured_response(response_schema, "chunk-1")

    request = CritiqueRequest(plan="Shelter in place near the river.", situation="Rising water", top_k=2)
    response = run_critique(request, _settings(), search=search, generator=generator_call)

    assert search.calls == [
        {"index_dir": Path("unused/for/fakes"), "query": "Rising water\n\nShelter in place near the river.",
         "hazard": None, "phase": None, "limit": 2}
    ]
    assert len(generator.calls) == 1
    assert response.model == "test-model"
    assert {chunk.chunk_id for chunk in response.citations} == {"chunk-1", "chunk-2"}
    all_cited_ids = {
        cid for item in (*response.objections, *response.alternatives) for cid in item.chunk_ids
    }
    assert all_cited_ids <= {hit["chunk_id"] for hit in hits}
    assert all_cited_ids  # at least one citation was actually returned


def test_run_critique_builds_query_from_plan_alone_when_situation_absent():
    hits = [_hit("chunk-1")]
    search = RecordingSearch(hits=hits)
    generator = RecordingGenerator(response=None)

    def generator_call(plan, situation, decision_point, chunks, response_schema, *, settings):
        generator.calls.append({"plan": plan})
        return _valid_structured_response(response_schema, "chunk-1")

    request = CritiqueRequest(plan="Shelter in place.")
    run_critique(request, _settings(), search=search, generator=generator_call)

    assert search.calls[0]["query"] == "Shelter in place."


def test_run_critique_passes_hazard_phase_and_top_k_filters_through():
    hits = [_hit("chunk-1")]
    search = RecordingSearch(hits=hits)

    def generator_call(plan, situation, decision_point, chunks, response_schema, *, settings):
        return _valid_structured_response(response_schema, "chunk-1")

    request = CritiqueRequest(plan="plan", hazard="flood", phase="response", top_k=3)
    run_critique(request, _settings(), search=search, generator=generator_call)

    assert search.calls[0]["hazard"] == "flood"
    assert search.calls[0]["phase"] == "response"
    assert search.calls[0]["limit"] == 3


def test_run_critique_uses_settings_default_top_k_when_not_supplied():
    hits = [_hit("chunk-1")]
    search = RecordingSearch(hits=hits)

    def generator_call(plan, situation, decision_point, chunks, response_schema, *, settings):
        return _valid_structured_response(response_schema, "chunk-1")

    request = CritiqueRequest(plan="plan")
    settings = Settings(aar_index_dir="unused", openai_model="test-model", default_top_k=7)
    run_critique(request, settings, search=search, generator=generator_call)

    assert search.calls[0]["limit"] == 7


def test_structured_schema_is_built_from_exactly_the_retrieved_chunk_ids():
    hits = [_hit("chunk-a"), _hit("chunk-b"), _hit("chunk-c")]
    search = RecordingSearch(hits=hits)
    captured = {}

    def generator_call(plan, situation, decision_point, chunks, response_schema, *, settings):
        captured["schema"] = response_schema
        return _valid_structured_response(response_schema, "chunk-a")

    request = CritiqueRequest(plan="plan")
    run_critique(request, _settings(), search=search, generator=generator_call)

    schema = captured["schema"]
    json_schema = schema.model_json_schema()
    enum_def = json_schema["$defs"]["ChunkIdEnum"]
    assert set(enum_def["enum"]) == {"chunk-a", "chunk-b", "chunk-c"}

    objection_schema = json_schema["$defs"]["CritiqueObjectionSchema"]
    assert objection_schema["properties"]["chunk_ids"]["minItems"] == 1
    alternative_schema = json_schema["$defs"]["CritiqueAlternativeSchema"]
    assert alternative_schema["properties"]["chunk_ids"]["minItems"] == 1

    # The schema structurally rejects an invented chunk ID -- not a post-hoc filter.
    with pytest.raises(Exception):
        schema(objections=[{"text": "t", "chunk_ids": ["not-a-real-chunk-id"]}], alternatives=[])


def test_run_critique_raises_no_historical_context_error_and_never_calls_generator():
    search = RecordingSearch(hits=[])
    generator = RecordingGenerator()

    with pytest.raises(NoHistoricalContextError):
        run_critique(CritiqueRequest(plan="plan"), _settings(), search=search, generator=generator)

    assert len(search.calls) == 1
    assert generator.calls == []


def test_run_critique_propagates_aar_index_error_and_never_calls_generator():
    search = RecordingSearch(exc=AarIndexError("corpus schema version is missing or incompatible"))
    generator = RecordingGenerator()

    with pytest.raises(AarIndexError, match="corpus schema version"):
        run_critique(CritiqueRequest(plan="plan"), _settings(), search=search, generator=generator)

    assert generator.calls == []


def test_run_critique_propagates_runtime_error_and_never_calls_generator():
    search = RecordingSearch(exc=RuntimeError("faiss-cpu is required to search an AAR corpus"))
    generator = RecordingGenerator()

    with pytest.raises(RuntimeError, match="faiss-cpu"):
        run_critique(CritiqueRequest(plan="plan"), _settings(), search=search, generator=generator)

    assert generator.calls == []


def test_run_critique_wraps_generator_failure_in_critique_generation_error():
    hits = [_hit("chunk-1")]
    search = RecordingSearch(hits=hits)
    generator = RecordingGenerator(exc=RuntimeError("OpenAI API request failed"))

    with pytest.raises(CritiqueGenerationError, match="OpenAI API request failed"):
        run_critique(CritiqueRequest(plan="plan"), _settings(), search=search, generator=generator)

    assert len(generator.calls) == 1


def _invalid_response(response_schema, chunk_id: str, invalid_token: str):
    # A fabricated structured `chunk_ids` entry cannot pass through
    # `response_schema` at all -- its `chunk_ids` fields are Enum-typed to
    # exactly the retrieved chunk IDs (schemas.py), so constructing an
    # invalid *structured* citation here would raise before the validator
    # ever runs. The independently-checkable failure mode this fake exercises
    # instead is an out-of-set bracketed inline citation in free text, which
    # the schema Enum cannot constrain (spec.md Problem, gap 2).
    return response_schema(
        objections=[
            {
                "text": f"As in [{invalid_token}] officials waited too long.",
                "chunk_ids": [chunk_id],
            }
        ],
        alternatives=[],
    )


def test_run_critique_regenerates_once_on_invalid_then_valid_response():
    hits = [_hit("chunk-1")]
    search = RecordingSearch(hits=hits)
    calls: list[dict] = []

    def generator_call(plan, situation, decision_point, chunks, response_schema, *, settings, correction=None):
        calls.append({"correction": correction})
        if len(calls) == 1:
            return _invalid_response(response_schema, "chunk-1", "WIM-2015-07")
        return _valid_structured_response(response_schema, "chunk-1")

    request = CritiqueRequest(plan="Shelter in place near the river.")
    response = run_critique(request, _settings(), search=search, generator=generator_call)

    assert len(calls) == 2
    assert calls[0]["correction"] is None
    assert calls[1]["correction"] is not None
    assert "WIM-2015-07" in calls[1]["correction"]
    all_cited_ids = {
        cid for item in (*response.objections, *response.alternatives) for cid in item.chunk_ids
    }
    assert all_cited_ids == {"chunk-1"}
    for item in (*response.objections, *response.alternatives):
        assert "WIM-2015-07" not in item.text


def test_run_critique_raises_after_exhausting_regeneration_attempts():
    hits = [_hit("chunk-1")]
    search = RecordingSearch(hits=hits)
    calls: list[dict] = []

    def generator_call(plan, situation, decision_point, chunks, response_schema, *, settings, correction=None):
        calls.append({"correction": correction})
        return _invalid_response(response_schema, "chunk-1", "WIM-2015-07")

    settings = _settings()
    request = CritiqueRequest(plan="Shelter in place near the river.")

    with pytest.raises(CritiqueGenerationError):
        run_critique(request, settings, search=search, generator=generator_call)

    assert len(calls) == settings.max_regeneration_attempts + 1


def test_run_critique_honors_max_regeneration_attempts_setting_of_zero():
    hits = [_hit("chunk-1")]
    search = RecordingSearch(hits=hits)
    calls: list[dict] = []

    def generator_call(plan, situation, decision_point, chunks, response_schema, *, settings, correction=None):
        calls.append({"correction": correction})
        return _invalid_response(response_schema, "chunk-1", "WIM-2015-07")

    settings = Settings(
        aar_index_dir="unused/for/fakes", openai_model="test-model", max_regeneration_attempts=0
    )
    request = CritiqueRequest(plan="Shelter in place near the river.")

    with pytest.raises(CritiqueGenerationError):
        run_critique(request, settings, search=search, generator=generator_call)

    assert len(calls) == 1
