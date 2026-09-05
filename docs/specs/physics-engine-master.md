# Physics engine master spec

Status: accepted 2026-09-05. Owner: physics track. Sub-specs derive from section 12, one per implementation cycle, written to `pipeline/features/<slug>/spec.md` using the team template. The parallel run configuration, file ownership, and per-cycle procedure are in [physics-engine-cycles.md](physics-engine-cycles.md).

Governing documents: decisions [0001](../decisions/0001-physics-engine-must-predict-not-package.md) to [0008](../decisions/0008-scenario-is-data-not-code.md), contract 0 [scenario](../contracts/scenario.md), contract 1 [physics products](../contracts/contract-1-physics-products.md), verified data facts [0000](../decisions/0000-verified-data-findings.md). Where this spec and an older document disagree, the decisions and contracts win.

## 1. Scope

The physics track owns, per FeatureBreakdown section 1 and the decisions:

| In scope | Out of scope for this track |
|---|---|
| Data ingest: HAND FIM artifacts, NWM analysis and short range, USGS continuous records | Impact extractor and exposure layers (RAG and data track, contract 1 is the interface) |
| The engine: state estimation, boundary forecasting, channel routing, HAND mapping, ensemble reduction | Any LLM call |
| Products and the engine API of contract 1 | Product UI (frontend track); the verifier here is a development tool |
| Clock service (FeatureBreakdown assigns it here) | Session state store (jointly owned, frontend builds it) |
| Verifier frontend (decision 0005) | PostGIS and TiTiler unless a decision 0006 trigger fires |
| Hindcast skill computation | Search-area tool (RAG and data track, reads contract 1 products) |
| Terrain tileset for Cesium, conditional on the frontend choosing Cesium | Residual correction model and 2D solver until Tier 1 skill is measured |

## 2. Goals and acceptance for the whole engine

1. For any `(p, t)` on the 5-minute grid within the record, the engine returns contract 1 products from data available at `p` only.
2. Hindcast skill is computed, stored, and displayed. Target for the demo scenario: mid-member discharge error at the interior gauges at 60 and 120 minute horizons is lower than persistence (last observed value held) for cutoffs between 06:00Z and 10:00Z on 2025-07-04. If not met, the verifier says so and the limitations text is updated.
3. Hindsight run reproduces observed discharge at gauged reaches within 5 percent at every 5-minute step where an observation exists, because observations are hard controls there.
4. A `(p, t)` request for the corridor completes within the budget measured in cycle C06 and recorded in decision 0003.
5. A second scenario file for another HUC8 runs the prep and produces a hindsight product with no code change.
6. Every raster matches its manifest grid; every table validates against its schema; no scenario literal exists in code.

## 3. Runtime and repository layout

- Python 3.12, which is installed at `C:\Users\splat\AppData\Local\Programs\Python\Python312`. Create the environment with `py -3.12 -m venv .venv`. No uv, no Docker for the engine. This machine has no NVIDIA GPU, so any PyTorch work is CPU only.
- Dependencies, pinned in `pyproject.toml`: numpy, pandas, pyarrow, scipy, rasterio, rio-cogeo, pyproj, shapely, geopandas, pyogrio, xarray, h5netcdf, httpx, pydantic 2, jsonschema, fastapi, uvicorn, websockets, pillow, pytest, pytest-asyncio.
- `src/` layout, package `flood`, console script `flood`.

