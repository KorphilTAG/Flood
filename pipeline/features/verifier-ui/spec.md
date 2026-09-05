# Feature spec

- Slug: verifier-ui
- Feature: C09. Single-page development viewer served at `/verifier`: depth overlay on a 2D map, timeline bound to the clock, nowcast, forecast, and stale-information modes, hindsight difference, gauge charts of observed versus predicted discharge, reach table, skill table, compute timing.
- Status: draft
- Product refs: decision 0005; `docs/specs/physics-engine-master.md` section 9; decision 0002 (three modes); contract 1 section 9 (endpoints).

## Problem

Engine output must be inspected early and numerically, without waiting for the product UI or standing up Cesium.

## In scope

- `src/flood/verifier/static/index.html`, `app.js`, `style.css`. No build step. Leaflet 1.9 and Chart.js 4 from cdnjs.
- All panels in the table below, fed only by the contract 1 endpoints and the clock endpoints.
- A manual acceptance checklist in this spec and an automated smoke test that the page and its assets are served and reference only existing endpoints.

## Out of scope

3D, terrain, Cesium, deck.gl, styling beyond legibility, any endpoint not in contract 1, editing API code.

## Approach

Vanilla JavaScript module. State object `{runId, mode, lagMin, horizonMin, t, band, showProb, showDiff}`. The clock WebSocket drives `t`; `p` is derived per mode; each change debounced 150 ms triggers `GET state`, then overlay, reaches, gauges in parallel. The overlay is a Leaflet `ImageOverlay` whose bounds come from `X-Bounds-3857` converted to lat and lon with Leaflet's `L.CRS.EPSG3857.unproject`.

## Files to change

| Path | Action (add/edit) | Why |
|---|---|---|
| `src/flood/verifier/__init__.py` | add | empty, so the static dir ships as package data |
| `src/flood/verifier/static/index.html`, `app.js`, `style.css` | add | The page |
| `pyproject.toml` | edit, one line | add `"flood.verifier" = ["static/*"]` under package-data (coordinate: this is a C01 file; make the single-line edit and record it in changes.md) |
| `tests/test_verifier_static.py` | add | Smoke test |

## Acceptance criteria

- [ ] Layout: left 70 percent map; right 30 percent column with controls, gauge chart, skill table; bottom strip with the reach table (scrollable, 240 px) and a timing readout.
- [ ] Controls: run selector populated from `GET /runs`; band selector over `RASTER_BANDS`; probability toggle (overlays `prob_inundated` at 50 percent opacity on top of depth); hindsight difference toggle; mode radio `nowcast | forecast | stale`; horizon select `30, 60, 120, 240` (forecast mode); lag select `15, 30, 60, 120` (stale mode); play, pause, reset, speed select `1, 10, 60, 300, 900` calling `POST /clock`; a timeline slider spanning `record_start` to `record_end` that reflects clock `t` and, on release, calls `POST /clock {t}`.
- [ ] Derivation: nowcast `p = t`; forecast `p = clockT, t = p + horizon`; stale `t = clockT, p = t - lag`. The header shows `p`, `t`, mode, and horizon or lag in both UTC and the scenario timezone (from `GET /scenarios/{id}`, using `Intl.DateTimeFormat`).
- [ ] Overlay: `GET overlay.png` for the selected band with `max_px=2048`; bounds from `X-Bounds-3857`; legend with the depth ramp stops; a "hindsight difference" mode that requests the hindsight overlay for the same `t` and shows it at 50 percent under the forecast overlay with a distinct hue shift (CSS filter `hue-rotate(120deg)`).
- [ ] Gauge chart: one Chart.js line chart per gauge (stacked vertically, scrollable), x from `record_start` to `p + horizon`, series `observed_q_cms` (solid), `predicted_q_mid_cms` (dashed), `low` and `high` as a shaded band, a vertical marker at `p`. Data from `GET gauges?p=`.
- [ ] Reach table: rows from `GET reaches?p=&t=`, columns `reach_ref, gauge_ref, q_mid_cms, q_low_cms, q_high_cms, stage_mid_m, rate_of_rise_m_per_h, velocity_ms, source, clipped_to_src`, sortable by clicking headers, rows with `source == observed` tinted.
- [ ] Skill table: from `GET /runs/{id}/skill`; shows `gauge_ref, horizon_minutes, mae_cms, persistence_mae_cms, skill = 1 - mae/persistence_mae, iou_015`; when 404, shows "skill not computed" and the CLI command to compute it.
- [ ] Timing readout: `compute_ms` stages and `cache` from the last state response.
- [ ] Errors from any endpoint render the `error.code` and `message` in a non-modal banner; the page never throws to the console on a 400 or 404.
- [ ] Automated smoke test: `GET /verifier/` returns 200 and HTML; `app.js` and `style.css` return 200; every `fetch(` string literal path in `app.js`, after stripping query strings and path parameters, matches a route in `create_app().routes`.
- [ ] Manual checklist recorded in `changes.md` against a Kerr run, each item marked done or blocked: page loads with zero console errors; switching band changes the overlay; play advances the slider and overlay; stale mode with lag 60 shows a visibly different extent from nowcast at 08:30Z; hindsight difference reveals under-forecast areas; gauge chart shows observed truncated at `p` and predicted continuing; reach table sorts; skill table renders.

## Non-goals and constraints

- No framework, no bundler, no npm.
- Only cdnjs for Leaflet and Chart.js, pinned versions, with `integrity` attributes.
- Do not call any endpoint outside contract 1 and `/clock`.

## Assumptions

- C07 mounts `/verifier` when the static directory exists.
- Overlay bounds are Web Mercator metres in `X-Bounds-3857`.

## Open questions

- None.

## Implementer notes

- Convert bounds: `L.CRS.EPSG3857.unproject(L.point(x, y))` returns a LatLng.
- Debounce with a single `setTimeout` handle; cancel in-flight fetches with `AbortController` when a newer request starts.
- Keep all endpoint paths in one `API` object at the top of `app.js` so the smoke test can find them.
