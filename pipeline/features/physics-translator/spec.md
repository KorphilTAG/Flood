# Feature spec

- Slug: physics-translator
- Feature: Contract 2 impact extractor that turns Contract 1 depth/velocity COGs and configured PostGIS exposure layers into deterministic, feature-ID-backed flood facts.
- Status: draft
- Product refs: PRD 5, 6.1, 6.5, 6.8, 8, and Milestone 3; FeatureBreakdown RAG + Human/Landscape Data steps 2–3; architecture 3, 5.4, and 6; contracts 0 and 1; decisions 0002 and 0008.

## Problem

The physics engine produces numerical rasters and reach tables, while downstream training, UI, and RAG components need checkable facts such as a particular crossing being impassable or a site's egress becoming blocked. The translation must preserve the engine query's knowledge cutoff `p` and target time `t`, use only configured exposure features, and never hand a raster or coordinates to an LLM.

The repository currently contains documentation and pipeline artifacts only; no `src/`, tests, active scenario copy, or package metadata exists yet. This is therefore the first translator milestone after the C01/C03/C06 engine foundation: establish Contract 2 and a deterministic core/CLI, not a new product UI or LLM service.

## In scope

- Define Contract 2 (`impact.json`): a versioned JSON document containing `run_id`, `p`, `t`, deterministic feature facts, projected impact times, egress status, and current reach metrics. It references features only as `<layer_id>:<source_id>` and includes no geometry or coordinates.
- Extend Contract 0's exposure registry with a `postgis` mapping (`schema`, `table`, `geometry_column`) and update the Kerr example and active scenario copy. The extractor requires that mapping; the existing `source` remains the raw-ingest source for the separate map-data-loading step. For the Kerr example, configure `flood_exposure.kerr_2025_07_04_<layer_id>` with geometry column `geometry`; code reads the mapping and never embeds that convention.
- Add a Python impact package and `flood impacts extract` CLI. It resolves a Contract 1 `(p, t)` query, opens the engine's COGs directly, reads configured features directly from PostGIS, and writes a validated `impact.json` under the run directory.
- Read `depth_mid`, `velocity_ms`, and `hazard_dv` by Contract 1 band description, honouring dry `0` and nodata `-9999`. Validate raster CRS/grid consistency before calculating facts.
- Use `geopandas`, `shapely`, and `rasterstats`: point sampling for point layers; zonal max/mean/wet coverage for line and polygon layers. Reproject returned features to the COG CRS if necessary, reject invalid/empty geometry and duplicate or missing source IDs.
- Classify point and line features as `impassable` and polygon features as `threatened` when a registry-configured depth threshold or optional `hazard_dv_limit` is met. No layer name, threshold, location, or operational recommendation may be hard-coded.
- Evaluate the current raster plus the same-`p` projections at `t+30`, `t+60`, and `t+120` minutes when those targets are within the Contract 1 horizon. Record the earliest impacted target; a missing required engine product is an error, never an implicit dry result.
- For configured polygon egress, join routes through the registry's `routes_layer` and `join_field`; report `open`, `blocked`, or `unknown` and the first blocked target. Copy the current Contract 1 reach metrics needed by the PRD (`reach_ref`, stage, rate of rise, velocity proxy, source) without coordinates.
- Add offline synthetic-raster/vector tests and an opt-in PostGIS integration test. Add `rasterstats` and a PostgreSQL driver to the Python dependencies.

## Out of scope

- Loading, sourcing, manually digitising, or inventing exposure data; it must already be loaded into the configured PostGIS relations with stable IDs (FeatureBreakdown RAG + Human/Landscape Data step 2).
- FastAPI routes, session-state writes, Cesium/React rendering, tile serving, and PostGIS provisioning. A later API/session feature consumes the written Contract 2 file.
- RAG, OpenAI calls, citation generation, autonomous dispatch or evacuation advice, search-area polygons, and learned residual/tactic models. This feature emits deterministic facts only.
- Live-mode optimization, TiTiler, and changes to the physics algorithm or Contract 1 products.

## Approach

Write the contract first, then implement an `ImpactExtractor` with two adapters: a Contract 1 raster/reach resolver and a PostGIS exposure store. The production CLI uses the engine's resolved, snapped `(p, t)` and materializes/locates its COG products before the extractor opens them with `rasterio`; tests inject a small resolver. The PostGIS adapter uses parameterized, identifier-quoted queries through `geopandas.read_postgis`, bounding reads to the raster extent. It accepts only the registry's ID, configured attributes, and geometry column.