```
pyproject.toml
.gitignore                      data/, runs/, .venv/, __pycache__/
scenarios/kerr-2025-07-04.json  copied from docs/contracts/examples, then maintained here
src/flood/
  contracts/      pydantic models mirroring docs/contracts/schemas, plus validate_json(schema_name, obj)
  scenario.py     load, validate, resolve relative paths
  timegrid.py     snap_p, snap_t, compact(), parse(), horizon checks
  timing.py       stage timer context manager emitting structured log lines
  ingest/
    hand.py       download HAND branch artifacts, clip to AOI, build the cube
    hydrotable.py rating tables per (branch, HydroID) as dense arrays
    network.py    reach network and topology from nwm_subset_streams_levelPaths.gpkg
    nwm.py        download and subset NWM analysis and short range to Parquet
    usgs.py       fetch USGS continuous records to Parquet
  engine/
    cube.py       HandCube: per-branch arrays on the common grid, catchment index
    rating.py     Q to stage, stage to Q, wetted area, hydraulic radius, top width, celerity
    forcing.py    ForcingView(p): what is known at p, with availability latency and outages
    routing.py    Muskingum-Cunge over the network with gauge controls and junction inference
    boundary.py   trend_relax member forecasts at boundary inputs
    mapping.py    Q per reach to depth, velocity, hazard rasters per member
    ensemble.py   member reduction, prob_inundated, time_to_exceedance
    run.py        Run: manifest, (p, t) resolution, product build, cache
  products/
    raster.py     COG writer with band descriptions and units, PNG overlay in EPSG:3857
    tables.py     reaches and gauges Parquet and JSON
    manifest.py   run.json creation and config_hash
  skill/
    hindcast.py   error by gauge, cutoff, horizon; persistence baseline; extent IoU vs hindsight
  api/
    app.py        FastAPI application factory
    runs.py       contract 1 section 9 routes
    scenarios.py
    clock.py      REST and WebSocket
  clock/
    service.py    replay clock state machine
  verifier/
    static/       index.html, app.js, style.css
  cli.py          flood prep hand | prep forcing | run create | run state | skill | serve
tests/
  fixtures/mini_huc/   synthetic 2-branch, 5-catchment cube, 6-reach network, canned forcing
  test_*.py
data/            gitignored; hand/<huc8>/, nwm/<scenario_id>/, usgs/<scenario_id>/, cube/<scenario_id>/
runs/            gitignored
```

## 4. Time model

- Grid step 5 minutes. `snap_p` floors, `snap_t` rounds to nearest. `t < p` and `t - p > max_horizon_minutes` are errors with the contract 1 error codes.
- `p = hindsight` means `p = record_end` and no forecast component; products go under `hindsight/t=<T>/`.
- Every ingested record has `valid_time` and an availability rule. A record is known at `p` if `valid_time + latency <= p` (observations, NWM analysis) or `issue_time + latency <= p` (NWM short range). Scenario overrides of type `gauge_outage` remove a gauge's observations with `valid_time >= from` (and `< to` if given).
- Internal timestamps are timezone-aware UTC `datetime`; Parquet columns are `timestamp[us, UTC]`; JSON uses the contract string form.

## 5. Data ingest

### 5.1 HAND FIM (`flood prep hand <scenario>`)

Source prefix: `https://ciroh-owp-hand-fim.s3.amazonaws.com/hand_fim_<fim_version with underscores>/<huc8>/`. Anonymous HTTPS GET. Files fetched per HUC8 into `data/hand/<huc8>/`:

- `hydrotable.parquet` (fallback `hydrotable.csv`), `branch_ids.csv`, `nwm_subset_streams_levelPaths.gpkg`, `usgs_elev_table.csv`, `nwm_lakes_proj_subset.gpkg`
- Per branch listed in `branch_ids.csv`: `branches/<b>/rem_zeroed_masked_<b>.tif`, `branches/<b>/gw_catchments_reaches_filtered_addedAttributes_<b>.tif`

Downloads are idempotent: skip when the file exists with the expected `Content-Length`.

Common grid: the scenario AOI bounds, which must be multiples of 10 in EPSG:5070 (validation error otherwise), at 10 m. `width = (xmax - xmin) / 10`, `height = (ymax - ymin) / 10`, `transform = [10, 0, xmin, 0, -10, ymax]`. All HAND branch rasters share this alignment, so clipping is a window read with `rasterio.windows.from_bounds`, padded with nodata where a branch does not cover the AOI. Branches whose extent does not intersect the AOI are dropped.

Cube on disk at `data/cube/<scenario_id>/`:

