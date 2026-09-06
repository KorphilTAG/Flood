"""Unit tests for flood.products.manifest."""
from __future__ import annotations

import hashlib
import json
from flood.contracts.validate import validate_json
from flood.interfaces import Grid
from flood.products.manifest import (
    ENGINE_LIMITATIONS,
    build_manifest,
    config_hash,
    make_run_id,
    merge_forcing,
)


def test_config_hash_and_make_run_id():
    cfg = {"routing": {"method": "muskingum_cunge", "dt_minutes": 1}}
    h = config_hash(cfg)
    expected_hex = hashlib.sha256(json.dumps(cfg, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    assert h == f"sha256:{expected_hex}"

    run_id = make_run_id("test-scenario", "replay", h)
    assert run_id == f"test-scenario-replay-{expected_hex[:6]}"


def test_merge_forcing(mini_scenario):
    defaults = mini_scenario.forcing_defaults.model_dump(mode="json", exclude_none=True)
    overrides = {
        "routing": {"dt_minutes": 2},
        "boundary_forecast": {
            "members": {"low": 0.3, "mid": 1.0, "high": 1.7}
        }
    }
    merged = merge_forcing(defaults, overrides)
    validate_json("forcing-config", merged)
    assert merged["routing"]["dt_minutes"] == 2
    assert merged["routing"]["method"] == defaults["routing"]["method"]
    assert merged["boundary_forecast"]["members"]["low"] == 0.3
    assert merged["boundary_forecast"]["members"]["high"] == 1.7


def test_merge_forcing_replaces_lists(mini_scenario):
    defaults = mini_scenario.forcing_defaults.model_dump(mode="json", exclude_none=True)
    new_sources = [
        {"type": "usgs_continuous", "availability_latency_min": 10, "sites": ["90000001"]}
    ]
    merged = merge_forcing(defaults, {"sources": new_sources})
    validate_json("forcing-config", merged)
    assert len(merged["sources"]) == 1
    assert merged["sources"][0]["availability_latency_min"] == 10


def test_build_manifest(mini_scenario):
    grid = Grid.from_bounds((0.0, 0.0, 400.0, 200.0), resolution_m=10.0)
    defaults = mini_scenario.forcing_defaults.model_dump(mode="json", exclude_none=True)
    manifest = build_manifest(mini_scenario, "replay", defaults, grid, "0.1.0")

    validate_json("run-manifest", manifest)
    assert manifest["schema_version"] == "1.0"
    assert manifest["mode"] == "replay"
    assert manifest["engine_version"] == "0.1.0"
    assert manifest["run_id"].startswith("mini-huc-replay-")
    assert manifest["products"]["raster"] == "products/p={p}/t={t}/depth.tif"
    assert manifest["products"]["hindsight_raster"] == "hindsight/t={t}/depth.tif"

    # Limitations check
    for item in ENGINE_LIMITATIONS:
        assert item in manifest["limitations"]
    # Junction inference check
    assert any("Tributary 102 inference at 103" in lim for lim in manifest["limitations"])
    # A Manning n scale other than 1 is disclosed as a limitation and changes the run id.
    scaled = build_manifest(
        mini_scenario, "replay", {**defaults, "roughness": {"manning_n_scale": 0.5}}, grid, "0.1.0"
    )
    validate_json("run-manifest", scaled)
    assert any("Manning n scale of 0.5" in lim for lim in scaled["limitations"])
    assert scaled["run_id"] != manifest["run_id"]
    assert not any("Manning n scale" in lim for lim in manifest["limitations"])