The extractor constructs a stable `feature_ref` from the registry rather than a row index. For each COG it produces numeric zonal summaries, applies the registry rule, and retains only features that are impacted now or at one of the required future targets. It scans projections with the original `p`, so facts respect the information horizon (decision 0002). Egress is derived from those route facts, not an LLM. `impact.json` is validated against Contract 2 and written atomically at `runs/<run_id>/impacts/p=<P>/t=<T>/impact.json` (or the analogous hindsight path).

The Contract 2 payload must have this shape (field names may be expanded only in a backward-compatible schema change):

```json
{
  "schema_version": "1.0",
  "run_id": "...",
  "p": "...",
  "t": "...",
  "velocity_is_proxy": true,
  "facts": [{
    "feature_ref": "road:...",
    "kind": "impassable",
    "impacted_now": true,
    "depth_max_m": 0.0,
    "depth_mean_m": 0.0,
    "hazard_dv_max_m2_per_s": 0.0,
    "attributes": {},
    "first_impacted_t": "...",
    "projections": [{"t": "...", "impacted": true}]
  }],
  "egress": [{"site_ref": "site:...", "route_refs": ["road:..."], "status": "blocked", "first_blocked_t": "..."}],
  "reaches": [{"reach_ref": "reach:...", "stage_mid_m": 0.0, "rate_of_rise_m_per_h": 0.0, "velocity_ms": 0.0, "source": "routed"}]
}
```

`p` is `null` only for Contract 1 hindsight queries. Attributes are exactly the registry allow-list. The schema must forbid `geometry`, `coordinates`, `lon`, and `lat` fields anywhere in Contract 2 output.

## Files to change

The application paths below do not yet exist in this worktree; create them against the C01 package layout once its foundation is available. Do not create a parallel application structure.

| Path | Action (add/edit) | Why |
|---|---|---|
| `docs/contracts/README.md` | edit | Mark Contract 2 and its producer/consumers as defined. |
| `docs/contracts/contract-2-impact-products.md` | add | Human-readable Contract 2, storage layout, thresholds, projection semantics, and no-coordinate rule. |
| `docs/contracts/schemas/impact-json.schema.json`, `docs/contracts/examples/impact-response.sample.json` | add | Machine-validatable Contract 2 and canned example. |
| `docs/contracts/scenario.md`, `docs/contracts/schemas/scenario.schema.json`, `docs/contracts/examples/scenario.kerr-2025-07-04.json` | edit | Document and validate the per-layer PostGIS mapping. |
| `scenarios/kerr-2025-07-04.json` | edit when C01 has created it | Keep the active scenario mapping in sync with the contract example. |
| `pyproject.toml` | edit when C01 has created it | Add `rasterstats` and `psycopg[binary]`; register a `postgis` pytest marker. |
| `src/flood/contracts/models.py`, `src/flood/contracts/validate.py`, `src/flood/contracts/schemas/scenario.schema.json`, `src/flood/contracts/schemas/impact-json.schema.json` | edit/add | Expose and validate the updated Contract 0 and Contract 2 in the package. |
| `src/flood/impact/__init__.py`, `postgis.py`, `extractor.py` | add | PostGIS adapter, zonal extraction, classification, egress, reach copying, and atomic output. |
| `src/flood/cli_impacts.py`, `src/flood/cli.py` | add/edit | `flood impacts extract` and its one registry registration. |
| `tests/test_impact_contract.py`, `tests/test_impact_extractor.py`, `tests/test_impact_postgis.py` | add | Contract, offline extraction, and opt-in direct-PostGIS coverage. |

## Acceptance criteria

