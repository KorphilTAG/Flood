# Feature spec

- Slug: engine-api
- Feature: C07. FastAPI application exposing contract 1 section 9: scenarios, runs, state, reaches, gauges, raster, time-to-exceedance, overlay PNG, hindsight, skill file, static verifier mount, and structured errors.
- Status: draft
- Product refs: `docs/contracts/contract-1-physics-products.md` section 9; `docs/contracts/schemas/state-response.schema.json`; C06 spec (`Run`, `RunStore`); C08 spec (clock router is mounted here but owned there).

## Problem

Consumers need the products over HTTP with the exact paths, parameters, and error codes in contract 1.

## In scope

- `api/app.py`: `create_app(settings) -> FastAPI`, settings from environment (`FLOOD_RUNS_DIR`, `FLOOD_DATA_DIR`, `FLOOD_SCENARIOS_DIR`, defaults `runs`, `data`, `scenarios`).
- `api/scenarios.py`, `api/runs.py` routers.
- Error handler mapping `TimeGridError` and lookup failures to `{ "error": { "code", "message" } }` with HTTP 400 or 404.
- `flood serve [--host 127.0.0.1] [--port 8000]`.
- Mounts: `/clock` router from `flood.api.clock` if importable; `/verifier` static files from `flood/verifier/static` if the directory exists; `/runs/{run_id}/products/...` and `/runs/{run_id}/hindsight/...` as static files from the run directory.

## Out of scope

Clock logic (C08), verifier content (C09), skill computation (C10). Authentication. Tiles.

## Approach

Thin routers over `RunStore`. The state route calls `Run.state(p, t, write=False)` and returns the dict; raster and table routes call `Run.state(..., write=True)` or the table builders and stream files. Overlay renders in memory from the arrays. Until C06 merges, develop against `tests/fakes/fake_run.py` (owned by this cycle) implementing the same method names with fixture-shaped data; the TestClient suite runs against the fake and, once C06 exists, against the real `Run` on the fixture.

## Files to change

| Path | Action (add/edit) | Why |
|---|---|---|
| `src/flood/api/__init__.py`, `app.py`, `scenarios.py`, `runs.py`, `errors.py`, `settings.py` | add | Application |
| `src/flood/cli_serve.py` | add | `register(sub)` for `serve` |
| `src/flood/cli.py` | edit | One line under the REGISTER marker |
| `tests/fakes/__init__.py`, `tests/fakes/fake_run.py` | add | Fake `RunStore` and `Run` for API tests |
| `tests/test_api.py` | add | TestClient suite |

## Acceptance criteria

- [ ] `GET /scenarios` returns `[{"scenario_id", "name"}]` for every `*.json` in the scenarios dir that validates; invalid files are skipped with a WARN log. `GET /scenarios/{id}` returns the file; unknown gives 404 `unknown_scenario`.
- [ ] `GET /runs` returns a list of manifests with only `run_id, created_at, mode, scenario, time, members` keys. `POST /runs` with body `{"scenario_id", "mode", "forcing_overrides"?}` returns 202 and the full manifest; invalid overrides give 400 `invalid_forcing`. `GET /runs/{run_id}` returns the manifest or 404 `unknown_run`.
- [ ] `GET /runs/{run_id}/state?p=&t=` returns the state response dict validating against `state-response`; `p=hindsight` allowed; missing `p` or `t` gives 400 with code `missing_parameter`; `TimeGridError` codes map to 400 with the same code string.
- [ ] `GET /runs/{run_id}/reaches?p=&t=` returns a JSON array whose rows validate against `reach-row`. `GET /runs/{run_id}/gauges?p=` likewise against `gauge-row`.
- [ ] `GET /runs/{run_id}/raster?p=&t=` ensures the product exists via `Run.state(write=True)` and returns the file as `application/octet-stream` with `Accept-Ranges: bytes` and correct `Content-Length`; a `Range: bytes=0-99` request returns 206 with 100 bytes.
- [ ] `GET /runs/{run_id}/tte?p=` returns `time_to_exceedance.tif`; 400 `hindsight_has_no_tte` when `p=hindsight`.
- [ ] `GET /runs/{run_id}/overlay.png?p=&t=&band=depth_mid&max_px=2048` returns `image/png` with header `X-Bounds-3857: xmin,ymin,xmax,ymax`; `band` must be one of `RASTER_BANDS` else 400 `unknown_band`; `max_px` clamped to `[256, 4096]`.
- [ ] `GET /runs/{run_id}/hindsight?t=` equals `state?p=hindsight&t=`.
- [ ] `GET /runs/{run_id}/skill` returns the rows of `runs/<run_id>/skill.parquet` as JSON if the file exists, else 404 `skill_not_computed`.
- [ ] `GET /verifier/` serves `index.html` when `flood/verifier/static` exists; the app starts without it.
- [ ] Every error body is `{"error": {"code": str, "message": str}}` and nothing else. Unhandled exceptions return 500 with code `internal`.
- [ ] `flood serve` starts uvicorn with `create_app()`.
- [ ] `tests/test_api.py` covers every route above and every error code, running against `FakeRunStore` always and against the real `RunStore` on the fixture when `flood.engine.run` imports successfully (skip otherwise with reason).
- [ ] `pytest -q` green offline.

## Non-goals and constraints

- No tile endpoints. No PostGIS, no TiTiler.
- Do not edit `interfaces.py` or any C06 file. If `Run` lacks something, use `getattr` with a fallback and record the gap.
- The route table and parameter names are frozen by contract 1; do not rename.

## Assumptions

- `Run.state(p, t, write)` returns `(StateArrays, dict)`; `Run.reaches(p, t)`, `Run.gauges(p)`, `Run.tte(p, write)`, `Run.product_path(kind, p, t)`, `Run.manifest`, `RunStore.list/get/create` exist per the C06 spec.

## Open questions

- None.

## Implementer notes

- Settings: pydantic `BaseSettings` is not a dependency; use a small dataclass reading `os.environ` with defaults.
- Static mounts: `app.mount("/runs/{run_id}/products", ...)` cannot be parameterised in Starlette; instead implement a route `GET /runs/{run_id}/products/{path:path}` and `GET /runs/{run_id}/hindsight/{path:path}` that resolve inside the run directory, reject `..`, and return `FileResponse`.
- Range support: implement a small `range_file_response(path, range_header)` helper returning 206 with `Content-Range`; uvicorn does not add this for you.
- Timing: log one JSON line per request with method, path, status, and milliseconds.
