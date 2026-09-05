# Feature spec

- Slug: hand-ingest-cube
- Feature: C02. Download HAND FIM artifacts for a scenario's HUC8s, clip every intersecting branch to the scenario AOI on the common grid, build rating tables and the reach network, and save a `HandCube`.
- Status: draft
- Product refs: `docs/specs/physics-engine-master.md` section 5.1; `docs/decisions/0000-verified-data-findings.md`; `docs/contracts/scenario.md`; C01 spec (interfaces, cube format).

## Problem

The engine needs an in-memory cube of HAND rasters, catchment indices, rating curves, and the reach network, on one grid fixed by the scenario AOI. The public artifacts are per-branch with differing extents, int16 millimetre encoding, and HydroIDs that collide across branches.

## In scope

- `flood prep hand <scenario.json> [--data-dir data] [--force]`.
- Idempotent download of the HUC-level files and per-branch rasters listed in master spec 5.1.
- AOI clip of each intersecting branch to the common grid; conversion to the cube arrays; rating tables keyed by `(branch_id, HydroID)`; network and gauge tables.
- `HandCube.save` to `data/cube/<scenario_id>/`.
- A network-marked smoke test for the Kerr scenario and offline unit tests for clipping, encoding, and table building on small synthetic rasters written by the test.

## Out of scope

Any physics, any product, forcing data (C04), the `HandCube` class itself (C01).

## Approach

`hand.py` orchestrates: list branches from `branch_ids.csv`, fetch rasters, compute each branch's intersection with the AOI, window-read with `rasterio.windows.from_bounds` against the branch transform, place into a full AOI-shaped array with nodata padding. `hydrotable.py` reads `hydrotable.parquet` (fallback CSV with explicit dtypes), filters to branches kept, builds `RatingTable` per branch with `cidx` assigned by sorted HydroID, and remaps the catchment raster from HydroID to `cidx`. `network.py` reads `nwm_subset_streams_levelPaths.gpkg` with geopandas, builds `NETWORK_COLUMNS`, and joins `usgs_elev_table.csv` plus the scenario gauge list into `GAUGE_COLUMNS`.

## Files to change

| Path | Action (add/edit) | Why |
|---|---|---|
| `src/flood/ingest/__init__.py` | add | empty |
| `src/flood/ingest/hand.py` | add | Download, clip, assemble, save |
| `src/flood/ingest/hydrotable.py` | add | Rating tables and catchment remap |
| `src/flood/ingest/network.py` | add | Network and gauge tables |
| `src/flood/cli_prep_hand.py` | add | `register(sub)` for `prep hand` |
| `src/flood/cli.py` | edit | One line under the REGISTER marker |
| `tests/test_ingest_hand.py`, `tests/test_hydrotable.py`, `tests/test_network.py` | add | Tests |

## Acceptance criteria

