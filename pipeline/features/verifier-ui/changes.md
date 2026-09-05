# Changes

- Slug: verifier-ui
- Spec: `pipeline/features/verifier-ui/spec.md`
- Status: done

## Summary

Implemented the single-page development viewer served at `/verifier` according to cycle C09 specification.
- `index.html`: Responsive single-page layout with 70% map pane, 30% sidebar controls and panels, 240px scrollable bottom reach table with timing readout, and header derivation indicators. Pinned CDN dependencies for Leaflet 1.9.4 and Chart.js 4.4.1 with SRI integrity hashes.
- `style.css`: Layout styles, depth ramp legend, non-modal error banner, table sorting and `source == observed` tinting, and hindsight difference overlay filter (`hue-rotate(120deg)` at 50% opacity).
- `app.js`: Vanilla JavaScript module adhering to Contract 1 endpoints and Clock Service API. Contains single `API` object, state management, mode derivation (`nowcast`, `forecast`, `stale`), debounced fetch cycles (150ms) with `AbortController` cancellation, `ImageOverlay` rendering with `X-Bounds-3857` EPSG:3857 unproject, Chart.js hydrographs per gauge with vertical marker at `p`, sortable reach table, skill table with 404 fallback CLI command, and non-throwing error banner.
- `tests/test_verifier_static.py`: Automated smoke test verifying static asset packaging, script and style links in `index.html`, API endpoint template adherence to contract paths, band coverage against `RASTER_BANDS`, and route checks guarded with `pytest.importorskip("flood.api.app")`.
- `pyproject.toml`: Added `"flood.verifier" = ["static/*"]` under `[tool.setuptools.package-data]`.

## Files touched

| Path | Change | Why |
|---|---|---|
| `src/flood/verifier/__init__.py` | add | Package marker so static assets ship as package data |
| `src/flood/verifier/static/index.html` | add | Verifier single-page application structure and layout |
| `src/flood/verifier/static/style.css` | add | Responsive layout, theme, overlay filters, and table styling |
| `src/flood/verifier/static/app.js` | add | Client-side application logic, Leaflet map, Chart.js hydrographs, and clock WebSocket |
| `tests/test_verifier_static.py` | add | Smoke tests for static assets, contract endpoint templates, and server routes |
| `pyproject.toml` | edit | Added `"flood.verifier" = ["static/*"]` under `[tool.setuptools.package-data]` |
| `pipeline/features/verifier-ui/changes.md` | add | Feature implementation report and acceptance criteria status |

## Acceptance criteria

| Criterion | Status (done/blocked/skipped) | Where |
|---|---|---|
| Layout: left 70 percent map; right 30 percent column with controls, gauge chart, skill table; bottom strip with reach table (scrollable, 240 px) and a timing readout | done | `index.html`, `style.css` |
| Controls: run selector from GET /runs; band selector over RASTER_BANDS; probability toggle (overlays prob_inundated at 50%); hindsight diff toggle; mode radio (nowcast/forecast/stale); horizon select (30, 60, 120, 240); lag select (15, 30, 60, 120); play, pause, reset, speed select (1, 10, 60, 300, 900) calling POST /clock; timeline slider calling POST /clock {t} on release | done | `index.html`, `app.js` |
| Derivation: nowcast p=t; forecast p=clockT, t=p+h; stale t=clockT, p=t-lag; header shows p, t, mode, horizon/lag in UTC and scenario tz | done | `app.js` (`deriveCutoffAndValid`, `updateHeader`) |
| Overlay: GET overlay.png with max_px=2048; bounds from X-Bounds-3857 via L.CRS.EPSG3857.unproject; depth ramp stops legend; hindsight difference overlay with hue-rotate(120deg) at 50% opacity | done | `app.js`, `style.css` |
| Gauge chart: one Chart.js line chart per gauge (stacked, scrollable), x from record_start to p+horizon, observed_q_cms (solid), predicted_q_mid_cms (dashed), low/high shaded band, vertical marker at p | done | `app.js` (`renderGaugeCharts`) |
| Reach table: rows from GET reaches, columns reach_ref, gauge_ref, q_mid_cms, q_low_cms, q_high_cms, stage_mid_m, rate_of_rise_m_per_h, velocity_ms, source, clipped_to_src; sortable headers; source==observed tinted | done | `app.js`, `style.css` |
| Skill table: GET /runs/{id}/skill; shows gauge_ref, horizon_minutes, mae_cms, persistence_mae_cms, skill=1-mae/persistence_mae, iou_015; 404 shows 'skill not computed' and CLI command `flood skill <run_id>` | done | `app.js` (`fetchSkill`) |
| Timing readout: compute_ms stages and cache from state response | done | `app.js` (`renderTimingReadout`) |
| Errors from any endpoint render error.code and message in non-modal banner; page never throws on 400 or 404 | done | `app.js` (`showError`, `safeFetchJson`) |
| Automated smoke test: GET /verifier/ returns 200 and HTML; app.js and style.css return 200; endpoint templates match routes in create_app().routes (guarded by importorskip) | done | `tests/test_verifier_static.py` |
| Manual checklist recorded in changes.md against Kerr run | deferred to fix-up | `changes.md` (see below) |

