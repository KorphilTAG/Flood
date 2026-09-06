# Changes

- Slug: physics-translator
- Spec: `pipeline/features/physics-translator/spec.md`
- Status: complete

## Summary

Second pass. The first pass defined Contract 2 and the Contract 0 `postgis` mapping in
`docs/`, and marked the extractor, CLI, dependency, and test criteria blocked because
`src/flood` did not exist in this worktree. Master has since landed that foundation
(package layout, CLI `register` marker, `Run.state`, the contract validator, and the
active `scenarios/kerr-2025-07-04.json`), and the merge with master is done, so this pass
implements the blocked criteria against it.

Added `flood.impact` (PostGIS adapter, zonal extraction, registry classification, egress,
reach copying, atomic validated output) and the `flood impacts extract` CLI, registered
Contract 2 in the packaged validator, synced the active scenario with the contract example,
and added offline plus opt-in PostGIS tests.

## Files touched

| Path | Change | Why |
|---|---|---|
| `src/flood/impact/__init__.py` | Added | Public surface of the impact package. |
| `src/flood/impact/postgis.py` | Added | `PostGISExposureStore`: quoted identifiers, parameterized bounds, DSN resolution, row/geometry validation. |
| `src/flood/impact/extractor.py` | Added | `ImpactExtractor`: band-by-description reads, zonal/point stats, registry classification, same-`p` projections, egress, reach reduction, canonical atomic write. |
| `src/flood/cli_impacts.py` | Added | `flood impacts extract`; materializes products via `Run.state(..., write=True)` and passes explicit paths to the extractor. |
| `src/flood/cli.py` | Edited | One `register_impacts(sub)` call under the REGISTER comment. |
| `src/flood/contracts/schemas/impact-json.schema.json` | Added | Copy of the documented Contract 2 schema, so the packaged validator can enforce it. |
| `src/flood/contracts/validate.py` | Edited | Registered `impact-json` in `SCHEMA_NAMES`. |
| `src/flood/contracts/schemas/scenario.schema.json` | Edited | Added the `postgis` block so the packaged copy matches the documented Contract 0. |
| `src/flood/contracts/models.py` | Edited | Added `PostgisMapping` and `ExposureLayer.postgis`, plus `SQL_IDENT_REGEX`. |
| `scenarios/kerr-2025-07-04.json` | Edited | Declares the spec's PostGIS mapping for every exposure layer. |
| `pyproject.toml` | Edited | Added `rasterstats` and `psycopg[binary]`; registered the `postgis` marker and deselected it by default. |
| `tests/test_impact_contract.py` | Added | Contract 2 schema behaviour, including geometry/coordinate and unknown-key rejection. |
| `tests/test_impact_extractor.py` | Added | Offline extraction over synthetic Contract 1 COGs and in-memory features. |
| `tests/test_impact_postgis.py` | Added | Offline query-composition tests plus the opt-in live round trip. |
| `pipeline/features/physics-translator/changes.md` | Edited | This record. |

Not changed: `ingestion/db/schema.sql` (see Residual risk), and the `docs/contracts/*`
files delivered by the first pass, which this pass only mirrors into the package.

## Acceptance criteria

