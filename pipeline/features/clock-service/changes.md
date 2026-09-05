# Changes

- Slug: clock-service
- Spec: `pipeline/features/clock-service/spec.md`
- Status: done

## Summary

Implemented C08 replay clock owning simulation time `t`:
- `ClockService`: State machine tracking mode ("replay"), simulation time `t` (tz-aware UTC datetime), speed (`[0.1, 3600]`), playing state, and record boundaries (`record_start`, `record_end`).
- Methods: `state()` returning contract dictionary, `set(t, speed, playing)` updating any subset with whole-second snapping and clamping, `reset()` reverting to `record_start` paused with speed unchanged, `tick(dt_wall_s)` pure simulation time advancement, `subscribe()` / `unsubscribe()` with subscriber queues, and `start()` / `stop()` controlling the background asyncio task running `_run()` that advances simulation time by wall elapsed and broadcasts state every wall second while playing.
- `make_clock_router(service)`: FastAPI APIRouter exposing `GET ""` (mounted as `/clock`), `POST ""` with subset of `{t, speed, playing}` and 400 error handling, `POST "/reset"`, and WebSocket `"/ws"` sending initial state on connect, broadcasting state updates, and accepting JSON commands.
- Tests in `tests/test_clock.py`: Unit and integration tests covering initial state, state transitions, clamping, snapping, validation, pure tick arithmetic, task lifecycle, REST endpoints, and WebSocket push with `TestClient`.

## Files touched

| Path | Change | Why |
|---|---|---|
| `src/flood/clock/__init__.py` | add | Clock package exports ClockService |
| `src/flood/clock/service.py` | add | ClockService state machine |
| `src/flood/api/__init__.py` | add | API package marker |
| `src/flood/api/clock.py` | add | Router factory make_clock_router |
| `tests/test_clock.py` | add | Unit and integration tests |
| `pipeline/features/clock-service/changes.md` | add | Tracking progress and verification output |

## Acceptance criteria

| Criterion | Status (done/blocked/skipped) | Where |
|---|---|---|
| `ClockService(record_start, record_end, t=None, speed=60.0)` starts paused at `record_start` when `t` is None. `state() -> dict` has exactly `mode ("replay"), t (ISO), speed, playing, record_start, record_end` | done | `src/flood/clock/service.py`, `tests/test_clock.py::test_clock_initial_state_default` |
| `set(t=None, speed=None, playing=None)`: any subset; `t` snapped to whole seconds and clamped to the record; `speed` in `[0.1, 3600]` else `ValueError`; setting `playing=True` at `record_end` leaves it paused. `reset()` returns to `record_start` paused with speed unchanged. Every `set` and `reset` broadcasts immediately. | done | `src/flood/clock/service.py`, `tests/test_clock.py::test_clock_set_and_reset`, `tests/test_clock.py::test_clock_clamping_and_snapping` |
| `tick(dt_wall_s)` advances `t` by `speed * dt_wall_s` while playing, clamps at `record_end`, and sets `playing=False` on reaching it. Unit test: `speed=60`, `tick(1.0)` advances 60 seconds. | done | `src/flood/clock/service.py`, `tests/test_clock.py::test_clock_tick_advances_and_clamps` |
| `subscribe() -> asyncio.Queue` and `unsubscribe(q)`; `_run()` task loop uses `asyncio.sleep(1.0)` and `tick(elapsed)` with measured wall elapsed, broadcasting `state()` after each tick while playing. | done | `src/flood/clock/service.py`, `tests/test_clock.py::test_clock_subscribers`, `tests/test_clock.py::test_clock_run_loop_ticks_and_broadcasts` |
| Router: `GET /clock` returns `state()`; `POST /clock` with JSON body subset of `{t, speed, playing}` applies `set` and returns the new state, 400 `{ "error": {"code": "invalid_clock", "message"} }` on `ValueError`; `POST /clock/reset`; WebSocket `/clock/ws` sends `state()` on connect and on every broadcast, and accepts the same JSON body as `POST /clock` as an incoming message. | done | `src/flood/api/clock.py`, `tests/test_clock.py::test_router_rest_endpoints`, `tests/test_clock.py::test_router_websocket_push_and_interaction` |
| TestClient WebSocket test: connect, receive initial state, `POST /clock` with `{"t": ...}`, receive the updated state on the socket within 1 second. | done | `tests/test_clock.py::test_router_websocket_push_and_interaction` |
| Timestamps use `flood.timegrid.to_iso` and `parse_iso` for the contract form. | done | `src/flood/clock/service.py`, `src/flood/api/clock.py` |
| `pytest -q` green. | done | `.venv\Scripts\python.exe -m pytest -q` |

