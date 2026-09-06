"""Runs API router covering state, reaches, gauges, raster, tte, overlay, hindsight, network, skill, and static products."""
from __future__ import annotations

import json
import logging
import mimetypes
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rasterio.warp
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import FileResponse, JSONResponse

from flood.api.errors import APIError
from flood.contracts.validate import ContractError, validate_json
from flood.interfaces import Grid, RASTER_BANDS
from flood.products.raster import render_overlay_png
from flood.scenario import load_scenario
from flood.timegrid import to_iso
from flood.timegrid import to_iso

logger = logging.getLogger(__name__)


def get_store(request: Request) -> Any:
    """Retrieve RunStore from app.state or raise 503 engine_unavailable."""
    store = getattr(request.app.state, "store", None)
    if store is None:
        raise APIError(
            status_code=503,
            code="engine_unavailable",
            message="Physics engine is unavailable",
        )
    return store


def _snap_to_precomputed(run: Any, p: str | None, t: str) -> tuple[str, str, dict[str, str]]:
    """Resolve to the nearest prewarmed product; 404 not_precomputed when none is within reach.

    Returns the served p (or "hindsight"), the served t, and the original request.
    """
    if not hasattr(run, "resolve_precomputed"):
        return (p if p else "hindsight"), t, {"p": p if p else "hindsight", "t": t}
    res = run.resolve_precomputed(p, t)
    if res is None:
        raise APIError(
            status_code=404,
            code="not_precomputed",
            message="No prewarmed product within 60 minutes of the requested cutoff; retry without precomputed=1 to compute",
        )
    return ("hindsight" if res.p is None else to_iso(res.p)), to_iso(res.t), res.requested


def _snap_to_precomputed(run: Any, p: str | None, t: str) -> tuple[str, str, dict[str, str]]:
    """Resolve to the nearest prewarmed product; 404 not_precomputed when none is within reach.

    Returns the served p (or "hindsight"), the served t, and the original request.
    """
    if not hasattr(run, "resolve_precomputed"):
        return (p if p else "hindsight"), t, {"p": p if p else "hindsight", "t": t}
    res = run.resolve_precomputed(p, t)
    if res is None:
        raise APIError(
            status_code=404,
            code="not_precomputed",
            message="No prewarmed product within 60 minutes of the requested cutoff; retry without precomputed=1 to compute",
        )
    return ("hindsight" if res.p is None else to_iso(res.p)), to_iso(res.t), res.requested


def _get_run(store: Any, run_id: str) -> Any:
    try:
        return store.get(run_id)
    except KeyError:
        raise APIError(
            status_code=404,
            code="unknown_run",
            message=f"Run '{run_id}' not found",
        )


def range_file_response(
    path: Path,
    range_header: str | None,
    media_type: str = "application/octet-stream",
) -> Response:
    """Serve a file with HTTP 206 byte-range support and 416 for unsatisfiable ranges."""
    if not path.is_file():
        raise APIError(status_code=404, code="not_found", message=f"File not found: {path.name}")

    file_size = path.stat().st_size

    if not range_header:
        return FileResponse(
            path=path,
            media_type=media_type,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
            },
        )

    range_str = range_header.strip()
    if not range_str.startswith("bytes="):
        return FileResponse(
            path=path,
            media_type=media_type,
            headers={
                "Accept-Ranges": "bytes",
                "Content-Length": str(file_size),
            },
        )

    byte_range = range_str[len("bytes="):].strip()
    if "," in byte_range:
        byte_range = byte_range.split(",")[0].strip()

    parts = byte_range.split("-", 1)
    if len(parts) != 2:
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{file_size}", "Accept-Ranges": "bytes"},
            content=json.dumps({"error": {"code": "range_not_satisfiable", "message": "Invalid range header"}}),
            media_type="application/json",
        )

    start_str, end_str = parts[0].strip(), parts[1].strip()
    try:
        if start_str and end_str:
            start = int(start_str)
            end = int(end_str)
        elif start_str and not end_str:
            start = int(start_str)
            end = file_size - 1
        elif not start_str and end_str:
            suffix = int(end_str)
            start = max(0, file_size - suffix)
            end = file_size - 1
        else:
            return Response(
                status_code=416,
                headers={"Content-Range": f"bytes */{file_size}", "Accept-Ranges": "bytes"},
                content=json.dumps({"error": {"code": "range_not_satisfiable", "message": "Empty range"}}),
                media_type="application/json",
            )
    except ValueError:
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{file_size}", "Accept-Ranges": "bytes"},
            content=json.dumps({"error": {"code": "range_not_satisfiable", "message": "Malformed byte range"}}),
            media_type="application/json",
        )

    if start > end or start >= file_size or start < 0:
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{file_size}", "Accept-Ranges": "bytes"},
            content=json.dumps({"error": {"code": "range_not_satisfiable", "message": "Requested range not satisfiable"}}),
            media_type="application/json",
        )

    end = min(end, file_size - 1)
    length = end - start + 1

    with open(path, "rb") as f:
        f.seek(start)
        data = f.read(length)

    return Response(
        content=data,
        status_code=206,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Content-Length": str(length),
            "Accept-Ranges": "bytes",
            "Content-Type": media_type,
        },
    )


