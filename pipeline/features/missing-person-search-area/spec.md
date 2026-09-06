# Feature spec

- Slug: missing-person-search-area
- Feature: Deterministic, probability-ranked missing-person search-area tool using Physics Engine velocity and downstream flowline topology, exposed as a LangChain tool
- Status: draft
- Product refs: PRD 2 (probability-weighted polygon, never a pin); PRD 4 and 6.6 (direct Physics Engine → search-area bypass and LLM reports tool output); PRD 6.2 and 6.8 (velocity is a labeled proxy); PRD 8 and 9 Milestone 4; FeatureBreakdown RAG + Human/Landscape Data step 8; architecture.md 5.3, 5.6, and 6; `docs/contracts/contract-1-physics-products.md` sections 4, 5, and 7; `docs/contracts/scenario.md`; existing `src/flood/engine/run.py`, `src/flood/interfaces.py`, `src/flood/ingest/network.py`, and `ingestion/lib/langchain_tools.py`.

## Problem

At the 4:03 a.m. replay decision point, responders need a defensible downstream search priority for a scripted last-known position (LKP). A point estimate would claim precision the fast-changing flood and HAND/Manning velocity proxy do not support. The PRD explicitly forbids a point-coordinate predictor and requires probability-weighted polygons.

The repository now has the needed engine contract: `Run.state(p, t)` returns in-memory `StateArrays` with `depth_mid`, `velocity_ms`, and `prob_inundated`; `Run.cube.network` carries `to_feature_id` topology and `flowline_wkb`; scenario data already holds scripted LKPs. Contract 1 says velocity magnitude is available in the raster but direction is not, so direction must come from flowline geometry plus downstream topology. Existing LangChain tools live in the separate ingestion scripts and wrap external fetches; this runtime Physics Engine tool belongs in the installable `flood` package.

This feature adds a bounded deterministic geometry estimator and a LangChain wrapper. It consumes the Physics Engine directly; neither an HTTP raster endpoint nor an LLM may calculate, infer, or alter its geometry.

## In scope

1. Add a `flood.search_area` package with a deterministic estimator that accepts an already-resolved `Run`, `p`, `t`, and a scenario `last_known_position_id`, returning a JSON-safe GeoJSON `FeatureCollection` with provenance and limitations.
2. Resolve the LKP only by its opaque scenario ID. Transform its WGS84 source coordinate to `run.cube.grid.crs` with GeoPandas, then do all distance, interpolation, and buffering in the projected engine CRS. The public tool input must not accept arbitrary `lon`/`lat` coordinates.
3. Call `run.state(p, t, write=False)` directly, using its in-memory `depth_mid` and `velocity_ms`. Do not call `/runs/.../raster`, read a COG/PNG, or compute a velocity field.
4. Deserialize `flowline_wkb` with Shapely and use `to_feature_id` to build a downstream-only route. Orient each reach toward the endpoint closest to its declared downstream reach. If orientation or a downstream continuation cannot be proven, stop rather than guess.
5. Advect the LKP along the route for elapsed time from its timestamp to canonical target `t`. At each segment, sample the current state at the grid cell, requiring finite wet depth (`>= MIN_DEPTH_M`) and finite positive `velocity_ms`; advance by velocity × elapsed seconds. Stop and mark truncation for dry/nodata/zero velocity, topology termination, or horizon expiry. Snap a start only to a wet directed flowline inside a documented configurable bound derived from grid resolution; otherwise return a typed unavailable result with no geometry.
6. Use Shapely buffers/unions to produce exactly three nested `Polygon`/`MultiPolygon` bands, `high`, `medium`, and `low`, around the traveled corridor (or valid stationary start). Buffers begin at least one grid cell wide and widen downstream according to a named deterministic configuration. Assign normalized relative weights summing to 1, explicitly labeled uncalibrated search-priority weights rather than detection, survival, or confidence probabilities. Reproject final geometry to EPSG:4326 for GeoJSON only.
7. Define a validated result shape containing `schema_version`, deterministic `search_area_id`, canonical/requested time provenance, LKP opaque ID and timestamp, the three features, relative weights, `source_refs` (scenario LKP plus each traversed `reach:<feature_id>`), proxy/disclaimer metadata, and a truncation/unavailability reason when relevant. Geometry must never be a Point and no “most likely coordinate” field may exist.
8. Add an injected-resolver `langchain_core.tools.BaseTool` (or one consistently equivalent structured tool) named `estimate_missing_person_search_area`. Its validated schema is `run_id`, `p`, `t`, and `last_known_position_id`; it resolves a run then returns the deterministic estimator result unchanged. Its description warns that it yields uncertain polygons based on a velocity proxy. Export a factory/constructor a later critic can register.
9. Add root-package `langchain-core` support. Keep this component independent of `ingestion/lib/langchain_tools.py`, which remains an external-data-fetch layer.
10. Add offline fixture-driven tests for topology/advection, polygon-only output, weights, safe failures, and LangChain invocation. They must need no Kerr data, network, PostGIS, or LLM API key.

