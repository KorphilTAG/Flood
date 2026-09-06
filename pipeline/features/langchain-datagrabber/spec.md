# Feature spec

- Slug: langchain-datagrabber
- Feature: Fix the `ingest_osm_buildings.py` relation-geometry bug and the untested live-endpoint gap from the `map-data-ingestion` review, and refactor the ingestion fetch layer to route every external-API call through LangChain `Tool` wrappers
- Status: draft
- Product refs: PRD 6.1 (Ingestion table — TxDOT roads, USGS NHD, OSM buildings/crossings, Census TIGER boundary all "Agent-pullable"), PRD 8 Data Contract 1 (stable `feature_id`, never a raw coordinate), PRD Design Principle 3 (Section 7); FeatureBreakdown "RAG + Human/Landscape Data" track, step 2; architecture.md 5.1 (Exposure layers) and 5.4 (Impact extractor, downstream consumer of these tables); prior feature `pipeline/features/map-data-ingestion/spec.md` and its `review.md` verdict "PASS WITH GAPS" (gap 1: relation geometry silently dropped in `lib/geo.py:119-135`; gap 2: the four live-source scripts were never run against real endpoints)

## Problem

The `map-data-ingestion` feature (schema, shared lib, five ingestion scripts, tests, `docker-compose.yml`) was implemented and reviewed with verdict **PASS WITH GAPS**. Two gaps are carried into this feature as required fixes:

1. **Real bug.** `overpass_element_to_geometry` in `ingestion/lib/geo.py` (lines ~119–135) only branches on `element["type"] in ("node", "way")` and falls through to `return None` for `type == "relation"`. `overpass_elements_to_geodataframe` then silently drops any element whose geometry is `None`. `ingest_osm_buildings.py`'s Overpass query explicitly requests `relation["building"]`, so every multipolygon-relation building in Kerr County is fetched and then silently discarded before it ever reaches `buildings`. This undercounts building footprints with no error, no log line, and no test catching it.
2. **Untested gap.** `ingest_txdot_roads.py`, `ingest_nhd_flowlines.py`, `ingest_osm_buildings.py`, `ingest_osm_crossings.py`, and `fetch_kerr_county_boundary.py` have only ever been exercised against fixtures/mocks or, in one reviewer session, a fully separate `docker compose` + `ingest_camps.py` fixture run — never against their real live endpoints (TxDOT ArcGIS FeatureServer, USGS NHDPlus HR MapServer, the public Overpass API, Census TIGER). The hard-coded FeatureServer URLs and field names (`OBJECTID`, `NHDPlusID`, `REACHCODE`) are the prior developer's best-effort guess, unconfirmed live. The prior review flagged this as a required follow-up, not a one-time note to repeat and defer again.

On top of those two fixes, this feature introduces **LangChain as the ingestion fetch layer** ("the datagrabber"). Today, `ingest_txdot_roads.py` and `ingest_nhd_flowlines.py` call `lib.geo.query_arcgis_feature_server` directly; `ingest_osm_buildings.py` and `ingest_osm_crossings.py` call `lib.geo.overpass_query` directly; `fetch_kerr_county_boundary.py` does its own inline `requests.get` + zip-extract against Census TIGER. Every one of these is a bespoke, uncomposable HTTP call site. This feature wraps each external data source behind a LangChain `Tool` (via `langchain_core.tools`) so the retrieval side of ingestion has one consistent, swappable, testable interface, while leaving the persistence layer (`lib/db.py`, `lib/upsert.py`, `db/schema.sql`) completely untouched, since that half was reviewed and confirmed correct.

