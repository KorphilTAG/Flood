"""Tests for replay ClockService and API router."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import time
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from flood.api.clock import make_clock_router
from flood.clock.service import ClockService
from flood.timegrid import parse_iso, to_iso

START_ISO = "2025-07-03T12:00:00Z"
END_ISO = "2025-07-05T12:00:00Z"


def test_clock_initial_state_default() -> None:
    """ClockService starts paused at record_start when t is None."""
    service = ClockService(START_ISO, END_ISO)
    st = service.state()
    assert set(st.keys()) == {"mode", "t", "speed", "playing", "record_start", "record_end"}
    assert st["mode"] == "replay"
    assert st["t"] == START_ISO
    assert st["speed"] == 60.0
    assert st["playing"] is False
    assert st["record_start"] == START_ISO
    assert st["record_end"] == END_ISO

    # Test property accessors
    assert service.mode == "replay"
    assert service.t == parse_iso(START_ISO)
    assert service.speed == 60.0
    assert service.playing is False
    assert service.record_start == parse_iso(START_ISO)
    assert service.record_end == parse_iso(END_ISO)


def test_clock_initial_state_custom() -> None:
    """ClockService accepts custom t and speed."""
    t_custom = "2025-07-04T00:00:00Z"
    service = ClockService(
        record_start=parse_iso(START_ISO),
        record_end=parse_iso(END_ISO),
        t=t_custom,
        speed=120.0,
    )
    st = service.state()
    assert st["t"] == t_custom
    assert st["speed"] == 120.0
    assert st["playing"] is False


def test_clock_set_and_reset() -> None:
    """set updates subsets and reset restores record_start with speed unchanged."""
    service = ClockService(START_ISO, END_ISO)
    # Update speed only
    st1 = service.set(speed=300.0)
    assert st1["speed"] == 300.0
    assert st1["t"] == START_ISO
    assert st1["playing"] is False

    # Update playing only
    st2 = service.set(playing=True)
    assert st2["playing"] is True
    assert st2["speed"] == 300.0

    # Update t only
    t_mid = "2025-07-04T06:00:00Z"
    st3 = service.set(t=t_mid)
    assert st3["t"] == t_mid
    assert st3["playing"] is True
    assert st3["speed"] == 300.0

    # Reset
    st_reset = service.reset()
    assert st_reset["t"] == START_ISO
    assert st_reset["playing"] is False
    assert st_reset["speed"] == 300.0


def test_clock_clamping_and_snapping() -> None:
    """t is clamped to record bounds and snapped to whole seconds."""
    service = ClockService(START_ISO, END_ISO)

    # Before record_start clamps to record_start
    st = service.set(t="2025-07-01T00:00:00Z")
    assert st["t"] == START_ISO

    # After record_end clamps to record_end
    st = service.set(t="2025-07-10T00:00:00Z")
    assert st["t"] == END_ISO

    # Setting playing=True at record_end leaves it paused
    st = service.set(t=END_ISO, playing=True)
    assert st["playing"] is False

    # Calling set(playing=True) when already at record_end leaves it paused
    st = service.set(playing=True)
    assert st["playing"] is False

    # Snapping whole seconds (<0.5s down, >=0.5s up)
    base_dt = parse_iso("2025-07-04T12:00:00Z")
    dt_down = base_dt + timedelta(microseconds=400_000)
    dt_up = base_dt + timedelta(microseconds=600_000)

    service.set(t=dt_down)
    assert service.t == base_dt

    service.set(t=dt_up)
    assert service.t == base_dt + timedelta(seconds=1)


def test_clock_validation() -> None:
    """Invalid arguments raise ValueError."""
    service = ClockService(START_ISO, END_ISO)

    # Speed out of bounds
    with pytest.raises(ValueError):
        service.set(speed=0.05)
    with pytest.raises(ValueError):
        service.set(speed=3601.0)
    with pytest.raises(ValueError):
        service.set(speed="fast")  # type: ignore
    with pytest.raises(ValueError):
        service.set(speed=True)  # type: ignore

    # Playing not boolean
    with pytest.raises(ValueError):
        service.set(playing="true")  # type: ignore
    with pytest.raises(ValueError):
        service.set(playing=1)  # type: ignore

    # Invalid timestamp
    with pytest.raises(ValueError):
        service.set(t="invalid-iso")
    with pytest.raises(ValueError):
        service.set(t=datetime.now())  # naive datetime

    # Constructor validation
    with pytest.raises(ValueError):
        ClockService(END_ISO, START_ISO)  # start > end
    with pytest.raises(ValueError):
        ClockService(START_ISO, END_ISO, speed=0.0)


def test_clock_tick_advances_and_clamps() -> None:
    """tick(dt_wall_s) advances t by speed * dt_wall_s while playing and clamps at record_end."""
    service = ClockService(START_ISO, END_ISO, speed=60.0)

    # When paused, tick does not advance t
    assert service.playing is False
    service.tick(1.0)
    assert service.state()["t"] == START_ISO

    # When playing, speed=60, tick(1.0) advances 60 seconds
    service.set(playing=True)
    service.tick(1.0)
    expected_t = to_iso(parse_iso(START_ISO) + timedelta(seconds=60))
    assert service.state()["t"] == expected_t

    # Tick past record_end clamps and sets playing=False
    almost_end = parse_iso(END_ISO) - timedelta(seconds=30)
    service.set(t=almost_end, playing=True)
    service.tick(1.0)  # at speed=60, would advance 60s, exceeding 30s remaining
    assert service.state()["t"] == END_ISO
    assert service.playing is False


def test_clock_subscribers() -> None:
    """subscribe receives broadcasts immediately on set and reset, and drops on full."""
    service = ClockService(START_ISO, END_ISO)
    q = service.subscribe(maxsize=2)

    # set broadcasts
    service.set(speed=120.0)
    msg1 = q.get_nowait()
    assert msg1["speed"] == 120.0

    # reset broadcasts
    service.reset()
    msg2 = q.get_nowait()
    assert msg2["t"] == START_ISO

    # Queue full handling drops subscriber
    q.put_nowait({"dummy": 1})
    q.put_nowait({"dummy": 2})
    assert q.full()
    # Next broadcast should drop q
    service.set(speed=200.0)
    assert q not in service._subscribers

    # Unsubscribe
    q2 = service.subscribe()
    assert q2 in service._subscribers
    service.unsubscribe(q2)
    assert q2 not in service._subscribers


@pytest.mark.asyncio
async def test_clock_task_start_stop() -> None:
    """start() spawns task and stop() cancels it cleanly."""
    service = ClockService(START_ISO, END_ISO)
    assert service._task is None

    service.start()
    assert service._task is not None
    assert not service._task.done()

    # Calling start again is idempotent
    task_ref = service._task
    service.start()
    assert service._task is task_ref

    service.stop()
    assert service._task is None
    await asyncio.sleep(0.01)
    assert task_ref.cancelled() or task_ref.done()


@pytest.mark.asyncio
async def test_clock_run_loop_ticks_and_broadcasts() -> None:
    """_run task ticks elapsed and broadcasts state while playing."""
    service = ClockService(START_ISO, END_ISO, speed=60.0)
    q = service.subscribe()
    service.start()

    # Set playing=True
    service.set(playing=True)
    # Drain set broadcast
    set_msg = q.get_nowait()
    assert set_msg["playing"] is True

    # Wait for the _run task loop (sleep 1.0) to tick and broadcast
    tick_msg = await asyncio.wait_for(q.get(), timeout=2.5)
    assert tick_msg["playing"] is True
    t_after = parse_iso(tick_msg["t"])
    t_before = parse_iso(START_ISO)
    elapsed_sim = (t_after - t_before).total_seconds()
    assert 50.0 <= elapsed_sim <= 75.0

    service.stop()


def _create_test_app(service: ClockService) -> FastAPI:
    """Create a FastAPI app mounting the clock router with prefix /clock and lifespan lifecycle."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        service.start()
        yield
        service.stop()

    app = FastAPI(lifespan=lifespan)
    router = make_clock_router(service)
    app.include_router(router, prefix="/clock")
    return app