- `meta.json`: grid, list of branches kept, per branch the catchment index table path, fim_version, source URLs, created_at.
- `rem_<b>.npy`: float32 metres, `NaN` where nodata (source int16 millimetres, nodata 32767, divided by 1000).
- `catch_<b>.npy`: int32 catchment index `cidx` into that branch's rating arrays, `-1` where nodata (source int16 HydroID, nodata 0).
- `rating_<b>.npz`: arrays of shape `[n_catchments, 84]` for `stage_m`, `q_cms`, `wet_area_m2`, `hyd_radius_m`, `top_width_m`; arrays of shape `[n_catchments]` for `hydro_id`, `feature_id`, `lake_id`, `stream_order`, `length_km`, `slope`, `manning_n`. Rows sorted by `cidx`. Built from the HUC hydrotable filtered to `branch_id == b`, keyed by `(branch_id, HydroID)` because HydroIDs repeat across branches.
- `network.parquet`: one row per reach in the HUC subset: `feature_id`, `to_feature_id` (0 at outlet), `stream_order`, `levelpath_id`, `length_m`, `slope`, `gauge_site` (nullable), `in_aoi` (flowline intersects AOI bounds), `preferred_branch` (the levelpath branch containing this feature_id if any, else 0), `representative_cidx` (the longest catchment of this feature_id in the preferred branch), plus the flowline as WKB for the overlay and the search-area tool.
- `gauges.parquet`: from `usgs_elev_table.csv`, one row per site: `site`, `feature_id`, `dem_adj_elevation_m`, `gauge_altitude_m`, `altitude_datum`, joined with the scenario's gauge list and role.

Reach set for routing: every reach in the HUC subset, not only `in_aoi`, so boundary inflows enter at true headwaters. Rasters cover the AOI only.

### 5.2 NWM (`flood prep forcing <scenario>`)

Bucket `national-water-model` on GCS, anonymous, listed with the JSON API `https://storage.googleapis.com/storage/v1/b/national-water-model/o?prefix=...`, downloaded from `https://storage.googleapis.com/national-water-model/<name>`.

- Analysis: `nwm.<YYYYMMDD>/analysis_assim/nwm.t<HH>z.analysis_assim.channel_rt.tm00.conus.nc` for every hour with `valid_time` in `[record_start, record_end]`.
- Short range: `nwm.<YYYYMMDD>/short_range/nwm.t<HH>z.short_range.channel_rt.f<FFF>.conus.nc` for every cycle with `issue_time` in the record window and `FFF` from 001 to `max_lead_hours` of the scenario's `nwm_short_range` source (6 for Kerr). About 48 cycles times 6 files times 14 MB.
- Open each file with `xarray` and `h5netcdf`, select `feature_id` values in the HUC subset (the union of `network.parquet` feature IDs), read `streamflow`, `velocity`, `qSfcLatRunoff`, `qBucket` with CF decoding on. Append to Parquet, then delete the raw file unless `--keep-raw`.
- Outputs: `data/nwm/<scenario_id>/analysis.parquet` with columns `valid_time`, `feature_id`, `q_cms`, `v_ms`, `qlat_cms` (`qSfcLatRunoff + qBucket`); `short_range.parquet` with `issue_time`, `valid_time`, `feature_id`, `q_cms`, `qlat_cms`.

### 5.3 USGS (`flood prep forcing <scenario>`, same command)

Endpoint `https://api.waterdata.usgs.gov/ogcapi/v0/collections/continuous/items` with `monitoring_location_id=USGS-<site>`, `parameter_code` in the source's `parameters`, `datetime=<record_start - 1 day>/<record_end + 1 day>`, `f=json`, `limit=10000`, following `links[rel=next]` until exhausted. One request per site and parameter.

Output `data/usgs/<scenario_id>/continuous.parquet`: `site`, `valid_time`, `parameter` (`00060` or `00065`), `value_si` (cfs times 0.0283168 to cms; ft times 0.3048 to m), `approval` if present. Gauge datum for WSE comes from the cube's `gauges.parquet`.

### 5.4 Terrain for Cesium (conditional cycle)

Only if the frontend picks CesiumJS. 3DEP 1 m tiles for the AOI from the AWS 3DEP bucket, merged and reprojected, converted to quantized mesh with `cesium-terrain-builder` in Docker. Output under `data/terrain/<scenario_id>/`, served as static files by the API. Not a dependency of anything else in this spec.

## 6. Engine

### 6.1 Rating (`rating.py`)

Per catchment arrays from the cube. `stage_from_q(cidx, q)` linear interpolation on `q_cms` to `stage_m`, clamped to the top row, returning a `clipped` flag. `wet_area(cidx, stage)`, `hyd_radius(cidx, stage)`, `top_width(cidx, stage)` by interpolation on stage. `celerity(cidx, q)` is `dQ/dA` from finite differences of `q_cms` against `wet_area_m2`, evaluated at `q`, floored at 0.1 m/s and capped at 10 m/s. Applying `roughness.manning_n_scale = s` multiplies `q_cms` by `1/s` before all lookups, which is the Manning relation's response to scaling n.

