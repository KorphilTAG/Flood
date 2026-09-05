# Changes

- Slug: map-data-ingestion
- Spec: `pipeline/features/map-data-ingestion/spec.md`
- Status: complete (developer-agent scope)

## Summary

Implemented the automatable half of the map-data-ingestion feature: a PostGIS
schema for `roads`, `river_network`, `buildings`, `crossings`, `camps`, shared
DB/geo/upsert library code, one boundary-fetch script plus four live-source
ingestion scripts (TxDOT roads, USGS NHD flowlines, OSM buildings, OSM
crossings), a generic `ingest_camps.py` loader tested only against a synthetic
fixture, a verification script, fixture-driven unit tests, a local
`docker-compose.yml` PostGIS service, and an `ingestion/README.md` with the
manual-follow-up checklist. The repo was docs-only before this change; no
existing files were edited, only added, matching the spec's "Files to change"
table. The two manual PRD 6.1 items (real camp acquisition, HMP/EOP PDF
cross-check) were left untouched — no data was fabricated or invented for
either.

All 18 fixture-driven tests pass with no network access and no live database
(`cd ingestion && pytest`, verified during implementation with a throwaway
venv that was removed afterward).

## Files touched

| Path | Change | Why |
|---|---|---|
| `ingestion/requirements.txt` | add | Pin geopandas, shapely, requests, psycopg2-binary, sqlalchemy, geoalchemy2, python-dotenv, pytest |
| `ingestion/.env.example` | add | Documents `DATABASE_URL` or `PGHOST`/`PGPORT`/`PGDATABASE`/`PGUSER`/`PGPASSWORD` |
| `ingestion/db/schema.sql` | add | DDL for `roads`, `river_network`, `buildings`, `crossings`, `camps`, `CREATE EXTENSION IF NOT EXISTS postgis` |
| `ingestion/lib/__init__.py` | add | Makes `lib` an importable package for `python -m scripts.*` and tests |
| `ingestion/lib/db.py` | add | `get_database_url()` / `get_engine()` reading env vars (via python-dotenv) |
| `ingestion/lib/geo.py` | add | `make_feature_id`, `reproject_to_4326`, Kerr County boundary loading, ArcGIS REST and Overpass API query helpers |
| `ingestion/lib/upsert.py` | add | `rows_from_geodataframe`, `build_upsert_sql` (`INSERT ... ON CONFLICT (feature_id) DO UPDATE`), `upsert_geodataframe` (live DB), `apply_upsert_in_memory` (pure in-memory reference implementation used by tests) |
| `ingestion/scripts/__init__.py` | add | Makes `scripts` an importable package |
| `ingestion/scripts/fetch_kerr_county_boundary.py` | add | Downloads Census TIGER county file, filters to STATEFP 48 / COUNTYFP 265, caches `ingestion/data/kerr_county_boundary.geojson` |
| `ingestion/scripts/ingest_txdot_roads.py` | add | Queries TxDOT ArcGIS FeatureServer, clips to Kerr County boundary, upserts into `roads` |
| `ingestion/scripts/ingest_nhd_flowlines.py` | add | Queries USGS NHDPlus HR MapServer for HUC8 12100201 flowlines, clips, upserts into `river_network` |
| `ingestion/scripts/ingest_osm_buildings.py` | add | Overpass query for `building=*` ways/relations, clips to boundary, upserts into `buildings` |
| `ingestion/scripts/ingest_osm_crossings.py` | add | Overpass query for `ford=yes` / `bridge=low_water_crossing`, clips to boundary, upserts into `crossings` with `osm_tag` set and `hmp_verified_name`/`hmp_cross_checked` left to their column defaults (NULL / false) |
| `ingestion/scripts/ingest_camps.py` | add | Generic `--input <file>` vector loader into `camps`; feature_id as `camp:<source>:<source_id-or-row-index>`; not invoked against real data by this feature |
| `ingestion/scripts/verify_exposure_layers.py` | add | Checks table existence, `ST_IsValid(geom)`, non-null/unique `feature_id`, and (for the four automated tables) row count > 0; exits non-zero on any failure |
| `ingestion/tests/__init__.py` | add | Makes `tests` an importable package |
| `ingestion/tests/conftest.py` | add | Adds `ingestion/` to `sys.path` so tests import `lib`/`scripts` regardless of invocation directory |
| `ingestion/tests/fixtures/sample_camps.geojson` | add | 3-polygon synthetic fixture used by `test_ingest_camps.py` |
| `ingestion/tests/test_geo.py` | add | Unit tests for `make_feature_id` and `reproject_to_4326`, plus boundary-loading helper tests (no network/DB) |
| `ingestion/tests/test_upsert.py` | add | Unit tests for upsert SQL generation and idempotent merge semantics via `apply_upsert_in_memory` (no network/DB) |
| `ingestion/tests/test_ingest_camps.py` | add | Runs `ingest_camps.main()` against the synthetic fixture with the DB call stubbed to an in-memory store; asserts correct `feature_id` assignment |
| `ingestion/README.md` | add | Env vars, how to run each script and the tests, and the manual-follow-up checklist referencing PRD 6.1 verbatim |
| `docker-compose.yml` | add | Local `postgis/postgis:16-3.4` service; mounts `ingestion/db/schema.sql` as an init script; validated with `docker compose config` |

