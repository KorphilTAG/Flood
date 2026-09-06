"""Human-readable (and machine-readable JSON) report rendering.

Pure, RAGAS-import-free: this module never imports `ragas`, `critic`, or
`langchain_openai` -- it only reads plain dicts/dataclasses already produced
by `runner.py`/`mapping.py`/`ragas_eval.py`.
"""
from __future__ import annotations

import json
from pathlib import Path

from .runner import SampleRun
from .settings import Settings

_PLAN_EXCERPT_LENGTH = 80


def _plan_excerpt(sample: dict) -> str:
    plan = sample.get("plan", "")
    if len(plan) <= _PLAN_EXCERPT_LENGTH:
        return plan
    return plan[:_PLAN_EXCERPT_LENGTH].rstrip() + "..."


def _decision_point(sample: dict) -> str:
    return sample.get("decision_point") or "(no decision_point)"


def _successful_runs(sample_runs: list[SampleRun]) -> list[SampleRun]:
    return [run for run in sample_runs if run.error is None]


def _errored_runs(sample_runs: list[SampleRun]) -> list[SampleRun]:
    return [run for run in sample_runs if run.error is not None]


def _below(score: float | None, threshold: float) -> bool:
    return score is None or score < threshold


def _score_rows(sample_runs: list[SampleRun], records: list[dict], scores: list[dict], settings: Settings) -> list[dict]:
    successful = _successful_runs(sample_runs)
    if not (len(successful) == len(records) == len(scores)):
        raise ValueError(
            "sample_runs (non-errored), records, and scores must have matching "
            f"lengths: {len(successful)}, {len(records)}, {len(scores)}"
        )
    rows = []
    for run, score in zip(successful, scores):
        faithfulness = score.get("faithfulness")
        context_precision = score.get("context_precision")
        rows.append(
            {
                "decision_point": _decision_point(run.sample),
                "plan_excerpt": _plan_excerpt(run.sample),
                "faithfulness": faithfulness,
                "context_precision": context_precision,
                "below_faithfulness_threshold": _below(faithfulness, settings.faithfulness_warn_threshold),
                "below_context_precision_threshold": _below(
                    context_precision, settings.context_precision_warn_threshold
                ),
            }
        )
    return rows


def _error_rows(sample_runs: list[SampleRun]) -> list[dict]:
    return [
        {
            "decision_point": _decision_point(run.sample),
            "plan_excerpt": _plan_excerpt(run.sample),
            "error": str(run.error),
        }
        for run in _errored_runs(sample_runs)
    ]


def _format_score(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def format_report(
    sample_runs: list[SampleRun], records: list[dict], scores: list[dict], settings: Settings
) -> str:
    """Render a human-readable report: one row per successfully-scored
    sample (decision point, a truncated plan excerpt, faithfulness score,
    context-precision score, and a `below threshold` marker per
    `settings.faithfulness_warn_threshold`/`context_precision_warn_threshold`),
    plus a trailing section listing any excluded/errored sample by its
    captured exception message.
    """
    rows = _score_rows(sample_runs, records, scores, settings)
    errors = _error_rows(sample_runs)

    lines = ["Citation quality evaluation (RAGAS) report", "=" * 43, ""]
    header = f"{'decision_point':<35} {'plan_excerpt':<45} {'faithfulness':>12} {'context_precision':>18}  flag"
    lines.append(header)
    lines.append("-" * len(header))
    for row in rows:
        flags = []
        if row["below_faithfulness_threshold"]:
            flags.append("below threshold (faithfulness)")
        if row["below_context_precision_threshold"]:
            flags.append("below threshold (context_precision)")
        flag_text = "; ".join(flags)
        lines.append(
            f"{row['decision_point']:<35} {row['plan_excerpt']:<45} "
            f"{_format_score(row['faithfulness']):>12} {_format_score(row['context_precision']):>18}  {flag_text}"
        )
    if not rows:
        lines.append("(no successfully-scored samples)")

    lines.append("")
    lines.append(f"Excluded/errored samples ({len(errors)}):")
    if not errors:
        lines.append("  (none)")
    else:
        for error in errors:
            lines.append(
                f"  - {error['decision_point']} [{error['plan_excerpt']}]: {error['error']}"
            )

    return "\n".join(lines) + "\n"


def write_report_json(
    sample_runs: list[SampleRun], records: list[dict], scores: list[dict], path: str | Path
) -> None:
    """Write the same per-sample data `format_report` renders (decision
    point, plan excerpt, faithfulness/context-precision scores, and the
    errored-sample section) to `path` as JSON, for archiving a specific
    pre-demo run. Takes no `settings` (unlike `format_report`) -- the JSON
    records raw per-metric scores; warn-threshold flags are a report-time
    presentation detail, not archived data.
    """
    successful = _successful_runs(sample_runs)
    if not (len(successful) == len(records) == len(scores)):
        raise ValueError(
            "sample_runs (non-errored), records, and scores must have matching "
            f"lengths: {len(successful)}, {len(records)}, {len(scores)}"
        )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "samples": [
            {
                "decision_point": _decision_point(run.sample),
                "plan_excerpt": _plan_excerpt(run.sample),
                "faithfulness": score.get("faithfulness"),
                "context_precision": score.get("context_precision"),
            }
            for run, score in zip(successful, scores)
        ],
        "errors": _error_rows(sample_runs),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