### 6.2 What is known at `p` (`forcing.py`)

`ForcingView(scenario, p)` exposes:

- `obs_q(site) -> Series` of observed discharge with `valid_time + 5 min <= p`, outages removed. Also `obs_wse`.
- `nwm_analysis(feature_id) -> Series` with `valid_time + 60 min <= p`.
- `latest_short_range(feature_id) -> Series` from the most recent cycle with `issue_time + 90 min <= p`, or empty.
- `qlat(feature_id, tau)`: lateral inflow at time `tau`: analysis where known, else the latest known short range at `tau`, else the last known analysis value held. Multiplied by the levelpath bias ratio (6.3).

### 6.3 Bias ratio

For each levelpath with at least one interior or boundary gauge, `ratio = clamp(obs_q / nwm_q, ratio_clamp)` using the latest time at which both are known, taken at the gauge nearest downstream of the reach on the same levelpath, else nearest upstream. Levelpaths with no gauge use ratio 1.0. When `bias_correction = none`, ratio is 1.0 everywhere.

### 6.4 Routing with controls (`routing.py`)

One routing pass per `p` produces `Q(feature_id, tau)` for `tau` from `p - 360 min` to `p + max_horizon_minutes` at `routing.dt_minutes`, for every reach in the network, in topological order (upstream first). Cached per `(run, p)` so every `t` for that `p` reuses it.

For each reach and step:

1. `q_in(tau) = sum of upstream Q_out(tau) + qlat(tau)`.
2. `Q_out(tau + dt)` by Muskingum-Cunge with variable parameters: `c = celerity(representative_cidx, q_ref)`, `B = top_width`, `K = length_m / c`, `X = 0.5 * (1 - q_ref / (B * slope * c * length_m))` clamped to `[0, 0.5]`, `q_ref = 0.5 * (q_in(tau) + Q_out(tau))`. Standard `C0, C1, C2` from `K, X, dt`. Sub-step within the reach when `dt > 2 K (1 - X)` so no coefficient is negative. Reaches without a rating row use `c` from Manning with `n = 0.06` and the network slope, `B` 10 m.
3. Controls at gauged reaches, by role:
   - `interior` and `boundary`: while an observation is known at `tau` (`tau <= t_last` for that site under `p`), `Q_out(tau) := obs_q(tau)` interpolated to `tau`. Hard control.
   - `interior` after `t_last`: `Q_out(tau) := routed(tau) + (obs_q(t_last) - routed(t_last)) * exp(-(tau - t_last) / relax_minutes)`. The bias decays; upstream routed water takes over.
   - `boundary` after `t_last`: `Q_out(tau) := trend_relax(site, tau, member)` from 6.5, because nothing upstream informs it.
   - `validation_only`: never a control.
4. Junction inference, when `use_junction_inferences` is true: for each entry, the inferred reach's `Q_out(tau) := max(0, obs_q(downstream_gauge, tau + travel_time) - sum(obs_q(g, tau) for g in subtract_gauges))` while those observations are known, else `trend_relax` on the inferred series after its own `t_last`. Applied before routing the inferred reach's downstream neighbours.
5. Members differ only in the `trend_relax` multiplier applied at boundary and inferred inputs. Three passes, or one vectorised pass over members.

### 6.5 Boundary forecast (`boundary.py`)

`trend_relax(series, tau, m)`: with `t_last` the last known time, `q0 = series(t_last)`, `r = (q0 - series(t_last - trend_window_minutes)) / trend_window_minutes` in cms per minute, `d = tau - t_last` in minutes: `q = max(0, q0 + m * r * relax_minutes * (1 - exp(-d / relax_minutes)))`. The rise continues at rate `m r` initially and plateaus at `q0 + m r relax` after a few relaxation times. `persistence` is `m = 0`. `nwm_short_range` and `blend` are not in Tier 1 and return `NotImplementedError` with a clear message.

### 6.6 Mapping (`mapping.py`)

