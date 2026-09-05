# Feature spec

- Slug: run-orchestrator-products
- Feature: C06. The `Run` object: manifest and `config_hash`, `(p, t)` resolution, routed-series cache, member mapping, ensemble reduction, contract 1 products on disk (raster, reaches, gauges, time-to-exceedance, hindsight), stage timing, and the `flood run` CLI.
- Status: draft
- Product refs: `docs/specs/physics-engine-master.md` sections 6.8, 7; `docs/contracts/contract-1-physics-products.md` sections 1 to 6; decision 0003; C03 and C05 specs.

## Problem

C03 maps discharge to rasters and C05 produces discharge series. Nothing yet ties a scenario, a forcing configuration, and a `(p, t)` query into contract 1 products with provenance, caching, and timing.

## In scope

- `engine/run.py`: `Run`, `RunStore`, `ResolvedQuery`.
- `products/manifest.py`: manifest creation, `config_hash`, run_id.
- `products/tables.py`: reaches and gauges DataFrames, Parquet and JSON writers that validate against the contract schemas.
- `flood run create <scenario.json> [--mode replay] [--override <json>]`, `flood run state <run_id> --p <iso|hindsight> --t <iso> [--write]`, `flood run list`.
- Timing per stage in every state call; decision 0003 measurements recorded in `changes.md`.

## Out of scope

HTTP (C07), clock (C08), verifier (C09), skill (C10).

## Approach

`Run.state` resolves and snaps the query, fetches or computes the `RoutedSeries` for `p` from an LRU cache (size 8), maps each member at `t` with `map_member`, reduces, and returns arrays plus the state response dict. Writing products is explicit (`write=True`) and idempotent. Hindsight is `p = record_end`.

## Files to change

| Path | Action (add/edit) | Why |
|---|---|---|
| `src/flood/engine/run.py` | add | `Run`, `RunStore`, `ResolvedQuery` |
| `src/flood/products/manifest.py` | add | Manifest and hash |
| `src/flood/products/tables.py` | add | Reach and gauge tables |
| `src/flood/cli_run.py` | add | `register(sub)` for `run` |
| `src/flood/cli.py` | edit | One line under the REGISTER marker |
| `tests/test_manifest.py`, `tests/test_tables.py`, `tests/test_run.py` | add | Tests on the fixture |

## Acceptance criteria

