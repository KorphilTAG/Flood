# Contract 1. Physics products

Producer: physics engine. Consumers: impact extractor, run store, verifier UI, product UI.
Schema version 1.0, drafted 2026-09-05. Schemas: [run-manifest](schemas/run-manifest.schema.json), [forcing-config](schemas/forcing-config.schema.json), [reach-row](schemas/reach-row.schema.json), [gauge-row](schemas/gauge-row.schema.json), [state-response](schemas/state-response.schema.json). Shared definitions: [common](schemas/common.schema.json).

## 1. A run

A run is one scenario under one forcing configuration. It owns a manifest and a tree of products. Every raster in a run shares the manifest's grid exactly (same CRS, transform, width, height), so arrays from different `(p, t)` pairs can be subtracted directly.

```
runs/<run_id>/
  run.json
  products/p=<P>/t=<T>/depth.tif
  products/p=<P>/t=<T>/reaches.parquet
  products/p=<P>/time_to_exceedance.tif
  products/p=<P>/gauges.parquet
  hindsight/t=<T>/depth.tif
  hindsight/t=<T>/reaches.parquet
```

`<P>` and `<T>` are compact UTC timestamps, `20250704T0800Z`. Products may be produced on demand and cached, precomputed, or both (decision [0003](../decisions/0003-compute-strategy-measure-before-choosing.md)); the layout is the same either way. A consumer must not assume a file exists before asking the API for it.

## 2. Time grid and snapping

- Step is 5 minutes. `p` snaps down to the grid, `t` snaps to the nearest grid point.
- After snapping, `t < p` is an error (HTTP 400). `t - p` greater than `time.max_horizon_minutes` is an error (400).
- `t == p` is a nowcast. `t > p` is a forecast. `p = hindsight` selects the truth run, which uses the full record and has no forecast component.
- Availability, not validity, decides what is known at `p`. Each forcing source declares `availability_latency_min`; a record valid at time `v` is known at `p` only if `v + latency <= p`.

## 3. Manifest, `run.json`

See the schema and [examples/run.json](examples/run.json). Field notes:

| Field | Notes |
|---|---|
| `schema_version` | `"1.0"` |
| `run_id` | Lowercase slug. Suggested form `<scenario_id>-<mode>-<6 hex of config_hash>` |
| `mode` | `replay` or `live` |
| `scenario` | Copied from the scenario file: `scenario_id`, `name`, `huc8[]`, `fim_version`, `record_start`, `record_end`, `timezone` |
| `grid` | `crs` (always `EPSG:5070`), `resolution_m`, `width`, `height`, `transform` (6 numbers, GDAL order), `bounds`. Fixed by the prep step when the corridor is clipped. The numbers in the example are placeholders. |
| `time` | `step_minutes` (5), `max_horizon_minutes` (360) |
| `members` | `["low", "mid", "high"]`. Scenario members, not quantiles. `mid` is the reference member. |
| `forcing.config` | The forcing configuration actually used, section 8 |
| `forcing.config_hash` | `sha256:` of the canonical JSON of `forcing.config`. Part of every cache key. |
| `products` | Path templates relative to the run directory, with `{p}` and `{t}` placeholders |
| `limitations` | Plain-language strings the UI and the AAR generator must surface. Never empty. |
| `engine_version`, `created_at` | Provenance |

## 4. Raster product, `depth.tif`

Cloud-Optimized GeoTIFF, float32, DEFLATE, 256 by 256 tiles, on the manifest grid. Dry is `0`, outside the domain is `-9999`. Each band's description tag carries its name from the table below, and `units` is set in band metadata, so QGIS and rasterio display them.

| Band | Description | Units | Meaning |
|---|---|---|---|
| 1 | `depth_mid` | m | Water depth, mid member |
| 2 | `depth_low` | m | Water depth, low member |
| 3 | `depth_high` | m | Water depth, high member |
| 4 | `velocity_ms` | m/s | Proxy velocity, mid member (section 7) |
| 5 | `hazard_dv` | m2/s | `depth_mid * velocity_ms` |
| 6 | `prob_inundated` | fraction | Share of members with depth at least 0.03 m |

Depth is computed as the reference algorithm does: stage from the catchment's rating curve by linear interpolation on discharge, depth = stage minus HAND where HAND is non-negative and the result is at least 0.03 m, lake catchments excluded, branches mosaicked by per-cell maximum. Discharge above the top of a rating curve is clamped to the top stage and flagged in the reach table.

### `time_to_exceedance.tif`, one per `p`

