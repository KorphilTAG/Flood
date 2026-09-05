# Review

- Slug: map-data-ingestion
- Spec: `pipeline/features/map-data-ingestion/spec.md`
- Changes: `pipeline/features/map-data-ingestion/changes.md`

## Verdict

PASS WITH GAPS

## Summary

The developer-agent scope is implemented essentially as described: schema, shared lib code, five ingestion scripts, a verification script, fixture-driven tests, `docker-compose.yml`, and `README.md` all exist and match `changes.md`'s file list exactly (`git status --porcelain` shows only `docker-compose.yml`, `ingestion/`, `pipeline/features/map-data-ingestion/` as untracked additions — no existing files edited, no extra files beyond what changes.md claims).

I independently verified, not just read:
- `cd ingestion && pytest` in a throwaway venv: **18/18 passed**, no network/DB, confirming changes.md's claim exactly.
- `docker compose up -d postgis` + `docker logs`: `ingestion/db/schema.sql` applies cleanly to a real `postgis/postgis:16-3.4` container (all 5 tables + GIST indexes created, no errors).
- `python -m scripts.ingest_camps --input tests/fixtures/sample_camps.geojson --source fixture --id-field camp_id` against that real DB: loaded 3 rows with feature_ids `camp:fixture:camp-a/b/c` exactly as spec's convention requires.
- Ran it a second time: row count stayed at 3, feature_ids unchanged — real (not just unit-tested) idempotency confirmed.
- `python -m scripts.verify_exposure_layers` against that DB: correctly reported `camps: 3 row(s), 0 check failure(s)` and correctly failed non-zero for `roads`/`river_network`/`buildings`/`crossings` being empty (expected, since the four live-source scripts were never run against real endpoints).
- Container and volumes torn down afterward (`docker compose down -v`); no real camp data or DB state persisted into the repo.

Two gaps keep this from a clean PASS:

1. **Disclosed by changes.md itself**: the four live-source scripts (`ingest_txdot_roads.py`, `ingest_nhd_flowlines.py`, `ingest_osm_buildings.py`, `ingest_osm_crossings.py`) were never executed against real TxDOT/USGS/Overpass endpoints. This is consistent with the spec's own "Testing without requiring live network/DB in CI" section, which explicitly defers live-endpoint runs to a "documented manual integration step" — so it is not a spec violation, but it is a real, un-exercised risk (the ArcGIS FeatureServer URLs are the developer's best-effort guess and are unconfirmed to be current/correct).
2. **Not disclosed by changes.md** — a genuine code defect I found by reading `ingestion/lib/geo.py`: `ingest_osm_buildings.py`'s Overpass query explicitly requests `relation["building"]` elements (matching spec's "ways/relations" language), but `overpass_element_to_geometry` (lib/geo.py:119-135) only handles `element.get("type") in ("node", "way")` and returns `None` for anything else, and `overpass_elements_to_geodataframe` silently drops any element whose geometry is `None`. Every relation-tagged (multipolygon) building fetched by the query is therefore silently discarded, never inserted. This doesn't crash the script, but it means the `buildings` table will always undercount relation-based footprints, contrary to the script's own stated intent.

## Spec coverage