def _records(df: pd.DataFrame) -> list[dict]:
    """DataFrame rows as JSON-safe dicts: contract ISO timestamps (second precision), NaN -> null."""
    out = df.copy()
    for col in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[col]):
            ser = out[col]
            if getattr(ser.dt, "tz", None) is None:
                ser = ser.dt.tz_localize("UTC")
            out[col] = ser.dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    out = out.astype(object).where(pd.notna(out), None)
    return out.to_dict(orient="records")


router = APIRouter(prefix="/runs", tags=["runs"], dependencies=[Depends(get_store)])


@router.get("")
def list_runs(store: Any = Depends(get_store)) -> list[dict[str, Any]]:
    """List run manifests with only summary keys."""
    manifests = store.list()
    allowed_keys = ("run_id", "created_at", "mode", "scenario", "time", "members")
    return [{k: m[k] for k in allowed_keys if k in m} for m in manifests]


@router.post("", status_code=202)
async def create_run(request: Request, store: Any = Depends(get_store)) -> JSONResponse:
    """Create a run. Body: {"scenario_id", "mode", "forcing_overrides"?}."""
    try:
        body = await request.json()
    except Exception as exc:
        raise APIError(status_code=400, code="invalid_request", message=f"Malformed JSON body: {exc}")

    if not isinstance(body, dict):
        raise APIError(status_code=400, code="invalid_request", message="Body must be a JSON object")

    scenario_id = body.get("scenario_id")
    if not scenario_id:
        raise APIError(status_code=400, code="missing_parameter", message="scenario_id is required")

    mode = body.get("mode")
    if not mode:
        raise APIError(status_code=400, code="missing_parameter", message="mode is required")

    forcing_overrides = body.get("forcing_overrides")

    # Locate and validate scenario
    scenarios_dir: Path = request.app.state.settings.scenarios_dir
    scenario_path = scenarios_dir / f"{scenario_id}.json"
    if not scenario_path.is_file():
        # Fallback search by scenario_id attribute
        found = None
        if scenarios_dir.is_dir():
            for p in scenarios_dir.glob("*.json"):
                try:
                    sc = load_scenario(p)
                    if sc.scenario_id == scenario_id:
                        found = sc
                        break
                except Exception:
                    continue
        if found is None:
            raise APIError(
                status_code=404,
                code="unknown_scenario",
                message=f"Scenario '{scenario_id}' not found",
            )
        scenario = found
    else:
        try:
            scenario = load_scenario(scenario_path)
        except Exception as exc:
            raise APIError(
                status_code=404,
                code="unknown_scenario",
                message=f"Scenario '{scenario_id}' invalid: {exc}",
            )

    # Validate forcing overrides if provided
    if forcing_overrides is not None:
        if not isinstance(forcing_overrides, dict):
            raise APIError(
                status_code=400,
                code="invalid_forcing",
                message="forcing_overrides must be a dictionary",
            )
        valid_override_keys = {
            "sources",
            "state_estimation",
            "boundary_forecast",
            "routing",
            "roughness",
            "scenario_overrides",
        }
        unknown_keys = set(forcing_overrides.keys()) - valid_override_keys
        if unknown_keys:
            raise APIError(
                status_code=400,
                code="invalid_forcing",
                message=f"Unknown forcing override keys: {', '.join(sorted(unknown_keys))}",
            )

    try:
        run = store.create(scenario, mode, overrides=forcing_overrides)
    except (ValueError, ContractError) as exc:
        raise APIError(status_code=400, code="invalid_forcing", message=str(exc))

    return JSONResponse(status_code=202, content=run.manifest)


@router.get("/{run_id}")
def get_run(run_id: str, store: Any = Depends(get_store)) -> JSONResponse:
    """Return full run manifest or 404 unknown_run."""
    run = _get_run(store, run_id)
    return JSONResponse(status_code=200, content=run.manifest)


