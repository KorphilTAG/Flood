# Changes

- Slug: engine-scaffold-contracts
- Spec: `pipeline/features/engine-scaffold-contracts/spec.md`
- Status: complete

## Summary

Implemented cycle C01 (`engine-scaffold-contracts`):
- Configured `pyproject.toml`, `.gitignore`, package metadata, console script `flood = flood.cli:main`, and pytest settings.
- Wrote `src/flood/interfaces.py` byte-for-byte from the spec specification.
- Copied all 7 JSON schemas to `src/flood/contracts/schemas/*.json` (byte-identical to `docs/contracts/schemas/*.json`).
- Implemented `src/flood/contracts/validate.py` with `validate_json`, `ContractError`, and a `referencing.Registry` resolving local and cross-schema references.
- Implemented Pydantic v2 models in `src/flood/contracts/models.py` for all schemas with `ConfigDict(extra="forbid")`.
- Implemented `src/flood/timegrid.py` for snapping, conversions, error handling, and grid generation.
- Implemented `src/flood/timing.py` with `StageTimer` context manager and structured JSON logging.
- Implemented `src/flood/scenario.py` with `load_scenario`, schema validation, model parsing, and AOI bounds alignment check.
- Implemented `src/flood/engine/cube.py` with `HandCube.save` and `HandCube.load` persisting arrays, rating tables, network, and gauges.
- Implemented `src/flood/cli.py` and `src/flood/cli_scenario.py` providing `flood scenario validate <path>`.
- Copied `scenarios/kerr-2025-07-04.json` from `docs/contracts/examples/`.
- Built deterministic test fixture generator in `tests/fixtures/mini_huc/build.py` and shared fixtures in `tests/conftest.py`.
- Added comprehensive acceptance tests in `tests/` verifying all 8 acceptance criteria.

## Files touched

| Path | Change | Why |
|---|---|---|
| `pyproject.toml` | add | Package metadata, dependencies, `flood` console script, pytest config |
| `.gitignore` | add | Ignore `data/`, `runs/`, `.venv/`, `__pycache__/`, `tests/fixtures/mini_huc/out/`, `*.egg-info/` |
| `src/flood/__init__.py` | add | Package version `__version__ = "0.1.0"` |
| `src/flood/interfaces.py` | add | Verbatim frozen shared types and protocols from spec |
| `src/flood/contracts/__init__.py` | add | Re-exports for contract models and validation |
| `src/flood/contracts/validate.py` | add | `validate_json`, `ContractError`, referencing schema registry |
| `src/flood/contracts/models.py` | add | Pydantic v2 models for contracts |
| `src/flood/contracts/schemas/*.json` | add | Byte-identical copies of contract schemas |
| `src/flood/scenario.py` | add | `load_scenario` with schema validation and AOI bounds check |
| `src/flood/timegrid.py` | add | Time grid snapping, formatting, and pair verification |
| `src/flood/timing.py` | add | `StageTimer` context manager and JSON log emitter |
| `src/flood/engine/__init__.py` | add | Engine package initialization |
| `src/flood/engine/cube.py` | add | `HandCube` save and load methods |
| `src/flood/cli.py` | add | Main CLI parser and subcommand registry |
| `src/flood/cli_scenario.py` | add | `flood scenario validate` CLI subcommand |
| `scenarios/kerr-2025-07-04.json` | add | Copy of example Kerr scenario file |
| `tests/conftest.py` | add | Pytest fixtures: `repo_root`, `mini_huc_dir`, `mini_cube`, `mini_scenario`, `kerr_scenario` |
| `tests/fixtures/mini_huc/__init__.py` | add | Mini HUC fixture package init |
| `tests/fixtures/mini_huc/build.py` | add | Deterministic synthetic fixture generator |
| `tests/test_contracts.py` | add | Acceptance tests for contracts, models, schemas, and literal check |
| `tests/test_scenario.py` | add | Acceptance tests for scenario loading, alignment, and CLI validation |
| `tests/test_timegrid.py` | add | Acceptance tests for timegrid snapping, conversion, and errors |
| `tests/test_cube.py` | add | Acceptance tests for HandCube save/load round-trip |
| `tests/test_fixture.py` | add | Acceptance tests for mini_huc fixture topology and forcing files |
| `tests/test_timing.py` | add | Acceptance tests for StageTimer and structured JSON logging |
| `pipeline/features/engine-scaffold-contracts/changes.md` | edit | Document implementation, verification outputs, and acceptance criteria |

