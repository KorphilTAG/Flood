# Changes

- Slug: engine-api
- Spec: `pipeline/features/engine-api/spec.md`
- Status: done

## Summary

Implemented the FastAPI application exposing contract 1 section 9 physics products:
- Scenarios router (`/scenarios`, `/scenarios/{scenario_id}`) validating JSON against contract schema on load.
- Runs router covering run creation, listing, manifest retrieval, state responses with snapping/validation, reaches and gauges tables as JSON arrays, raster GeoTIFF streaming with HTTP 206 byte-range support, time-to-exceedance, EPSG:3857 PNG overlay rendering with `X-Bounds-3857` header, hindsight endpoints, skill evaluation parquet reading, and static product downloads resolving safely within run directories.
- Structured contract error responses (`{"error": {"code": str, "message": str}}`) mapping `TimeGridError`, `APIError`, HTTP exceptions, validation errors, and internal server errors.
- Clock router integration under `/clock` with lifecycle start/stop management in application lifespan.
- Verifier static mount under `/verifier` when static assets directory exists.
- `flood serve` CLI subcommand registration.
- Test doubles `FakeRunStore` and `FakeRun` implementing the frozen C06 interface on `mini_huc`.
- Complete test suite in `tests/test_api.py` covering every route and error code, with dual parameterization skipping the real `RunStore` until C06 merges.

## Files touched

| Path | Change | Why |
|---|---|---|
| `src/flood/api/settings.py` | add | Application settings dataclass loading from environment variables (`FLOOD_RUNS_DIR`, `FLOOD_DATA_DIR`, `FLOOD_SCENARIOS_DIR`) |
| `src/flood/api/errors.py` | add | Standard error handler, APIError, and contract JSON error format |
| `src/flood/api/scenarios.py` | add | Scenarios listing and retrieval router |
| `src/flood/api/runs.py` | add | Runs router for state, reaches, gauges, raster, tte, overlay, hindsight, skill, and static products with byte ranges |
| `src/flood/api/app.py` | add | FastAPI application factory `create_app` with clock, verifier, timing middleware, and error handlers |
| `src/flood/cli_serve.py` | add | CLI subcommand `flood serve [--host 127.0.0.1] [--port 8000]` |
| `src/flood/cli.py` | edit | Register `serve` subcommand under `# REGISTER:` marker |
| `tests/fakes/__init__.py` | add | Package init for test doubles |
| `tests/fakes/fake_run.py` | add | `FakeRun` and `FakeRunStore` implementation on `mini_huc` grid |
| `tests/test_api.py` | add | TestClient test suite covering all routes, parameters, and error codes |

## Acceptance criteria

| Criterion | Status (done/blocked/skipped) | Where |
|---|---|---|
| `GET /scenarios` returns `[{"scenario_id", "name"}]` for valid files; skips invalid with WARN; `GET /scenarios/{id}` returns file or 404 `unknown_scenario` | done | `src/flood/api/scenarios.py`, `tests/test_api.py::test_scenarios_list_and_get` |
| `GET /runs` returns manifest summaries; `POST /runs` creates run (202) or 400 `invalid_forcing`; `GET /runs/{run_id}` returns full manifest or 404 `unknown_run` | done | `src/flood/api/runs.py`, `tests/test_api.py::test_runs_create_list_get` |
| `GET /runs/{run_id}/state?p=&t=` returns state response dict validating against schema; `p=hindsight` allowed; missing p/t -> 400 `missing_parameter`; `TimeGridError` -> 400 | done | `src/flood/api/runs.py`, `tests/test_api.py::test_state_route_and_timegrid_errors` |
| `GET /runs/{run_id}/reaches?p=&t=` returns rows validating against reach-row; `GET /runs/{run_id}/gauges?p=` against gauge-row | done | `src/flood/api/runs.py`, `tests/test_api.py::test_reaches_and_gauges_routes` |
| `GET /runs/{run_id}/raster?p=&t=` ensures product exists via `Run.state(write=True)` and returns octet-stream with byte ranges (206 on `bytes=0-99`) | done | `src/flood/api/runs.py`, `tests/test_api.py::test_raster_and_byte_ranges` |
| `GET /runs/{run_id}/tte?p=` returns `time_to_exceedance.tif`; 400 `hindsight_has_no_tte` when `p=hindsight` | done | `src/flood/api/runs.py`, `tests/test_api.py::test_tte_route` |
| `GET /runs/{run_id}/overlay.png` returns image/png with `X-Bounds-3857` header; validates band against `RASTER_BANDS` (else 400 `unknown_band`); clamps `max_px` [256, 4096] | done | `src/flood/api/runs.py`, `tests/test_api.py::test_overlay_route` |
| `GET /runs/{run_id}/hindsight?t=` equals `state?p=hindsight&t=` | done | `src/flood/api/runs.py`, `tests/test_api.py::test_hindsight_route` |
| `GET /runs/{run_id}/skill` returns rows of `runs/<run_id>/skill.parquet` as JSON or 404 `skill_not_computed` | done | `src/flood/api/runs.py`, `tests/test_api.py::test_skill_route` |
| `GET /verifier/` serves index.html when `flood/verifier/static` exists; app starts without it | done | `src/flood/api/app.py`, `tests/test_api.py::test_verifier_mount` |
| Every error body is `{"error": {"code": str, "message": str}}` and nothing else; unhandled exceptions return 500 `internal` | done | `src/flood/api/errors.py`, `tests/test_api.py::test_unhandled_exception_returns_500` |
| `flood serve` starts uvicorn with `create_app()` | done | `src/flood/cli_serve.py`, `src/flood/cli.py`, `tests/test_api.py::test_cli_serve_parser` |
| `tests/test_api.py` covers all routes and error codes, running against `FakeRunStore` and skipping real `RunStore` when C06 is not merged | done | `tests/test_api.py` |
| `pytest -q` green offline | done | Whole test suite |

## How to verify

```
$ .venv\Scripts\python.exe -m pytest -q
.s.s.s.s.s.s.s.s.s.s.s..s.s............................................. [ 62%]
...........................................                              [100%]
102 passed, 13 skipped, 2 deselected, 17 warnings in 10.91s
```

## Residual risk

None. All interfaces and contract specifications implemented and verified. When C06 merges `flood.engine.run`, the second parameterization of `tests/test_api.py` will automatically exercise `RunStore` on the fixture.

## Not done

None.