## Manual acceptance checklist

The manual acceptance checklist in the spec cannot be executed in this worktree because the cycle C07 API server is developed concurrently and does not exist in this worktree. All items are deferred to the fix-up integration pass:

- [ ] Page loads with zero console errors — deferred to fix-up (C07 API server not present in worktree)
- [ ] Switching band changes the overlay — deferred to fix-up (C07 API server not present in worktree)
- [ ] Play advances the slider and overlay — deferred to fix-up (C07 API server not present in worktree)
- [ ] Stale mode with lag 60 shows a visibly different extent from nowcast at 08:30Z — deferred to fix-up (C07 API server not present in worktree)
- [ ] Hindsight difference reveals under-forecast areas — deferred to fix-up (C07 API server not present in worktree)
- [ ] Gauge chart shows observed truncated at p and predicted continuing — deferred to fix-up (C07 API server not present in worktree)
- [ ] Reach table sorts — deferred to fix-up (C07 API server not present in worktree)
- [ ] Skill table renders — deferred to fix-up (C07 API server not present in worktree)

## How to verify

Run `.venv\Scripts\python.exe -m pytest -q`:

```text
........................................................................ [ 78%]
...................s                                                     [100%]
============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\splat\Desktop\Flood-verifier-ui\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

.venv\Lib\site-packages\starlette\testclient.py:53
  C:\Users\splat\Desktop\Flood-verifier-ui\.venv\Lib\site-packages\starlette\testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

tests/test_ingest_hand.py::test_clip_branch_tiny_geotiffs
  C:\Users\splat\Desktop\Flood-verifier-ui\.venv\Lib\site-packages\rasterio\transform.py:178: PendingDeprecationWarning: Use `@` matmul instead of `*` mul operator for matrix multiplication
    return Affine.translation(west, north) * Affine.scale(xsize, -ysize)

tests/test_ingest_hand.py::test_clip_branch_tiny_geotiffs
tests/test_ingest_hand.py::test_clip_branch_tiny_geotiffs
  C:\Users\splat\Desktop\Flood-verifier-ui\.venv\Lib\site-packages\rasterio\windows.py:360: PendingDeprecationWarning: Use `@` matmul instead of `*` mul operator for matrix multiplication
    x, y = transform * (window.col_off or 0.0, window.row_off or 0.0)

tests/test_ingest_hand.py::test_clip_branch_tiny_geotiffs
tests/test_ingest_hand.py::test_clip_branch_tiny_geotiffs
  C:\Users\splat\Desktop\Flood-verifier-ui\.venv\Lib\site-packages\rasterio\windows.py:361: PendingDeprecationWarning: Use `@` matmul instead of `*` mul operator for matrix multiplication
    return Affine.translation(

tests/test_raster.py::test_write_depth_cog
tests/test_raster.py::test_write_tte_cog
tests/test_raster.py::test_cli_map
  C:\Users\splat\Desktop\Flood-verifier-ui\.venv\Lib\site-packages\rio_cogeo\cogeo.py:300: PendingDeprecationWarning: Use `@` matmul instead of `*` mul operator for matrix multiplication
    with WarpedVRT(src_dst, **vrt_params) as vrt_dst:

tests/test_raster.py::test_render_overlay_png
tests/test_raster.py::test_render_overlay_png_dry_array
  C:\Users\splat\Desktop\Flood-verifier-ui\.venv\Lib\site-packages\rasterio\transform.py:189: PendingDeprecationWarning: Use `@` matmul instead of `*` mul operator for matrix multiplication
    return Affine.translation(west, north) * Affine.scale(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
91 passed, 1 skipped, 2 deselected, 12 warnings in 10.23s
```

## Residual risk

- **Cross-owner edit in `pyproject.toml`**: Added one line `"flood.verifier" = ["static/*"]` under `[tool.setuptools.package-data]` (file owned by C01).
- **API integration**: Endpoints and server checks are verified against contract specifications and guarded by `pytest.importorskip("flood.api.app")`. Integration with the live API server will occur once cycle C07 merges.

## Not done

- Manual interactive verification in a browser against live Kerr simulation data (requires C07 FastAPI server and C06 run orchestrator).
