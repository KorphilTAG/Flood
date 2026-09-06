"""PRD Addendum 2: static vulnerability x live hazard depth fusion.

No PostGIS and no rasters: the impact-extractor side is a synthetic Contract 2
payload (already-validated shape from test_impact_contract.py's sample), and the
vulnerability side is a synthetic Addendum 1 GeoJSON. The multiplicative fusion,
the feature_id<->feature_ref mapping, and the output-validator extension are all
pure functions of those two inputs.
"""
from __future__ import annotations

import json

import pytest

from flood.contracts.validate import validate_json
from flood.impact.exposure_fusion import (
    DEFAULT_DEPTH_THRESHOLD_M,
    ExposureFusionError,
    compute_exposure_layer,
    demographic_feature_id_to_feature_ref,
    depth_threshold_for,
    normalize_depth,
    validate_exposure_layer,
    weights_from_geojson,
)


# ---------------------------------------------------------------------------
# feature_id <-> feature_ref (Section 4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "feature_id, expected",
    [
        ("building:osm:way/123456", "structure:osm.way.123456"),
        ("building:osm:relation/987", "structure:osm.relation.987"),
    ],
)
def test_feature_id_mapping_matches_the_exposure_view_transform(feature_id, expected):
    """Must mirror ingestion/db/exposure_views.sql's kerr_2025_07_04_structure view exactly,
    or the join in Section 4 silently produces a heatmap with no data."""
    assert demographic_feature_id_to_feature_ref(feature_id) == expected


def test_feature_id_mapping_rejects_empty_id():
    with pytest.raises(ExposureFusionError):
        demographic_feature_id_to_feature_ref("")


# ---------------------------------------------------------------------------
# Static layer indexing (Section 5 / Addendum 1 abstention rule)
# ---------------------------------------------------------------------------


def _geojson(*props_list):
    return {
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "properties": p} for p in props_list],
    }


def test_abstained_footprints_are_never_treated_as_zero():
    geojson = _geojson(
        {"feature_id": "building:osm:way/1", "weight": 0.5, "citation_ids": ["a"]},
        {"feature_id": "building:osm:way/2", "weight": None, "citation_ids": ["b"], "score_source": "insufficient_data"},
    )
    weights = weights_from_geojson(geojson)
    assert set(weights) == {"structure:osm.way.1"}


def test_weight_zero_is_kept_distinct_from_abstained():
    """weight=0.0 is a real (if minimal) score and must survive; only weight=None abstains."""
    geojson = _geojson({"feature_id": "building:osm:way/1", "weight": 0.0, "citation_ids": ["a"]})
    weights = weights_from_geojson(geojson)
    assert weights["structure:osm.way.1"]["weight"] == 0.0


# ---------------------------------------------------------------------------
# Normalization and threshold lookup (Section 3)
# ---------------------------------------------------------------------------


def test_normalize_depth_clamps_to_unit_interval():
    assert normalize_depth(0.0, 0.1) == 0.0
    assert normalize_depth(0.05, 0.1) == pytest.approx(0.5)
    assert normalize_depth(10.0, 0.1) == 1.0


def test_normalize_depth_zero_threshold_is_zero_not_a_crash():
    assert normalize_depth(1.0, 0.0) == 0.0


def test_depth_threshold_for_reads_the_structure_layers_threatened_depth(kerr_scenario):
    assert depth_threshold_for(kerr_scenario) == pytest.approx(0.1)


def test_depth_threshold_for_falls_back_when_layer_absent(kerr_scenario):
    assert depth_threshold_for(kerr_scenario, layer_id="no-such-layer") == DEFAULT_DEPTH_THRESHOLD_M


# ---------------------------------------------------------------------------
# Multiplicative fusion (Section 3 / Section 6)
# ---------------------------------------------------------------------------


@pytest.fixture
def impact_payload():
    return {
        "schema_version": "1.0",
        "run_id": "kerr-2025-07-04-replay-a1b2c3",
        "p": "2025-07-04T06:10:00Z",
        "t": "2025-07-04T06:45:00Z",
        "velocity_is_proxy": True,
        "facts": [
            {"feature_ref": "structure:osm.way.1", "kind": "threatened", "impacted_now": False,
             "depth_max_m": 0.05, "depth_mean_m": 0.05, "wet_fraction": 1.0,
             "hazard_dv_max_m2_per_s": 0.0, "attributes": {}, "first_impacted_t": "2025-07-04T06:45:00Z",
             "projections": []},
            {"feature_ref": "structure:osm.way.2", "kind": "threatened", "impacted_now": True,
             "depth_max_m": 0.5, "depth_mean_m": 0.4, "wet_fraction": 1.0,
             "hazard_dv_max_m2_per_s": 0.2, "attributes": {}, "first_impacted_t": "2025-07-04T06:15:00Z",
             "projections": []},
        ],
        "egress": [],
        "reaches": [],
    }