## Acceptance criteria

| Criterion | Status (done/blocked/skipped) | Where |
|---|---|---|
| `py -3.12 -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"` succeeds on Windows; `flood --help` lists `scenario` | done | `pyproject.toml`, `src/flood/cli.py` |
| `flood scenario validate scenarios/kerr-2025-07-04.json` exits 0 and prints `OK kerr-2025-07-04`. Validating a file with `"crs": "EPSG:4326"` in the AOI exits 2 and prints the schema error path | done | `src/flood/cli_scenario.py`, `tests/test_scenario.py` |
| `tests/test_contracts.py`: every file in `docs/contracts/examples/` validates with `validate_json` against its schema and parses into its pydantic model; `src/flood/contracts/schemas/*.json` are byte-identical to `docs/contracts/schemas/*.json`; an example with an extra field fails validation | done | `tests/test_contracts.py`, `src/flood/contracts/` |
| `tests/test_timegrid.py`: `snap_p(06:07:30Z) == 06:05:00Z`; `snap_t(06:07:30Z) == 06:10:00Z`; `snap_t(06:07:29Z) == 06:05:00Z`; `check_pair` raises `TimeGridError(code="t_before_p")` for `t < p`, `code="horizon_exceeded"` for `t - p > 360 min`, `code="outside_record"` for `p < record_start` or `t > record_end`; `to_compact(2025-07-04T06:14:00Z) == "20250704T0614Z"`; round trips for compact and ISO forms | done | `src/flood/timegrid.py`, `tests/test_timegrid.py` |
| `tests/test_cube.py`: `HandCube.save` then `HandCube.load` round-trips the fixture cube with array equality, NaN-aware, and identical `Grid` | done | `src/flood/engine/cube.py`, `tests/test_cube.py` |
| `tests/test_fixture.py`: `build.py` writes the fixture; `network` has 6 reaches with the stated topology; the fixture scenario validates against the scenario schema; forcing Parquet files exist with the stated columns | done | `tests/fixtures/mini_huc/build.py`, `tests/test_fixture.py` |
| `pytest -q` passes with no network access | done | `tests/`, `pyproject.toml` |
| No string in `src/` matches `Kerr|Hunt|Guadalupe|Mystic|12100201|0816` (a test greps for this) | done | `src/`, `tests/test_contracts.py::test_no_scenario_literals_in_src` |

## How to verify

Full test suite output:
```
$ .venv\Scripts\python.exe -m pytest
============================= test session starts =============================
platform win32 -- Python 3.12.0, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\Users\splat\Desktop\Flood
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.15.1, asyncio-1.4.0
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 18 items

tests\test_contracts.py ....                                             [ 22%]
tests\test_cube.py ..                                                    [ 33%]
tests\test_fixture.py .                                                  [ 38%]
tests\test_scenario.py ....                                              [ 61%]
tests\test_timegrid.py .....                                             [ 88%]
tests\test_timing.py ..                                                  [100%]

============================= 18 passed in 0.41s ==============================
```

Scenario validation output:
```
$ .venv\Scripts\flood.exe scenario validate scenarios/kerr-2025-07-04.json
OK kerr-2025-07-04
```

## Residual risk

None identified. Shared types in `src/flood/interfaces.py` match the specification byte-for-byte and all downstream cycles can build on this scaffold without modification.

## Not done

None. All acceptance criteria met.

## Fix-up pass (Claude, after review PASS)

- `tests/fixtures/mini_huc/build.py`: single cube save at `out/data/cube/mini-huc/`; forcing at `out/data/usgs/mini-huc/` and `out/data/nwm/mini-huc/`, mirroring the production `data/` layout so `out/data` is a valid `data_dir`. Removed the duplicate root-level cube save the reviewer flagged.
- `tests/conftest.py`: added `mini_data_dir`; `mini_cube` loads from `mini_data_dir / "cube" / "mini-huc"`.
- `tests/test_fixture.py`: paths updated; asserts the cube exists only under `data/cube/`.
- `.gitignore`: added `.claude/settings.local.json`.
- Spec: fixture layout and conftest fixture list updated to match. C04, C05, C06 specs now reference `mini_data_dir` and the single layout.
- Verification after fix-up: `pytest -q` 18 passed; `flood scenario validate scenarios/kerr-2025-07-04.json` prints `OK kerr-2025-07-04`.