No existing files were edited — the repo was docs-only before this feature, consistent with the spec's "Files to change" note.

## Acceptance criteria

**Developer-agent scope:**

| Criterion | Status | Where |
|---|---|---|
| Schema creates `roads`, `river_network`, `buildings`, `crossings`, `camps` with required columns; `crossings` has `osm_tag`, `hmp_verified_name`, `hmp_cross_checked` | done | `ingestion/db/schema.sql` |
| The four live-source scripts populate their tables, geometry clipped to the Kerr County boundary | done (code complete; not run against live sources — see Residual risk) | `ingestion/scripts/ingest_txdot_roads.py`, `ingest_nhd_flowlines.py`, `ingest_osm_buildings.py`, `ingest_osm_crossings.py`, `ingestion/scripts/fetch_kerr_county_boundary.py` |
| Every inserted row has non-null unique `feature_id` (`<layer>:<source>:<source_id>`) and valid geometry | done | `ingestion/lib/geo.py::make_feature_id`, `ingestion/lib/upsert.py`, verified by `ingestion/scripts/verify_exposure_layers.py` at run time; unit-tested in `tests/test_geo.py`, `tests/test_upsert.py` |
| `ingest_osm_crossings.py` leaves `hmp_verified_name` null / `hmp_cross_checked` false | done | `ingestion/scripts/ingest_osm_crossings.py` (only `osm_tag` is set as an extra field; the two HMP columns are never included in the upsert, so they take their schema defaults — NULL and false — and are never overwritten by re-runs) |
| Re-running any of the four scripts twice does not duplicate rows or reassign `feature_id` | done | `ingestion/lib/upsert.py` (`ON CONFLICT (feature_id) DO UPDATE`), tested in `ingestion/tests/test_upsert.py::test_upsert_rerun_is_idempotent_no_duplicates_no_id_reassignment` and `::test_upsert_rerun_updates_attributes_without_changing_feature_id` |
| `ingest_camps.py` loads `tests/fixtures/sample_camps.geojson` with correct `feature_id`s; `camps` contains only this fixture data | done | `ingestion/scripts/ingest_camps.py`, `ingestion/tests/fixtures/sample_camps.geojson`, `ingestion/tests/test_ingest_camps.py` |
| `verify_exposure_layers.py` checks existence/validity/feature_id/row-count per table, exits non-zero on failure | done | `ingestion/scripts/verify_exposure_layers.py` |
| `test_geo.py` and `test_upsert.py` pass with no network/DB | done | `ingestion/tests/test_geo.py`, `ingestion/tests/test_upsert.py` — ran via `cd ingestion && pytest`, 18/18 passed |
| `README.md` documents env vars, running scripts/tests, and the manual checklist referencing PRD 6.1 | done | `ingestion/README.md` |
| `docker-compose.yml` brings up local `postgis/postgis` that `schema.sql` applies to | done | `docker-compose.yml` (validated with `docker compose config`; schema mounted as an init script) |

