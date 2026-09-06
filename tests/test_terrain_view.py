"""Static assets, API contract, and network GeoJSON for the 3D terrain view (decision 0009)."""
from __future__ import annotations

from importlib import resources
from pathlib import Path
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient

from flood.api.app import create_app
from flood.api.settings import Settings
from tests.fakes.fake_run import FakeRunStore

TERRAIN_CONTRACT_PATHS = [
    "/scenarios/{scenario_id}",
    "/runs",
    "/runs/{run}",
    "/runs/{run}/state?p=&t=",
    "/runs/{run}/reaches?p=&t=",
    "/runs/{run}/gauges?p=",
    "/runs/{run}/overlay.png?p=&t=&band=&max_px=&smooth=",
    "/runs/{run}/network.geojson",
    "/runs/{run}/vulnerability.geojson",
    "/runs/{run}/exposure?p=&t=",
    "/clock",
    "/clock/ws",
]


def _static(name: str) -> str:
    return resources.files("flood.verifier").joinpath("static").joinpath(name).read_text(encoding="utf-8")


def test_terrain_static_files_exist_in_package() -> None:
    for name in ("terrain.html", "terrain.js", "terrain.css"):
        assert len(_static(name)) > 0, f"{name} missing or empty"


def test_terrain_html_pins_maplibre_and_lists_bands() -> None:
    from flood.interfaces import RASTER_BANDS

    html = _static("terrain.html")
    assert re.search(r'href=["\'][^"\']*terrain\.css["\']', html)
    assert re.search(r'src=["\'][^"\']*terrain\.js["\']', html)
    assert "cdnjs.cloudflare.com/ajax/libs/maplibre-gl/5.24.0" in html
    assert len(re.findall(r'integrity=["\']sha512-[^"\']+["\']', html)) >= 2
    assert "leaflet" not in html.lower()
    for band in RASTER_BANDS:
        assert f'value="{band}"' in html, f"band {band} missing from terrain.html band select"


def test_terrain_api_object_matches_contract() -> None:
    js = _static("terrain.js")
    api_match = re.search(r"(?:export\s+)?const\s+API\s*=\s*\{([\s\S]*?)\};", js)
    assert api_match, "API object not found in terrain.js"
    urls = re.findall(r"['\"]([^'\"]+)['\"]", api_match.group(1))
    assert sorted(urls) == sorted(TERRAIN_CONTRACT_PATHS)


def test_verifier_index_links_to_terrain_view() -> None:
    assert re.search(r'href=["\']terrain\.html["\']', _static("index.html"))


@pytest.fixture
def api_dirs(tmp_path: Path, repo_root: Path, mini_huc_dir: Path) -> dict[str, Path]:
    scenarios_dir = tmp_path / "scenarios"
    scenarios_dir.mkdir(parents=True)
    kerr_src = repo_root / "scenarios" / "kerr-2025-07-04.json"
    (scenarios_dir / "kerr-2025-07-04.json").write_text(kerr_src.read_text(encoding="utf-8"), encoding="utf-8")
    (scenarios_dir / "mini-huc.json").write_text(
        (mini_huc_dir / "scenario.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir(parents=True)
    return {"scenarios_dir": scenarios_dir, "runs_dir": runs_dir, "data_dir": mini_huc_dir / "data"}


@pytest.fixture(params=["fake", "real"])
def store(request: pytest.FixtureRequest, api_dirs: dict[str, Path]) -> Any:
    if request.param == "fake":
        return FakeRunStore(runs_dir=api_dirs["runs_dir"], data_dir=api_dirs["data_dir"])
    from flood.engine.run import RunStore

    return RunStore(runs_dir=api_dirs["runs_dir"], data_dir=api_dirs["data_dir"])


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


def test_terrain_page_and_assets_served(client: TestClient) -> None:
    resp = client.get("/verifier/terrain.html")
    assert resp.status_code == 200
    assert "Flood Terrain View" in resp.text
    assert "maplibre" in client.get("/verifier/terrain.js").text.lower()
    assert ".gauge-chip" in client.get("/verifier/terrain.css").text


def test_smooth_overlay_route(client: TestClient) -> None:
    """overlay.png accepts smooth=1 and a max_px above the old 4096 clamp, and still reports bounds."""
    run_id = client.post("/runs", json={"scenario_id": "mini-huc", "mode": "replay"}).json()["run_id"]
    resp = client.get(
        f"/runs/{run_id}/overlay.png?p=2025-01-01T08:00:00Z&t=2025-01-01T10:00:00Z&band=depth_mid&max_px=300&smooth=1"
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert len(resp.headers["X-Bounds-4326"].split(",")) == 4
    assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"

    resp_big = client.get(
        f"/runs/{run_id}/overlay.png?p=2025-01-01T08:00:00Z&t=2025-01-01T10:00:00Z&band=depth_mid&max_px=99999&smooth=1"
    )
    assert resp_big.status_code == 200
    from PIL import Image
    import io

    w, h = Image.open(io.BytesIO(resp_big.content)).size
    assert max(w, h) == 8192


def test_network_geojson_route(client: TestClient) -> None:
    """GET /runs/{run_id}/network.geojson returns WGS84 reach lines and gauge points keyed by feature id."""
    resp_unknown = client.get("/runs/does-not-exist/network.geojson")
    assert resp_unknown.status_code == 404
    assert resp_unknown.json()["error"]["code"] == "unknown_run"

    run_id = client.post("/runs", json={"scenario_id": "mini-huc", "mode": "replay"}).json()["run_id"]
    resp = client.get(f"/runs/{run_id}/network.geojson")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/geo+json")
    fc = resp.json()
    assert fc["type"] == "FeatureCollection"

    reaches = [f for f in fc["features"] if f["properties"]["kind"] == "reach"]
    gauges = [f for f in fc["features"] if f["properties"]["kind"] == "gauge"]
    assert reaches, "no reach features"
    for f in reaches:
        assert f["geometry"]["type"] in ("LineString", "MultiLineString")
        assert f["id"] == f["properties"]["feature_id"]
        assert isinstance(f["id"], int)
        assert f["properties"]["reach_ref"] == f"reach:{f['id']}"
        coords = f["geometry"]["coordinates"] if f["geometry"]["type"] == "LineString" else [
            c for part in f["geometry"]["coordinates"] for c in part
        ]
        for lon, lat in coords:
            assert -180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0, "coordinates are not WGS84"
        for key in ("stream_order", "levelpath_id", "length_m", "in_aoi"):
            assert key in f["properties"]

    gauged = [f for f in reaches if f["properties"]["gauge_site"]]
    assert len(gauges) == len(gauged)
    for g in gauges:
        assert g["geometry"]["type"] == "Point"
        assert g["id"] == f"gauge:{g['properties']['site']}"
        assert g["properties"]["gauge_ref"] == g["id"]
        assert any(r["properties"]["gauge_site"] == g["properties"]["site"] for r in gauged)

    # Second call is served from the per-run cache and is identical.
    assert client.get(f"/runs/{run_id}/network.geojson").json() == fc