- [ ] `config_hash(config: dict) -> str` returns `"sha256:" + sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()`; `make_run_id(scenario_id, mode, config_hash)` returns `f"{scenario_id}-{mode}-{hash[7:13]}"`.
- [ ] `build_manifest(scenario, mode, merged_config, grid, engine_version, created_at) -> dict` validates against `run-manifest`; `products` templates exactly as in contract 1 section 3; `limitations` starts with the scenario-independent engine limitations list defined in `manifest.py` (`ENGINE_LIMITATIONS`, at least the four in the contract example without scenario words) and appends one line per junction inference from the scenario, phrased from the inference's `label`.
- [ ] Forcing merge: `merge_forcing(defaults: dict, overrides: dict | None) -> dict` is a deep merge where override keys replace defaults at any depth and lists replace wholesale; the result validates against `forcing-config`.
- [ ] `Run.create(scenario, mode, overrides, runs_dir, data_dir, engine_version)` writes `runs/<run_id>/run.json`, creates `products/` and `hindsight/`, loads the cube from `data/cube/<scenario_id>/` and the forcing store, and returns the `Run`. Creating the same configuration twice reuses the directory and does not rewrite `run.json`. `Run.open(run_dir, data_dir)` loads an existing run. `RunStore(runs_dir, data_dir).list()` returns manifests sorted by `created_at`.
- [ ] `Run.resolve(p, t) -> ResolvedQuery(mode, p, t, horizon_minutes, requested)`: accepts ISO strings or datetimes; `p == "hindsight"` gives `mode = "hindsight"`, `p = None`, internal cutoff `record_end`; otherwise `snap_p`, `snap_t`, `check_pair`, `mode = "nowcast"` if `t == p` else `"forecast"`. `TimeGridError` propagates with its code.
- [ ] `Run.routed(p_internal) -> RoutedSeries` calls `route(...)` with a `ParquetForcingView` at `p_internal` and caches by `p_internal` in an LRU of 8.
- [ ] `Run.state(p, t, write=False) -> tuple[StateArrays, dict]`: maps the three members from `routed.at(t)` via `map_member` (velocity only for mid), reduces, fills `StateArrays.compute_ms` from a `StageTimer` with stages `state_estimation` (forcing view construction), `boundary_forecast` (0 unless separately timed), `routing`, `hand_mapping`, `reduce`, `write`, `total`. The dict validates against `state-response` with `cache` in `{hit, miss, precomputed}` (`precomputed` when the raster already exists on disk and `write` is requested, `hit` when the routed series came from cache, else `miss`) and `products` URLs built from `RunStore.url_base` (default `/runs/<run_id>`) exactly as in `docs/contracts/examples/state-response.json`.
- [ ] With `write=True`: `depth.tif` at `products/p=<P>/t=<T>/` (or `hindsight/t=<T>/`) via `write_depth_cog`; `reaches.parquet` beside it; `gauges.parquet` and `time_to_exceedance.tif` under `products/p=<P>/` (skipped in hindsight mode). Rewrites are skipped when the file exists.
- [ ] `build_reaches(run, routed, t, member_fields) -> DataFrame`: one row per `network` row with `in_aoi`, sorted by `feature_id`, exactly the contract columns and dtypes; `stage_*` via `stage_from_q` at `representative_cidx` (0 when `-1`); `rate_of_rise_m_per_h = (stage(t) - stage(t - 30 min)) * 2` using the routed mid series, 0 when `t - 30 min` precedes the series; `velocity_ms = q_mid / wet_area(stage_mid)` (0 when wet area is 0); `source` decoded from `routed.source`; `clipped_to_src` from `member_fields[mid].clipped`. Every row validates against `reach-row` after JSON conversion.
- [ ] `build_gauges(run, routed, p_internal) -> DataFrame`: one row per scenario gauge per 5-minute `t` from `record_start` to `p + max_horizon` (capped at `record_end`); observed columns from the view (null when unknown at `p`); predicted from routed members at the gauge's `feature_id`; `predicted_wse_mid_m = dem_adj_elevation_m + stage_mid`; `observed_wse_m = gauge_altitude_m + obs stage`; `wse_datum = "NAVD88"`. Validates against `gauge-row`.
- [ ] Fixture tests: create a run for `mini-huc` with `mode = replay`; `state("2025-01-01T04:00:00Z", "2025-01-01T06:00:00Z", write=True)` produces all files; the reach table has 6 rows; reach 101 `source == "forecast_trend"`; the gauge table for site 90000001 has null `observed_q_cms` for `t > 03:55Z`; a second identical call reports `cache == "hit"` and `write` stage under 5 ms; `state("hindsight", "2025-01-01T06:00:00Z")` writes under `hindsight/` and has no `forecast_trend` sources.
- [ ] `flood run create tests/fixtures/mini_huc/out/scenario.json --runs-dir <tmp> --data-dir <tmp>` prints the run_id; `flood run state <run_id> --p 2025-01-01T04:00:00Z --t 2025-01-01T06:00:00Z --write` prints the state response JSON.
- [ ] `changes.md` records measured `compute_ms` for the fixture and, if the Kerr cube and forcing exist locally, for Kerr at three `(p, t)` pairs, and states which decision 0003 branch they fall in.
- [ ] `pytest -q` green offline.

## Non-goals and constraints

- No HTTP. No scenario literals. Do not edit `interfaces.py`.
- `Run` holds one cube in memory; do not reload per call.

## Assumptions

- C03 and C05 are merged; their public functions have the signatures in their specs.
- The forcing store for the fixture lives at `tests/fixtures/mini_huc/out/forcing/`; `Run.create` accepts `data_dir` pointing there for tests (cube at `<data_dir>/cube/<scenario_id>` and forcing at `<data_dir>/forcing/...`). Document the exact layout the fixture builder produces and make `RunStore` accept both the fixture layout and the production layout through one `DataPaths` helper.

## Open questions

- None.

## Implementer notes

- `ResolvedQuery` is a frozen dataclass: `mode: str`, `p: datetime | None`, `t: datetime`, `p_internal: datetime`, `horizon_minutes: int`, `requested: dict`.
- `product_path(kind, p, t)` maps `kind in {"raster", "reaches", "time_to_exceedance", "gauges"}` to the manifest templates with compact timestamps; hindsight uses the `hindsight_*` templates.
- JSON conversion of tables: timestamps to contract ISO strings, `NaN` to `null`, numpy scalars to Python.
- Log one JSON timing line per `state` call using `StageTimer.log`.