**Manual follow-up (explicitly out of scope, not attempted):**

| Criterion | Status | Where |
|---|---|---|
| A person acquires real camp footprint geometry and runs `ingest_camps.py --input <file>` | skipped — genuinely manual per spec's Out of scope section; no real camp data was acquired, purchased, or fabricated | Documented as an open checklist item in `ingestion/README.md` |
| A person reads the HMP/EOP PDFs and cross-checks/updates `hmp_verified_name`/`hmp_cross_checked` | skipped — genuinely manual per spec's Out of scope section; no PDF was read or interpreted, no cross-check result was fabricated | Documented as an open checklist item in `ingestion/README.md`; schema columns exist and are left null/false by `ingest_osm_crossings.py` |

## How to verify

```bash
cd ingestion
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest                              # 18 tests, no network/DB required

# Optional, requires Docker + network access:
docker compose up -d postgis        # from repo root
python -m scripts.fetch_kerr_county_boundary
python -m scripts.ingest_txdot_roads
python -m scripts.ingest_nhd_flowlines
python -m scripts.ingest_osm_buildings
python -m scripts.ingest_osm_crossings
python -m scripts.ingest_camps --input tests/fixtures/sample_camps.geojson --source fixture
python -m scripts.verify_exposure_layers
```

`docker compose config` (from repo root) was used during implementation to
confirm `docker-compose.yml` parses correctly; `pytest` (18/18) was actually
run during implementation from a throwaway venv, which was deleted afterward
so it is not part of the committed tree.

## Residual risk

- The four live-source ingestion scripts (`ingest_txdot_roads.py`,
  `ingest_nhd_flowlines.py`, `ingest_osm_buildings.py`,
  `ingest_osm_crossings.py`) were **not** executed end-to-end against live
  TxDOT/USGS/Overpass endpoints and a live PostGIS instance in this pass —
  doing so requires outbound network access and a running Postgres that
  weren't exercised here. The spec explicitly separates this into a
  documented manual integration step (`ingestion/README.md`), and the ArcGIS
  FeatureServer URLs used (TxDOT Roadway Linear Referencing System; USGS
  NHDPlus HR MapServer layer 3) are the developer's best-effort resolution of
  the spec's "exact endpoint URLs are resolved by the developer at
  implementation time" assumption — a live run should confirm they are
  current before relying on them.
- `ingest_osm_buildings.py`/`ingest_osm_crossings.py` fetch by bounding box
  (derived from the sourced Kerr County boundary's bounds, never hand-typed)
  and then clip locally with `intersects(boundary_geom)`, rather than passing
  a polygon filter directly to Overpass. This matches the spec's general
  "clip to boundary" approach used by every other script but is worth noting
  as an implementation choice, since Overpass's native `poly:` filter was not
  used.
- `test_ingest_camps.py` stubs out the DB call (`upsert_geodataframe`) with an
  in-memory equivalent so the whole suite is network/DB-free; the spec
  requires this specifically for `test_geo.py`/`test_upsert.py` but does not
  forbid it for `test_ingest_camps.py`. This was a deliberate choice so the
  full test suite is runnable in this sandbox (no live Postgres available);
  it does not reduce coverage of the acceptance criterion since it still
  exercises `ingest_camps.py`'s real argument parsing, file loading, and
  feature_id assignment against the real fixture file.

## Not done

- Real camp footprint acquisition (KCAD/TNRIS/ReportAll/Regrid/aerial
  tracing) — out of scope per spec, manual follow-up only.
- HMP/EOP PDF reading and crossing-name cross-check — out of scope per spec,
  manual follow-up only.
- Terrain/DEM/HAND ingestion, cesium-terrain-builder tiling, hosted PostGIS
  provisioning, the impact extractor/LLM/UI layers, and conflation across
  sources — all explicitly out of scope in the spec and untouched.