**Precondition the implementer must handle first.** As of this spec, the `ingestion/` directory and `pipeline/features/map-data-ingestion/{spec,changes,review}.md` described above exist only in this repo's `git stash@{0}` ("On master: wip: non-docs (pipeline agents, ingestion, docker)") — they are not present in the checked-out working tree on any branch (`master`, `RAGDataGrabber`, or `fix/live-rescue-positioning`) as of this writing. Before any edit in this spec can be made, the implementer must restore that tree, e.g. `git stash apply stash@{0}` (verify contents against this spec's citations before applying; do not blindly pop if the stash has since changed or been dropped) or, if the stash is no longer available, recreate `ingestion/` from the file contents quoted/described in this spec and in `pipeline/features/map-data-ingestion/changes.md`. This spec's "Files to change" table assumes that restoration has happened.

## In scope

1. Fix `overpass_element_to_geometry` (and, if needed, `overpass_elements_to_geodataframe`) in `ingestion/lib/geo.py` to correctly convert Overpass `relation` elements (multipolygon geometry) into a shapely geometry, built from the relation's member ways, instead of returning `None`.
2. Add a fixture-driven unit test using a synthetic Overpass relation (multipolygon) response that proves a relation element now produces valid Polygon/MultiPolygon geometry, and that `ingest_osm_buildings.py`'s pipeline (query → geometry → GeoDataFrame) no longer drops it.
3. Add an opt-in, manual live-endpoint smoke-test script that actually calls the four real external APIs (TxDOT ArcGIS FeatureServer, USGS NHDPlus HR MapServer, Overpass API for buildings, Overpass API for crossings) plus the Census TIGER boundary download, and asserts each returns a non-empty, well-formed result (valid GeoJSON/geometry, at least one feature, no HTTP error). This script is never invoked by the default `pytest` run.
4. Introduce a LangChain-based fetch layer (`ingestion/lib/langchain_tools.py`) with one `Tool`/`BaseTool` per external data source:
   - `ArcGISFeatureServerTool` — wraps the existing `query_arcgis_feature_server` ArcGIS REST call (used by TxDOT roads and USGS NHD).
   - `OverpassApiTool` — wraps the existing `overpass_query` Overpass QL call (used by OSM buildings and OSM crossings).
   - `CensusTigerCountyBoundaryTool` — wraps the Census TIGER county-boundary download + zip-extract + state/county filter currently inlined in `fetch_kerr_county_boundary.py`, promoted into `lib/geo.py` as a plain function first so the tool has something to wrap.
5. Refactor all five ingestion entry points (`ingest_txdot_roads.py`, `ingest_nhd_flowlines.py`, `ingest_osm_buildings.py`, `ingest_osm_crossings.py`, `fetch_kerr_county_boundary.py`) to invoke the LangChain tool for their data source instead of calling the underlying `requests`-based helper directly. The helpers in `lib/geo.py` are not deleted — the tools call them internally — so this is additive plumbing, not a rewrite of the HTTP logic itself.
6. Add `langchain-core` to `ingestion/requirements.txt` (see Approach for why not the full `langchain` or `langchain-community` packages).
7. Unit tests for every new LangChain tool that mock the underlying HTTP call (`requests.get`/`requests.post`, or the wrapped `lib.geo` function) and assert: correct arguments are passed through, the tool's return value matches what the wrapped function would have returned, and invalid/missing input is rejected by the tool's schema before any network call is attempted. No test in the default suite makes a real network call.
8. Update `ingestion/README.md` to document the LangChain tool layer (what each tool wraps, how scripts call it) and the new opt-in live smoke-test procedure.

## Out of scope

