"""Offline checks for deterministic missing-person search-area estimates."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, shape

from flood.interfaces import Grid, StateArrays
from flood.search_area import (
    SearchAreaInputError,
    SearchAreaTool,
    estimate_missing_person_search_area,
)


UTC = timezone.utc
P = "2025-01-01T00:00:00Z"
T = "2025-01-01T00:05:00Z"


class _MiniRun:
    def __init__(self, *, dry: bool = False, lkp_lon: float = 0.0) -> None:
        self.run_id = "mini-search-run"
        self.manifest = {"time": {"max_horizon_minutes": 10}}
        self.grid = Grid.from_bounds((-100.0, -100.0, 500.0, 100.0), resolution_m=10.0, crs="EPSG:3857")
        self.cube = SimpleNamespace(
            grid=self.grid,
            network=pd.DataFrame(
                [
                    {"feature_id": 1, "to_feature_id": 2, "flowline_wkb": LineString([(0, 0), (200, 0)]).wkb},
                    {"feature_id": 2, "to_feature_id": 0, "flowline_wkb": LineString([(200, 0), (400, 0)]).wkb},
                    # This unconnected upstream reach must never enter the route.
                    {"feature_id": 3, "to_feature_id": 1, "flowline_wkb": LineString([(-90, 50), (-20, 50)]).wkb},
                ]
            ),
        )
        self.scenario = SimpleNamespace(
            last_known_positions=[SimpleNamespace(id="lkp_test", t=P, lon=lkp_lon, lat=0.0)]
        )
        depth = np.zeros((self.grid.height, self.grid.width), dtype=np.float32)
        velocity = np.zeros_like(depth)
        if not dry:
            # Rows around y=0 and columns spanning the downstream chain are wet.
            depth[8:12, 10:51] = 1.0
            velocity[8:12, 10:51] = 1.0
        target = datetime(2025, 1, 1, 0, 5, tzinfo=UTC)
        self.arrays = StateArrays(
            p=datetime(2025, 1, 1, 0, 0, tzinfo=UTC),
            t=target,
            depth_mid=depth,
            depth_low=depth,
            depth_high=depth,
            velocity_ms=velocity,
            hazard_dv=depth * velocity,
            prob_inundated=(depth > 0).astype(np.float32),
            compute_ms={},
        )
        self.state_calls: list[tuple[object, object, bool]] = []

    def state(self, p: object, t: object, write: bool = False) -> tuple[StateArrays, dict]:
        self.state_calls.append((p, t, write))
        return self.arrays, {"t": T}


def _estimate(run: _MiniRun) -> dict:
    return estimate_missing_person_search_area(run, P, T, "lkp_test")


def test_downstream_polygon_bands_and_direct_state_access() -> None:
    run = _MiniRun()
    result = _estimate(run)

    assert run.state_calls == [(P, T, False)]
    assert result["type"] == "FeatureCollection"
    assert result["status"] == "available"
    assert [feature["properties"]["band"] for feature in result["features"]] == ["high", "medium", "low"]
    assert all(feature["geometry"]["type"] in {"Polygon", "MultiPolygon"} for feature in result["features"])
    assert "reach:1" in result["source_refs"]
    assert "reach:2" not in result["source_refs"]
    assert "reach:3" not in result["source_refs"]
    assert result["truncated"] is True
    assert result["reason"] == "downstream_direction_unproven"
    assert sum(result["relative_weights"].values()) == pytest.approx(1.0)
    high, medium, low = [shape(feature["geometry"]) for feature in result["features"]]
    assert medium.covers(high)
    assert low.covers(medium)
    assert "relative search-priority weights are not calibrated probabilities" in result["limitations"]


def test_dry_or_distant_start_returns_no_geometry() -> None:
    dry = _estimate(_MiniRun(dry=True))
    distant = _estimate(_MiniRun(lkp_lon=1.0))
    for result in (dry, distant):
        assert result["status"] == "unavailable"
        assert result["features"] == []
        assert result["reason"] == "dry_or_distant_start"


def test_unknown_lkp_is_rejected_before_state_or_geometry() -> None:
    run = _MiniRun()
    with pytest.raises(SearchAreaInputError, match="last_known_position_id") as exc_info:
        estimate_missing_person_search_area(run, P, T, "not-a-scenario-id")
    assert exc_info.value.code == "unknown_last_known_position_id"
    assert run.state_calls == []


def test_langchain_tool_invocation_and_argument_rejection() -> None:
    run = _MiniRun()
    tool = SearchAreaTool(run_resolver=lambda run_id: run if run_id == run.run_id else None)
    result = tool.invoke({"run_id": run.run_id, "p": P, "t": T, "last_known_position_id": "lkp_test"})
    assert result["status"] == "available"
    with pytest.raises(Exception):
        tool.invoke(
            {
                "run_id": run.run_id,
                "p": P,
                "t": T,
                "last_known_position_id": "lkp_test",
                "lon": 0.0,
            }
        )
