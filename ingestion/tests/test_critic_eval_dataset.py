"""Offline tests for `critic_eval.dataset.load_sample_plans`.

No LLM/network/corpus access anywhere in this file -- it only reads local
JSON fixtures.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from critic.schemas import CritiqueRequest
from critic_eval.dataset import load_sample_plans

REAL_FIXTURE_PATH = Path(__file__).resolve().parent.parent / "critic_eval" / "fixtures" / "sample_plans.json"


def test_load_sample_plans_returns_a_list_of_dicts_constructible_as_critique_requests():
    samples = load_sample_plans(REAL_FIXTURE_PATH)
    assert isinstance(samples, list)
    assert len(samples) >= 5
    for sample in samples:
        assert isinstance(sample, dict)
        CritiqueRequest(**sample)  # must not raise


def test_real_fixture_has_at_least_one_entry_per_named_decision_point():
    samples = load_sample_plans(REAL_FIXTURE_PATH)
    decision_points = {sample.get("decision_point") for sample in samples}
    assert any("1:14" in dp for dp in decision_points if dp)
    assert any("2:30" in dp for dp in decision_points if dp)
    assert any("4:03" in dp for dp in decision_points if dp)


def test_load_sample_plans_raises_value_error_naming_the_offending_entry_on_blank_plan(tmp_path):
    broken = {
        "entries": [
            {"decision_point": "1:14 a.m. flash flood warning", "plan": "A perfectly fine plan."},
            {"decision_point": "2:30 a.m. rising gauge", "plan": "   "},
        ]
    }
    fixture_path = tmp_path / "broken_sample_plans.json"
    fixture_path.write_text(json.dumps(broken), encoding="utf-8")

    with pytest.raises(ValueError, match="2:30 a.m. rising gauge"):
        load_sample_plans(fixture_path)


def test_load_sample_plans_raises_value_error_naming_the_offending_entry_on_missing_plan(tmp_path):
    broken = {
        "entries": [
            {"decision_point": "4:03 a.m. flash flood emergency"},
        ]
    }
    fixture_path = tmp_path / "broken_sample_plans.json"
    fixture_path.write_text(json.dumps(broken), encoding="utf-8")

    with pytest.raises(ValueError, match="4:03 a.m. flash flood emergency"):
        load_sample_plans(fixture_path)


def test_load_sample_plans_raises_value_error_on_malformed_json(tmp_path):
    fixture_path = tmp_path / "malformed.json"
    fixture_path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ValueError):
        load_sample_plans(fixture_path)


def test_load_sample_plans_raises_value_error_when_entries_key_is_missing(tmp_path):
    fixture_path = tmp_path / "no_entries.json"
    fixture_path.write_text(json.dumps({"not_entries": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="entries"):
        load_sample_plans(fixture_path)


def test_load_sample_plans_raises_value_error_when_an_entry_is_not_an_object(tmp_path):
    fixture_path = tmp_path / "bad_entry.json"
    fixture_path.write_text(json.dumps({"entries": ["not-an-object"]}), encoding="utf-8")

    with pytest.raises(ValueError, match="entry 0"):
        load_sample_plans(fixture_path)