@router.get("/{run_id}/state")
def get_state(
    run_id: str,
    p: str | None = None,
    t: str | None = None,
    precomputed: bool = False,
    store: Any = Depends(get_store),
) -> JSONResponse:
    """Resolve (p, t) and return the state response.

    precomputed=1 serves the nearest prewarmed product instead of computing (404
    not_precomputed if none is within an hour); the response's `requested` keeps the
    original query and `p`/`t` say what was served.
    """
    if not p or not t:
        raise APIError(
            status_code=400,
            code="missing_parameter",
            message="Both 'p' and 't' query parameters are required",
        )
    run = _get_run(store, run_id)
    requested = None
    if precomputed:
        p, t, requested = _snap_to_precomputed(run, p, t)
    _, state_dict = run.state(p, t, write=False)
    if requested is not None and isinstance(state_dict, dict) and "requested" in state_dict:
        state_dict = {**state_dict, "requested": requested}
    return JSONResponse(status_code=200, content=state_dict)


@router.get("/{run_id}/reaches")
def get_reaches(
    run_id: str,
    p: str | None = None,
    t: str | None = None,
    precomputed: bool = False,
    store: Any = Depends(get_store),
) -> JSONResponse:
    """Return reach table as JSON array (precomputed=1: nearest prewarmed product, never computes)."""
    if not p or not t:
        raise APIError(
            status_code=400,
            code="missing_parameter",
            message="Both 'p' and 't' query parameters are required",
        )
    run = _get_run(store, run_id)
    if precomputed:
        p, t, _ = _snap_to_precomputed(run, p, t)
    df = run.reaches(p, t)
    rows = _records(df)
    return JSONResponse(status_code=200, content=rows)


@router.get("/{run_id}/gauges")
def get_gauges(
    run_id: str,
    p: str | None = None,
    precomputed: bool = False,
    store: Any = Depends(get_store),
) -> JSONResponse:
    """Return gauge table as JSON array (precomputed=1: nearest prewarmed cutoff, never computes)."""
    if not p:
        raise APIError(
            status_code=400,
            code="missing_parameter",
            message="'p' query parameter is required",
        )
    run = _get_run(store, run_id)
    if precomputed and p != "hindsight":
        p, _, _ = _snap_to_precomputed(run, p, p)
    df = run.gauges(p)
    rows = _records(df)
    return JSONResponse(status_code=200, content=rows)


@router.get("/{run_id}/raster")
def get_raster(
    run_id: str,
    request: Request,
    p: str | None = None,
    t: str | None = None,
    store: Any = Depends(get_store),
) -> Response:
    """Ensure depth.tif exists and return as application/octet-stream with byte range support."""
    if not p or not t:
        raise APIError(
            status_code=400,
            code="missing_parameter",
            message="Both 'p' and 't' query parameters are required",
        )
    run = _get_run(store, run_id)
    run.state(p, t, write=True)
    raster_path = run.product_path("raster", p, t)
    return range_file_response(raster_path, request.headers.get("Range"), media_type="application/octet-stream")


@router.get("/{run_id}/tte")
def get_tte(
    run_id: str,
    request: Request,
    p: str | None = None,
    precomputed: bool = False,
    store: Any = Depends(get_store),
) -> Response:
    """Return time_to_exceedance.tif. 400 hindsight_has_no_tte when p=hindsight."""
    if not p:
        raise APIError(
            status_code=400,
            code="missing_parameter",
            message="'p' query parameter is required",
        )
    if p == "hindsight":
        raise APIError(
            status_code=400,
            code="hindsight_has_no_tte",
            message="Hindsight mode has no time-to-exceedance",
        )
    run = _get_run(store, run_id)
    if precomputed:
        p, _, _ = _snap_to_precomputed(run, p, p)
    run.tte(p, write=True)
    tte_path = run.product_path("time_to_exceedance", p)
    return range_file_response(tte_path, request.headers.get("Range"), media_type="application/octet-stream")


