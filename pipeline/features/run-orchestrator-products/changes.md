# Changes

- Slug: run-orchestrator-products
- Spec: `pipeline/features/run-orchestrator-products/spec.md`
- Status: in progress

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

## Residual risk

## Not done
