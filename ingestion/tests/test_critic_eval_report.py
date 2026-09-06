"""Offline tests for `critic_eval.report.format_report`/`write_report_json`.

Pure functions against canned data -- no RAGAS import, no LLM, no network,
no corpus anywhere in this file.
"""
from __future__ import annotations

import json

from critic_eval.report import format_report, write_report_json
from critic_eval.runner import SampleRun
from critic_eval.settings import Settings


def _settings() -> Settings:
    return Settings(
        aar_index_dir="unused",
        faithfulness_warn_threshold=0.7,
        context_precision_warn_threshold=0.7,
    )


def _run(plan: str, decision_point: str | None = "1:14 a.m. flash flood warning", error=None) -> SampleRun:
    return SampleRun(
        sample={"plan": plan, "decision_point": decision_point},
        response=object() if error is None else None,
        error=error,
    )


def test_format_report_flags_scores_below_threshold():
    runs = [_run("Plan A"), _run("Plan B")]
    records = [{"user_input": "u1"}, {"user_input": "u2"}]
    scores = [
        {"faithfulness": 0.9, "context_precision": 0.9},
        {"faithfulness": 0.4, "context_precision": 0.5},
    ]

    report = format_report(runs, records, scores, _settings())

    assert "Plan A" in report
    assert "Plan B" in report
    lines = report.splitlines()
    plan_a_line = next(line for line in lines if "Plan A" in line)
    plan_b_line = next(line for line in lines if "Plan B" in line)
    assert "below threshold" not in plan_a_line
    assert "below threshold (faithfulness)" in plan_b_line
    assert "below threshold (context_precision)" in plan_b_line


def test_format_report_lists_errored_samples_by_exception_message():
    ok_run = _run("Plan A")
    failed_run = _run("Plan B (fails)", decision_point="2:30 a.m. rising gauge", error=RuntimeError("no historical context matched"))
    runs = [ok_run, failed_run]
    records = [{"user_input": "u1"}]
    scores = [{"faithfulness": 0.9, "context_precision": 0.9}]

    report = format_report(runs, records, scores, _settings())

    assert "Excluded/errored samples (1):" in report
    assert "Plan B (fails)" in report
    assert "no historical context matched" in report


def test_format_report_reports_none_score_as_below_threshold():
    runs = [_run("Plan A")]
    records = [{"user_input": "u1"}]
    scores = [{"faithfulness": None, "context_precision": 0.9}]

    report = format_report(runs, records, scores, _settings())

    lines = report.splitlines()
    plan_a_line = next(line for line in lines if "Plan A" in line)
    assert "below threshold (faithfulness)" in plan_a_line
    assert "n/a" in plan_a_line


def test_write_report_json_writes_valid_json_with_same_per_sample_data(tmp_path):
    ok_run = _run("Plan A")
    failed_run = _run("Plan B (fails)", error=RuntimeError("generation failed"))
    runs = [ok_run, failed_run]
    records = [{"user_input": "u1"}]
    scores = [{"faithfulness": 0.85, "context_precision": 0.6}]

    out_path = tmp_path / "reports" / "run.json"
    write_report_json(runs, records, scores, out_path)

    assert out_path.is_file()
    payload = json.loads(out_path.read_text(encoding="utf-8"))

    assert len(payload["samples"]) == 1
    assert payload["samples"][0]["faithfulness"] == 0.85
    assert payload["samples"][0]["context_precision"] == 0.6
    assert payload["samples"][0]["decision_point"] == "1:14 a.m. flash flood warning"

    assert len(payload["errors"]) == 1
    assert payload["errors"][0]["error"] == "generation failed"


def test_write_report_json_creates_parent_directories(tmp_path):
    runs = [_run("Plan A")]
    records = [{"user_input": "u1"}]
    scores = [{"faithfulness": 1.0, "context_precision": 1.0}]

    out_path = tmp_path / "nested" / "dir" / "run.json"
    write_report_json(runs, records, scores, out_path)

    assert out_path.is_file()