@router.get("/{run_id}/overlay.png")
def get_overlay(
    run_id: str,
    p: str | None = None,
    t: str | None = None,
    band: str = "depth_mid",
    max_px: int = 2048,
    precomputed: bool = False,
    smooth: int = 0,
    store: Any = Depends(get_store),
) -> Response:
    """Return a colour-ramped PNG in EPSG:3857 with its extent in the X-Bounds-3857 header.

    X-Bounds-4326 carries the same extent as west,south,east,north degrees for map
    clients that place images by geographic rectangle (Cesium, Leaflet, MapLibre).
    ``smooth=1`` renders for draping on 3D terrain: bilinear at every scale, no dilation,
    anti-aliased wet edge. ``max_px`` is clamped to 256..8192.
    """
    if not p or not t:
        raise APIError(
            status_code=400,
            code="missing_parameter",
            message="Both 'p' and 't' query parameters are required",
        )
    if band not in RASTER_BANDS:
        raise APIError(
            status_code=400,
            code="unknown_band",
            message=f"Band '{band}' must be one of {RASTER_BANDS}",
        )

    clamped_max_px = max(256, min(8192, int(max_px)))
    run = _get_run(store, run_id)
    if precomputed:
        p, t, _ = _snap_to_precomputed(run, p, t)
    state_arrays, _ = run.state(p, t, write=False)
    array = getattr(state_arrays, band)

    if hasattr(run, "cube") and getattr(run.cube, "grid", None) is not None:
        grid = run.cube.grid
    elif hasattr(run, "grid") and run.grid is not None:
        grid = run.grid
    else:
        g = run.manifest["grid"]
        grid = Grid(
            crs=g["crs"],
            resolution_m=float(g["resolution_m"]),
            width=int(g["width"]),
            height=int(g["height"]),
            transform=tuple(g["transform"]),
            bounds=tuple(g["bounds"]),
        )

    png_bytes, bounds = render_overlay_png(array, grid, max_px=clamped_max_px, smooth=bool(smooth))
    xmin, ymin, xmax, ymax = bounds
    west, south, east, north = rasterio.warp.transform_bounds("EPSG:3857", "EPSG:4326", xmin, ymin, xmax, ymax)
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={
            "X-Bounds-3857": f"{xmin},{ymin},{xmax},{ymax}",
            "X-Bounds-4326": f"{west:.7f},{south:.7f},{east:.7f},{north:.7f}",
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.get("/{run_id}/hindsight")
def get_hindsight(
    run_id: str,
    t: str | None = None,
    store: Any = Depends(get_store),
) -> JSONResponse:
    """State response for the truth run. Equivalent to state?p=hindsight&t=."""
    if not t:
        raise APIError(
            status_code=400,
            code="missing_parameter",
            message="'t' query parameter is required",
        )
    run = _get_run(store, run_id)
    _, state_dict = run.state("hindsight", t, write=False)
    return JSONResponse(status_code=200, content=state_dict)


def _network_frame(run: Any, store: Any) -> tuple[pd.DataFrame, str]:
    """Reach network table and its CRS for a run: the loaded cube's, else the cube directory on disk."""
    cube = getattr(run, "cube", None)
    if cube is not None and getattr(cube, "network", None) is not None:
        return cube.network, str(cube.grid.crs)
    manifest = getattr(run, "manifest", None) or {}
    scenario_id = (manifest.get("scenario") or {}).get("scenario_id")
    grid = getattr(run, "grid", None)
    crs = str((manifest.get("grid") or {}).get("crs") or getattr(grid, "crs", None) or "EPSG:5070")
    path = Path(getattr(store, "data_dir", "data")) / "cube" / str(scenario_id) / "network.parquet"
    if not path.is_file():
        raise APIError(
            status_code=404,
            code="not_found",
            message=f"Network table not found for run '{getattr(run, 'run_id', '?')}'",
        )
    return pd.read_parquet(path), crs


def build_network_geojson(network: pd.DataFrame, crs: str) -> dict[str, Any]:
    """Reach flowlines and gauge points as a WGS84 GeoJSON FeatureCollection.

    Reach features have kind="reach", the NWM feature_id as the feature id, and the network
    columns as properties. Gauged reaches also emit a kind="gauge" Point at the flowline
    midpoint with id "gauge:<site>", so the client can join the reach and gauge tables by id.
    """
    import shapely
    import shapely.wkb
    from pyproj import Transformer
    from shapely.geometry import mapping

    transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)

    def to_wgs84(coords: np.ndarray) -> np.ndarray:
        x, y = transformer.transform(coords[:, 0], coords[:, 1])
        return np.column_stack([x, y])

    features: list[dict[str, Any]] = []
    for row in network.itertuples(index=False):
        wkb = getattr(row, "flowline_wkb", None)
        if wkb is None or (isinstance(wkb, float) and np.isnan(wkb)):
            continue
        geom = shapely.wkb.loads(bytes(wkb))
        if geom.is_empty:
            continue
        geom_ll = shapely.transform(geom, to_wgs84)
        fid = int(row.feature_id)
        gauge_site = row.gauge_site if isinstance(row.gauge_site, str) and row.gauge_site else None
        in_aoi = bool(row.in_aoi)
        features.append({
            "type": "Feature",
            "id": fid,
            "geometry": mapping(geom_ll),
            "properties": {
                "kind": "reach",
                "reach_ref": f"reach:{fid}",
                "feature_id": fid,
                "to_feature_id": int(row.to_feature_id) if pd.notna(row.to_feature_id) else None,
                "stream_order": int(row.stream_order),
                "levelpath_id": int(row.levelpath_id),
                "length_m": float(row.length_m),
                "slope": float(row.slope) if pd.notna(row.slope) else None,
                "gauge_site": gauge_site,
                "in_aoi": in_aoi,
            },
        })
        if gauge_site:
            pt = shapely.line_interpolate_point(geom_ll, 0.5, normalized=True)
            features.append({
                "type": "Feature",
                "id": f"gauge:{gauge_site}",
                "geometry": {"type": "Point", "coordinates": [float(pt.x), float(pt.y)]},
                "properties": {
                    "kind": "gauge",
                    "gauge_ref": f"gauge:{gauge_site}",
                    "site": gauge_site,
                    "feature_id": fid,
                    "in_aoi": in_aoi,
                },
            })
    return {"type": "FeatureCollection", "features": features}


