"""Contract 2 impact facts as critic grounding context.

Offline: no OpenAI key, no network, no built FAISS corpus. `search_index` and the
LLM `generator` are faked, exactly as in `test_critic_service.py`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from critic.facts import ImpactFacts, ImpactFactsError
from critic.schemas import CritiqueRequest
from critic.service import CritiqueGenerationError, run_critique
from critic.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE = REPO_ROOT / "docs" / "contracts" / "examples" / "impact-response.sample.json"


@pytest.fixture
def impact_doc() -> dict:
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def _hit(chunk_id: str) -> dict:
    return {
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


class FakeSearch:
    def __init__(self, hits):
        self.hits = hits
        self.calls: list[dict] = []

    def __call__(self, index_dir, query, *, hazard=None, phase=None, limit=10):
        self.calls.append({"query": query, "limit": limit})
        return self.hits


def _settings() -> Settings:
    return Settings(aar_index_dir="unused/for/fakes", openai_model="test-model")


# --- ImpactFacts ------------------------------------------------------------


def test_feature_ids_cover_facts_egress_and_reaches(impact_doc):
    ids = ImpactFacts(impact_doc).feature_ids()
    assert ids == {"crossing:cr-17", "site:camp-4", "road:seg-17", "reach:3586192"}


def test_render_leads_every_line_with_a_citable_reference(impact_doc):
    text = ImpactFacts(impact_doc).render()
    for ref in ImpactFacts(impact_doc).feature_ids():
        assert f"[{ref}]" in text
    assert "2025-07-04T06:45:00Z" in text  # the projection times survive


def test_render_handles_a_document_with_no_impacts():
    empty = {"schema_version": "1.0", "run_id": "r", "p": None, "t": "2025-07-04T06:15:00Z",
             "velocity_is_proxy": True, "facts": [], "egress": [], "reaches": []}
    assert "no impacted features" in ImpactFacts(empty).render()


def test_coordinate_bearing_document_is_rejected(impact_doc):
    impact_doc["facts"][0]["lon"] = -99.2
    with pytest.raises(ImpactFactsError, match="lon"):
        ImpactFacts(impact_doc)


def test_nested_geometry_is_rejected(impact_doc):
    impact_doc["facts"][0]["attributes"] = {"shape": {"geometry": "POINT(1 2)"}}
    with pytest.raises(ImpactFactsError, match="geometry"):
        ImpactFacts(impact_doc)


def test_malformed_feature_refs_never_become_citable(impact_doc):
    impact_doc["facts"][0]["feature_ref"] = "not a valid ref"
    assert "not a valid ref" not in ImpactFacts(impact_doc).feature_ids()


def test_from_path_reports_a_missing_document(tmp_path):
    with pytest.raises(ImpactFactsError, match="not found"):
        ImpactFacts.from_path(tmp_path / "nope.json")


# --- service wiring ---------------------------------------------------------


def test_feature_ids_become_citable_alongside_chunk_ids(impact_doc):
    """A response may cite a crossing from the impact document, not only an AAR chunk."""
    search = FakeSearch([_hit("aar:doc-1.p1.c1." + "a" * 16)])
    seen: dict = {}

    def generator(plan, situation, decision_point, chunks, response_schema, *, settings, **kw):
        seen["schema"] = response_schema
        seen["impact_text"] = kw.get("impact_text")
        return response_schema(
            objections=[{"text": "Crossing floods first.", "chunk_ids": ["crossing:cr-17"]}],
            alternatives=[{"text": "Use the north route.", "chunk_ids": ["road:seg-17"]}],
        )

    response = run_critique(
        CritiqueRequest(plan="Send a truck over the low-water crossing.", impact=impact_doc),
        _settings(), search=search, generator=generator,
    )
    assert response.objections[0].chunk_ids == ["crossing:cr-17"]
    assert response.feature_citations == ["crossing:cr-17", "road:seg-17"]


def test_fabricated_feature_ref_fails_closed(impact_doc):
    """An invented crossing is rejected exactly as an invented chunk ID is."""
    search = FakeSearch([_hit("aar:doc-1.p1.c1." + "a" * 16)])

    def generator(plan, situation, decision_point, chunks, response_schema, *, settings, **kw):
        # Bypass the enum the way a non-conforming model would: build the payload raw.
        return type("R", (), {
            "objections": [type("O", (), {"text": "x", "chunk_ids": [type("E", (), {"value": "crossing:does-not-exist"})()]})()],
            "alternatives": [],
        })()

    with pytest.raises(CritiqueGenerationError, match="non-existent"):
        run_critique(
            CritiqueRequest(plan="Send a truck.", impact=impact_doc),
            _settings(), search=search, generator=generator,
        )


def test_impact_text_reaches_the_prompt_and_the_retrieval_query(impact_doc):
    search = FakeSearch([_hit("aar:doc-1.p1.c1." + "a" * 16)])
    seen: dict = {}

    def generator(plan, situation, decision_point, chunks, response_schema, *, settings, **kw):
        seen["impact_text"] = kw.get("impact_text")
        return response_schema(objections=[], alternatives=[])

    run_critique(
        CritiqueRequest(plan="Hold position.", impact=impact_doc),
        _settings(), search=search, generator=generator,
    )
    assert "[crossing:cr-17]" in seen["impact_text"]
    # Retrieval is steered by the situation, not by the plan text alone (PRD 6.6).
    assert "crossing:cr-17" in search.calls[0]["query"]


def test_request_without_impact_is_unchanged(impact_doc):
    """The pre-existing contract still works, and no impact_text is forwarded."""
    search = FakeSearch([_hit("aar:doc-1.p1.c1." + "a" * 16)])
    chunk = "aar:doc-1.p1.c1." + "a" * 16

    def generator(plan, situation, decision_point, chunks, response_schema, *, settings):
        # No **kw: a generator written before impact facts existed must still be callable.
        return response_schema(
            objections=[{"text": "t", "chunk_ids": [chunk]}], alternatives=[],
        )

    response = run_critique(
        CritiqueRequest(plan="Hold position."), _settings(), search=search, generator=generator,
    )
    assert response.feature_citations == []
    assert response.objections[0].chunk_ids == [chunk]
