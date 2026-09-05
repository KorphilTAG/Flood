"""Static assets and smoke tests for the verifier UI (cycle C09)."""
from importlib import resources
from pathlib import Path
import re
import pytest

CONTRACT_PATHS = [
    "/scenarios",
    "/scenarios/{scenario_id}",
    "/runs",
    "/runs/{run}",
    "/runs/{run}/state?p=&t=",
    "/runs/{run}/reaches?p=&t=",
    "/runs/{run}/gauges?p=",
    "/runs/{run}/overlay.png?p=&t=&band=&max_px=2048",
    "/runs/{run}/skill",
    "/clock",
    "/clock/reset",
    "/clock/ws",
]


def test_static_files_exist_in_package():
    """Assert the three static files exist in the flood.verifier.static package directory."""
    static_files = resources.files("flood.verifier").joinpath("static")
    assert static_files.is_dir(), "Static directory not found in flood.verifier package"

    index_html = static_files.joinpath("index.html")
    app_js = static_files.joinpath("app.js")
    style_css = static_files.joinpath("style.css")

    assert index_html.is_file(), "index.html missing from flood.verifier/static"
    assert app_js.is_file(), "app.js missing from flood.verifier/static"
    assert style_css.is_file(), "style.css missing from flood.verifier/static"

    assert len(index_html.read_text(encoding="utf-8")) > 0
    assert len(app_js.read_text(encoding="utf-8")) > 0
    assert len(style_css.read_text(encoding="utf-8")) > 0


def test_index_references_assets_and_pinned_cdns():
    """Assert index.html references app.js and style.css, and uses pinned Leaflet and Chart.js."""
    index_path = resources.files("flood.verifier").joinpath("static/index.html")
    content = index_path.read_text(encoding="utf-8")

    # References app.js and style.css
    assert re.search(r'href=["\'][^"\']*style\.css["\']', content), "style.css not linked in index.html"
    assert re.search(r'src=["\'][^"\']*app\.js["\']', content), "app.js not loaded in index.html"

    # Leaflet 1.9.4 pinned with integrity
    assert "cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4" in content
    assert re.search(r'integrity=["\']sha512-[^"\']+["\']', content)

    # Chart.js 4.4.x pinned with integrity
    assert "cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4" in content


def test_api_object_urls_match_contract():
    """Assert every URL template in the API object of app.js appears in CONTRACT_PATHS."""
    app_js_path = resources.files("flood.verifier").joinpath("static/app.js")
    content = app_js_path.read_text(encoding="utf-8")

    # Extract API object block
    api_match = re.search(r"(?:export\s+)?const\s+API\s*=\s*\{([\s\S]*?)\};", content)
    assert api_match, "API object not found in app.js"

    api_block = api_match.group(1)
    urls = re.findall(r"['\"]([^'\"]+)['\"]", api_block)
    assert len(urls) == len(CONTRACT_PATHS), f"Expected {len(CONTRACT_PATHS)} API endpoints, found {len(urls)}"

    for url in urls:
        assert url in CONTRACT_PATHS, f"URL template {url!r} from app.js is not in CONTRACT_PATHS"


def test_raster_bands_covered_in_ui():
    """Assert all RASTER_BANDS from flood.interfaces are present in the band selector."""
    from flood.interfaces import RASTER_BANDS

    index_html = resources.files("flood.verifier").joinpath("static/index.html").read_text(encoding="utf-8")
    for band in RASTER_BANDS:
        assert f'value="{band}"' in index_html, f"RASTER_BAND {band} missing from band select"


def test_verifier_server_routes():
    """Smoke test against FastAPI server when C07 (flood.api.app) merges."""
    app_module = pytest.importorskip("flood.api.app")
    create_app = getattr(app_module, "create_app", None) or getattr(app_module, "app", None)
    assert create_app is not None, "Could not find create_app or app in flood.api.app"

    app = create_app() if callable(create_app) else create_app
    from fastapi.testclient import TestClient

    client = TestClient(app)

    # Verifier page served
    resp_index = client.get("/verifier/")
    assert resp_index.status_code == 200
    assert "Flood Verifier" in resp_index.text

    # Static assets served
    resp_js = client.get("/verifier/app.js")
    assert resp_js.status_code == 200
    assert "API" in resp_js.text

    resp_css = client.get("/verifier/style.css")
    assert resp_css.status_code == 200
    assert "#map" in resp_css.text

    # Check routes against the OpenAPI schema (robust across FastAPI versions, which
    # differ in how included routers appear in app.routes). WebSocket routes are not in
    # OpenAPI, so /clock/ws is checked by connecting.
    openapi_paths = set(app.openapi()["paths"].keys())
    for template in CONTRACT_PATHS:
        base_path = template.split("?")[0].replace("{run}", "{run_id}")
        if base_path == "/clock/ws":
            with client.websocket_connect("/clock/ws") as ws:
                first = ws.receive_json()
                assert "t" in first
            continue
        assert base_path in openapi_paths, f"{base_path} not found in OpenAPI paths {sorted(openapi_paths)}"