Float32, three bands, on the manifest grid. Value is minutes after `p` (a multiple of 5) at which the mid member's depth first exceeds the band threshold, scanning `t` from `p` to `p + max_horizon_minutes`.

| Band | Description | Threshold | Rough meaning |
|---|---|---|---|
| 1 | `tte_015` | 0.15 m | Wading becomes unsafe with any current |
| 2 | `tte_030` | 0.30 m | Passenger vehicles lose traction or float |
| 3 | `tte_060` | 0.60 m | High-clearance vehicles float, ground-floor damage |

Special values: `0` already exceeded at `p`; `-1` not exceeded within the horizon; `-9999` outside domain.

## 5. Reach table, `reaches.parquet`

One row per NWM reach whose flowline intersects the AOI. Rows sorted by `feature_id`. Parquet with the types below; the API serves the same rows as JSON. Row schema: [reach-row.schema.json](schemas/reach-row.schema.json), sample: [examples/reaches.sample.json](examples/reaches.sample.json).

| Column | Parquet type | Notes |
|---|---|---|
| `reach_ref` | string | `reach:<feature_id>` |
| `feature_id` | int64 | NWM feature_id, for joins |
| `levelpath_id` | int64 | From the FIM stream network |
| `stream_order` | int8 | |
| `gauge_ref` | string, nullable | `gauge:<site>` when a gauge is on this reach |
| `p` | timestamp[us, UTC] | |
| `t` | timestamp[us, UTC] | |
| `is_forecast` | bool | `t > p` |
| `q_mid_cms`, `q_low_cms`, `q_high_cms` | float32 | Discharge per member, at least 0 |
| `stage_mid_m`, `stage_low_m`, `stage_high_m` | float32 | HAND stage above the reach's drainage cell. Not gauge height. |
| `rate_of_rise_m_per_h` | float32 | Mid member; stage at `t` minus stage at `t - 30 min`, times 2 |
| `velocity_ms` | float32 | Proxy, mid member |
| `source` | string | One of `observed`, `nwm_analysis_scaled`, `mass_balance`, `nwm_analysis`, `routed`, `forecast_trend`, `forecast_nwm_sr`. The dominant origin of `q_mid_cms` for this reach at `t`. |
| `clipped_to_src` | bool | Discharge exceeded the rating table and stage was clamped |

## 6. Gauge table, `gauges.parquet`, one per `p`

One row per gauge per 5-minute `t` from `record_start` to `p + max_horizon_minutes`. Rows with `t <= p` compare the engine's state estimate to observations; rows with `t > p` compare its forecast. Comparison is primarily on discharge, which is datum-free. Water surface elevation is NAVD88 metres: observed WSE is gauge height plus the gauge datum; predicted WSE is the DEM-adjusted drainage-cell elevation from `usgs_elev_table.csv` plus HAND stage. Row schema: [gauge-row.schema.json](schemas/gauge-row.schema.json).

| Column | Type | Notes |
|---|---|---|
| `gauge_ref`, `site`, `feature_id` | string, string, int64 | |
| `p`, `t`, `is_forecast` | timestamp, timestamp, bool | |
| `observed_q_cms` | float32, nullable | Null when no observation is known at `p` (latency, outage, or `t > p`) |
| `observed_wse_m` | float32, nullable | |
| `predicted_q_mid_cms`, `predicted_q_low_cms`, `predicted_q_high_cms` | float32 | |
| `predicted_wse_mid_m` | float32 | |
| `wse_datum` | string | Always `NAVD88` |

## 7. Velocity proxy

Reach velocity is `q_mid_cms / WetArea(stage)` using the hydrotable's wetted area at the interpolated stage. Per cell, `v_cell = v_reach * (depth_cell / HydraulicRadius(stage)) ^ (2/3)`, clamped to `[0, 3 * v_reach]`. This is a proxy and every consumer must label it as one. Direction is not in the raster; the search-area tool takes flow direction from the reach flowline geometry.

## 8. Forcing configuration

Schema: [forcing-config.schema.json](schemas/forcing-config.schema.json). The scenario file supplies `forcing_defaults`; a run may override any part; the manifest records the merged result.

