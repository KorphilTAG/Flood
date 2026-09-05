"""Tests for Run, RunStore, and ResolvedQuery in flood.engine.run."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import pandas as pd
import pytest

from flood.contracts.validate import validate_json
from flood.engine.run import Run, RunStore
from flood.interfaces import TimeGridError


def test_run_create_open_and_store(mini_scenario, mini_data_dir, tmp_path):
    runs_dir = tmp_path / "runs"
    run = Run.create(mini_scenario, "replay", None, runs_dir, mini_data_dir, "0.1.0")
    assert run.run_id.startswith("mini-huc-replay-")
    assert (run.run_dir / "run.json").exists()

    # Re-creating the same configuration does not error and reuses run_dir
    run2 = Run.create(mini_scenario, "replay", None, runs_dir, mini_data_dir, "0.1.0")
    assert run2.run_id == run.run_id

    # Run.open
    opened = Run.open(run.run_dir, mini_data_dir)
    assert opened.run_id == run.run_id

    # RunStore
    store = RunStore(runs_dir, mini_data_dir)
    assert store.exists(run.run_id)
    manifests = store.list()
    assert len(manifests) == 1
    assert manifests[0]["run_id"] == run.run_id

    retrieved = store.get(run.run_id)
    assert retrieved.run_id == run.run_id


def test_run_resolve(mini_scenario, mini_data_dir, tmp_path):
    runs_dir = tmp_path / "runs"
    run = Run.create(mini_scenario, "replay", None, runs_dir, mini_data_dir, "0.1.0")

    # Nowcast
    res_now = run.resolve("2025-01-01T04:00:00Z", "2025-01-01T04:00:00Z")
    assert res_now.mode == "nowcast"
    assert res_now.horizon_minutes == 0

    # Forecast
    res_fc = run.resolve("2025-01-01T04:00:00Z", "2025-01-01T06:00:00Z")
    assert res_fc.mode == "forecast"
    assert res_fc.horizon_minutes == 120
    assert res_fc.p == datetime(2025, 1, 1, 4, 0, tzinfo=timezone.utc)
    assert res_fc.t == datetime(2025, 1, 1, 6, 0, tzinfo=timezone.utc)

    # Hindsight
    res_hind = run.resolve("hindsight", "2025-01-01T06:00:00Z")
    assert res_hind.mode == "hindsight"
    assert res_hind.p is None
    assert res_hind.p_internal == run.record_end
    assert res_hind.horizon_minutes == 0

    # Errors
    with pytest.raises(TimeGridError) as exc_outside:
        run.resolve("2024-01-01T00:00:00Z", "2025-01-01T06:00:00Z")
    assert exc_outside.value.code == "outside_record"

    with pytest.raises(TimeGridError) as exc_t_before_p:
        run.resolve("2025-01-01T06:00:00Z", "2025-01-01T04:00:00Z")
    assert exc_t_before_p.value.code == "t_before_p"

    with pytest.raises(TimeGridError) as exc_horizon:
        run.resolve("2025-01-01T01:00:00Z", "2025-01-01T08:00:00Z")  # 7 hours > 6 hours
    assert exc_horizon.value.code == "horizon_exceeded"


def test_fixture_run_state_and_products(mini_scenario, mini_data_dir, tmp_path):
    runs_dir = tmp_path / "runs"
    run = Run.create(mini_scenario, "replay", None, runs_dir, mini_data_dir, "0.1.0")

    # State call with write=True
    arrays, resp = run.state("2025-01-01T04:00:00Z", "2025-01-01T06:00:00Z", write=True)
    validate_json("state-response", resp)
    assert resp["cache"] == "miss"

    # Verify files created
    depth_tif = run.product_path("raster", "2025-01-01T04:00:00Z", "2025-01-01T06:00:00Z")
    reaches_parquet = run.product_path("reaches", "2025-01-01T04:00:00Z", "2025-01-01T06:00:00Z")
    gauges_parquet = run.product_path("gauges", "2025-01-01T04:00:00Z")
    tte_tif = run.product_path("time_to_exceedance", "2025-01-01T04:00:00Z")

    assert depth_tif.exists()
    assert reaches_parquet.exists()
    assert gauges_parquet.exists()
    assert tte_tif.exists()

    # Reach table check
    reaches_df = run.reaches("2025-01-01T04:00:00Z", "2025-01-01T06:00:00Z")
    assert len(reaches_df) == 6
    r101 = reaches_df[reaches_df["feature_id"] == 101].iloc[0]
    assert r101["source"] == "forecast_trend"

    # Gauge table check
    gauges_df = run.gauges("2025-01-01T04:00:00Z")
    g901 = gauges_df[gauges_df["site"] == "90000001"]
    t_cutoff = pd.Timestamp("2025-01-01T03:55:00Z")
    assert g901[g901["t"] > t_cutoff]["observed_q_cms"].isna().all()

    # Second identical call: cache == "hit", write stage under 5 ms
    arrays2, resp2 = run.state("2025-01-01T04:00:00Z", "2025-01-01T06:00:00Z", write=True)
    validate_json("state-response", resp2)
    assert resp2["cache"] == "hit"
    assert resp2["compute_ms"]["write"] < 5

    # Hindsight state call
    arr_h, resp_h = run.state("hindsight", "2025-01-01T06:00:00Z", write=True)
    validate_json("state-response", resp_h)
    assert resp_h["mode"] == "hindsight"
    h_depth = run.product_path("raster", "hindsight", "2025-01-01T06:00:00Z")
    h_reaches = run.product_path("reaches", "hindsight", "2025-01-01T06:00:00Z")
    assert "hindsight" in str(h_depth)
    assert h_depth.exists()
    assert h_reaches.exists()

    # Check hindsight reach sources have no forecast_trend
    h_reaches_df = run.reaches("hindsight", "2025-01-01T06:00:00Z")
    assert "forecast_trend" not in h_reaches_df["source"].values


def test_cli_run(mini_huc_dir, mini_data_dir, tmp_path, capsys):
    from flood.cli import main

    runs_dir = tmp_path / "cli_runs"
    scenario_json = str(mini_huc_dir / "scenario.json")

    # 1. create
    ret = main(["run", "create", scenario_json, "--runs-dir", str(runs_dir), "--data-dir", str(mini_data_dir)])
    assert ret == 0
    captured = capsys.readouterr()
    run_id = captured.out.strip()
    assert run_id.startswith("mini-huc-replay-")

    # 2. state
    ret = main([
        "run", "state", run_id,
        "--p", "2025-01-01T04:00:00Z",
        "--t", "2025-01-01T06:00:00Z",
        "--write",
        "--runs-dir", str(runs_dir),
        "--data-dir", str(mini_data_dir),
    ])
    assert ret == 0
    captured_state = capsys.readouterr()
    resp = json.loads(captured_state.out)
    validate_json("state-response", resp)
    assert resp["run_id"] == run_id
    assert resp["cache"] == "miss"

    # 3. list
    ret = main(["run", "list", "--runs-dir", str(runs_dir), "--data-dir", str(mini_data_dir)])
    assert ret == 0
    captured_list = capsys.readouterr()
    manifests = json.loads(captured_list.out)
    assert len(manifests) == 1
    assert manifests[0]["run_id"] == run_id

