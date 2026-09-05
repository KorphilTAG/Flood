# Feature spec

- Slug: clock-service
- Feature: C08. Replay clock owning simulation time `t`: REST get and set, WebSocket push every wall second while playing, adjustable speed, clamped to the scenario record.
- Status: draft
- Product refs: `docs/specs/physics-engine-master.md` section 8; architecture doc 5.2; PRD 6.7 item 4; decision 0002 (the clock owns one time only).

## Problem

Every component must agree on "now". The clock is the single owner of `t`. It knows nothing about `p`, lag, or horizon; those are UI or session settings.

## In scope

- `clock/service.py`: `ClockService` state machine.
- `api/clock.py`: router with REST and WebSocket, mounted by C07 at `/clock`.
- Tests for state transitions, clamping, tick arithmetic, and WebSocket push using FastAPI's TestClient.

## Out of scope

Live mode wall-clock following (cut list). Persisting clock state. Any engine call.

## Approach

`ClockService` holds `mode`, `t`, `speed`, `playing`, `record_start`, `record_end`, and an `asyncio` task that, while playing, advances `t` by `speed` seconds per wall second and broadcasts. Subscribers are `asyncio.Queue`s. The router is a plain `APIRouter` constructed by `make_clock_router(service)`; C07 creates the service from the first scenario's record or from environment variables `FLOOD_CLOCK_START`, `FLOOD_CLOCK_END`.

## Files to change

| Path | Action (add/edit) | Why |
|---|---|---|
| `src/flood/clock/__init__.py`, `src/flood/clock/service.py` | add | State machine |
| `src/flood/api/clock.py` | add | Router factory |
| `tests/test_clock.py` | add | Tests |

## Acceptance criteria

- [ ] `ClockService(record_start, record_end, t=None, speed=60.0)` starts paused at `record_start` when `t` is None. `state() -> dict` has exactly `mode ("replay"), t (ISO), speed, playing, record_start, record_end`.
- [ ] `set(t=None, speed=None, playing=None)`: any subset; `t` snapped to whole seconds and clamped to the record; `speed` in `[0.1, 3600]` else `ValueError`; setting `playing=True` at `record_end` leaves it paused. `reset()` returns to `record_start` paused with speed unchanged. Every `set` and `reset` broadcasts immediately.
- [ ] `tick(dt_wall_s)` advances `t` by `speed * dt_wall_s` while playing, clamps at `record_end`, and sets `playing=False` on reaching it. Unit test: `speed=60`, `tick(1.0)` advances 60 seconds.
- [ ] `subscribe() -> asyncio.Queue` and `unsubscribe(q)`; `_run()` task loop uses `asyncio.sleep(1.0)` and `tick(elapsed)` with measured wall elapsed, broadcasting `state()` after each tick while playing.
- [ ] Router: `GET /clock` returns `state()`; `POST /clock` with JSON body subset of `{t, speed, playing}` applies `set` and returns the new state, 400 `{ "error": {"code": "invalid_clock", "message"} }` on `ValueError`; `POST /clock/reset`; WebSocket `/clock/ws` sends `state()` on connect and on every broadcast, and accepts the same JSON body as `POST /clock` as an incoming message.
- [ ] TestClient WebSocket test: connect, receive initial state, `POST /clock` with `{"t": ...}`, receive the updated state on the socket within 1 second.
- [ ] Timestamps use `flood.timegrid.to_iso` and `parse_iso` for the contract form.
- [ ] `pytest -q` green.

## Non-goals and constraints

- One clock instance per process. No scenario literals; record bounds are injected.
- Do not edit `api/app.py`; C07 mounts `make_clock_router`.

## Assumptions

- C07 will call `make_clock_router(ClockService(...))` and include it with prefix `/clock`.

## Open questions

- None.

## Implementer notes

- Keep `t` as a tz-aware UTC `datetime`; expose ISO strings only at the API boundary.
- Use `asyncio.get_running_loop().time()` for elapsed measurement inside `_run`.
- Broadcast with `queue.put_nowait`; drop the subscriber on `QueueFull` after logging.
