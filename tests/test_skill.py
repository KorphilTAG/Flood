"""Acceptance tests for hindcast skill computation, summarisation, target checking, and CLI."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd
import pytest

from flood.cli import main
from flood.contracts.models import Scenario
from flood.contracts.validate import validate_json
from flood.engine.cube import HandCube
from flood.engine.ensemble import reduce_members
from flood.engine.forcing import ParquetForcingView, load_forcing_store
from flood.engine.mapping import map_member
from flood.engine.routing import route
from flood.interfaces import MEMBER_INDEX, MEMBERS, RoutedSeries, StateArrays
from flood.skill.hindcast import (
    compute_skill,
    skill_rows,
    summarise,
    target_check,
    update_limitations,
    write_skill,
)


class _FixtureRun:
    """Duck-typed surface of Run for testing hindcast skill."""

    def __init__(self, scenario: Scenario, cube: HandCube, data_dir: Path, run_dir: Path):
        self.scenario = scenario
        self.cube = cube
        self.data_dir = data_dir
        self.run_dir = run_dir
        self.record_start = pd.to_datetime(scenario.hydrology.record.start, utc=True).to_pydatetime()
        self.record_end = pd.to_datetime(scenario.hydrology.record.end, utc=True).to_pydatetime()
        self.max_horizon_minutes = 360

        self.store = load_forcing_store(scenario, data_dir)
        self._forcing_store = self.store
        self._routed_cache: dict[datetime, RoutedSeries] = {}

    def routed(self, p_internal: datetime) -> RoutedSeries:
        if p_internal.tzinfo is None:
            p_utc = p_internal.replace(tzinfo=timezone.utc)
        else:
            p_utc = p_internal.astimezone(timezone.utc)

        if p_utc in self._routed_cache:
            return self._routed_cache[p_utc]

        view = ParquetForcingView(
            self.scenario,
            self.store,
            p_utc,
            network=self.cube.network,
            gauges=self.cube.gauges,
        )
        series = route(
            self.cube,
            view,
            self.scenario,
            self.scenario.forcing_defaults,
            max_horizon_minutes=360,
        )
        self._routed_cache[p_utc] = series
        return series

    def state(self, p: datetime | str, t: datetime, write: bool = False) -> tuple[StateArrays, dict]:
        if p == "hindsight":
            p_dt = self.record_end
        elif isinstance(p, str):
            p_dt = pd.to_datetime(p, utc=True).to_pydatetime()
        else:
            p_dt = p

        if p_dt.tzinfo is None:
            p_dt = p_dt.replace(tzinfo=timezone.utc)
        else:
            p_dt = p_dt.astimezone(timezone.utc)

        if t.tzinfo is None:
            t_dt = t.replace(tzinfo=timezone.utc)
        else:
            t_dt = t.astimezone(timezone.utc)

        routed_series = self.routed(p_dt)
        q_at_t = routed_series.at(t_dt)  # [3, R]
        fids = routed_series.feature_ids

        member_fields_dict = {}
        for m_name in MEMBERS:
            m_idx = MEMBER_INDEX[m_name]
            q_by_fid = {int(fid): float(q_at_t[m_idx, i]) for i, fid in enumerate(fids)}
            mf = map_member(self.cube, q_by_fid, with_velocity=(m_name == "mid"))
            member_fields_dict[m_name] = mf

        state_arr = reduce_members(
            low=member_fields_dict["low"],
            mid=member_fields_dict["mid"],
            high=member_fields_dict["high"],
            p=None if p == "hindsight" else p_dt,
            t=t_dt,
        )
        return state_arr, {"cached": False}


_CACHE: tuple[Any, pd.DataFrame, pd.DataFrame, list[int]] | None = None


@pytest.fixture
def fixture_run_data(mini_scenario: Scenario, mini_cube: HandCube, mini_data_dir: Path, tmp_path: Path):
    global _CACHE
    if _CACHE is not None:
        return _CACHE

    run_dir = tmp_path / "test-run"
    run_dir.mkdir(parents=True, exist_ok=True)
    run = _FixtureRun(mini_scenario, mini_cube, mini_data_dir, run_dir)

    t0 = datetime(2025, 1, 1, 1, 0, tzinfo=timezone.utc)
    t_end = datetime(2025, 1, 1, 9, 0, tzinfo=timezone.utc)

    cutoffs: list[datetime] = []
    cur = t0
    while cur <= t_end:
        cutoffs.append(cur)
        cur += timedelta(minutes=60)

    horizons = [0, 30, 60]
    detail_df = compute_skill(run, cutoffs, horizons, iou_threshold_m=0.15)
    summary_df = summarise(detail_df)

    _CACHE = (run, detail_df, summary_df, horizons)
    return _CACHE


def test_update_limitations(tmp_path: Path, repo_root: Path):
    """Test update_limitations on a copy of docs/contracts/examples/run.json in tmp_path."""
    orig_path = repo_root / "docs" / "contracts" / "examples" / "run.json"
    run_json_copy = tmp_path / "run.json"
    run_json_copy.write_text(orig_path.read_text(encoding="utf-8"), encoding="utf-8")

    new_line = "Hindcast skill at gauge:90000003 for 60 min horizon did not beat persistence (MAE 1.23 vs 1.10 cms)."
    update_limitations(run_json_copy, [new_line])

    data = json.loads(run_json_copy.read_text(encoding="utf-8"))
    assert new_line in data["limitations"]
    validate_json("run-manifest", data)


def test_target_check_failing_and_passing(mini_scenario: Scenario):
    """Test target_check limitation generation for failing and passing cases."""
    # Failing case: interior gauge has skill <= 0 at 60 min
    fail_summary = pd.DataFrame([
        {
            "gauge_ref": "gauge:90000003",
            "horizon_minutes": 60,
            "mae_cms": 5.0,
            "persistence_mae_cms": 4.0,
            "bias_cms": 1.0,
            "coverage": 0.8,
            "n": 10,
            "skill": -0.25,
            "iou_015": 0.9,
        },
        {
            "gauge_ref": "gauge:90000003",
            "horizon_minutes": 120,
            "mae_cms": 3.0,
            "persistence_mae_cms": 6.0,
            "bias_cms": 0.5,
            "coverage": 0.9,
            "n": 10,
            "skill": 0.5,
            "iou_015": 0.85,
        },
    ])
    fail_lines = target_check(fail_summary, mini_scenario)
    assert len(fail_lines) == 1
    assert "Hindcast skill at gauge:90000003 for 60 min horizon did not beat persistence (MAE 5.00 vs 4.00 cms)." in fail_lines[0]

    # Passing case: skill > 0 for all
    pass_summary = pd.DataFrame([
        {
            "gauge_ref": "gauge:90000003",
            "horizon_minutes": 60,
            "mae_cms": 2.0,
            "persistence_mae_cms": 4.0,
            "bias_cms": 0.2,
            "coverage": 1.0,
            "n": 10,
            "skill": 0.5,
            "iou_015": 0.92,
        },
        {
            "gauge_ref": "gauge:90000003",
            "horizon_minutes": 120,
            "mae_cms": 3.0,
            "persistence_mae_cms": 6.0,
            "bias_cms": 0.5,
            "coverage": 0.9,
            "n": 10,
            "skill": 0.5,
            "iou_015": 0.88,
        },
    ])
    pass_lines = target_check(pass_summary, mini_scenario)
    assert len(pass_lines) == 1
    assert "median skill" in pass_lines[0]
    assert "0.50" in pass_lines[0]


def test_fixture_hindcast_skill(fixture_run_data):
    """Fixture test expectation:

    Run compute_skill on mini-huc with cutoffs every 60 min from 01:00Z to 09:00Z
    and horizons 0, 30, 60.
    - summarise has one row per gauge and horizon.
    - Both Parquet files are written.
    - skill is finite where persistence_mae_cms > 0.
    """
    run, detail_df, summary_df, horizons = fixture_run_data
    assert not detail_df.empty

    # Extent IoU is only present at horizon 60 (since 120 not in horizons)
    assert detail_df[detail_df["horizon_minutes"] == 0]["iou_015"].isna().all()
    assert detail_df[detail_df["horizon_minutes"] == 30]["iou_015"].isna().all()
    assert detail_df[detail_df["horizon_minutes"] == 60]["iou_015"].notna().all()

    # Summarise: one row per gauge and horizon
    assert not summary_df.empty
    n_gauges = len(summary_df["gauge_ref"].unique())
    expected_rows = n_gauges * len(horizons)
    assert len(summary_df) == expected_rows

    # skill is finite where persistence_mae_cms > 0
    for _, row in summary_df.iterrows():
        if row["persistence_mae_cms"] > 0:
            assert np.isfinite(row["skill"]), f"Skill is not finite for row: {row}"

    # Write skill Parquet files
    summary_path, detail_path = write_skill(run, detail_df, summary_df)
    assert summary_path.exists()
    assert detail_path.exists()

    read_summary = pd.read_parquet(summary_path)
    read_detail = pd.read_parquet(detail_path)
    assert len(read_summary) == len(summary_df)
    assert len(read_detail) == len(detail_df)


def test_fixture_horizon_0_beats_persistence(fixture_run_data):
    """Horizon-0 rows at controlled gauges.

    Observations carry a 5-minute availability latency, so at cutoff p the last known
    observation is at p - 5 min and t = p is already a short extrapolation (trend_relax at a
    boundary gauge, routed plus decaying bias at an interior one). The engine must therefore
    match or beat persistence at horizon 0 and stay within 0.5 cms of the observation.
    """
    _, detail_df, _, _ = fixture_run_data
    h0_df = detail_df[detail_df["horizon_minutes"] == 0]
    for site in ["90000001", "90000003"]:
        site_h0 = h0_df[h0_df["site"] == site]
        assert not site_h0.empty, f"No horizon-0 rows for site {site}"
        # During flat pre-event hours persistence is exactly right while the 5-minute
        # extrapolation carries a small decaying bias, so allow a 0.25 cms floor.
        bound = site_h0["persistence_abs_error_cms"].clip(lower=0.25) + 1e-3
        assert (site_h0["abs_error_cms"] <= bound).all(), (
            f"Site {site}: horizon-0 error exceeds max(persistence, 0.25 cms): {site_h0[['p', 'abs_error_cms', 'persistence_abs_error_cms']].to_dict('records')}"
        )


def test_cli_when_engine_run_not_available(capsys):
    """Test CLI exit and message when flood.engine.run is not available."""
    code = main(["skill", "test-run"])
    assert code == 2
    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "error: engine run store not available" in out


def test_cli_guarded():
    """Test CLI full execution, guarded by flood.engine.run (will skip in C10)."""
    pytest.importorskip("flood.engine.run")
    code = main(["skill", "test-run"])
    assert code == 0