# RunStore.get opens a fresh Run per request, so the per-run network GeoJSON is cached here,
# keyed by store identity and run id. A run's network never changes after creation.
_NETWORK_GEOJSON_CACHE: dict[tuple[int, str], dict[str, Any]] = {}


@router.get("/{run_id}/network.geojson")
def get_network_geojson(run_id: str, store: Any = Depends(get_store)) -> JSONResponse:
    """Reach flowlines and gauge points in WGS84 for the terrain view. Static per run."""
    run = _get_run(store, run_id)
    key = (id(store), run_id)
    cached = _NETWORK_GEOJSON_CACHE.get(key)
    if cached is None:
        network, crs = _network_frame(run, store)
        cached = build_network_geojson(network, crs)
        _NETWORK_GEOJSON_CACHE[key] = cached
    return JSONResponse(status_code=200, content=cached, media_type="application/geo+json")


@router.get("/{run_id}/skill")
def get_skill(run_id: str, store: Any = Depends(get_store)) -> JSONResponse:
    """Return rows of runs/<run_id>/skill.parquet as JSON if exists, else 404 skill_not_computed."""
    run = _get_run(store, run_id)
    skill_file = run.run_dir / "skill.parquet"
    if not skill_file.is_file():
        raise APIError(
            status_code=404,
            code="skill_not_computed",
            message=f"Skill file not computed for run '{run_id}'",
        )
    df = pd.read_parquet(skill_file)
    rows = _records(df)
    return JSONResponse(status_code=200, content=rows)


@router.get("/{run_id}/products/{path:path}")
def get_product_file(
    run_id: str,
    path: str,
    request: Request,
    store: Any = Depends(get_store),
) -> Response:
    """Serve static product file from run directory with byte-range support."""
    run = _get_run(store, run_id)
    if ".." in path.split("/") or ".." in path.split("\\"):
        raise APIError(status_code=404, code="not_found", message="Path outside run directory")

    base_dir = (run.run_dir / "products").resolve()
    target_file = (base_dir / path).resolve()

    try:
        target_file.relative_to(run.run_dir.resolve())
    except ValueError:
        raise APIError(status_code=404, code="not_found", message="Path outside run directory")

    if not target_file.is_file():
        raise APIError(status_code=404, code="not_found", message=f"Product file '{path}' not found")

    guessed_type, _ = mimetypes.guess_type(target_file)
    media_type = guessed_type or "application/octet-stream"
    return range_file_response(target_file, request.headers.get("Range"), media_type=media_type)


@router.get("/{run_id}/hindsight/{path:path}")
def get_hindsight_file(
    run_id: str,
    path: str,
    request: Request,
    store: Any = Depends(get_store),
) -> Response:
    """Serve static hindsight file from run directory with byte-range support."""
    run = _get_run(store, run_id)
    if ".." in path.split("/") or ".." in path.split("\\"):
        raise APIError(status_code=404, code="not_found", message="Path outside run directory")

    base_dir = (run.run_dir / "hindsight").resolve()
    target_file = (base_dir / path).resolve()

    try:
        target_file.relative_to(run.run_dir.resolve())
    except ValueError:
        raise APIError(status_code=404, code="not_found", message="Path outside run directory")

    if not target_file.is_file():
        raise APIError(status_code=404, code="not_found", message=f"Hindsight file '{path}' not found")

    guessed_type, _ = mimetypes.guess_type(target_file)
    media_type = guessed_type or "application/octet-stream"
    return range_file_response(target_file, request.headers.get("Range"), media_type=media_type)
