"""FastAPI `TestClient` tests for the historical critic API: request
validation, the success path, and every error mapping.

No real `OPENAI_API_KEY`, no network access, and no real built FAISS corpus:
both `search_index` and the LLM `generator` are faked/monkeypatched via
`critic.service` module patches.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from aar.models import IndexError as AarIndexError
import critic.service as service_module
from critic.app import create_app
from critic.settings import Settings

from .test_critic_service import RecordingGenerator, RecordingSearch, _hit, _valid_structured_response


def _client(monkeypatch, search=None, generator=None) -> TestClient:
    settings = Settings(aar_index_dir="unused/for/fakes", openai_model="test-model")
    app = create_app(settings)

    def patched_run_critique(request, settings_arg, **kwargs):
        return service_module.run_critique(request, settings_arg, search=search, generator=generator)

    monkeypatch.setattr("critic.app.run_critique", patched_run_critique)
    return TestClient(app)


def _generator_call(plan, situation, decision_point, chunks, response_schema, *, settings):
    return _valid_structured_response(response_schema, chunks[0]["chunk_id"])


def test_healthz_returns_200_without_touching_search_or_llm(monkeypatch):
    search = RecordingSearch()
    generator = RecordingGenerator()
    client = _client(monkeypatch, search=search, generator=generator)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert search.calls == []
    assert generator.calls == []


def test_critique_success_returns_grounded_response(monkeypatch):
    hits = [_hit("chunk-1"), _hit("chunk-2")]
    search = RecordingSearch(hits=hits)
    client = _client(monkeypatch, search=search, generator=_generator_call)

    response = client.post("/v1/critique", json={"plan": "Shelter in place near the river."})

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) >= {"objections", "alternatives", "citations", "model"}
    assert body["model"] == "test-model"
    citation_ids = {c["chunk_id"] for c in body["citations"]}
    assert citation_ids == {"chunk-1", "chunk-2"}
    for item in (*body["objections"], *body["alternatives"]):
        assert set(item["chunk_ids"]) <= citation_ids
        assert len(item["chunk_ids"]) >= 1


def test_critique_missing_plan_returns_422_before_any_fake_is_called(monkeypatch):
    search = RecordingSearch(hits=[_hit("chunk-1")])
    generator = RecordingGenerator()
    client = _client(monkeypatch, search=search, generator=generator)

    response = client.post("/v1/critique", json={})

    assert response.status_code == 422
    assert search.calls == []
    assert generator.calls == []


def test_critique_empty_plan_returns_422_before_any_fake_is_called(monkeypatch):
    search = RecordingSearch(hits=[_hit("chunk-1")])
    generator = RecordingGenerator()
    client = _client(monkeypatch, search=search, generator=generator)

    response = client.post("/v1/critique", json={"plan": "   "})

    assert response.status_code == 422
    assert search.calls == []
    assert generator.calls == []


def test_critique_no_historical_context_returns_4xx_and_never_calls_generator(monkeypatch):
    search = RecordingSearch(hits=[])
    generator = RecordingGenerator()
    client = _client(monkeypatch, search=search, generator=generator)

    response = client.post("/v1/critique", json={"plan": "Shelter in place."})

    assert 400 <= response.status_code < 500
    body = response.json()
    assert "historical" in body["error"]["message"].lower() or "context" in body["error"]["message"].lower()
    assert generator.calls == []


def test_critique_aar_index_error_returns_5xx_with_underlying_message(monkeypatch):
    search = RecordingSearch(exc=AarIndexError("Corpus schema version is missing or incompatible"))
    generator = RecordingGenerator()
    client = _client(monkeypatch, search=search, generator=generator)

    response = client.post("/v1/critique", json={"plan": "Shelter in place."})

    assert 500 <= response.status_code < 600
    body = response.json()
    assert "corpus schema version is missing or incompatible" in body["error"]["message"].lower()
    assert generator.calls == []


def test_critique_search_runtime_error_returns_5xx(monkeypatch):
    search = RecordingSearch(exc=RuntimeError("faiss-cpu is required to search an AAR corpus"))
    generator = RecordingGenerator()
    client = _client(monkeypatch, search=search, generator=generator)

    response = client.post("/v1/critique", json={"plan": "Shelter in place."})

    assert 500 <= response.status_code < 600
    body = response.json()
    assert "faiss-cpu" in body["error"]["message"].lower()


def test_critique_generator_failure_returns_5xx_not_200(monkeypatch):
    search = RecordingSearch(hits=[_hit("chunk-1")])
    generator = RecordingGenerator(exc=RuntimeError("OpenAI API request failed"))
    client = _client(monkeypatch, search=search, generator=generator)

    response = client.post("/v1/critique", json={"plan": "Shelter in place."})

    assert 500 <= response.status_code < 600
    body = response.json()
    assert "error" in body