## Out of scope

- A calibrated drift, survival, detection, or search-effectiveness model; the three weights are a transparent relative prior, not empirical confidence intervals.
- New hydrology, velocity math, raster bands, network ingestion, or edits to frozen Contract 1 schemas. This feature consumes the current state arrays and flowline WKB.
- PostGIS, impact extraction, exposure ingestion, or real call-data/camp acquisition. MVP uses existing scripted LKP scenario data and never geocodes or invents an incident coordinate.
- A FastAPI route, session persistence, Cesium/deck.gl rendering, UI control, LLM critic/chat/validator/RAG/AgentExecutor, or an LLM model binding. GeoJSON is the handoff to those later layers.
- Arbitrary coordinate prompts, map pins, autonomous dispatch, resource assignments, or instructions to deploy teams. A human commander owns every operational decision.

## Approach

Create `src/flood/search_area/`, not an ingestion module: production engine callers import `flood`, whereas `ingestion/` contains script-oriented wrappers for HTTP source fetches.

**Inputs and time.** The estimator request and LangChain args schema contain only `run_id`, `p`, `t`, and `last_known_position_id`. Resolve `run = run_store.get(run_id)`, find exactly one LKP in `run.scenario.last_known_positions`, then call `run.state(p, t, write=False)` once. Use the state response/arrays’ snapped target time as canonical, preserve requested values as provenance, reject target-before-LKP and elapsed durations beyond `manifest.time.max_horizon_minutes`, and use the existing `p`/`t` availability contract rather than introducing a second clock.

**Transport.** GeoPandas transforms the source LKP from EPSG:4326 into the engine grid CRS. Load WKB flowlines into a GeoDataFrame in that CRS. The only start snap is to the nearest wet, direction-resolved line within a default maximum of `2 * grid.resolution_m`, stored in named estimator configuration and result metadata. Orient lines by endpoint distance to the `to_feature_id` geometry, trace only explicit topology, and sample grid cells at the moving location. For each finite wet positive-velocity sample, travel `velocity_ms * remaining_seconds`, splitting at reach boundaries. Record traversed reach refs; on insufficient data/topology, retain a bounded partial corridor with `truncated: true` and an explicit reason. If start validation fails, return `unavailable` with no geometry.

**Bands and output.** Build a swept `LineString` (or valid start buffer), then Shapely-buffer it into three nested zones using a base width of at least one grid cell plus a distance-widening term. Keep base width, widening factor, band multipliers, and weights together in default configuration. Normalize the three relative weights to 1 and include the literal limitation: `relative search-priority weights are not calibrated probabilities`. Serialize final vector geometry as EPSG:4326 GeoJSON, retaining no raw grid/raster in the result. Feature properties include `band`, `relative_weight`, `search_area_id`, common source refs, time, and proxy warning.

**LangChain boundary.** The tool’s `_run` does only schema validation, injected run lookup, and estimator delegation. It has no HTTP client, chat-model import, AgentExecutor, or text-generation path. A later critic must forward the tool’s `source_refs` and limitations; it must not turn tool geometry into a coordinate claim.

**Tests.** Use a purpose-built deterministic mini run/cube/scenario with a valid projected WKB chain, wet velocity cells, and scenario LKP. Assert downstream-only motion, polygonal/nested output, normalized weights, direct `state(..., write=False)` use, and that dry/distant starts or ambiguous/terminal topology produce unavailable/truncated output with no fabricated continuation. Test `SearchAreaTool().invoke(...)` and schema rejection of missing/coordinate inputs under the normal offline test suite.

## Files to change