- Acquiring real camp footprint geometry (KCAD/TNRIS/ReportAll/Regrid/aerial tracing) — still genuinely manual per PRD 6.1, untouched by this feature. `ingest_camps.py` and the `camps` table are not modified.
- Reading Kerr County's HMP/EOP PDFs to cross-check named low-water crossings — still manual per PRD 6.1. `hmp_verified_name`/`hmp_cross_checked` remain untouched, still populated by no script.
- Any change to `ingestion/lib/db.py`, `ingestion/lib/upsert.py`, or `ingestion/db/schema.sql`. Persistence, the upsert/idempotency guarantee, and the `feature_id` convention were reviewed and confirmed correct in the prior pass and are not in scope for LangChain or for these two bug fixes.
- Turning the fetch layer into an LLM-driven or nondeterministic component. **LangChain here is used strictly for its `Tool`/`BaseTool` retrieval abstraction and pluggability — a uniform, schema-validated, swappable interface for "call this external API with these arguments and get this structured result back."** It is explicitly NOT used to have an LLM decide which data source to query, reformulate a query, summarize a response, or otherwise sit in the hot path of fetching a deterministic GeoJSON file. Each ingestion script already knows exactly which one source and one tool it needs (there is no ambiguity for an LLM to resolve), so no `AgentExecutor`, no chat model, and no LangChain LLM/embedding integration is added by this feature. Fetching a road centerline is not "an LLM claim" under PRD Design Principle 3 and must not be made to route through one.
- The PRD 6.6 LLM/RAG layer (OpenAI API, embeddings, RAGAS, the critic/enrichment agent) is a separate, later feature and is not started, extended, or touched here. This feature's LangChain usage does not imply or presuppose that later layer's design.
- Terrain/DEM/HAND ingestion, the impact extractor, and any UI work — unrelated tracks, untouched.
- Provisioning a hosted PostGIS instance or any production deployment concern — `docker-compose.yml` is unchanged.
- Conflation/deduplication of overlapping features across sources — unchanged from the prior feature's scope.
- Any new tactical, dispatch, or recommendation behavior. Not a live tactical recommender, no invented coordinates, no uncited LLM claims, physics does physics (PRD Design Principles 1 and 3) — restated here for consistency even though this feature is data-ingestion-only and touches none of the physics/LLM/tactics layers.

## Approach

