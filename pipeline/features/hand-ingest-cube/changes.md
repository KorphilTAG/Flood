# Changes

- Slug: hand-ingest-cube
- Spec: `pipeline/features/hand-ingest-cube/spec.md`
- Status: in progress

## Summary

Implementation of C02: HAND ingest cube. Downloads HAND FIM artifacts for a scenario's HUC8s, clips intersecting branches to the scenario AOI on the common grid, builds rating tables and the reach network, and saves a HandCube.

## Files touched

| Path | Change | Why |
|---|---|---|
| `pipeline/features/hand-ingest-cube/changes.md` | add | Track changes and criteria |
| `src/flood/ingest/__init__.py` | add | Package init |
| `src/flood/ingest/hand.py` | add | Download, clip, assemble, save |
| `src/flood/ingest/hydrotable.py` | add | Rating tables and catchment remap |
| `src/flood/ingest/network.py` | add | Network and gauge tables |
| `src/flood/cli_prep_hand.py` | add | CLI subcommand registration |
| `src/flood/cli.py` | edit | Register cli_prep_hand |
| `tests/test_ingest_hand.py` | add | Unit and smoke tests for hand ingest |
| `tests/test_hydrotable.py` | add | Tests for rating table and catchment remap |
| `tests/test_network.py` | add | Tests for network and gauge building |

## Acceptance criteria

| Criterion | Status (done/blocked/skipped) | Where |
|---|---|---|
| `download(url, dest, expected_size=None)` skips when `dest` exists and size equals Content-Length; streams to temp file and renames | in progress | `src/flood/ingest/hand.py`, `tests/test_ingest_hand.py` |
| `clip_branch(rem_path, catch_path, grid) -> (rem_f32, catch_hydroid_i32)` exact values and padding | in progress | `src/flood/ingest/hand.py`, `tests/test_ingest_hand.py` |
| `branch_intersects(branch_bounds, grid.bounds)` false for disjoint branch and omitted from cube | in progress | `src/flood/ingest/hand.py`, `tests/test_ingest_hand.py` |
| `build_rating(hydrotable_df, branch_id) -> (RatingTable, hydroid_to_cidx)` exact arrays, sorted, checks | in progress | `src/flood/ingest/hydrotable.py`, `tests/test_hydrotable.py` |
| `remap_catchments(catch_hydroid, hydroid_to_cidx) -> int32` maps unknown HydroIDs to -1 and logs count | in progress | `src/flood/ingest/hydrotable.py`, `tests/test_hydrotable.py` |
| `build_network(streams_gdf, hydrotable_df, scenario, grid) -> DataFrame` exact NETWORK_COLUMNS | in progress | `src/flood/ingest/network.py`, `tests/test_network.py` |
| `build_gauges(usgs_elev_df, scenario) -> DataFrame` exact GAUGE_COLUMNS, elevation conversion, error on missing | in progress | `src/flood/ingest/network.py`, `tests/test_network.py` |
| Network smoke test `test_kerr_smoke` downloads Kerr, builds cube, asserts meta, branches, gauge | in progress | `tests/test_ingest_hand.py` |
| `pytest -q` passes offline; no scenario literal in `src/` | in progress | offline test suite |

## How to verify

## Residual risk

## Not done