- [ ] `download(url, dest, expected_size=None)` skips when `dest` exists and its size equals the `Content-Length` from a HEAD request; otherwise streams to a temp file and renames.
- [ ] `clip_branch(rem_path, catch_path, grid) -> (rem_f32, catch_hydroid_i32)`: output shape `(grid.height, grid.width)`; REM in metres (`int16 mm / 1000`), `NaN` where source nodata 32767 or outside the branch extent; catchments `-1` where source nodata 0 or outside. Unit test builds two tiny GeoTIFFs with `rasterio` at offsets partially overlapping a 6 by 4 grid and asserts exact values, including padding.
- [ ] `branch_intersects(branch_bounds, grid.bounds)` is false for a disjoint branch and that branch is omitted from the cube.
- [ ] `build_rating(hydrotable_df, branch_id) -> (RatingTable, hydroid_to_cidx: dict)`: rows sorted by HydroID; every array shaped `[n, 84]` or `[n]`; `stage_m` rows equal `0.3048 * arange(84)` within 1e-6; `q_cms` taken from `discharge_cms`; a test with a hand-built 2-catchment frame asserts exact arrays. Duplicate `(branch_id, HydroID)` pairs raise `ValueError`.
- [ ] `remap_catchments(catch_hydroid, hydroid_to_cidx) -> int32` maps unknown HydroIDs to `-1` and logs a count.
- [ ] `build_network(streams_gdf, hydrotable_df, scenario, grid) -> DataFrame` has exactly `NETWORK_COLUMNS`; `to_feature_id` is 0 where the `to` reach is outside the HUC subset; `preferred_branch` is the levelpath branch containing the feature if present else 0; `representative_cidx` is the cidx of the longest catchment (`LENGTHKM`) of that feature in the preferred branch; `in_aoi` is true iff the flowline intersects the AOI box; `flowline_wkb` is bytes.
- [ ] `build_gauges(usgs_elev_df, scenario) -> DataFrame` has exactly `GAUGE_COLUMNS`, one row per scenario gauge, `gauge_altitude_m` converted from feet, `altitude_datum` copied; raises `ValueError` naming any scenario site missing from `usgs_elev_table.csv`.
- [ ] `flood prep hand tests/fixtures/mini_huc/out/scenario.json` is not required to work (fixture HUC is fake); instead `pytest -m network tests/test_ingest_hand.py::test_kerr_smoke` downloads Kerr, builds the cube, and asserts `meta.json` grid equals `Grid.from_bounds(scenario AOI)`, at least branches 0 and 1619000006 are present, and `network` contains feature 3586192 with `gauge_site == "08165500"`.
- [ ] `pytest -q` passes offline; no scenario literal in `src/` (the C01 grep test still passes).

## Non-goals and constraints

- Do not edit `interfaces.py` or `cube.py`.
- URL pattern is built from `scenario.hydrology.fim_version` and `huc8`; nothing hardcoded beyond the bucket host, which lives in one module-level constant `HAND_BASE_URL`.

## Assumptions

- Branch rasters are all EPSG:5070, 10 m, aligned to multiples of 10. Assert this and raise if not.
- The HUC-level `hydrotable.parquet` exists; fall back to CSV with `dtype={"HydroID": "int64", "branch_id": "int64", "feature_id": "int64", "LakeID": "int64"}` and `low_memory=False`.

## Open questions

- None.

## Implementer notes

- `HAND_BASE_URL = "https://ciroh-owp-hand-fim.s3.amazonaws.com"`; prefix `f"{HAND_BASE_URL}/hand_fim_{fim_version.replace('.', '_')}/{huc8}/"`.
- Files per HUC: `hydrotable.parquet`, `branch_ids.csv` (two columns, no header: huc8, branch_id), `nwm_subset_streams_levelPaths.gpkg`, `usgs_elev_table.csv`, `nwm_lakes_proj_subset.gpkg`. Per branch `b`: `branches/{b}/rem_zeroed_masked_{b}.tif`, `branches/{b}/gw_catchments_reaches_filtered_addedAttributes_{b}.tif`.
- Hydrotable columns used: `HydroID, branch_id, feature_id, order_, LakeID, LENGTHKM, SLOPE, ManningN, stage, discharge_cms, WetArea (m2), HydraulicRadius (m), TopWidth (m)`.
- Streams gpkg columns used: `ID` (feature_id), `to`, `order_`, `Slope`, `Length`, `levpa_id`, `gages`, geometry. `gages` is whitespace-padded; strip and treat empty as null.
- `usgs_elev_table.csv` columns used: `location_id` (site, keep leading zeros by reading as str), `feature_id`, `dem_adj_elevation`, `usgs_data_altitude` (feet), `usgs_data_alt_datum_code`. Multiple rows per site exist (one per branch); take the first.
- Window read: `win = rasterio.windows.from_bounds(*grid.bounds, transform=src.transform)`, then `src.read(1, window=win, boundless=True, fill_value=src.nodata)`; assert result shape equals `(grid.height, grid.width)`.
- Log with `logging.getLogger("flood.ingest.hand")`; one INFO line per file and per branch with sizes and shapes.