| Key | Meaning |
|---|---|
| `sources[]` | Ordered list. Types: `usgs_continuous` (sites, parameters, latency), `nwm_analysis_assim` (latency), `nwm_short_range` (latency, max lead), `scripted` (path to a discharge series for what-if runs). |
| `state_estimation.bias_correction` | `none` or `nearest_gauge_ratio`: scale NWM analysis on ungauged reaches by observed over modelled discharge at the nearest gauge on the same levelpath, known at `p`. |
| `state_estimation.use_junction_inferences` | Apply the scenario's mass-balance junctions (downstream gauge minus known tributaries, lagged by travel time). |
| `boundary_forecast.method` | `persistence`, `trend_relax`, `nwm_short_range`, or `blend`. |
| `boundary_forecast.members` | Rate-of-rise multipliers for `low`, `mid`, `high` under `trend_relax` and `blend`. |
| `boundary_forecast.relax_minutes` | Time constant over which the continued trend decays to a plateau. |
| `routing.method`, `routing.dt_minutes` | `none` or `muskingum_cunge`; time step. |
| `roughness.manning_n_scale` | Multiplier applied to hydrotable discharge as a crude roughness sensitivity. |
| `scenario_overrides[]` | `gauge_outage` (gauge_ref, from, optional to) drops observations from `p` onward; `reach_scale` (reach_ref, factor, from, to) scales inflow on a reach for what-if runs. |

## 9. Engine API

Served by the FastAPI process. Paths are relative to the API root. All responses are JSON unless stated. Errors are `{ "error": { "code": string, "message": string } }`.

| Method and path | Purpose | Notes |
|---|---|---|
| `GET /scenarios` | List scenario IDs and names | |
| `GET /scenarios/{scenario_id}` | The scenario file | Validated against the scenario schema on load |
| `GET /runs` | List run manifests | Summary fields only |
| `POST /runs` | Create a run | Body `{ "scenario_id", "mode", "forcing_overrides"? }`. Returns 202 with the manifest; products compute on demand or in background. |
| `GET /runs/{run_id}` | The manifest | |
| `GET /runs/{run_id}/state?p=&t=` | Resolve a `(p, t)` query | Snaps, validates, computes or fetches, returns a [state response](schemas/state-response.schema.json) with product URLs and timing. `p=hindsight` allowed. |
| `GET /runs/{run_id}/reaches?p=&t=` | Reach table as JSON array | Same rows as the Parquet |
| `GET /runs/{run_id}/gauges?p=` | Gauge table as JSON array | |
| `GET /runs/{run_id}/raster?p=&t=` | The `depth.tif` | `application/octet-stream`, range requests supported |
| `GET /runs/{run_id}/tte?p=` | The `time_to_exceedance.tif` | |
| `GET /runs/{run_id}/overlay.png?p=&t=&band=depth_mid&max_px=2048&smooth=0` | Colour-ramped PNG in EPSG:3857 for map clients | Response headers `X-Bounds-3857: xmin,ymin,xmax,ymax` and `X-Bounds-4326: west,south,east,north` (degrees, for `Rectangle.fromDegrees` style placement). Transparent where dry or nodata. `p=hindsight` allowed. `max_px` clamped to 256..8192. `smooth=1` renders for draping on 3D terrain: bilinear at every scale, no dilation, anti-aliased wet edge; wet cells are the same either way. |
| `GET /runs/{run_id}/hindsight?t=` | State response for the truth run | Equivalent to `state?p=hindsight&t=` |
| `GET /runs/{run_id}/network.geojson` | Reach flowlines and gauge points as WGS84 GeoJSON | Static per run. Reach features: id = NWM `feature_id`, `kind: "reach"`, network columns as properties. Gauged reaches add a `kind: "gauge"` Point (id `gauge:<site>`) at the flowline midpoint. Used by the terrain view to join the reach and gauge tables to geometry. |

Error codes: `t_before_p`, `horizon_exceeded`, `outside_record`, `unknown_run`, `unknown_scenario`, `invalid_forcing`.

Cross-origin access: the API sends CORS headers for the origins in `FLOOD_CORS_ORIGINS` (comma-separated, default `*`, no credentials) and exposes `X-Bounds-3857`, `X-Bounds-4326`, `Content-Range` and `Accept-Ranges`, so a map front end served from another port can read the JSON routes, use `overlay.png` as a WebGL texture and range-read the COGs directly.

## 10. Rules every implementer follows

1. Rasters match the manifest grid exactly. A consumer may assert `transform`, `width`, `height` and refuse mismatches.
2. The reach table covers every reach in the AOI at every `(p, t)`. Missing flow is an error, not a missing row.
3. No product is written without its manifest already on disk.
4. Products are immutable once written. A changed forcing config is a new run with a new `config_hash`.
5. Every response and file states its `schema_version`.
6. The engine never reads the clock service. `p` and `t` arrive in the request.
7. Nothing scenario-specific in code (decision [0008](../decisions/0008-scenario-is-data-not-code.md)).
