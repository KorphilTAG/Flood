"""Offline tests for `critic_eval.runner.run_critic_on_samples`, plus
`critic_eval.ragas_eval.evaluate_records` (spec.md's "Files to change" table
and In-scope item 2 name only four test files -- `test_critic_eval_dataset`,
`_runner`, `_mapping`, `_report` -- with no dedicated file for
`ragas_eval.py`, even though the Acceptance criteria require an offline test
of `evaluate_records`'s fake-`evaluate_fn` behavior. Resolved by placing
those tests in *this* file: `runner.py` and `ragas_eval.py` are both
injectable-callable, service-boundary orchestration modules of the same
kind, and adding a fifth test file was avoided per the explicit four-file
list -- see changes.md).

No real `OPENAI_API_KEY`, no network call, no real built FAISS corpus, and
no real `ragas.evaluate` call anywhere in this file: the `run_critique` and
`evaluate_fn` callables are always test-only fakes.
"""
from __future__ import annotations

import sys

from critic.schemas import CritiqueResponse
from critic_eval.ragas_eval import evaluate_records
from critic_eval.runner import SampleRun, run_critic_on_samples
from critic_eval.settings import Settings


def _canned_response(model: str = "test-model") -> CritiqueResponse:
    return CritiqueResponse(objections=[], alternatives=[], citations=[], decision_point=None, model=model)


class RecordingRunCritique:
    """Fake `run_critique` replacement: returns a canned response for some
    samples (keyed by `plan`) and raises for others; records every call.
    """

    def __init__(self, responses: dict[str, CritiqueResponse], errors: dict[str, Exception]):
        self.responses = responses
        self.errors = errors
        self.calls: list[dict] = []

    def __call__(self, request, settings):
        self.calls.append({"plan": request.plan, "settings": settings})
        if request.plan in self.errors:
            raise self.errors[request.plan]
        return self.responses[request.plan]


def _settings() -> Settings:
    return Settings(aar_index_dir="unused/for/fakes")


def test_run_critic_on_samples_returns_one_sample_run_per_input_sample():
    samples = [{"plan": "Plan A"}, {"plan": "Plan B"}, {"plan": "Plan C"}]
    response = _canned_response()
    fake = RecordingRunCritique(responses={p["plan"]: response for p in samples}, errors={})

    runs = run_critic_on_samples(samples, _settings(), run_critique=fake)

    assert len(runs) == 3
    assert all(isinstance(run, SampleRun) for run in runs)
    assert [run.sample for run in runs] == samples
    assert all(run.error is None for run in runs)
    assert all(run.response is response for run in runs)
    assert len(fake.calls) == 3


def test_run_critic_on_samples_isolates_a_failure_and_still_runs_later_samples():
    samples = [{"plan": "Plan A"}, {"plan": "Plan B (fails)"}, {"plan": "Plan C"}, {"plan": "Plan D"}]
    boom = RuntimeError("corpus not built")
    fake = RecordingRunCritique(
        responses={"Plan A": _canned_response("m-a"), "Plan C": _canned_response("m-c"), "Plan D": _canned_response("m-d")},
        errors={"Plan B (fails)": boom},
    )

    runs = run_critic_on_samples(samples, _settings(), run_critique=fake)

    assert len(runs) == 4
    # Samples after the raising one are still present -- one failure does
    # not abort the batch.
    assert [run.sample["plan"] for run in runs] == [s["plan"] for s in samples]
    assert runs[0].error is None
    assert runs[0].response.model == "m-a"
    assert runs[1].error is boom
    assert runs[1].response is None
    assert runs[2].error is None
    assert runs[2].response.model == "m-c"
    assert runs[3].error is None
    assert runs[3].response.model == "m-d"
    # Every sample was actually attempted, including the ones after the failure.
    assert len(fake.calls) == 4


def test_run_critic_on_samples_captured_exception_round_trips_unchanged():
    samples = [{"plan": "Plan A (fails)"}]
    boom = ValueError("no historical context matched this plan")
    fake = RecordingRunCritique(responses={}, errors={"Plan A (fails)": boom})

    runs = run_critic_on_samples(samples, _settings(), run_critique=fake)

    assert len(runs) == 1
    assert runs[0].error is boom
    assert str(runs[0].error) == "no historical context matched this plan"


# --- critic_eval.ragas_eval.evaluate_records -------------------------------

# Imported here (not lazily) to build fake `evaluate_fn` return values keyed
# by the *actual* metric names `ragas_eval.py` looks up by, without
# hardcoding a metric-name string this test doesn't control (spec.md
# Assumptions: RAGAS's exact metric names may differ by installed version).
from ragas.metrics import Faithfulness, LLMContextPrecisionWithoutReference  # noqa: E402

_FAITHFULNESS_NAME = Faithfulness().name
_CONTEXT_PRECISION_NAME = LLMContextPrecisionWithoutReference().name


def _eval_settings() -> Settings:
    return Settings(ragas_judge_model="test-judge-model")


class _FakeEvaluationResult:
    def __init__(self, scores: list[dict]):
        self.scores = scores


def test_evaluate_records_returns_one_score_dict_per_record_from_fake_evaluate_fn():
    records = [
        {"user_input": "u1", "response": "r1", "retrieved_contexts": ["c1"]},
        {"user_input": "u2", "response": "r2", "retrieved_contexts": ["c2"]},
    ]
    fake_result = _FakeEvaluationResult(
        scores=[
            {_FAITHFULNESS_NAME: 0.8, _CONTEXT_PRECISION_NAME: 0.6},
            {_FAITHFULNESS_NAME: float("nan"), _CONTEXT_PRECISION_NAME: 0.9},
        ]
    )

    def fake_evaluate_fn(dataset, metrics):
        return fake_result

    scores = evaluate_records(records, _eval_settings(), evaluate_fn=fake_evaluate_fn)

    assert scores == [
        {"faithfulness": 0.8, "context_precision": 0.6},
        {"faithfulness": None, "context_precision": 0.9},
    ]


def test_evaluate_records_returns_empty_list_for_empty_records_without_calling_evaluate_fn():
    calls = []

    def fake_evaluate_fn(dataset, metrics):
        calls.append(1)
        return _FakeEvaluationResult(scores=[])

    scores = evaluate_records([], _eval_settings(), evaluate_fn=fake_evaluate_fn)

    assert scores == []
    assert calls == []


def test_evaluate_records_never_imports_langchain_openai_when_evaluate_fn_supplied(monkeypatch):
    # `None` in `sys.modules` makes any `import langchain_openai` raise
    # ImportError -- proving the real-judge-construction branch (which does
    # `from langchain_openai import ChatOpenAI`) is never reached when a
    # fake `evaluate_fn` is supplied.
    monkeypatch.setitem(sys.modules, "langchain_openai", None)

    records = [{"user_input": "u1", "response": "r1", "retrieved_contexts": ["c1"]}]
    fake_result = _FakeEvaluationResult(scores=[{_FAITHFULNESS_NAME: 1.0, _CONTEXT_PRECISION_NAME: 1.0}])
    calls = []

    def fake_evaluate_fn(dataset, metrics):
        calls.append((dataset, metrics))
        return fake_result

    scores = evaluate_records(records, _eval_settings(), evaluate_fn=fake_evaluate_fn)

    assert scores == [{"faithfulness": 1.0, "context_precision": 1.0}]
    assert len(calls) == 1