def test_router_rest_endpoints() -> None:
    """Test GET /clock, POST /clock, and POST /clock/reset."""
    service = ClockService(START_ISO, END_ISO, speed=60.0)
    app = _create_test_app(service)

    with TestClient(app) as client:
        # GET /clock
        res_get = client.get("/clock")
        assert res_get.status_code == 200
        data = res_get.json()
        assert data["t"] == START_ISO
        assert data["speed"] == 60.0
        assert data["playing"] is False

        # POST /clock valid subsets
        res_post1 = client.post("/clock", json={"speed": 100})
        assert res_post1.status_code == 200
        assert res_post1.json()["speed"] == 100.0

        res_post2 = client.post("/clock", json={"playing": True})
        assert res_post2.status_code == 200
        assert res_post2.json()["playing"] is True

        new_t = "2025-07-04T00:00:00Z"
        res_post3 = client.post("/clock", json={"t": new_t})
        assert res_post3.status_code == 200
        assert res_post3.json()["t"] == new_t

        # POST /clock empty body
        res_empty = client.post("/clock", json={})
        assert res_empty.status_code == 200

        # POST /clock invalid inputs return 400 invalid_clock
        res_err_speed = client.post("/clock", json={"speed": 0.05})
        assert res_err_speed.status_code == 400
        assert res_err_speed.json()["error"]["code"] == "invalid_clock"

        res_err_t = client.post("/clock", json={"t": "invalid-iso"})
        assert res_err_t.status_code == 400
        assert res_err_t.json()["error"]["code"] == "invalid_clock"

        res_err_unknown = client.post("/clock", json={"horizon": 120})
        assert res_err_unknown.status_code == 400
        assert res_err_unknown.json()["error"]["code"] == "invalid_clock"

        # POST /clock/reset
        res_reset = client.post("/clock/reset")
        assert res_reset.status_code == 200
        reset_data = res_reset.json()
        assert reset_data["t"] == START_ISO
        assert reset_data["playing"] is False
        assert reset_data["speed"] == 100.0


def test_router_websocket_push_and_interaction() -> None:
    """Test WebSocket /clock/ws initial state, POST trigger broadcast, and WS commands."""
    service = ClockService(START_ISO, END_ISO, speed=60.0)
    app = _create_test_app(service)

    with TestClient(app) as client:
        with client.websocket_connect("/clock/ws") as ws:
            # Connect: receive initial state
            init_state = ws.receive_json()
            assert init_state["t"] == START_ISO
            assert init_state["speed"] == 60.0
            assert init_state["playing"] is False

            # AC 6: POST /clock with {"t": ...}, receive updated state on socket within 1 second
            target_t = "2025-07-04T00:00:00Z"
            t_start = time.time()
            post_res = client.post("/clock", json={"t": target_t})
            assert post_res.status_code == 200

            ws_msg = ws.receive_json()
            assert time.time() - t_start < 1.0
            assert ws_msg["t"] == target_t

            # Send valid message directly over WebSocket
            ws.send_json({"speed": 120.0})
            ws_speed_msg = ws.receive_json()
            assert ws_speed_msg["speed"] == 120.0

            # Send invalid message directly over WebSocket
            ws.send_json({"speed": -5.0})
            ws_err_msg = ws.receive_json()
            assert ws_err_msg["error"]["code"] == "invalid_clock"
