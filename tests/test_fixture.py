"""Acceptance tests for mini_huc fixture generation and consistency."""
from __future__ import annotations

import json
from pathlib import Path
import pandas as pd
from flood.contracts.validate import validate_json
from flood.engine.cube import HandCube
from flood.scenario import load_scenario


def test_fixture_contents(mini_huc_dir: Path) -> None:
    # 1. Cube loads from fixture directory
    data_dir = mini_huc_dir / "data"
    assert not (mini_huc_dir / "meta.json").exists(), "cube must live only under data/cube/<scenario_id>"
    cube = HandCube.load(data_dir / "cube" / "mini-huc")
    assert cube.grid.width == 40
    assert cube.grid.height == 20
    assert cube.grid.crs == "EPSG:5070"

    # 2. Network topology: 6 reaches with stated topology
    net = cube.network
    assert len(net) == 6
    assert list(net["feature_id"]) == [101, 102, 103, 104, 105, 106]
    assert list(net["to_feature_id"]) == [103, 103, 104, 105, 106, 0]
    assert list(net["stream_order"]) == [2, 2, 3, 3, 3, 3]
    assert list(net["levelpath_id"]) == [9, 8, 9, 9, 9, 9]
    assert all(net["length_m"] == 1000.0)
    assert all(net["slope"] == 0.002)
    assert list(net["preferred_branch"]) == [0, 0, 9, 9, 9, 9]
    assert all(net["in_aoi"])

    # Gauge sites on reaches
    gauge_sites = list(net["gauge_site"])
    assert gauge_sites[0] == "90000001"
    assert pd.isna(gauge_sites[1]) or gauge_sites[1] is None
    assert gauge_sites[2] == "90000003"
    assert pd.isna(gauge_sites[3]) or gauge_sites[3] is None
    assert gauge_sites[4] == "90000005"
    assert pd.isna(gauge_sites[5]) or gauge_sites[5] is None

    # 3. Scenario JSON validates against schema
    scenario_path = mini_huc_dir / "scenario.json"
    assert scenario_path.exists()
    scenario_data = json.loads(scenario_path.read_text(encoding="utf-8"))
    validate_json("scenario", scenario_data)
    scen = load_scenario(scenario_path)
    assert scen.scenario_id == "mini-huc"
    assert len(scen.hydrology.gauges) == 3
    assert len(scen.hydrology.junction_inferences) == 1

    # 4. Forcing Parquet files exist with stated columns
    usgs_pq = data_dir / "usgs" / "mini-huc" / "continuous.parquet"
    assert usgs_pq.exists()
    usgs_df = pd.read_parquet(usgs_pq)
    for col in ("site", "valid_time", "parameter", "value_si"):
        assert col in usgs_df.columns

    analysis_pq = data_dir / "nwm" / "mini-huc" / "analysis.parquet"
    assert analysis_pq.exists()
    analysis_df = pd.read_parquet(analysis_pq)
    for col in ("valid_time", "feature_id", "q_cms", "v_ms", "qlat_cms"):
        assert col in analysis_df.columns

    sr_pq = data_dir / "nwm" / "mini-huc" / "short_range.parquet"
    assert sr_pq.exists()
    sr_df = pd.read_parquet(sr_pq)
    for col in ("issue_time", "valid_time", "feature_id", "q_cms", "qlat_cms"):
        assert col in sr_df.columns
