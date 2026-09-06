Implement exactly the spec at the path below. Read it in full first, then read `docs/specs/physics-engine-cycles.md` (sections "File ownership" and "Interface freeze"), `src/flood/interfaces.py`, `src/flood/timegrid.py`, and every existing file the spec names. Follow "Files to change" and "Implementer notes" literally: exact paths, signatures, constants, and test names. Never edit `src/flood/interfaces.py`, `src/flood/cli.py`, `tests/conftest.py`, or anything under `tests/fixtures/`. Do not edit files you do not own; if you need a change elsewhere, record it under Residual risk in changes.md. No scenario constants in `src/`: record bounds are injected. Do not commit, stage, or run any git command that changes state.

Spec: pipeline/features/clock-service/spec.md

Environment:
- You are at the root of a git worktree on branch `feature/clock-service`. Windows 11; use PowerShell syntax for shell commands.
- First create the environment: `py -3.12 -m venv .venv` then `.venv\Scripts\python.exe -m pip install -e ".[dev]"`. Use `.venv\Scripts\python.exe` for everything, including `-m pytest -q`.
- Copy `pipeline/templates/changes.md` to `pipeline/features/clock-service/changes.md`, fill the Slug and Spec lines, and keep it updated as you work.
- Cycles C02, C03, C04, C05 are being implemented concurrently. Import only `flood.interfaces`, `flood.timegrid`, FastAPI, and the standard library. There is no `src/flood/api/` package yet: create `src/flood/api/__init__.py` (empty) and `src/flood/api/clock.py`; C07 will add the application later and call `make_clock_router(service)` with prefix `/clock`, so the router itself must not include the `/clock` prefix in its route paths (`GET ""`, `POST ""`, `POST "/reset"`, WebSocket `"/ws"`).
- Provide `ClockService.start()` that creates the `_run` task on the running loop and `stop()` that cancels it. Tests build a `FastAPI()` app, include the router with `prefix="/clock"`, and start the service in a startup handler; use `fastapi.testclient.TestClient` as a context manager so startup and shutdown run, and `client.websocket_connect("/clock/ws")` for the socket test.
- Time handling: `t` is a tz-aware UTC `datetime` internally; ISO strings only at the API boundary via `flood.timegrid.to_iso` and `parse_iso`. `tick(dt_wall_s)` is a pure method so it can be unit tested without sleeping.
- Acceptance criteria are the definition of done. Run pytest until green. If a criterion cannot be met, keep the test, mark it xfail with a reason, and record it under Not done.
- Finish: run `.venv\Scripts\python.exe -m pytest -q` and paste the output into changes.md under "How to verify".

Work order: `clock/service.py` with unit tests for `state`, `set`, `reset`, `tick`, clamping, and validation; `api/clock.py` router; the REST and WebSocket tests.