- [ ] Contract 2's schema and sample validate with the existing contract validation mechanism; `docs/contracts/README.md` identifies it as the impact-extractor output consumed by the LLM/UI. Its schema requires the payload fields described above, `feature_ref`/`reach_ref` formats from `common.schema.json`, `velocity_is_proxy: true`, and rejects geometry/coordinate fields and unknown keys.
- [ ] Contract 0 accepts a safe, explicit `postgis` object on an exposure layer (`schema`, `table`, `geometry_column`); the Kerr documentation example and active scenario copy declare it for every exposure layer. The extractor raises a clear configuration error if a referenced layer lacks the mapping or a threshold applicable to its geometry type.
- [ ] `PostGISExposureStore` reads the configured table through `geopandas.read_postgis` using a DSN supplied by `FLOOD_POSTGIS_DSN` or the CLI argument, parameterized raster bounds, and quoted identifiers. It returns only the ID, configured attributes, and geometry; it rejects missing/duplicate IDs, invalid/empty geometry, unsupported geometry type, or a CRS that cannot be aligned to the COG.
- [ ] Given a six-band Contract 1 fixture COG, extraction finds bands by description (not fixed band number), treats `-9999` as nodata and `0` as dry, and fails clearly for a missing required band, a grid/CRS mismatch, or a nonexistent future COG.
- [ ] Offline fixtures cover a point crossing, line road, structure polygon, and site with egress. They assert depth and hazard classifications use only the registry thresholds; the returned attributes are exactly the declared allow-list; every emitted fact has a stable feature reference; and serialized output contains no geometry or coordinate field.
- [ ] With fixture COGs at current, +30, +60, and +120 minutes, the output preserves one fixed `p`, records each projection target, and reports the correct earliest impact/egress-blocked time. Features dry at all targets are absent from `facts`.
- [ ] A fixture `reaches.parquet` sidecar produces Contract 2 reach rows with only `reach_ref`, `stage_mid_m`, `rate_of_rise_m_per_h`, `velocity_ms`, and `source`; velocity is labeled as a proxy in the parent document.
- [ ] `flood impacts extract --scenario <path> --run-dir <path> --p <iso|hindsight> --t <iso> [--postgis-dsn <dsn>]` uses the engine's snapped query, writes the canonical Contract 2 path atomically, prints that path, and validates the written JSON. It never emits a raw raster or coordinates.
- [ ] `pytest -q` passes without network access or a database. `pytest -m postgis` creates isolated test data in a caller-supplied `FLOOD_TEST_POSTGIS_DSN`, proves the adapter uses `read_postgis`, and cleans it up.

## Non-goals and constraints

- Preserve the architecture boundary: physics produces rasters; this deterministic extractor produces facts; any later LLM receives only Contract 2 and must cite its feature IDs (PRD 4 and 6.5; architecture principle 1).
- This is decision support only. Do not generate orders, recommended tactics, uncited narratives, or a point prediction for a person.
- Use the query pair supplied by Contract 1; never substitute wall-clock time or future information. Future facts must be computed with the same `p`.
- No scenario literals, generated IDs, or coordinates in output (decision 0008 and Contract conventions). Preserve configured source IDs and attributes only.
- Decision 0006 normally starts exposure data as files, but the invocation explicitly requires PostGIS. This feature uses PostGIS for reads without adding database provisioning, TiTiler, or unrelated state infrastructure.

## Assumptions

- C01 supplies the `src/flood` package, scenario loader, contract validator, and CLI registration marker; C03/C06 supply valid Contract 1 COGs, reach sidecars, and query resolution. The extractor may be developed against injected fixture adapters until those cycles merge.
- A prior exposure-ingest task has loaded each configured relation into PostGIS with stable source IDs, a spatial index, and a geometry column whose CRS is known; the extractor may reproject it to the Contract 1 grid CRS.
- Contract 1's default 360-minute horizon makes +30/+60/+120 available except at record boundaries. At a boundary, the implementation includes only targets inside the allowed record/horizon and records no fabricated outcome.

## Open questions

None.

## Implementer notes

- Make `postgis.schema`, `postgis.table`, and `postgis.geometry_column` lower-case SQL identifiers in the Contract 0 schema. Compose identifiers with the driver's identifier API; pass only bounds as SQL parameters. Do not treat `source` as SQL.
- Resolve bands by the COG's descriptions and calculate `wet_fraction` from `depth_mid >= 0.03`. For points use `rasterstats.point_query`; for lines and polygons use `rasterstats.zonal_stats` over depth and hazard bands. A geometry with no valid pixels is not evidence that it is dry.
- The production resolver may call `Run.state(..., write=True)` to obtain current/projection files, but `ImpactExtractor` itself must accept explicit COG and reach-sidecar paths so it remains a direct raster consumer and is independently testable.
- Preserve the engine's snapped UTC values in JSON and path names. For a target that is outside the record or max horizon, omit that target from `projections`; do not substitute a later or hindsight raster.