| Criterion | Status | Where |
|---|---|---|
| Contract 2 schema/sample validate; README names producer/consumers; schema rejects geometry/coordinates and unknown keys | done | `tests/test_impact_contract.py`; `docs/contracts/README.md` (first pass) |
| Contract 0 accepts `postgis`; Kerr docs example and active scenario declare it for every layer; extractor raises a clear config error for a missing mapping or inapplicable threshold | done | `src/flood/contracts/models.py`, `scenarios/kerr-2025-07-04.json`, `test_layer_without_postgis_mapping_is_a_config_error`, `test_layer_without_applicable_threshold_is_a_config_error` |
| `PostGISExposureStore` uses `read_postgis`, DSN from env or CLI, parameterized bounds, quoted identifiers; rejects missing/duplicate IDs, invalid/empty/unsupported geometry, unalignable CRS | done | `src/flood/impact/postgis.py`, `tests/test_impact_postgis.py` |
| Six-band fixture COG: bands found by description, `-9999` nodata, `0` dry; clear failure for a missing band, grid/CRS mismatch, or nonexistent future COG | done | `test_bands_resolved_by_description_not_index`, `test_missing_required_band_is_an_error`, `test_grid_mismatch_is_an_error`, `test_missing_future_cog_is_an_error_not_implicit_dry` |
| Offline fixtures cover point/line/polygon/site egress; registry-only thresholds; allow-list attributes; stable refs; no geometry or coordinates serialized | done | `test_classification_uses_only_registry_thresholds`, `test_attributes_are_exactly_the_registry_allow_list`, `test_output_validates_and_carries_no_coordinates` |
| Current/+30/+60/+120 fixtures preserve one fixed `p`, record each target, report earliest impact and egress-blocked time; all-dry features absent | done | `test_projections_hold_one_fixed_p_and_earliest_impact`, `test_egress_blocked_reports_first_blocked_time`, `test_feature_dry_at_every_target_is_absent` |
| Reach sidecar reduced to the five Contract 2 fields; velocity labeled proxy in the parent | done | `test_reaches_are_reduced_to_contract_2_columns` |
| `flood impacts extract --scenario --run-dir --p --t [--postgis-dsn]` uses the snapped query, writes the canonical path atomically, prints it, validates output | done | `src/flood/cli_impacts.py`; path/atomicity in `test_write_is_atomic_and_at_the_canonical_path`, `test_hindsight_path_and_null_p` |
| `pytest -q` passes with no network or database; `pytest -m postgis` is opt-in against `FLOOD_TEST_POSTGIS_DSN` and cleans up | done | Full suite run below; marker verified selected/deselected and green against a live PostGIS 16-3.4 |

## How to verify

The repo has no checked-in virtualenv; create one on Python 3.12 first.

```
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q                                  # postgis deselected by default
.venv/bin/python -m pytest -q tests/test_impact_contract.py tests/test_impact_extractor.py tests/test_impact_postgis.py
.venv/bin/flood impacts extract --help
```

Opt-in database coverage, against any PostGIS the caller supplies:

```
docker compose up -d postgis
FLOOD_TEST_POSTGIS_DSN=postgresql://flood:flood@127.0.0.1:5432/flood \
  .venv/bin/python -m pytest -q -m postgis
```

The two marked tests create a `flood_it_<random>` schema, exercise the adapter, and drop
it in a fixture teardown.

## Residual risk

- ~~**Exposure relations named by the spec do not exist yet.**~~ **Resolved in a follow-up
  pass.** `ingestion/db/exposure_views.sql` now creates `flood_exposure.kerr_2025_07_04_*`
  views over the ingest tables, renaming `geom` to `geometry` and projecting each layer's
  declared id field and attribute allow-list. `schema.sql` was not changed. Verified against
  a live PostGIS 16-3.4: `Find_SRID` resolves on the views, the AOI bbox filter works, and
  `PostGISExposureStore` loads all four layers. That pass also found and fixed two real bugs
  this mismatch had been hiding — the ingest `feature_id` (`crossing:osm:node/1`) is already
  layer-prefixed and contains `/`, which the `feature_ref` grammar forbids, and the store
  never fetched the egress `join_field`, so egress could never have resolved against a real
  database.
- **The live-database path is proven only against a throwaway PostGIS 16-3.4.** The opt-in
  tests passed there (`read_postgis` used, bbox filter applied, reprojection to the raster
  CRS, schema dropped), but the adapter has never run against the project's own compose
  database or a table populated by the real ingestion path.
- **`geopandas.read_postgis` with a raw psycopg connection emits a pandas warning** that only
  SQLAlchemy connectables are formally supported. It works and the spec names `read_postgis`,
  so it was left as is; a future change may want a SQLAlchemy engine.
- **The CLI end-to-end path is not covered by an automated test.** Extraction, the canonical
  path, atomic write, and validation are tested directly, and the CLI's argument and error
  handling were exercised by hand, but no test drives `flood impacts extract` against a real
  run directory, because that needs both engine products and a database.
- **Egress semantics are a reading of the contract, not something the contract pins down.** A
  site is `blocked` only when every configured route is impassable, `first_blocked_t` is the
  latest of those route times, and a site with no matching route is `unknown` rather than
  `open`. If the intended reading is "any route blocked", `_build_egress` is the one place
  to change.
- **Zonal sampling uses `all_touched=True`** so a road narrower than one cell still samples
  the cells it crosses. That is deliberately inclusive and will read slightly wetter than a
  centre-line-only sample for sub-cell geometry.