Given `Q(feature_id)` for one member at one `t`: for each branch in the cube, `stage_lut[cidx] = stage_from_q(cidx, Q[feature_id of cidx])` in metres, `NaN` for lake catchments and for catchments whose feature has no Q. `depth = stage_lut[catch] - rem`, set to 0 where `rem < 0`, where `depth < 0.03`, or where either input is nodata. Mosaic across branches by `np.fmax`. Velocity per contract 1 section 7 using the mid-member Q. `hazard = depth * velocity`. Returns float32 arrays on the common grid; nodata `-9999` is applied only at write time where no branch covers the cell.

### 6.7 Ensemble (`ensemble.py`)

`prob_inundated = mean over members of (depth >= 0.03)`. `time_to_exceedance` per threshold scans `t` from `p` to `p + max_horizon` in 5-minute steps on the mid member and records the first exceedance in minutes, `0` if exceeded at `p`, `-1` if never.

### 6.8 Run orchestration (`run.py`)

`Run.create(scenario, mode, forcing_overrides)` merges forcing, computes `config_hash` as `sha256` of `json.dumps(config, sort_keys=True, separators=(",", ":"))`, writes `run.json`, creates the directory tree. `Run.state(p, t)` snaps, validates, gets or builds the routed series for `p`, maps each member at `t`, reduces, writes products only when asked for file outputs, returns the state response with `compute_ms` per stage. In-memory LRU of routed series and of the last N depth arrays; disk cache of written products; `cache` field reports `hit`, `miss`, or `precomputed`. Timing lines are logged as JSON per stage. Hindsight uses the same path with `p = record_end`.

## 7. Products

Exactly contract 1. Raster band descriptions and `units` set via rasterio `set_band_description` and `update_tags(band, units=...)`. COG via `rio_cogeo.cog_translate` with `deflate` profile and 256 blocks. PNG overlay: reproject the requested band to EPSG:3857 with `rasterio.warp.reproject` at a size capped by `max_px`, apply the ramp `0.03 m #bfe3ff, 0.5 m #6fb3ff, 1.0 m #2a7fff, 2.0 m #0a4fc0, 4.0 m and above #052a66`, transparent below 0.03 m and at nodata, return bounds in the `X-Bounds-3857` header.

## 8. Clock service

REST: `GET /clock` returns `{mode, t, speed, playing, record_start, record_end}`; `POST /clock` accepts any subset of `{t, speed, playing}`; `POST /clock/reset`. WebSocket `/clock/ws` pushes the same object every wall second while playing and immediately on any change. Replay advances `t` by `speed` seconds per wall second, clamped to the record. The clock knows nothing about `p`; lag and horizon are UI or session settings.

## 9. Verifier

Static page served at `/verifier`. Panels and the endpoints they use:

| Panel | Endpoint |
|---|---|
| Map with depth PNG overlay, band selector, prob toggle | `overlay.png` |
| Timeline bound to the clock, mode selector nowcast, forecast with horizon, stale with lag | `/clock`, `/clock/ws`, `state` |
| Hindsight difference toggle | `overlay.png` twice, blended client side |
| Gauge chart: observed vs predicted discharge per site for the selected `p` | `gauges` |
| Reach table for the selected `(p, t)` | `reaches` |
| Skill table | `/runs/{run_id}/skill` (cycle C10) |
| Compute timing readout | `state.compute_ms` |

Leaflet from a CDN, a plain `<canvas>` chart or Chart.js, no build step.

## 10. Hindcast skill (`skill/hindcast.py`)

For cutoffs `p` on a configurable grid (default every 30 minutes across the record) and horizons `{0, 30, 60, 120, 240}`: per gauge, mid-member predicted discharge vs observed at `p + h`, mean absolute error and bias, and the same for persistence. Extent IoU of mid-member depth at least 0.15 m vs hindsight at the same `t`. Stored as `runs/<run_id>/skill.parquet`, served as `GET /runs/{run_id}/skill`, shown in the verifier. This is acceptance criterion 2.

## 11. Testing strategy

- `tests/fixtures/mini_huc/`: a synthetic cube with two branches, five catchments, a six-reach network with one confluence and two gauges, a hand-built rating table, and canned forcing. Every algorithm test runs on it in under a second.
- Mapping test asserts exact depths for a hand-computed case. Routing tests assert mass conservation at steady state, a lag between upstream and downstream peaks within 20 percent of `length / celerity`, and that a hard control reproduces observations exactly. Forcing tests assert availability filtering at latency boundaries and outage removal.
- Contract tests validate every produced JSON and every Parquet schema against `docs/contracts/schemas`.
- Network-dependent tests are marked `@pytest.mark.network` and skipped by default.

