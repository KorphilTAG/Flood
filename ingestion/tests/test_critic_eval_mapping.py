"""Offline, pure-function tests of `critic_eval.mapping.to_ragas_records`.

No LLM, no network, no fake needed beyond canned `critic.schemas` objects --
`to_ragas_records` is a pure function.
"""
from __future__ import annotations

from critic.schemas import (
    CitationDetail,
    CritiqueAlternative,
    CritiqueObjection,
    CritiqueResponse,
    RetrievedChunk,
)
from critic_eval.mapping import to_ragas_records
from critic_eval.runner import SampleRun


def _citation_detail(document_id: str) -> CitationDetail:
    return CitationDetail(
        document_id=document_id,
        title="Synthetic AAR",
        publisher="Synthetic publisher",
        canonical_url=f"https://example.invalid/{document_id}",
        pdf_sha256="a" * 64,
        page_start=1,
        page_end=1,
    )


def _retrieved_chunk(chunk_id: str, excerpt: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        score=0.9,
        excerpt=excerpt,
        citation=_citation_detail("doc-1"),
    )


def _response(**overrides) -> CritiqueResponse:
    defaults = dict(
        objections=[CritiqueObjection(text="Objection one.", chunk_ids=["chunk-1"])],
        alternatives=[CritiqueAlternative(text="Alternative one.", chunk_ids=["chunk-1"])],
        citations=[_retrieved_chunk("chunk-1", "excerpt one"), _retrieved_chunk("chunk-2", "excerpt two")],
        decision_point=None,
        model="test-model",
    )
    defaults.update(overrides)
    return CritiqueResponse(**defaults)


def test_to_ragas_records_excludes_errored_sample_runs():
    ok_run = SampleRun(sample={"plan": "ok plan"}, response=_response(), error=None)
    failed_run = SampleRun(sample={"plan": "failed plan"}, response=None, error=RuntimeError("boom"))

    records = to_ragas_records([ok_run, failed_run])

    assert len(records) == 1
    assert records[0]["user_input"] == "ok plan"


def test_to_ragas_records_retrieved_contexts_is_exactly_the_excerpts_in_order_not_full_text_not_cited_only():
    response = _response(
        # Only chunk-1 is actually cited by the objection/alternative, but
        # retrieved_contexts must include every retrieved citation, not just
        # the cited one, and must use the (truncated) excerpt, not any
        # longer full-chunk-text stand-in.
        citations=[
            _retrieved_chunk("chunk-1", "excerpt one (truncated)"),
            _retrieved_chunk("chunk-2", "excerpt two (truncated, not cited by any objection/alternative)"),
        ],
    )
    run = SampleRun(sample={"plan": "plan"}, response=response, error=None)

    records = to_ragas_records([run])

    assert records[0]["retrieved_contexts"] == [
        "excerpt one (truncated)",
        "excerpt two (truncated, not cited by any objection/alternative)",
    ]


def test_to_ragas_records_response_is_newline_joined_objections_then_alternatives():
    response = _response(
        objections=[
            CritiqueObjection(text="Objection A.", chunk_ids=["chunk-1"]),
            CritiqueObjection(text="Objection B.", chunk_ids=["chunk-1"]),
        ],
        alternatives=[
            CritiqueAlternative(text="Alternative A.", chunk_ids=["chunk-1"]),
        ],
    )
    run = SampleRun(sample={"plan": "plan"}, response=response, error=None)

    records = to_ragas_records([run])

    assert records[0]["response"] == "Objection A.\nObjection B.\nAlternative A."


def test_to_ragas_records_user_input_joins_situation_and_plan_when_situation_present():
    run = SampleRun(
        sample={"plan": "Shelter in place near the river.", "situation": "Rising water"},
        response=_response(),
        error=None,
    )

    records = to_ragas_records([run])

    assert records[0]["user_input"] == "Rising water\n\nShelter in place near the river."


def test_to_ragas_records_user_input_is_plan_alone_when_situation_absent():
    run = SampleRun(sample={"plan": "Shelter in place."}, response=_response(), error=None)

    records = to_ragas_records([run])

    assert records[0]["user_input"] == "Shelter in place."


def test_to_ragas_records_user_input_is_plan_alone_when_situation_is_blank():
    run = SampleRun(sample={"plan": "Shelter in place.", "situation": ""}, response=_response(), error=None)

    records = to_ragas_records([run])

    assert records[0]["user_input"] == "Shelter in place."
