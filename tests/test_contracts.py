"""Acceptance tests for contracts, schema validation, and Pydantic models."""
from __future__ import annotations

import json
from pathlib import Path
import re
import pytest
from pydantic import ValidationError
from flood.contracts.models import (
    GaugeRow,
    ReachRow,
    RunManifest,
    Scenario,
    StateResponse,
)
from flood.contracts.validate import ContractError, validate_json


def test_schemas_byte_identical(repo_root: Path) -> None:
    docs_schemas = repo_root / "docs" / "contracts" / "schemas"
    src_schemas = repo_root / "src" / "flood" / "contracts" / "schemas"

    doc_files = sorted(docs_schemas.glob("*.json"))
    assert len(doc_files) > 0

    for doc_file in doc_files:
        src_file = src_schemas / doc_file.name
        assert src_file.exists(), f"Missing schema in src: {doc_file.name}"
        assert (
            src_file.read_bytes() == doc_file.read_bytes()
        ), f"Schema byte mismatch: {doc_file.name}"


def test_examples_validate_and_parse(repo_root: Path) -> None:
    examples_dir = repo_root / "docs" / "contracts" / "examples"

    # 1. run.json -> run-manifest
    run_data = json.loads((examples_dir / "run.json").read_text(encoding="utf-8"))
    validate_json("run-manifest", run_data)
    manifest = RunManifest.model_validate(run_data)
    assert manifest.run_id == run_data["run_id"]

    # 2. scenario.kerr-2025-07-04.json -> scenario
    scenario_data = json.loads(
        (examples_dir / "scenario.kerr-2025-07-04.json").read_text(encoding="utf-8")
    )
    validate_json("scenario", scenario_data)
    scenario = Scenario.model_validate(scenario_data)
    assert scenario.scenario_id == scenario_data["scenario_id"]

    # 3. state-response.json -> state-response
    state_data = json.loads(
        (examples_dir / "state-response.json").read_text(encoding="utf-8")
    )
    validate_json("state-response", state_data)
    state = StateResponse.model_validate(state_data)
    assert state.run_id == state_data["run_id"]

    # 4. reaches.sample.json -> list of reach-row
    reaches_data = json.loads(
        (examples_dir / "reaches.sample.json").read_text(encoding="utf-8")
    )
    assert isinstance(reaches_data, list)
    for row in reaches_data:
        validate_json("reach-row", row)
        reach = ReachRow.model_validate(row)
        assert reach.reach_ref == row["reach_ref"]

    # 5. gauges.sample.json -> list of gauge-row
    gauges_data = json.loads(
        (examples_dir / "gauges.sample.json").read_text(encoding="utf-8")
    )
    assert isinstance(gauges_data, list)
    for row in gauges_data:
        validate_json("gauge-row", row)
        gauge = GaugeRow.model_validate(row)
        assert gauge.gauge_ref == row["gauge_ref"]


def test_extra_field_fails_validation(repo_root: Path) -> None:
    examples_dir = repo_root / "docs" / "contracts" / "examples"
    run_data = json.loads((examples_dir / "run.json").read_text(encoding="utf-8"))
    run_data["unexpected_extra_field"] = "illegal"

    with pytest.raises(ContractError):
        validate_json("run-manifest", run_data)

    with pytest.raises(ValidationError):
        RunManifest.model_validate(run_data)


def test_no_scenario_literals_in_src(repo_root: Path) -> None:
    src_dir = repo_root / "src"
    pattern = re.compile(r"Kerr|Hunt|Guadalupe|Mystic|12100201|0816")

    matches: list[str] = []
    for path in src_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        found = pattern.findall(text)
        if found:
            matches.append(f"{path.relative_to(repo_root)}: {set(found)}")

    assert not matches, f"Forbidden scenario literals found in src/: {matches}"
