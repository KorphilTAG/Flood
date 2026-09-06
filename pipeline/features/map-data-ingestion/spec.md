# Feature spec

- Slug: map-data-ingestion
- Feature: Load exposure-layer map data (roads, river network, building footprints, low-water crossings, camp footprint schema) into PostGIS with stable feature IDs
- Status: draft
- Product refs: PRD 5 (Technology Stack — PostGIS row), PRD 6.1 (Ingestion table + sequencing implication), PRD 8 (Data Contracts item 1 — stable `feature_id`), PRD Design Principle 3 (Section 7); FeatureBreakdown "RAG + Human/Landscape Data" track, step 2; architecture.md 5.1 (Exposure layers) and 5.4 (Impact extractor, downstream consumer)

## Problem

Milestone 1 (PRD Section 9) requires "Static terrain tileset + PostGIS exposure layers loaded" before anything else in the pipeline can render or reason about the map. Right now the repo is docs-only — there is no database schema, no ingestion code, and no exposure data. Every downstream component (impact extractor, LLM layer, 3D map) depends on exposure features existing in PostGIS with a stable `feature_id`, because per Design Principle 3 the LLM layer is only ever allowed to reference geometry by ID, never by raw coordinate. This feature builds that foundation: the PostGIS schema for roads, the river network, buildings, low-water crossings, and camp footprints, plus the ingestion scripts for every source that is actually agent-pullable (TxDOT roads, USGS NHD flowlines, OSM buildings, OSM-tagged crossings).

Two of the six ingestion rows in PRD 6.1 are explicitly manual and cannot be completed by a coding agent in this pass: cross-checking OSM crossing names against Kerr County's Hazard Mitigation Plan (HMP) text (requires a human reading a PDF), and acquiring camp footprints at all (requires a KCAD interactive parcel search, a TNRIS special request, a paid Regrid/ReportAll purchase decision, or hands-on aerial-imagery tracing). No script can perform any of those four camp-data paths, and no script can "read and interpret" the HMP the way PRD 6.1 requires. This spec scopes the developer pass to exactly what is automatable, and turns the manual items into schema hooks and a documented follow-up so the manual work has a clear place to land later without blocking Milestone 1.

## In scope