@pytest.fixture
def vulnerability_weights():
    return {
        "structure:osm.way.1": {"weight": 0.8, "citation_ids": ["acs:x"]},
        "structure:osm.way.2": {"weight": 0.0, "citation_ids": ["acs:y"]},
        # No hazard fact exists for this footprint at this t; must never appear in the output.
        "structure:osm.way.3": {"weight": 0.9, "citation_ids": ["acs:z"]},
    }


def test_dry_but_vulnerable_footprint_scores_zero_not_a_glow(impact_payload, vulnerability_weights):
    """Section 3's core claim: multiplication, not addition. depth 0.05m against a 0.1m
    threshold is non-zero hazard, so this checks the *weight* math, not just the zero case."""
    features = compute_exposure_layer(impact_payload, vulnerability_weights, depth_threshold_m=0.1)
    by_id = {f["feature_id"]: f for f in features}
    assert by_id["structure:osm.way.1"]["weight"] == pytest.approx(0.8 * 0.5)
    assert by_id["structure:osm.way.1"]["hazard_severity_t"] == pytest.approx(0.5)


def test_footprint_with_no_hazard_reading_is_omitted_not_zeroed(impact_payload, vulnerability_weights):
    features = compute_exposure_layer(impact_payload, vulnerability_weights, depth_threshold_m=0.1)
    assert "structure:osm.way.3" not in {f["feature_id"] for f in features}


def test_zero_vulnerability_still_multiplies_through_to_zero(impact_payload, vulnerability_weights):
    features = compute_exposure_layer(impact_payload, vulnerability_weights, depth_threshold_m=0.1)
    by_id = {f["feature_id"]: f for f in features}
    assert by_id["structure:osm.way.2"]["weight"] == 0.0
    assert by_id["structure:osm.way.2"]["hazard_severity_t"] == 1.0  # hazard itself is not zero


def test_citation_ids_carry_forward_plus_the_impact_extractor_trace(impact_payload, vulnerability_weights):
    features = compute_exposure_layer(impact_payload, vulnerability_weights, depth_threshold_m=0.1, run_id="run-x")
    by_id = {f["feature_id"]: f for f in features}
    ids = by_id["structure:osm.way.1"]["citation_ids"]
    assert ids[:-1] == ["acs:x"]
    assert ids[-1] == "impact_extractor:run-x:2025-07-04T06:45:00Z"


def test_output_matches_the_exposure_density_contract(impact_payload, vulnerability_weights):
    features = compute_exposure_layer(impact_payload, vulnerability_weights, depth_threshold_m=0.1, run_id="run-x")
    validate_json("exposure-density", features)


def test_documented_sample_validates(repo_root):
    sample = json.loads(
        (repo_root / "docs" / "contracts" / "examples" / "exposure-density.sample.json").read_text()
    )
    validate_json("exposure-density", sample)


def test_packaged_schema_matches_the_documented_one(repo_root):
    """The package copy is the one code validates against; it must not drift."""
    docs = json.loads((repo_root / "docs" / "contracts" / "schemas" / "exposure-density.schema.json").read_text())
    packaged = json.loads(
        (repo_root / "src" / "flood" / "contracts" / "schemas" / "exposure-density.schema.json").read_text()
    )
    assert docs == packaged


def test_schema_is_registered_by_name():
    from flood.contracts.validate import SCHEMA_NAMES

    assert "exposure-density" in SCHEMA_NAMES


# ---------------------------------------------------------------------------
# Output validator extension (Section 8)
# ---------------------------------------------------------------------------


def test_validator_accepts_well_formed_output(impact_payload, vulnerability_weights):
    features = compute_exposure_layer(impact_payload, vulnerability_weights, depth_threshold_m=0.1)
    validate_exposure_layer(features, impact_payload)  # must not raise


def test_validator_rejects_a_feature_id_not_backed_by_this_ticks_facts(impact_payload, vulnerability_weights):
    features = compute_exposure_layer(impact_payload, vulnerability_weights, depth_threshold_m=0.1)
    forged = [{**features[0], "feature_id": "structure:osm.way.404"}]
    with pytest.raises(ExposureFusionError):
        validate_exposure_layer(forged, impact_payload)


def test_validator_rejects_a_stale_or_future_tick(impact_payload, vulnerability_weights):
    """Guards the race condition: a frontend requesting a tick the backend has not produced yet."""
    features = compute_exposure_layer(impact_payload, vulnerability_weights, depth_threshold_m=0.1)
    stale = [{**features[0], "t": "2025-07-04T05:00:00Z"}]
    with pytest.raises(ExposureFusionError):
        validate_exposure_layer(stale, impact_payload)


def test_validator_rejects_missing_citations(impact_payload, vulnerability_weights):
    features = compute_exposure_layer(impact_payload, vulnerability_weights, depth_threshold_m=0.1)
    uncited = [{**features[0], "citation_ids": []}]
    with pytest.raises(ExposureFusionError):
        validate_exposure_layer(uncited, impact_payload)