**0. Restore the working tree.** Apply `git stash apply stash@{0}` (or recreate from this spec's citations) before touching anything else, per the Problem section's precondition. Confirm `ingestion/` and `pipeline/features/map-data-ingestion/*.md` exist and `cd ingestion && pytest` passes (18 tests, no network/DB) before starting the changes below, as a sanity baseline.

**1. Relation-geometry bug fix.** Overpass's `out geom;` output for a `relation` element includes a `members` array; each member has `type` ("way"), `ref`, `role` ("outer"/"inner"/other), and its own `geometry` list of `{lat, lon}` points (the same shape a top-level `way` element carries). Fix `overpass_element_to_geometry`:
   - When `element["type"] == "relation"`, iterate `element.get("members", [])`.
   - Build a closed ring (list of `(lon, lat)` tuples) from each member with `role == "outer"` and a `geometry` of length ≥ 4 with matching first/last points (close it if the Overpass response left it open); collect `role == "inner"` members the same way as holes.
   - If there is exactly one outer ring, return `shapely.geometry.Polygon(outer_coords, holes=[inner_coords, ...])` (inner rings only included if they fall within that outer ring; a simple "assign every inner ring to its containing outer ring" pass is sufficient for this scope — multi-outer relations with disjoint inners are rare for building footprints).
   - If there are multiple outer rings, return a `shapely.geometry.MultiPolygon` of one `Polygon` per outer ring (with any holes assigned to their containing outer ring).
   - If no `outer`-role member yields a usable ring (empty `members`, all rings degenerate), return `None` **and print a one-line warning to stderr** (e.g. `f"Skipping relation {element.get('id')}: no usable outer ring"`) so a future undercount is visible in script output instead of silent, closing the "silently dropping" complaint even in the residual None-returning path.
   - `overpass_elements_to_geodataframe` needs no change beyond this — it already skips `None` geometries, which is now the true "genuinely unusable" case rather than "every relation, always."

**2. Concrete test case (relation fixture).** Add `ingestion/tests/fixtures/overpass_relation_building.json`: a synthetic Overpass JSON response containing one `relation` element tagged `building=yes` with two `outer`-role way members forming a simple rectangle (no holes needed for the minimal case — a second fixture variant with one `inner` member is a reasonable stretch but not required) plus lat/lon `geometry` arrays on each member. Add tests (in `ingestion/tests/test_geo.py` or a new `ingestion/tests/test_geo_relation.py`):
   - `overpass_element_to_geometry` on the fixture's relation element returns a valid (`.is_valid`), non-empty `Polygon`.
   - `overpass_elements_to_geodataframe([relation_element])` returns a 1-row GeoDataFrame (not 0), proving the element is no longer dropped.
   - A relation with an empty `members` list still returns `None` (regression guard on the fallback path).

**3. Live smoke test (opt-in, manual).** Add `ingestion/scripts/live_smoke_test.py`, runnable via `python -m scripts.live_smoke_test`. It is a standalone script, not a pytest test file, so `pytest` never collects or runs it by default. Behavior:
   - Calls `CensusTigerCountyBoundaryTool` for Kerr County (FIPS 48/265) and asserts a valid boundary polygon comes back.
   - Calls `ArcGISFeatureServerTool` against the real TxDOT roads FeatureServer URL, filtered to that boundary, and asserts the response parses as GeoJSON with `len(features) > 0`.
   - Calls `ArcGISFeatureServerTool` against the real USGS NHDPlus HR flowlines URL (HUC8 `12100201` filter) the same way.
   - Calls `OverpassApiTool` with the real `building=*` query used by `ingest_osm_buildings.py` and asserts `len(elements) > 0`.
   - Calls `OverpassApiTool` with the real `ford=yes`/`bridge=low_water_crossing` query used by `ingest_osm_crossings.py` and asserts a well-formed response (`elements` key present; Kerr County may legitimately have zero tagged crossings, so this check is "valid JSON with an `elements` list," not "non-empty," and the script prints the count either way).
   - Prints a per-source PASS/FAIL line and exits non-zero if any of the four "must be non-empty" checks fails, or if any request errors/times out.
   - Does not write to PostGIS — this checks the fetch layer only, independent of whether a DB is reachable, so it can run in more environments than the full `ingest_*` scripts.
   - Document it in `ingestion/README.md` under a new "Live smoke test (manual, opt-in)" section: requires network access, is not run in CI or by default `pytest`, and should be run at least once before trusting the four live-source scripts against production data (this directly satisfies the prior review's "Required follow-up #1").

**4. LangChain tool layer.** New file `ingestion/lib/langchain_tools.py`:
   - Define a small Pydantic `args_schema` per tool (e.g. `ArcGISQueryInput(url: str, boundary_geojson: dict, where: str = "1=1", out_fields: str = "*")`, `OverpassQueryInput(query: str)`, `TigerBoundaryInput(state_fp: str, county_fp: str)`).
   - Implement each tool as a `langchain_core.tools.BaseTool` subclass (or `StructuredTool.from_function`, whichever keeps typing simplest for `args_schema` — the implementer's choice, but pick one convention and use it for all three) whose run method calls straight into the corresponding `lib.geo` function and returns its result unchanged (a dict for the ArcGIS/Overpass tools, a `geopandas.GeoDataFrame` for the boundary tool). Do not reshape or re-serialize the payload — the point is a uniform *call* interface, not a new data format.
   - Move the Census TIGER download/extract/filter logic currently inlined in `fetch_kerr_county_boundary.py`'s `fetch_boundary()` into a new `lib.geo.fetch_tiger_county_boundary(state_fp: str, county_fp: str, url: str = TIGER_COUNTY_URL) -> gpd.GeoDataFrame` function first (pure refactor, same behavior), so `CensusTigerCountyBoundaryTool` has a single function to wrap, matching the pattern already used for the ArcGIS/Overpass tools.
   - These tools are invoked directly and synchronously by ingestion scripts via `.invoke({...})` (or `.run(...)`) — never through a LangChain `AgentExecutor`, never bound to a chat model. There is no LLM anywhere in this file or in its call path.

**5. Script refactor.** Edit each script to call its LangChain tool instead of the raw `lib.geo` function:
   - `ingest_txdot_roads.py::fetch_roads` calls `ArcGISFeatureServerTool().invoke({...})` instead of `query_arcgis_feature_server(...)` directly, with the same arguments.
   - `ingest_nhd_flowlines.py::fetch_flowlines` — same pattern against the NHD FeatureServer.
   - `ingest_osm_buildings.py::main` calls `OverpassApiTool().invoke({"query": build_query(bbox)})` instead of `overpass_query(build_query(bbox))`.
   - `ingest_osm_crossings.py::main` — same pattern.
   - `fetch_kerr_county_boundary.py::fetch_boundary` calls `CensusTigerCountyBoundaryTool().invoke({"state_fp": TEXAS_STATEFP, "county_fp": KERR_COUNTYFP})` and writes the returned GeoDataFrame to `OUTPUT_PATH`, instead of doing the download/zip/filter inline.
   - No script's CLI, exit codes, printed messages, or DB-facing behavior change — this is a fetch-layer substitution, not a behavior change. Existing tests that stub `upsert_geodataframe`/`get_engine` (`test_ingest_camps.py`) are unaffected since `ingest_camps.py` has no external-API fetch to route through LangChain (it reads a local file).

**6. Dependency choice.** Add `langchain-core>=0.3` (not the full `langchain` metapackage, and not `langchain-community`) to `ingestion/requirements.txt`. `langchain-core` provides `BaseTool`/`StructuredTool` and Pydantic-based tool schemas without pulling in any LLM provider SDK, memory/agent orchestration, or community document-loader surface this feature does not use — keeping the dependency footprint aligned with "no LLM in the hot path."

**7. Tests.** New `ingestion/tests/test_langchain_tools.py`: for each of the three tools, mock the network call (`monkeypatch` on `requests.get`/`requests.post`, or on the wrapped `lib.geo` function — either is acceptable, but be consistent) and assert:
   - Valid input reaches the mocked call with the expected parameters and the tool returns the mocked response unchanged.
   - Missing/invalid required input (e.g. `OverpassQueryInput` with no `query`) raises a validation error before any mocked network function is called (assert the mock has zero calls).
   - No test in this file, or anywhere in the default suite, makes a real HTTP request or requires an API key — LangChain's tool abstraction here needs no LLM API key at all, since it never calls a language model.

## Files to change

| Path | Action (add/edit) | Why |
|---|---|---|
| `ingestion/lib/geo.py` | edit | Fix `overpass_element_to_geometry` to build relation (multipolygon) geometry from member ways instead of returning `None`; add `fetch_tiger_county_boundary()` extracted from `fetch_kerr_county_boundary.py` so it can be wrapped as a tool |
| `ingestion/lib/langchain_tools.py` | add | `ArcGISFeatureServerTool`, `OverpassApiTool`, `CensusTigerCountyBoundaryTool` — LangChain `BaseTool` wrappers around the existing `lib.geo` fetch functions, with Pydantic input schemas |
| `ingestion/scripts/ingest_txdot_roads.py` | edit | Call `ArcGISFeatureServerTool` instead of `query_arcgis_feature_server` directly |
| `ingestion/scripts/ingest_nhd_flowlines.py` | edit | Same, for the NHD FeatureServer |
| `ingestion/scripts/ingest_osm_buildings.py` | edit | Call `OverpassApiTool` instead of `overpass_query` directly |
| `ingestion/scripts/ingest_osm_crossings.py` | edit | Same, for the crossings query |
| `ingestion/scripts/fetch_kerr_county_boundary.py` | edit | Call `CensusTigerCountyBoundaryTool` instead of inlining the TIGER download/zip/filter logic |
| `ingestion/scripts/live_smoke_test.py` | add | Opt-in, manual script that calls all four real external APIs plus Census TIGER and asserts non-empty/well-formed results; never run by default `pytest` |
| `ingestion/requirements.txt` | edit | Add `langchain-core>=0.3` |
| `ingestion/tests/fixtures/overpass_relation_building.json` | add | Synthetic Overpass relation (multipolygon) response used to test the geometry-reconstruction fix |
| `ingestion/tests/test_geo.py` (or new `ingestion/tests/test_geo_relation.py`) | edit/add | Tests proving a relation element now yields valid Polygon geometry and is retained by `overpass_elements_to_geodataframe`, plus a regression test for the empty-`members` fallback |
| `ingestion/tests/test_langchain_tools.py` | add | Unit tests for all three LangChain tools, mocking the underlying HTTP/`lib.geo` call; asserts no real network access and no API key required |
| `ingestion/README.md` | edit | Document the LangChain tool layer (what each tool wraps) and the new "Live smoke test (manual, opt-in)" procedure/section |

No changes to `ingestion/lib/db.py`, `ingestion/lib/upsert.py`, `ingestion/db/schema.sql`, `ingestion/scripts/ingest_camps.py`, `ingestion/scripts/verify_exposure_layers.py`, `docker-compose.yml`, `ingestion/tests/test_upsert.py`, or `ingestion/tests/test_ingest_camps.py` — persistence and the camps loader are unaffected by this feature.

## Acceptance criteria

**Bug fix (relation geometry):**
- [ ] `overpass_element_to_geometry` returns a valid (`shapely` `.is_valid == True`), non-`None` `Polygon`/`MultiPolygon` for a `relation` element with at least one `outer`-role member way carrying ≥ 4 coordinate points.
- [ ] `overpass_elements_to_geodataframe` run on a list containing the fixture relation element (`ingestion/tests/fixtures/overpass_relation_building.json`) returns a GeoDataFrame with that row present (row count ≥ 1 for that element), not silently dropped.
- [ ] A relation element with an empty or missing `members` list still returns `None` from `overpass_element_to_geometry` (documented fallback, not a crash), and this path is covered by a test.
- [ ] This test suite change and the fix pass under `cd ingestion && pytest` with no network access.

**Live smoke test (opt-in):**
- [ ] `ingestion/scripts/live_smoke_test.py` exists, is runnable via `python -m scripts.live_smoke_test`, and is not collected or executed by a default `pytest` invocation (verify: `pytest --collect-only` does not list any test from this file, because it is not a pytest test module).
- [ ] Manually running `live_smoke_test.py` with network access performs at least one real call to each of: TxDOT ArcGIS FeatureServer, USGS NHDPlus HR MapServer, Overpass API (buildings query), Overpass API (crossings query), and Census TIGER, and reports per-source PASS/FAIL based on non-empty (where applicable) and well-formed results, exiting non-zero on any hard failure (HTTP error, malformed response, or an unexpectedly empty required source).
- [ ] `ingestion/README.md` documents this script under a clearly labeled manual/opt-in section, stating it requires network access and is not run in CI or by default `pytest`.

**LangChain refactor:**
- [ ] `ingestion/lib/langchain_tools.py` defines `ArcGISFeatureServerTool`, `OverpassApiTool`, and `CensusTigerCountyBoundaryTool`, each a LangChain `BaseTool` (or `StructuredTool`) with a Pydantic `args_schema`, each internally calling the corresponding function in `lib.geo` (no reimplementation of the HTTP logic).
- [ ] `ingest_txdot_roads.py`, `ingest_nhd_flowlines.py`, `ingest_osm_buildings.py`, `ingest_osm_crossings.py`, and `fetch_kerr_county_boundary.py` each invoke their LangChain tool rather than calling the raw `lib.geo` fetch function directly (verify by diff: the direct call site is replaced by a `.invoke(...)`/`.run(...)` call on the tool).
- [ ] `ingestion/lib/db.py`, `ingestion/lib/upsert.py`, and `ingestion/db/schema.sql` are byte-identical to their pre-feature state — the diff touches no persistence code.
- [ ] `ingestion/tests/test_langchain_tools.py` exists and, for each of the three tools, has at least one test that mocks the underlying HTTP call (or the wrapped `lib.geo` function) and asserts the tool's output and passed-through arguments, and at least one test that asserts invalid/missing required input is rejected before any network call is attempted.
- [ ] The full test suite (`cd ingestion && pytest`) passes with no network access and no API key set in the environment — grep confirms no test file in `ingestion/tests/` imports or configures an LLM provider (`ChatOpenAI`, `OpenAI`, etc.); the only LangChain import needed anywhere is `langchain_core.tools`.
- [ ] `ingestion/requirements.txt` adds `langchain-core` and does not add `langchain-openai`, `openai`, or any other LLM-provider SDK.
- [ ] `ingestion/README.md` documents, for each LangChain tool, what it wraps and which script(s) call it.

## Non-goals and constraints

- Physics does physics, the LLM does tactics (PRD Design Principle 1) — unaffected; this feature touches only the ingestion fetch layer.
- No invented coordinates (PRD Design Principle 3) — the relation-geometry fix builds polygons only from Overpass-supplied member-way coordinates, never a hand-typed or synthesized point.
- No uncited LLM claims — moot here since no LLM call exists anywhere in this feature's code path; LangChain's tools are invoked directly and deterministically by ingestion scripts, never through an agent that "decides" or "claims" anything.
- Not a live tactical recommender, not a point-coordinate predictor — restated for consistency; irrelevant in substance to this ingestion-only feature.
- No LLM API key (OpenAI or otherwise) is required to run any test or any of the five ingestion scripts after this change. If a future feature adds an actual LangChain LLM/agent (e.g. the PRD 6.6 critic), that is a separate feature with its own spec and its own key requirement — not introduced here.
- This feature does not change how `feature_id` is constructed, how upserts work, or the schema — those remain exactly as reviewed in `map-data-ingestion`.

## Assumptions

- The `ingestion/` tree and `pipeline/features/map-data-ingestion/*.md` files exist only in `git stash@{0}` as of this spec's writing and are not present in any branch's working tree; restoring that stash (or reconstructing from the content cited in this spec and in `changes.md`) is a precondition for implementation, not an optional nice-to-have. If the stash has been dropped or altered by the time this spec is implemented, the implementer should treat this spec's quoted file contents (in the Problem/Approach sections) as the source of truth for what "already exists" means, and flag the discrepancy rather than silently reinventing the prior feature from scratch.
- `langchain-core` (not the full `langchain` package) is sufficient for `BaseTool`/`StructuredTool` and Pydantic `args_schema` support at the version pinned; if the implementer finds `langchain-core` alone insufficient for a chosen tool-construction pattern, adding the full `langchain` package is acceptable but `langchain-community` and any LLM-provider package (`langchain-openai`, `openai`, etc.) should still not be needed and should not be added.
- The public Overpass API's `out geom;` response shape for relations (each member carrying its own `geometry` array of `{lat, lon}` points, plus a `role` of `outer`/`inner`) is stable enough to hand-build fixtures against, consistent with Overpass's documented output format.
- The TxDOT and USGS NHD FeatureServer URLs and field names already hard-coded in `ingest_txdot_roads.py`/`ingest_nhd_flowlines.py` are used as-is by the LangChain tool refactor; this feature does not re-verify or change those URLs beyond what the live smoke test surfaces. If the live smoke test reveals a stale/incorrect URL or field name, fixing that is a follow-up, not blocking for this spec's LangChain/bug-fix scope (though the implementer should note it if found).
- No live PostGIS instance is required to satisfy this spec's acceptance criteria — the live smoke test is fetch-only by design (see Approach, step 3), so its acceptance criteria can be verified with network access alone.

## Open questions

None. Where a fact was missing (whether `ingestion/` exists in the working tree, which LangChain package to depend on, whether the live smoke test needs a database), this spec resolves it with a documented assumption above rather than leaving it for the developer to guess.
