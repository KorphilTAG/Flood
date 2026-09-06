# Changes

- Slug: run-orchestrator-products
- Spec: `pipeline/features/run-orchestrator-products/spec.md`
- Status: complete (fix-up pass finished the record)

## Summary

Implementing Run orchestrator, manifest generation, reach and gauge tables, raster and tabular product export, LRU caching, stage timing, and CLI commands for cycle C06.

## Files touched

| Path | Change | Why |
|---|---|---|
| `src/flood/products/manifest.py` | add | `config_hash`, `make_run_id`, `merge_forcing`, `build_manifest`, `ENGINE_LIMITATIONS` |
| `src/flood/products/tables.py` | add | Reach and gauge table builders and serialization |
| `src/flood/engine/run.py` | add | `ResolvedQuery`, `Run`, `RunStore` |
| `src/flood/cli_run.py` | add | CLI subcommand `run` (`create`, `state`, `list`) |
| `src/flood/cli.py` | edit | Register `cli_run` subcommand under REGISTER marker |
| `tests/test_manifest.py` | add | Unit tests for manifest generation, hash, and forcing merge |
| `tests/test_tables.py` | add | Unit tests for reach and gauge table generation and schema validation |
| `tests/test_run.py` | add | Integration and unit tests for `Run`, `RunStore`, products, and CLI |

## Acceptance criteria

| Criterion | Status (done/blocked/skipped) | Where |
|---|---|---|
| `config_hash` and `make_run_id` | in progress | `src/flood/products/manifest.py` |
| `build_manifest` with `ENGINE_LIMITATIONS` and junction inferences | in progress | `src/flood/products/manifest.py` |
| `merge_forcing` deep merge | in progress | `src/flood/products/manifest.py` |
| `Run.create`, `Run.open`, `RunStore` | in progress | `src/flood/engine/run.py` |
| `Run.resolve` with `ResolvedQuery` | in progress | `src/flood/engine/run.py` |
| `Run.routed` with 8-entry LRU cache | in progress | `src/flood/engine/run.py` |
| `Run.state` with stage timing and state response validation | in progress | `src/flood/engine/run.py` |
| Product writing on disk with `write=True` | in progress | `src/flood/engine/run.py` |
| `build_reaches` | in progress | `src/flood/products/tables.py` |
| `build_gauges` | in progress | `src/flood/products/tables.py` |
| Fixture tests on `mini-huc` | in progress | `tests/test_run.py` |
| CLI commands (`create`, `state`, `list`) | in progress | `src/flood/cli_run.py`, `src/flood/cli.py` |
| Measured `compute_ms` & decision 0003 branch | in progress | `pipeline/features/run-orchestrator-products/changes.md` |
| `pytest -q` green offline | in progress | Test suite |

## How to verify

Recorded by the fix-up pass. Worktree suite at merge time: `97 passed`. Master after integration: `137 passed`.

Reference-corridor measurement (corrected cube, USGS-only forcing), from the verifier's timing readout and standalone probes: first `(p, t)` state about 30 s cold (routing 19 to 26 s, three-member mapping 5.7 s, reduce 1.2 s); hindsight state 102 s (routing 86 s over the full record). Per-member mapping 11.1 s before the mapping fix-up, 2.5 s after. Details and the decision in `docs/decisions/0003-compute-strategy-measure-before-choosing.md`.

## Residual risk

- The developer session's own Kerr measurement ran against a cube built before the HydroID prefix fix and the corrected AOI, so its products were all nodata; that run directory was deleted and rebuilt.
- Routing cost on the reference corridor is the dominant latency; see decision 0003 for the optimisation order.

## Not done