| Criterion | Result | Evidence |
|---|---|---|
| `schema.sql` creates `roads`, `river_network`, `buildings`, `crossings`, `camps` with `feature_id` PK, SRID-4326 `geom`, `source`, `source_id`, `attributes JSONB`, `created_at`; `crossings` adds `osm_tag`, `hmp_verified_name` (nullable), `hmp_cross_checked BOOLEAN DEFAULT false` | Implemented | `ingestion/db/schema.sql` lines 12-71; applied successfully to a live PostGIS container in this review |
| Four live-source scripts populate their tables, clipped to Kerr County boundary | Partial — code complete, correct clip approach (`intersects(boundary_geom)` for OSM scripts, ArcGIS polygon filter for TxDOT/NHD), but never run against live endpoints; additionally, `ingest_osm_buildings.py` silently drops all `relation`-typed results (see Summary) | `ingestion/scripts/ingest_txdot_roads.py`, `ingest_nhd_flowlines.py`, `ingest_osm_buildings.py`, `ingest_osm_crossings.py`; bug in `ingestion/lib/geo.py:119-135` |
| Every inserted row has non-null unique `feature_id` (`<layer>:<source>:<source_id>`) and valid geometry | Implemented | `ingestion/lib/geo.py::make_feature_id`; enforced by DB `PRIMARY KEY` + `verify_exposure_layers.py`'s `ST_IsValid`/uniqueness checks; confirmed working against a real DB in this review |
| `ingest_osm_crossings.py` leaves `hmp_verified_name` null / `hmp_cross_checked` false on every inserted row | Implemented | `ingestion/scripts/ingest_osm_crossings.py` — `extra_fields` only sets `osm_tag`; the two HMP columns are never referenced in `build_upsert_sql`'s column list, so they always take schema defaults (NULL / false) and are never overwritten on re-run |
| Re-running any of the four scripts twice does not duplicate rows or reassign `feature_id` | Implemented | `ingestion/lib/upsert.py` (`ON CONFLICT (feature_id) DO UPDATE`); unit-tested in `test_upsert.py` (2 tests) and confirmed against a real DB in this review (re-ran `ingest_camps.py` twice: same 3 rows, same feature_ids) |
| `ingest_camps.py` loads `tests/fixtures/sample_camps.geojson` with correct `feature_id`s; `camps` ships with only this fixture data | Implemented | `ingestion/scripts/ingest_camps.py`, `ingestion/tests/fixtures/sample_camps.geojson` (3 synthetic polygons), `test_ingest_camps.py` (2 tests, passing); confirmed against a real DB in this review — exact feature_ids `camp:fixture:camp-a/b/c` |
| `verify_exposure_layers.py` checks existence/validity/`feature_id`/row-count per table, exits non-zero on failure | Implemented | `ingestion/scripts/verify_exposure_layers.py`; confirmed against a real DB in this review — correctly reported 0 failures for populated `camps` and exit code 1 for the four empty required tables |
| `test_geo.py` and `test_upsert.py` pass without network/DB | Implemented | Ran `cd ingestion && pytest` myself in a throwaway venv: 18/18 passed, matching changes.md's claim exactly |
| `README.md` documents env vars, running scripts/tests, and the manual follow-up checklist referencing PRD 6.1 | Implemented | `ingestion/README.md`; manual checklist wording matches spec's two manual bullets near-verbatim (only the `(Manual, not this pass)` prefix is dropped) and text references "PRD 6.1" directly |
| `docker-compose.yml` brings up a local `postgis/postgis` container that `schema.sql` applies to | Implemented | `docker-compose.yml`; confirmed in this review — `docker compose up -d postgis` succeeded and `docker logs` showed `schema.sql` applying with no errors (all 5 `CREATE TABLE` + 5 `CREATE INDEX` statements succeeded) |

**Manual follow-up (explicitly out of scope):**

| Criterion | Result | Evidence |
|---|---|---|
| Real camp footprint acquisition + `ingest_camps.py --input <acquired-file>` | Correctly not attempted | `camps` table has no seed `INSERT`s in `schema.sql`; no real camp geometry anywhere in the diff |
| HMP/EOP PDF reading and crossing cross-check | Correctly not attempted | `hmp_verified_name`/`hmp_cross_checked` are schema placeholders only, never written by any script |

## changes.md accuracy

Accurate. Every file changes.md lists under "Files touched" exists at the stated path with content matching its stated purpose; `git status --porcelain` shows no untracked files outside `docker-compose.yml`, `ingestion/`, and `pipeline/features/map-data-ingestion/`, so nothing was omitted or fabricated. The "18 tests pass" claim is independently confirmed (18/18, same test names). The "Residual risk" section's claim that the four live-source scripts were not run against real endpoints is honest and confirmed true. However, changes.md's residual-risk section does **not** mention the `ingest_osm_buildings.py` relation-handling gap described above — that gap exists in the actual code but is absent from the self-report.

## Out-of-scope drift

None found. No real camp data, no HMP/EOP PDF interpretation or fabricated cross-check values, no terrain/DEM/HAND ingestion, no FastAPI/impact-extractor/LLM/UI code, no hosted PostGIS provisioning, and no cross-source conflation/dedup logic were added — all consistent with the spec's Out of scope section. `feature_id`s are deterministically derived from source data (`make_feature_id`, unit-tested to reject any missing part) — no raw coordinates or invented IDs found anywhere in the diff, consistent with PRD Design Principle 3. No flood physics or tactical computation is present, consistent with Design Principle 1.

## Required follow-ups

1. Run the four live-source scripts end-to-end against real TxDOT ArcGIS, USGS NHDPlus HR, and Overpass endpoints (with a reachable PostGIS instance) to confirm the hard-coded FeatureServer URLs in `ingest_txdot_roads.py`/`ingest_nhd_flowlines.py` are current and that the field names (`OBJECTID`, `NHDPlusID`, `REACHCODE`) match the live schema. This is the manual integration step the spec itself defers, but it must happen before Milestone 1 is considered actually satisfied (not just code-complete).
2. Fix `ingest_osm_buildings.py`: either add relation-geometry handling to `overpass_element_to_geometry`/`overpass_elements_to_geodataframe` (Overpass `out geom;` on relations returns per-member geometries under `members`, requiring multipolygon reconstruction), or drop `relation["building"]` from the query and document that only way-based footprints are loaded, so the code's behavior matches its stated intent.
3. Minor: `ingestion/README.md`'s manual-follow-up checklist drops the spec's `(Manual, not this pass)` prefix from each bullet — cosmetic, not a functional gap, but worth aligning if strict verbatim-ness matters for future audits.
