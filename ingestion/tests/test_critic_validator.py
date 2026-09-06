"""Unit tests for `critic.validator.find_citation_violations`.

Pure-function tests: no LLM, no network, no fakes needed beyond plain dicts.
"""
from __future__ import annotations

from critic.validator import CitationViolation, find_citation_violations


def test_find_citation_violations_returns_empty_for_fully_valid_response():
    known = {"chunk-1", "chunk-2"}
    objections = [{"text": "See [chunk-1] for precedent.", "chunk_ids": ["chunk-1"]}]
    alternatives = [{"text": "Also consider [chunk-2].", "chunk_ids": ["chunk-2"]}]

    violations = find_citation_violations(objections, alternatives, known)

    assert violations == []


def test_find_citation_violations_flags_structured_chunk_id_outside_retrieved_set():
    known = {"chunk-1"}
    objections = [{"text": "No inline citation here.", "chunk_ids": ["chunk-1", "fabricated-id"]}]

    violations = find_citation_violations(objections, [], known)

    assert any(v.field == "chunk_ids" and v.value == "fabricated-id" for v in violations)
    assert all(isinstance(v, CitationViolation) for v in violations)


def test_find_citation_violations_flags_inline_bracketed_token_outside_retrieved_set():
    known = {"chunk-1"}
    alternatives = [
        {"text": "As in [WIM-2015-07] officials waited too long.", "chunk_ids": ["chunk-1"]}
    ]

    violations = find_citation_violations([], alternatives, known)

    assert any(
        v.field == "text" and v.value == "WIM-2015-07" and v.item_kind == "alternative"
        for v in violations
    )


def test_find_citation_violations_does_not_flag_inline_bracketed_token_in_retrieved_set():
    known = {"chunk-1", "chunk-2"}
    objections = [{"text": "See [chunk-2] for the precedent.", "chunk_ids": ["chunk-1"]}]

    violations = find_citation_violations(objections, [], known)

    assert violations == []


def test_find_citation_violations_returns_empty_for_empty_objections_and_alternatives():
    violations = find_citation_violations([], [], {"chunk-1"})

    assert violations == []