| Path | Action (add/edit) | Why |
|---|---|---|
| `pyproject.toml` | edit | Add the minimal root `langchain-core` runtime dependency; `geopandas` and `shapely` already exist. |
| `src/flood/search_area/__init__.py` | add | Export estimator request/result types and LangChain tool/factory. |
| `src/flood/search_area/estimator.py` | add | Direct state-array sampling, projected geometry, downstream advection, bands, result validation, and safe domain errors. |
| `src/flood/search_area/tool.py` | add | Schema-validated `estimate_missing_person_search_area` LangChain wrapper with injected run resolver and no model/HTTP path. |
| `tests/test_search_area.py` | add | Offline tests for direct-engine transport, geometry, provenance, safety boundaries, and tool invocation. |

## Acceptance criteria

- [ ] `pyproject.toml` declares `langchain-core` for the root `flood` package; this feature neither moves nor modifies `ingestion/lib/langchain_tools.py`.
- [ ] Estimator/tool inputs are limited to run context/ID, `p`, `t`, and a scenario LKP ID. `lon`, `lat`, GeoJSON-point input, and unknown LKP IDs are rejected before geometry production.
- [ ] The estimator uses `run.state(p, t, write=False)` arrays and `run.cube.network.flowline_wkb`; it neither calls an HTTP endpoint nor reads rendered products, invokes an LLM, or calculates velocity itself.
- [ ] Calculation is in the engine grid CRS using GeoPandas/Shapely. Final GeoJSON has exactly three named `Polygon`/`MultiPolygon` features (`high`, `medium`, `low`), no Point feature, and no single-coordinate/predicted-location property.
- [ ] Transport follows only declared `to_feature_id` links and orientation proven against the next reach. The synthetic fixture moves only downstream and does not cross to an unconnected/upstream reach.
- [ ] Every movement sample requires finite positive `velocity_ms` and `depth_mid >= MIN_DEPTH_M`. A dry/distant start returns explicit unavailable/no geometry; missing, ambiguous, or terminal continuation stops safely with `truncated: true` and a machine-readable reason.
- [ ] The output has schema/time/LKP provenance, deterministic search-area ID, traversed `reach:<feature_id>` refs, velocity-proxy disclosure, deterministic widening configuration, and the literal uncalibrated-weight limitation. Weights are non-negative and normalize to 1 within floating-point tolerance.
- [ ] `SearchAreaTool` is a LangChain `BaseTool`/equivalent named `estimate_missing_person_search_area`, validates its schema, resolves a run through injected infrastructure, returns the validated estimator result unchanged, and imports no chat model or AgentExecutor.
- [ ] `tests/test_search_area.py` covers downstream transport, polygon-only nested bands, weight normalization, direct in-memory state access, LKP validation, dry/distant start, topology termination, argument rejection, and a successful `.invoke(...)`; `pytest -q` passes offline.

## Non-goals and constraints

- Physics does physics; the LLM does not do geometry (PRD Design Principles 1 and 3). LangChain is a typed callable interface only.
- This is human decision support, never autonomous dispatch. It prioritizes search areas but does not order teams or assert a person’s location.
- Never emit a pin, centroid, “most likely coordinate,” raw coordinate prose, calibrated likelihood, survival chance, or confidence interval. The only coordinate-bearing material is tool-computed polygon geometry for rendering.
- Label velocity as the Physics Engine Manning/HAND proxy. Direction comes only from flowline topology/geometry, never from scalar raster values or LLM inference.
- Do not hard-code Kerr values; existing LKP data remains scenario data. Require no new network service, PostGIS, OpenAI key, or RAG dependency.

## Assumptions

- Current `Run` exposes `scenario`, `cube.grid`, `cube.network`, and `state(p, t, write=False)`; `flowline_wkb` is in the grid CRS, as established by `src/flood/ingest/network.py`.
- The existing scenario LKP longitude/latitude is source data and may be transformed internally; the LangChain caller supplies only its opaque ID.
- Existing `manifest.time.max_horizon_minutes` is the correct MVP safety cap for transport duration. Any calibrated SAR model needs a separate reviewed feature.
- If downstream direction cannot be proved, truncation/unavailability is safer than trusting arbitrary coordinate order in a terminal line.
- No critic registry exists in the repo; an exported injected LangChain tool is the complete non-invasive integration point for this pass.

## Open questions

None. The PRD supplies the required safety posture and Contract 1 supplies the velocity/direction handoff. This spec resolves drift uncertainty as clearly labeled relative search-priority bands, not calibrated probability claims.