1. A PostGIS schema (migration/DDL) with tables for `roads`, `river_network`, `buildings`, `crossings`, and `camps`, every row carrying a stable, human-legible `feature_id` (never a raw coordinate) per PRD Design Principle 3 / Data Contract 1.
2. A script that fetches the Kerr County boundary polygon (US Census TIGER/Line county boundary, FIPS 48265 — public, agent-pullable) and uses it as the clip mask for every other ingestion script, so no script hand-types a bounding box.
3. An ingestion script that pulls TxDOT road centerlines (TxDOT open data / ArcGIS Open Data portal) clipped to the Kerr County boundary and loads them into `roads`.
4. An ingestion script that pulls USGS NHD flowlines for HUC8 `12100201` (matching `docs/README.md`'s HAND HUC8) and loads them into `river_network`.
5. An ingestion script that pulls OSM building footprints inside the Kerr County boundary via the Overpass API and loads them into `buildings`.
6. An ingestion script that pulls OSM-tagged low-water crossings (`ford=yes`, `bridge=low_water_crossing`) via the Overpass API and loads them into `crossings`, leaving the HMP cross-check columns null (see below).
7. A `camps` table schema and a generic, source-agnostic loader script (`ingest_camps.py`) that can ingest a local vector file (GeoJSON/Shapefile) into `camps` once one becomes available — the script itself ships and is tested against a small synthetic fixture, but this feature does not ship, purchase, or acquire real camp data.
8. Shared library code: DB connection handling, a `feature_id` convention, CRS reprojection to EPSG:4326, and an idempotent upsert helper so re-running a script never duplicates rows or reassigns an existing feature's ID.
9. A verification script that checks every populated table for valid geometry, non-null `feature_id`, and row counts, so a developer can confirm Milestone 1's PostGIS half is actually satisfied.
10. `README.md` documentation, inside this feature's ingestion directory, of exactly what remains manual and who/what needs to do it next (KCAD search, TNRIS request, ReportAll/Regrid purchase decision, aerial tracing, and HMP/EOP PDF reading for the crossing cross-check) — a follow-up checklist, not a task this developer pass performs.

## Out of scope

These are genuinely manual, non-automatable data-acquisition tasks per PRD 6.1. No script can complete them, and the developer agent implementing this spec must not attempt to fake, guess, or hallucinate a substitute for any of them:

- Acquiring real camp footprint geometry by any of the four PRD-listed manual paths: KCAD parcel search (interactive, per-camp owner/address lookup), a TNRIS StratMap special request (human-submitted request to a state agency), a paid aggregator license (ReportAll USA or Regrid/Acres.com — requires a purchase decision), or manual tracing from NAIP/Google Earth historical imagery (hands-on digitizing). The `camps` table ships empty from this feature.
- Reading Kerr County's 2024 Hazard Mitigation Plan and Emergency Operations Plan PDFs to extract named low-water crossings and cross-checking those names against the OSM-tagged crossings pulled in this feature. The `crossings.hmp_verified_name` and `crossings.hmp_cross_checked` columns exist but are populated later, manually.
- Any purchase, subscription, or formal data-request decision (Regrid/ReportAll license, TNRIS special request submission) — those are business/legal decisions for the user, not something a coding agent can execute.
- Terrain/DEM ingestion, HAND rasters, and cesium-terrain-builder tiling — that is the Physics Engine track (PRD 6.1 rows 2–3, FeatureBreakdown Physics track step 3), a separate feature.
- The impact extractor, the LLM/RAG layer, and any UI rendering of these layers — those are separate downstream features (architecture.md 5.4–5.9) that consume this feature's tables but are not built here.
- A live/streaming exposure-layer feed. Exposure geometry (roads, buildings, crossings, camps) is treated as static for MVP; only the hydrology feed is live/replay per PRD 6.1.
- Conflation/deduplication of overlapping features across sources (e.g., an OSM way that duplicates a TxDOT centerline) beyond the per-source, per-table load described above.
- Provisioning a hosted PostGIS instance (RDS, Supabase, etc.) for production/demo use. This spec assumes a local or already-reachable PostGIS instance addressed by environment variables; a `docker-compose.yml` service is added for local development only.

## Approach

**Directory layout.** Since the repo is docs-only, this feature creates a new top-level `ingestion/` directory, independent of the (not-yet-built) FastAPI app, containing schema, scripts, shared library code, and tests. This keeps the ingestion pipeline runnable on its own before any service layer exists, matching PRD Design Principle 5 (contracts before code) — the PostGIS schema *is* the contract the impact extractor and UI will later read.

**Schema and feature IDs.** Every table has a `feature_id TEXT PRIMARY KEY` built as `"<layer>:<source>:<source_id>"` (e.g. `road:txdot:1023481`, `crossing:osm:way/38291029`, `river:nhd:12345600001234`). This is deterministic from the source data — never a hand-typed or invented coordinate or sequence number — so reruns are idempotent and the LLM layer can later cite it as an opaque, stable handle per Design Principle 3. Every table also carries `source TEXT`, `source_id TEXT`, `geom` (typed geometry column, SRID 4326), `attributes JSONB` (the original source's non-geometry fields, kept for traceability), and `created_at TIMESTAMPTZ DEFAULT now()`. `crossings` additionally carries `osm_tag TEXT` (which of `ford=yes` / `bridge=low_water_crossing` matched), `hmp_verified_name TEXT` (nullable), and `hmp_cross_checked BOOLEAN DEFAULT false` — placeholders for the manual follow-up, not populated by this feature.

**Boundary-driven clipping, not invented bounding boxes.** `scripts/fetch_kerr_county_boundary.py` downloads the Kerr County (FIPS 48265) polygon from US Census TIGER/Line and caches it locally (e.g. `ingestion/data/kerr_county_boundary.geojson`). Every other ingestion script imports this boundary and clips/filters its source pull against it, rather than hard-coding a lat/lon box.

**Idempotent load.** All scripts share a `lib/db.py` connection helper and a `lib/upsert.py` helper that does `INSERT ... ON CONFLICT (feature_id) DO UPDATE SET geom = EXCLUDED.geom, attributes = EXCLUDED.attributes` (or an equivalent GeoPandas `to_postgis` + merge pattern). Re-running any script against unchanged source data must not create duplicate rows or change any existing `feature_id`.

**Per-source scripts:**
- `ingest_txdot_roads.py` — pulls road centerlines from the TxDOT open data / ArcGIS Open Data portal (GeoJSON via the ArcGIS REST API), clipped to the Kerr County boundary, loaded into `roads`.
- `ingest_nhd_flowlines.py` — pulls NHD flowlines for HUC8 `12100201` from USGS's National Map / NHDPlus HR service, loaded into `river_network`.
- `ingest_osm_buildings.py` — Overpass API query for `building=*` ways/relations within the Kerr County boundary, loaded into `buildings`.
- `ingest_osm_crossings.py` — Overpass API query for nodes/ways tagged `ford=yes` or `bridge=low_water_crossing` within the Kerr County boundary, loaded into `crossings` with `hmp_verified_name = NULL`.
- `ingest_camps.py` — generic vector-file loader (accepts `--input <path to GeoJSON/Shapefile>`), assigns `feature_id` as `camp:<source>:<source_id-or-row-index>`, loads into `camps`. Ships tested against a small synthetic fixture file checked into the repo; not run against real camp data by this feature.

**Verification.** `verify_exposure_layers.py` connects to the DB and asserts, per table: the table exists, `ST_IsValid(geom)` is true for every row, `feature_id` is non-null and unique, and (for the four automated tables) row count > 0 after a live run.

**Testing without requiring live network/DB in CI.** Unit tests exercise the pure-Python pieces — `feature_id` construction, CRS reprojection, and upsert SQL/merge generation — against small fixture GeoDataFrames, so they run without network access or a live PostGIS instance. A documented manual integration step (in the ingestion `README.md`) covers running the real scripts end-to-end against a live DB, since that requires network access to TxDOT/USGS/Overpass and a reachable Postgres.

## Files to change

| Path | Action (add/edit) | Why |
|---|---|---|
| `ingestion/requirements.txt` | add | Pin `geopandas`, `shapely`, `requests`, `psycopg2-binary`, `sqlalchemy`, `geoalchemy2`, `python-dotenv`, `pytest` |
| `ingestion/.env.example` | add | Document `PGHOST`/`PGPORT`/`PGDATABASE`/`PGUSER`/`PGPASSWORD` (or a single `DATABASE_URL`) needed by every script |
| `ingestion/db/schema.sql` | add | DDL for `roads`, `river_network`, `buildings`, `crossings`, `camps`, including `CREATE EXTENSION IF NOT EXISTS postgis;` |
| `ingestion/lib/db.py` | add | Shared DB connection/session helper read from env vars |
| `ingestion/lib/geo.py` | add | `feature_id` construction, EPSG:4326 reprojection, Kerr County boundary loading helper |
| `ingestion/lib/upsert.py` | add | Idempotent `INSERT ... ON CONFLICT` / upsert helper shared by all ingestion scripts |
| `ingestion/scripts/fetch_kerr_county_boundary.py` | add | Downloads and caches the Census TIGER Kerr County (FIPS 48265) boundary used as the clip mask everywhere else |
| `ingestion/scripts/ingest_txdot_roads.py` | add | Loads TxDOT road centerlines into `roads` |
| `ingestion/scripts/ingest_nhd_flowlines.py` | add | Loads USGS NHD flowlines (HUC8 12100201) into `river_network` |
| `ingestion/scripts/ingest_osm_buildings.py` | add | Loads OSM building footprints into `buildings` via Overpass API |
| `ingestion/scripts/ingest_osm_crossings.py` | add | Loads OSM `ford=yes`/`bridge=low_water_crossing` features into `crossings` via Overpass API |
| `ingestion/scripts/ingest_camps.py` | add | Generic local-file loader into `camps`; not invoked with real data by this feature |
| `ingestion/scripts/verify_exposure_layers.py` | add | Post-ingestion smoke check: table existence, geometry validity, `feature_id` non-null/unique, row counts |
| `ingestion/tests/fixtures/sample_camps.geojson` | add | Small synthetic fixture (2–3 polygons) used to test `ingest_camps.py` without real camp data |
| `ingestion/tests/test_geo.py` | add | Unit tests for `feature_id` construction and CRS reprojection |
| `ingestion/tests/test_upsert.py` | add | Unit tests for idempotent upsert behavior (rerun does not duplicate or reassign IDs) |
| `ingestion/tests/test_ingest_camps.py` | add | Runs `ingest_camps.py` against the synthetic fixture and asserts rows land correctly |
| `ingestion/README.md` | add | How to run each script, required env vars, and the manual-follow-up checklist (camp acquisition paths, HMP cross-check) with references back to PRD 6.1 |
| `docker-compose.yml` | add | Local `postgis/postgis` service for development, so ingestion scripts have a DB target without a hosted instance |

No existing files are edited; the repo has no code yet for this area (docs-only per `docs/README.md`'s "Status" note).

## Acceptance criteria

**Developer-agent scope — automatable, must be satisfied by this implementation pass:**

- [ ] `ingestion/db/schema.sql` creates `roads`, `river_network`, `buildings`, `crossings`, `camps`, each with `feature_id TEXT PRIMARY KEY`, a typed `geom` column with `SRID 4326`, `source`, `source_id`, `attributes JSONB`, `created_at`; `crossings` additionally has `osm_tag`, `hmp_verified_name` (nullable), `hmp_cross_checked BOOLEAN DEFAULT false`.
- [ ] Running `ingest_txdot_roads.py`, `ingest_nhd_flowlines.py`, `ingest_osm_buildings.py`, and `ingest_osm_crossings.py` against live sources with a reachable PostGIS instance populates `roads`, `river_network`, `buildings`, and `crossings` respectively with row count > 0, every row's geometry clipped to (or filtered by) the Kerr County boundary from `fetch_kerr_county_boundary.py`.
- [ ] Every row inserted by any of the four scripts above has a non-null, unique `feature_id` following the `<layer>:<source>:<source_id>` convention, and `ST_IsValid(geom)` is true.
- [ ] `ingest_osm_crossings.py` leaves `hmp_verified_name` null and `hmp_cross_checked` false on every row it inserts — it must not fabricate a cross-check result.
- [ ] Running any of the four ingestion scripts twice in a row against unchanged source data does not create duplicate rows and does not change any previously assigned `feature_id` (idempotent upsert, verified by a test in `test_upsert.py`).
- [ ] `ingest_camps.py` successfully loads `ingestion/tests/fixtures/sample_camps.geojson` into `camps` with correctly assigned `feature_id`s, verified by `test_ingest_camps.py`. This is the only data `camps` contains after this feature is implemented — no real camp geometry ships.
- [ ] `verify_exposure_layers.py` runs against a populated DB and reports, per table, existence / geometry validity / `feature_id` non-null+unique / row count, exiting non-zero if any check fails.
- [ ] `test_geo.py` and `test_upsert.py` pass without network access or a live database (fixture-driven unit tests only).
- [ ] `ingestion/README.md` documents required env vars, how to run each script, how to run tests, and lists the manual follow-up items below verbatim as a checklist referencing PRD 6.1.
- [ ] `docker-compose.yml` brings up a local `postgis/postgis` container that `ingestion/db/schema.sql` can be applied to.

**Manual follow-up — explicitly out of scope for this developer pass, tracked here so it is not silently dropped:**

- [ ] (Manual, not this pass) A person acquires real camp footprint geometry via KCAD parcel search, a TNRIS StratMap special request, a ReportAll/Regrid purchase, or aerial-imagery tracing, then runs `ingest_camps.py --input <acquired-file>` to load it.
- [ ] (Manual, not this pass) A person reads the Kerr County 2024 HMP and EOP PDFs, identifies named low-water crossings, matches them against rows in `crossings`, and updates `hmp_verified_name`/`hmp_cross_checked` (e.g. via a follow-up SQL script or a small manual-entry CSV + loader written in a later feature).

## Non-goals and constraints

- Physics does physics, the LLM does tactics (PRD Design Principle 1) — this feature only stores exposure geometry; it performs no flood computation and no tactical reasoning.
- No invented coordinates (PRD Design Principle 3 / Non-Goals): every `feature_id` is derived from source data, never hand-typed; the Kerr County boundary itself comes from Census TIGER, not a manually guessed bounding box.
- Not a live tactical recommender, not a point-coordinate predictor — irrelevant scope-wise to this feature but stated for consistency with the PRD's non-goals; nothing here produces tactical output or point predictions.
- This feature does not stand up the FastAPI service, the impact extractor, or any HTTP API over these tables — those are separate features per architecture.md 5.4 and beyond. Scripts connect to PostGIS directly.
- This feature does not attempt to substitute automated text-scraping of the HMP/EOP PDFs for the "manual" cross-check PRD 6.1 requires; PRD 6.1 is explicit that this step requires a person to read and interpret the document, not just fetch it.
- No purchase or formal data-request decision (Regrid/ReportAll, TNRIS) is made or initiated by code in this feature.

## Assumptions

- A PostGIS-enabled Postgres instance is reachable via environment variables at ingestion time; for local development, `docker-compose.yml`'s `postgis/postgis` service is sufficient. No hosted DB is provisioned by this feature.
- Storage CRS is EPSG:4326 (WGS84 lat/lon) for all geometry columns, matching GeoJSON/Cesium conventions used later in the pipeline; any source data in a different CRS is reprojected on ingest.
- The Kerr County boundary is identified by FIPS/GEOID `48265` (Texas state FIPS 48, Kerr County FIPS 265) and sourced from US Census TIGER/Line, which is public and agent-pullable.
- The relevant HUC8 for the river network is `12100201`, matching the HAND HUC8 already named in `docs/README.md`.
- TxDOT and USGS NHD are available as public bulk/API downloads without an approval step, consistent with PRD 6.1's "Agent-pullable" labeling; exact endpoint URLs are resolved by the developer at implementation time rather than hard-coded into this spec.
- The Overpass API's public instance (`overpass-api.de` or an equivalent public mirror) is sufficient for Kerr County-scale queries without special rate-limit handling beyond a basic retry.
- "Camp footprints" in this feature refers only to the `camps` table's schema and loader; no assumption is made about what a real camp dataset will look like beyond "a vector file with polygon or point geometry," since the actual source is not yet chosen (manual, PRD 6.1).

## Open questions

None. Where PRD 6.1 leaves an item manual (camp acquisition, HMP cross-check), this spec resolves the ambiguity by scoping it out rather than asking a question the developer agent cannot act on anyway.
