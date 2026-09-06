"""Contract 2 schema behaviour: what it accepts, and what it must refuse."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from flood.contracts.validate import ContractError, validate_json


@pytest.fixture
def sample(repo_root: Path) -> dict:
    return json.loads(
        (repo_root / "docs" / "contracts" / "examples" / "impact-response.sample.json").read_text()
    )


def test_packaged_schema_matches_the_documented_one(repo_root: Path):
    """The package copy is the one code validates against; it must not drift."""
    docs = json.loads((repo_root / "docs" / "contracts" / "schemas" / "impact-json.schema.json").read_text())
    packaged = json.loads(
        (repo_root / "src" / "flood" / "contracts" / "schemas" / "impact-json.schema.json").read_text()
    )
    assert docs == packaged


def test_sample_validates(sample):
    validate_json("impact-json", sample)


def test_schema_is_registered_by_name():
    from flood.contracts.validate import SCHEMA_NAMES

    assert "impact-json" in SCHEMA_NAMES


@pytest.mark.parametrize("field", ["schema_version", "run_id", "p", "t", "velocity_is_proxy", "facts", "egress", "reaches"])
def test_required_top_level_fields(sample, field):
    del sample[field]
    with pytest.raises(ContractError):
        validate_json("impact-json", sample)


def test_velocity_is_proxy_must_be_true(sample):
    sample["velocity_is_proxy"] = False
    with pytest.raises(ContractError):
        validate_json("impact-json", sample)


def test_p_may_be_null_for_hindsight(sample):
    sample["p"] = None
    validate_json("impact-json", sample)


def test_unknown_top_level_key_is_rejected(sample):
    sample["raster_path"] = "runs/x/depth.tif"
    with pytest.raises(ContractError):
        validate_json("impact-json", sample)


@pytest.mark.parametrize("banned", ["geometry", "coordinates", "lon", "lat"])
def test_fact_rejects_geometry_and_coordinate_keys(sample, banned):
    sample["facts"][0][banned] = 1.0
    with pytest.raises(ContractError):
        validate_json("impact-json", sample)


@pytest.mark.parametrize("banned", ["geometry", "coordinates", "lon", "lat"])
def test_attributes_reject_geometry_and_coordinate_names(sample, banned):
    sample["facts"][0]["attributes"][banned] = 1.0
    with pytest.raises(ContractError):
        validate_json("impact-json", sample)


def test_attribute_values_must_be_scalar(sample):
    sample["facts"][0]["attributes"]["nested"] = {"lon": 1.0}
    with pytest.raises(ContractError):
        validate_json("impact-json", sample)


def test_feature_ref_must_be_layer_qualified(sample):
    sample["facts"][0]["feature_ref"] = "cr-17"
    with pytest.raises(ContractError):
        validate_json("impact-json", sample)


def test_reach_ref_format_is_enforced(sample):
    sample["reaches"][0]["reach_ref"] = "reach:not-a-number"
    with pytest.raises(ContractError):
        validate_json("impact-json", sample)


def test_fact_kind_is_constrained(sample):
    sample["facts"][0]["kind"] = "evacuate"
    with pytest.raises(ContractError):
        validate_json("impact-json", sample)


def test_egress_status_is_constrained(sample):
    sample["egress"][0]["status"] = "probably fine"
    with pytest.raises(ContractError):
        validate_json("impact-json", sample)


def test_reach_row_rejects_extra_engine_columns(sample):
    """Contract 2 keeps five reach fields; the sidecar's other columns must not leak."""
    sample["reaches"][0]["q_mid_cms"] = 412.0
    with pytest.raises(ContractError):
        validate_json("impact-json", sample)
