"""Tests for the Flood Engine API application."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

import flood
from flood.api.app import create_app
from flood.api.settings import Settings
from flood.contracts.validate import validate_json
from tests.fakes.fake_run import FakeRunStore


@pytest.fixture
def api_dirs(tmp_path: Path, repo_root: Path) -> dict[str, Path]:
    scenarios_dir = tmp_path / "scenarios"
    scenarios_dir.mkdir(parents=True)
    # Copy valid Kerr scenario
    kerr_src = repo_root / "scenarios" / "kerr-2025-07-04.json"
    (scenarios_dir / "kerr-2025-07-04.json").write_text(kerr_src.read_text(encoding="utf-8"), encoding="utf-8")

    # Add an invalid json file to test skipping
    (scenarios_dir / "broken.json").write_text("not json", encoding="utf-8")

    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    return {
        "scenarios_dir": scenarios_dir,
        "runs_dir": runs_dir,
        "data_dir": data_dir,
    }


@pytest.fixture(params=["fake", "real"])
def store(request: pytest.FixtureRequest, api_dirs: dict[str, Path]) -> Any:
    if request.param == "fake":
        return FakeRunStore(runs_dir=api_dirs["runs_dir"], data_dir=api_dirs["data_dir"])
    elif request.param == "real":
        pytest.importorskip("flood.engine.run", reason="C06 run orchestrator not yet merged")
        from flood.engine.run import RunStore
        return RunStore(runs_dir=api_dirs["runs_dir"], data_dir=api_dirs["data_dir"])
    raise ValueError(f"Unknown store param: {request.param}")


@pytest.fixture
def client(api_dirs: dict[str, Path], store: Any) -> TestClient:
    settings = Settings(
        runs_dir=api_dirs["runs_dir"],
        data_dir=api_dirs["data_dir"],
        scenarios_dir=api_dirs["scenarios_dir"],
    )
    app = create_app(settings=settings, store=store)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_scenarios_list_and_get(client: TestClient, api_dirs: dict[str, Path]) -> None:
    """GET /scenarios lists valid files, skipping broken.json, and GET /scenarios/{id} returns it."""
    resp = client.get("/scenarios")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["scenario_id"] == "kerr-2025-07-04"
    assert "name" in data[0]

    # Get valid scenario
    resp_sc = client.get("/scenarios/kerr-2025-07-04")
    assert resp_sc.status_code == 200
    sc_json = resp_sc.json()
    assert sc_json["scenario_id"] == "kerr-2025-07-04"
    validate_json("scenario", sc_json)

    # Unknown scenario
    resp_unk = client.get("/scenarios/unknown-scenario")
    assert resp_unk.status_code == 404
    err = resp_unk.json()
    assert err == {"error": {"code": "unknown_scenario", "message": "Scenario 'unknown-scenario' not found"}}


def test_runs_create_list_get(client: TestClient) -> None:
    """POST /runs creates a run, GET /runs lists summary, GET /runs/{run_id} returns manifest."""
    # List runs initially empty
    resp_list = client.get("/runs")
    assert resp_list.status_code == 200
    assert resp_list.json() == []

    # POST /runs with unknown scenario -> 404
    resp_bad_sc = client.post("/runs", json={"scenario_id": "nonexistent", "mode": "replay"})
    assert resp_bad_sc.status_code == 404
    assert resp_bad_sc.json()["error"]["code"] == "unknown_scenario"

    # POST /runs with invalid forcing overrides -> 400 invalid_forcing
    resp_bad_forcing = client.post(
        "/runs",
        json={
            "scenario_id": "kerr-2025-07-04",
            "mode": "replay",
            "forcing_overrides": {"nonexistent_override_key": 123},
        },
    )
    assert resp_bad_forcing.status_code == 400
    assert resp_bad_forcing.json()["error"]["code"] == "invalid_forcing"

    # Valid POST /runs -> 202
    resp_create = client.post(
        "/runs",
        json={"scenario_id": "kerr-2025-07-04", "mode": "replay"},
    )
    assert resp_create.status_code == 202
    manifest = resp_create.json()
    run_id = manifest["run_id"]
    assert "schema_version" in manifest
    validate_json("run-manifest", manifest)

    # GET /runs summary fields only
    resp_list2 = client.get("/runs")
    assert resp_list2.status_code == 200
    items = resp_list2.json()
    assert len(items) == 1
    assert set(items[0].keys()) == {"run_id", "created_at", "mode", "scenario", "time", "members"}

    # GET /runs/{run_id}
    resp_get = client.get(f"/runs/{run_id}")
    assert resp_get.status_code == 200
    assert resp_get.json()["run_id"] == run_id

    # GET /runs/unknown_run -> 404 unknown_run
    resp_unk = client.get("/runs/nonexistent-run")
    assert resp_unk.status_code == 404
    assert resp_unk.json()["error"]["code"] == "unknown_run"


def test_state_route_and_timegrid_errors(client: TestClient) -> None:
    """GET /runs/{run_id}/state tests validation, hindsight, and error codes."""
    create_resp = client.post("/runs", json={"scenario_id": "kerr-2025-07-04", "mode": "replay"})
    run_id = create_resp.json()["run_id"]

    # Missing parameters -> 400 missing_parameter
    resp_missing = client.get(f"/runs/{run_id}/state")
    assert resp_missing.status_code == 400
    assert resp_missing.json()["error"]["code"] == "missing_parameter"

    resp_missing_t = client.get(f"/runs/{run_id}/state?p=2025-07-04T08:00:00Z")
    assert resp_missing_t.status_code == 400
    assert resp_missing_t.json()["error"]["code"] == "missing_parameter"

    # Valid nowcast: p == t
    resp_nowcast = client.get(f"/runs/{run_id}/state?p=2025-07-04T08:00:00Z&t=2025-07-04T08:00:00Z")
    assert resp_nowcast.status_code == 200
    state_json = resp_nowcast.json()
    assert state_json["mode"] == "nowcast"
    assert state_json["horizon_minutes"] == 0
    validate_json("state-response", state_json)

    # Valid forecast: t > p
    resp_fc = client.get(f"/runs/{run_id}/state?p=2025-07-04T08:00:00Z&t=2025-07-04T10:00:00Z")
    assert resp_fc.status_code == 200
    state_fc = resp_fc.json()
    assert state_fc["mode"] == "forecast"
    assert state_fc["horizon_minutes"] == 120
    validate_json("state-response", state_fc)

    # Valid hindsight: p=hindsight
    resp_hind = client.get(f"/runs/{run_id}/state?p=hindsight&t=2025-07-04T10:00:00Z")
    assert resp_hind.status_code == 200
    state_hind = resp_hind.json()
    assert state_hind["mode"] == "hindsight"
    assert state_hind["p"] is None
    validate_json("state-response", state_hind)

    # Error: t_before_p
    resp_t_before_p = client.get(f"/runs/{run_id}/state?p=2025-07-04T08:00:00Z&t=2025-07-04T07:00:00Z")
    assert resp_t_before_p.status_code == 400
    assert resp_t_before_p.json()["error"]["code"] == "t_before_p"

    # Error: horizon_exceeded (> 360 min)
    resp_horizon = client.get(f"/runs/{run_id}/state?p=2025-07-04T08:00:00Z&t=2025-07-04T15:00:00Z")
    assert resp_horizon.status_code == 400
    assert resp_horizon.json()["error"]["code"] == "horizon_exceeded"

    # Error: outside_record
    resp_outside = client.get(f"/runs/{run_id}/state?p=2020-01-01T00:00:00Z&t=2020-01-01T01:00:00Z")
    assert resp_outside.status_code == 400
    assert resp_outside.json()["error"]["code"] == "outside_record"


def test_hindsight_route(client: TestClient) -> None:
    """GET /runs/{run_id}/hindsight?t= equals state?p=hindsight&t=."""
    create_resp = client.post("/runs", json={"scenario_id": "kerr-2025-07-04", "mode": "replay"})
    run_id = create_resp.json()["run_id"]

    # Missing t
    resp_missing = client.get(f"/runs/{run_id}/hindsight")
    assert resp_missing.status_code == 400
    assert resp_missing.json()["error"]["code"] == "missing_parameter"

    t = "2025-07-04T09:00:00Z"
    resp_h = client.get(f"/runs/{run_id}/hindsight?t={t}")
    assert resp_h.status_code == 200

    resp_s = client.get(f"/runs/{run_id}/state?p=hindsight&t={t}")
    assert resp_s.status_code == 200
    assert resp_h.json() == resp_s.json()


def test_reaches_and_gauges_routes(client: TestClient) -> None:
    """GET /runs/{run_id}/reaches and /gauges return rows conforming to schemas."""
    create_resp = client.post("/runs", json={"scenario_id": "kerr-2025-07-04", "mode": "replay"})
    run_id = create_resp.json()["run_id"]

    # Reaches missing parameter
    resp_r_miss = client.get(f"/runs/{run_id}/reaches?p=2025-07-04T08:00:00Z")
    assert resp_r_miss.status_code == 400
    assert resp_r_miss.json()["error"]["code"] == "missing_parameter"

    # Reaches valid
    resp_r = client.get(f"/runs/{run_id}/reaches?p=2025-07-04T08:00:00Z&t=2025-07-04T10:00:00Z")
    assert resp_r.status_code == 200
    reaches_rows = resp_r.json()
    assert len(reaches_rows) > 0
    for row in reaches_rows:
        validate_json("reach-row", row)

    # Gauges missing parameter
    resp_g_miss = client.get(f"/runs/{run_id}/gauges")
    assert resp_g_miss.status_code == 400
    assert resp_g_miss.json()["error"]["code"] == "missing_parameter"

    # Gauges valid
    resp_g = client.get(f"/runs/{run_id}/gauges?p=2025-07-04T08:00:00Z")
    assert resp_g.status_code == 200
    gauges_rows = resp_g.json()
    assert len(gauges_rows) > 0
    for row in gauges_rows:
        validate_json("gauge-row", row)


def test_raster_and_byte_ranges(client: TestClient) -> None:
    """GET /runs/{run_id}/raster serves file with byte range support."""
    create_resp = client.post("/runs", json={"scenario_id": "kerr-2025-07-04", "mode": "replay"})
    run_id = create_resp.json()["run_id"]

    p = "2025-07-04T08:00:00Z"
    t = "2025-07-04T08:00:00Z"

    # Missing parameter
    resp_miss = client.get(f"/runs/{run_id}/raster?p={p}")
    assert resp_miss.status_code == 400
    assert resp_miss.json()["error"]["code"] == "missing_parameter"

    # Full file request
    resp_full = client.get(f"/runs/{run_id}/raster?p={p}&t={t}")
    assert resp_full.status_code == 200
    assert resp_full.headers["content-type"] == "application/octet-stream"
    assert resp_full.headers["accept-ranges"] == "bytes"
    total_len = int(resp_full.headers["content-length"])
    assert total_len > 100
    assert len(resp_full.content) == total_len

    # Range request: Range: bytes=0-99
    resp_range = client.get(f"/runs/{run_id}/raster?p={p}&t={t}", headers={"Range": "bytes=0-99"})
    assert resp_range.status_code == 206
    assert len(resp_range.content) == 100
    assert resp_range.headers["content-length"] == "100"
    assert resp_range.headers["content-range"] == f"bytes 0-99/{total_len}"
    assert resp_range.headers["accept-ranges"] == "bytes"
    assert resp_range.content == resp_full.content[0:100]

    # Unsatisfiable range
    resp_unsat = client.get(f"/runs/{run_id}/raster?p={p}&t={t}", headers={"Range": f"bytes={total_len + 10}-{total_len + 50}"})
    assert resp_unsat.status_code == 416


def test_tte_route(client: TestClient) -> None:
    """GET /runs/{run_id}/tte serves time_to_exceedance.tif; 400 hindsight_has_no_tte."""
    create_resp = client.post("/runs", json={"scenario_id": "kerr-2025-07-04", "mode": "replay"})
    run_id = create_resp.json()["run_id"]

    # Missing p
    resp_miss = client.get(f"/runs/{run_id}/tte")
    assert resp_miss.status_code == 400
    assert resp_miss.json()["error"]["code"] == "missing_parameter"

    # Hindsight mode -> 400 hindsight_has_no_tte
    resp_hind = client.get(f"/runs/{run_id}/tte?p=hindsight")
    assert resp_hind.status_code == 400
    assert resp_hind.json()["error"]["code"] == "hindsight_has_no_tte"

    # Valid tte
    p = "2025-07-04T08:00:00Z"
    resp_tte = client.get(f"/runs/{run_id}/tte?p={p}")
    assert resp_tte.status_code == 200
    assert resp_tte.headers["accept-ranges"] == "bytes"
    assert len(resp_tte.content) > 0


def test_overlay_route(client: TestClient) -> None:
    """GET /runs/{run_id}/overlay.png serves PNG with X-Bounds-3857; validates band and clamps max_px."""
    create_resp = client.post("/runs", json={"scenario_id": "kerr-2025-07-04", "mode": "replay"})
    run_id = create_resp.json()["run_id"]

    p = "2025-07-04T08:00:00Z"
    t = "2025-07-04T08:00:00Z"

    # Missing parameters
    resp_miss = client.get(f"/runs/{run_id}/overlay.png?p={p}")
    assert resp_miss.status_code == 400
    assert resp_miss.json()["error"]["code"] == "missing_parameter"

    # Unknown band -> 400 unknown_band
    resp_band = client.get(f"/runs/{run_id}/overlay.png?p={p}&t={t}&band=invalid_band")
    assert resp_band.status_code == 400
    assert resp_band.json()["error"]["code"] == "unknown_band"

    # Valid overlay request
    resp_png = client.get(f"/runs/{run_id}/overlay.png?p={p}&t={t}&band=depth_mid&max_px=2048")
    assert resp_png.status_code == 200
    assert resp_png.headers["content-type"] == "image/png"
    assert "x-bounds-3857" in resp_png.headers
    bounds_str = resp_png.headers["x-bounds-3857"]
    parts = bounds_str.split(",")
    assert len(parts) == 4
    for pt in parts:
        float(pt)


def test_skill_route(client: TestClient, store: Any) -> None:
    """GET /runs/{run_id}/skill returns rows of skill.parquet or 404 skill_not_computed."""
    create_resp = client.post("/runs", json={"scenario_id": "kerr-2025-07-04", "mode": "replay"})
    run_id = create_resp.json()["run_id"]
    run = store.get(run_id)

    # Initially skill file does not exist -> 404 skill_not_computed
    resp_missing = client.get(f"/runs/{run_id}/skill")
    assert resp_missing.status_code == 404
    assert resp_missing.json()["error"]["code"] == "skill_not_computed"

    # Create a dummy skill.parquet
    skill_df = pd.DataFrame([
        {"metric": "csi", "threshold_m": 0.15, "lead_h": 1, "value": 0.82},
        {"metric": "csi", "threshold_m": 0.30, "lead_h": 2, "value": 0.75},
    ])
    skill_df.to_parquet(run.run_dir / "skill.parquet")

    # Request skill -> 200 with JSON rows
    resp_skill = client.get(f"/runs/{run_id}/skill")
    assert resp_skill.status_code == 200
    rows = resp_skill.json()
    assert len(rows) == 2
    assert rows[0]["metric"] == "csi"
    assert rows[0]["value"] == 0.82


def test_static_products_and_hindsight_routes(client: TestClient, store: Any) -> None:
    """Test static product and hindsight downloads, byte-ranges, and path traversal rejection."""
    create_resp = client.post("/runs", json={"scenario_id": "kerr-2025-07-04", "mode": "replay"})
    run_id = create_resp.json()["run_id"]
    run = store.get(run_id)

    # Ensure files exist via run.state(write=True)
    p = "2025-07-04T08:00:00Z"
    t = "2025-07-04T08:00:00Z"
    run.state(p, t, write=True)

    # GET static product
    prod_path = "p=20250704T0800Z/t=20250704T0800Z/depth.tif"
    resp_prod = client.get(f"/runs/{run_id}/products/{prod_path}")
    assert resp_prod.status_code == 200
    assert resp_prod.headers["accept-ranges"] == "bytes"

    # Byte-range request on static product
    resp_prod_range = client.get(f"/runs/{run_id}/products/{prod_path}", headers={"Range": "bytes=0-49"})
    assert resp_prod_range.status_code == 206
    assert len(resp_prod_range.content) == 50

    # Path traversal rejection -> 404 not_found
    resp_traversal = client.get(f"/runs/{run_id}/products/%2e%2e/run.json")
    assert resp_traversal.status_code == 404
    assert resp_traversal.json()["error"]["code"] == "not_found"

    # Non-existent static product
    resp_missing = client.get(f"/runs/{run_id}/products/nonexistent.file")
    assert resp_missing.status_code == 404
    assert resp_missing.json()["error"]["code"] == "not_found"

    # GET static hindsight
    run.state("hindsight", t, write=True)
    hind_path = "t=20250704T0800Z/depth.tif"
    resp_hind = client.get(f"/runs/{run_id}/hindsight/{hind_path}")
    assert resp_hind.status_code == 200
    assert resp_hind.headers["accept-ranges"] == "bytes"


def test_unhandled_exception_returns_500(client: TestClient, store: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unhandled exceptions return HTTP 500 with code 'internal'."""
    create_resp = client.post("/runs", json={"scenario_id": "kerr-2025-07-04", "mode": "replay"})
    run_id = create_resp.json()["run_id"]
    run = store.get(run_id)

    def explode(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Something exploded")

    monkeypatch.setattr(run, "state", explode)

    resp = client.get(f"/runs/{run_id}/state?p=2025-07-04T08:00:00Z&t=2025-07-04T08:00:00Z")
    assert resp.status_code == 500
    assert resp.json() == {"error": {"code": "internal", "message": "Something exploded"}}


def test_engine_unavailable(api_dirs: dict[str, Path]) -> None:
    """When store is None, /runs routes return 503 engine_unavailable, while scenarios still work."""
    settings = Settings(
        runs_dir=api_dirs["runs_dir"],
        data_dir=api_dirs["data_dir"],
        scenarios_dir=api_dirs["scenarios_dir"],
    )
    app = create_app(settings=settings, store=None)
    with TestClient(app) as c:
        # Scenarios still work
        resp_sc = c.get("/scenarios")
        assert resp_sc.status_code == 200

        # /runs returns 503 engine_unavailable
        resp_runs = c.get("/runs")
        assert resp_runs.status_code == 503
        assert resp_runs.json() == {"error": {"code": "engine_unavailable", "message": "Physics engine is unavailable"}}

        resp_post = c.post("/runs", json={"scenario_id": "kerr-2025-07-04", "mode": "replay"})
        assert resp_post.status_code == 503
        assert resp_post.json()["error"]["code"] == "engine_unavailable"

        resp_state = c.get("/runs/any/state?p=2025-07-04T08:00:00Z&t=2025-07-04T08:00:00Z")
        assert resp_state.status_code == 503
        assert resp_state.json()["error"]["code"] == "engine_unavailable"


def test_verifier_mount(api_dirs: dict[str, Path], store: Any) -> None:
    """Mount /verifier serves index.html when flood/verifier/static exists; app starts without it."""
    settings = Settings(
        runs_dir=api_dirs["runs_dir"],
        data_dir=api_dirs["data_dir"],
        scenarios_dir=api_dirs["scenarios_dir"],
    )
    # Test without verifier/static
    app_no_v = create_app(settings=settings, store=store)
    with TestClient(app_no_v) as c:
        resp = c.get("/verifier/")
        assert resp.status_code == 404

    # Test with verifier/static
    static_dir = Path(flood.__file__).parent / "verifier" / "static"
    created = False
    try:
        static_dir.mkdir(parents=True, exist_ok=True)
        index_file = static_dir / "index.html"
        index_file.write_text("<h1>Verifier UI Test</h1>", encoding="utf-8")
        created = True

        app_v = create_app(settings=settings, store=store)
        with TestClient(app_v) as c:
            resp_v = c.get("/verifier/")
            assert resp_v.status_code == 200
            assert "<h1>Verifier UI Test</h1>" in resp_v.text
    finally:
        if created:
            index_file.unlink(missing_ok=True)
            static_dir.rmdir()
            try:
                static_dir.parent.rmdir()
            except OSError:
                pass


def test_clock_integration(client: TestClient) -> None:
    """Clock endpoints mounted under /clock are accessible."""
    resp = client.get("/clock")
    assert resp.status_code == 200
    data = resp.json()
    assert "mode" in data
    assert "t" in data
    assert "speed" in data

    # POST /clock
    post_resp = client.post("/clock", json={"speed": 120.0})
    assert post_resp.status_code == 200
    assert post_resp.json()["speed"] == 120.0

    # Reset
    reset_resp = client.post("/clock/reset")
    assert reset_resp.status_code == 200
    assert reset_resp.json()["playing"] is False


def test_cli_serve_parser() -> None:
    """Test that flood serve CLI command is registered and parses arguments."""
    import argparse
    from flood.cli_serve import register

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="subcommand")
    register(sub)
    args = parser.parse_args(["serve", "--host", "0.0.0.0", "--port", "9000"])
    assert args.subcommand == "serve"
    assert args.host == "0.0.0.0"
    assert args.port == 9000