## How to verify

Run pytest across the suite:
```powershell
.venv\Scripts\python.exe -m pytest -q
```
Output:
```
...................................................................      [100%]
============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\splat\Desktop\Flood-hand-ingest-cube\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

.venv\Lib\site-packages\starlette\testclient.py:53
  C:\Users\splat\Desktop\Flood-hand-ingest-cube\.venv\Lib\site-packages\starlette\testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

tests/test_ingest_hand.py::test_clip_branch_tiny_geotiffs
  C:\Users\splat\Desktop\Flood-hand-ingest-cube\.venv\Lib\site-packages\rasterio\transform.py:178: PendingDeprecationWarning: Use `@` matmul instead of `*` mul operator for matrix multiplication
    return Affine.translation(west, north) * Affine.scale(xsize, -ysize)

tests/test_ingest_hand.py::test_clip_branch_tiny_geotiffs
tests/test_ingest_hand.py::test_clip_branch_tiny_geotiffs
  C:\Users\splat\Desktop\Flood-hand-ingest-cube\.venv\Lib\site-packages\rasterio\windows.py:360: PendingDeprecationWarning: Use `@` matmul instead of `*` mul operator for matrix multiplication
    x, y = transform * (window.col_off or 0.0, window.row_off or 0.0)

tests/test_ingest_hand.py::test_clip_branch_tiny_geotiffs
tests/test_ingest_hand.py::test_clip_branch_tiny_geotiffs
  C:\Users\splat\Desktop\Flood-hand-ingest-cube\.venv\Lib\site-packages\rasterio\windows.py:361: PendingDeprecationWarning: Use `@` matmul instead of `*` mul operator for matrix multiplication
    return Affine.translation(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
67 passed, 2 deselected, 7 warnings in 9.22s
```

Run test_clock.py:
```powershell
.venv\Scripts\python.exe -m pytest tests/test_clock.py -v
```
Output:
```
tests/test_clock.py::test_clock_initial_state_default PASSED             [  9%]
tests/test_clock.py::test_clock_initial_state_custom PASSED              [ 18%]
tests/test_clock.py::test_clock_set_and_reset PASSED                     [ 27%]
tests/test_clock.py::test_clock_clamping_and_snapping PASSED             [ 36%]
tests/test_clock.py::test_clock_validation PASSED                        [ 45%]
tests/test_clock.py::test_clock_tick_advances_and_clamps PASSED          [ 54%]
tests/test_clock.py::test_clock_subscribers PASSED                       [ 63%]
tests/test_clock.py::test_clock_task_start_stop PASSED                   [ 72%]
tests/test_clock.py::test_clock_run_loop_ticks_and_broadcasts PASSED     [ 81%]
tests/test_clock.py::test_router_rest_endpoints PASSED                   [ 90%]
tests/test_clock.py::test_router_websocket_push_and_interaction PASSED   [100%]
======================= 11 passed, 2 warnings in 2.41s ========================
```

## Residual risk

- Concurrent cycle C05 test `test_runtime` in `tests/test_routing.py` has a 2.0s wall clock assertion that can intermittently flap depending on host machine CPU load during test execution.
- Starlette deprecation warnings regarding `TestClient` with `httpx` and `BlockingPortal` from third-party dependencies (`fastapi`, `starlette`).

## Not done

None.
