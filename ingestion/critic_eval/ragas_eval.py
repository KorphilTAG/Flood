"""Builds the RAGAS evaluation dataset/metrics and scores each record.

Faithfulness and (a no-reference variant of) context precision are the two
PRD 11 names (spec.md Approach). No ground-truth `reference` field is ever
populated for either metric -- both are the no-reference variants, per
PRD 5's own framing ("without requiring hand-labeled ground truth").

`ragas.metrics` and `ragas.dataset_schema` are imported at module load (no
OpenAI/network dependency there -- these are just dataclass/metric
definitions). `langchain_openai.ChatOpenAI` and `ragas.llms.LangchainLLMWrapper`
(the real judge LLM) are imported lazily, and constructed only on the
default (`evaluate_fn=None`) path -- a caller-supplied `evaluate_fn` (every
offline test) never triggers that import, matching `critic/llm.py`'s own
lazy-import convention for the same reason.
"""
from __future__ import annotations

import math
from typing import Callable

from ragas.dataset_schema import EvaluationDataset, SingleTurnSample
from ragas.metrics import Faithfulness, LLMContextPrecisionWithoutReference

from .settings import Settings

EvaluateFn = Callable[..., object]

# Constructing these does not call an LLM or require an API key -- they are
# metric *definitions*; the LLM judge is bound at `evaluate()` call time
# (real path) or ignored entirely (fake `evaluate_fn` path).
_FAITHFULNESS_METRIC = Faithfulness()
_CONTEXT_PRECISION_METRIC = LLMContextPrecisionWithoutReference()


def _coerce_score(value: object) -> float | None:
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(value):
        return None
    return value


def _extract_scores(result: object, expected_count: int) -> list[dict]:
    scores = getattr(result, "scores", None)
    if scores is None:
        raise ValueError(
            "evaluate_fn/ragas.evaluate result has no 'scores' attribute "
            "(expected a RAGAS EvaluationResult, or a fake exposing the same "
            "'.scores: list[dict]' shape)"
        )
    if len(scores) != expected_count:
        raise ValueError(
            f"evaluate_fn/ragas.evaluate returned {len(scores)} score rows for "
            f"{expected_count} input records"
        )
    return [
        {
            "faithfulness": _coerce_score(row.get(_FAITHFULNESS_METRIC.name)),
            "context_precision": _coerce_score(row.get(_CONTEXT_PRECISION_METRIC.name)),
        }
        for row in scores
    ]


def evaluate_records(
    records: list[dict],
    settings: Settings,
    *,
    evaluate_fn: EvaluateFn | None = None,
) -> list[dict]:
    """Score every RAGAS-shaped record (see `mapping.py::to_ragas_records`)
    for faithfulness and (no-reference) context precision, returning one
    score dict per input record: `{"faithfulness": float | None,
    "context_precision": float | None}` (`None` on a per-metric scoring
    failure -- e.g. RAGAS returning `NaN` -- not a crash of the whole run).

    `evaluate_fn` defaults to `ragas.evaluate`, called with a real
    `ragas.llms.LangchainLLMWrapper`-wrapped `langchain_openai.ChatOpenAI`
    judge (model from `settings.ragas_judge_model`) -- a real run therefore
    requires a real `OPENAI_API_KEY` and network access. Passing a fake
    `evaluate_fn` (every offline test) bypasses both entirely: no OpenAI/
    LangChain client is imported or constructed on that path.
    """
    if not records:
        return []

    dataset = EvaluationDataset(samples=[SingleTurnSample(**record) for record in records])
    metrics = [_FAITHFULNESS_METRIC, _CONTEXT_PRECISION_METRIC]

    if evaluate_fn is not None:
        result = evaluate_fn(dataset=dataset, metrics=metrics)
    else:
        from langchain_openai import ChatOpenAI
        from ragas import evaluate as ragas_evaluate
        from ragas.llms import LangchainLLMWrapper

        judge_llm = LangchainLLMWrapper(ChatOpenAI(model=settings.ragas_judge_model, temperature=0))
        result = ragas_evaluate(dataset=dataset, metrics=metrics, llm=judge_llm)

    return _extract_scores(result, len(records))