## 12. Sub-spec plan

Each row is one implementation cycle. Sub-specs are written to `pipeline/features/<slug>/spec.md` in the team's template, with a section "Implementer notes" giving exact signatures, file paths, and test names, since the implementer is a fast model.

| # | Slug | Scope | Depends on | Acceptance in one line |
|---|---|---|---|---|
| C01 | `engine-scaffold-contracts` | pyproject, venv instructions, package skeleton, `.gitignore`, pydantic models for all contract schemas, `scenario.py`, `timegrid.py`, `timing.py`, CLI skeleton, `scenarios/kerr-2025-07-04.json` | none | `pytest` green; `flood scenario validate scenarios/kerr-2025-07-04.json` passes; contract examples validate through the pydantic models |
| C02 | `hand-ingest-cube` | 5.1 in full, mini_huc fixture builder | C01 | `flood prep hand` builds the cube for Kerr; fixture cube built by a test; meta.json grid equals scenario AOI |
| C03 | `hand-mapping-core` | 6.1, 6.6, 6.7, COG writer, `flood map --q <csv> --t <T>` for ad hoc Q | C02 | Exact-depth test passes on fixture; a real Kerr map from a CSV of Q renders in QGIS with named bands |
| C04 | `forcing-ingest-nwm-usgs` | 5.2, 5.3, 6.2 ForcingView, 6.3 ratio | C01 | Parquet outputs for Kerr; availability and outage tests pass on canned fixtures |
| C05 | `routing-forecast` | 6.4, 6.5, junction inference, member passes, routed-series cache | C02, C04 | Routing tests pass; hindsight at Hunt and Kerrville reproduces observations (criterion 3) |
| C06 | `run-orchestrator-products` | 6.8, 7, tables, manifest, cache, timing; `flood run create` and `flood run state` | C03, C05 | Full `(p, t)` for Kerr produces all contract 1 products that validate; timings logged; decision 0003 updated with measurements |
| C07 | `engine-api` | Contract 1 section 9 routes, overlay.png, error codes, static file serving | C06 | TestClient suite covers every route and error code; example state response validates |
| C08 | `clock-service` | Section 8 | C01 | REST and WebSocket tests; replay advances and clamps |
| C09 | `verifier-ui` | Section 9 | C07, C08 | Manual checklist in the spec passes; page loads with zero console errors against a Kerr run |
| C10 | `hindcast-skill` | Section 10 | C06 | `skill.parquet` for Kerr; criterion 2 evaluated and result written into the run's limitations text |
| C11 | `second-scenario-smoke` | Scenario file for another HUC8, prep and hindsight only | C06 | Criterion 5 met with zero code diff |
| C12 | `terrain-cesium` | 5.4 | frontend decision | Tileset loads in Cesium sandcastle |
| C13 | `boundary-blend-short-range` | `nwm_short_range` and `blend` methods in 6.5 | C10 | Skill table shows the comparison |
| C14 | `rainfall-inflow-tier2` | MRMS QPE ingest, catchment aggregation, simple runoff to `qlat` | C13, data check | Skill at ungauged South Fork improves against hindsight |

Cycle order for one developer: C01, C02, C03, C04, C05, C06, C07, C08, C09, C10, C11. C08 can run any time after C01 if a second person is free. C12 to C14 only after C10.

## 13. Assumptions and known risks

- Corridor AOI bounds in the scenario are placeholders until C02 confirms them against the HAND branch extents and the gauge locations.
- NWM short-range volume is about 4 GB raw for the Kerr record window; raw files are deleted after subsetting.
- The Hunt gauge may have a gap at the peak. Controls fall back to the `interior` post-`t_last` rule automatically; the scenario may also declare it as a `gauge_outage` to test the stale-information mode.
- `usgs_data_altitude` datums differ (NAVD88 and NGVD29). WSE is reported as approximate; discharge is the primary skill metric.
- FeatureBreakdown names PostGIS and TiTiler for this track. Decision 0006 supersedes it: files and in-process serving first.
- No GPU on the development machine, so the 2D inertial solver from decision 0001 Tier 2 is deferred unless a teammate has one.
