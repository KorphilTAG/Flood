"""Pure conversion from successful `SampleRun`s to RAGAS's per-turn input
shape (`user_input`/`response`/`retrieved_contexts`). No LLM call, no
network call -- see spec.md Approach, "RAGAS input mapping", for the exact
field-mapping rationale this module implements.
"""
from __future__ import annotations

from .runner import SampleRun


def _build_user_input(sample: dict) -> str:
    # Mirrors `critic/service.py::_build_query` exactly, so the RAGAS judge
    # is asked about the same input the retriever and the LLM both actually
    # saw, not a differently-worded proxy question.
    situation = sample.get("situation")
    plan = sample["plan"]
    if situation:
        return f"{situation}\n\n{plan}"
    return plan


def _build_response(response) -> str:
    # Every objection's, then every alternative's, `text` field, newline-
    # joined in list order. `chunk_ids` are deliberately not fed to RAGAS --
    # existence is `critic-output-validator`'s job, not this one.
    lines = [item.text for item in response.objections]
    lines.extend(item.text for item in response.alternatives)
    return "\n".join(lines)


def _build_retrieved_contexts(response) -> list[str]:
    # The (already-500-char-truncated) `excerpt` of every retrieved chunk in
    # `citations`, in original order -- not the full untruncated chunk text,
    # and not filtered down to only the chunk IDs the response happened to
    # cite (spec.md Approach explains why both restrictions would be wrong).
    return [citation.excerpt for citation in response.citations]


def to_ragas_records(runs: list[SampleRun]) -> list[dict]:
    """Convert every successful `SampleRun` (one carrying a captured
    exception is excluded here, not silently dropped -- it is reported
    separately by `report.py`) into a RAGAS `SingleTurnSample`-shaped dict:
    `{"user_input": str, "response": str, "retrieved_contexts": list[str]}`.
    """
    records: list[dict] = []
    for run in runs:
        if run.error is not None or run.response is None:
            continue
        records.append(
            {
                "user_input": _build_user_input(run.sample),
                "response": _build_response(run.response),
                "retrieved_contexts": _build_retrieved_contexts(run.response),
            }
        )
    return records
