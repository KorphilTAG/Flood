"""Replay clock state machine owning simulation time t."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from flood.timegrid import parse_iso, to_iso

logger = logging.getLogger(__name__)


def _snap_to_seconds(dt: datetime) -> datetime:
    """Round tz-aware UTC datetime to nearest whole second, exact halves rounding up."""
    if dt.microsecond >= 500_000:
        return (dt + timedelta(seconds=1)).replace(microsecond=0)
    return dt.replace(microsecond=0)


def _coerce_utc_datetime(val: datetime | str, name: str) -> datetime:
    """Validate and convert input to tz-aware UTC datetime."""
    if isinstance(val, str):
        return parse_iso(val)
    if isinstance(val, datetime):
        if val.tzinfo is None:
            raise ValueError(f"{name} must be timezone-aware")
        return val.astimezone(timezone.utc)
    raise ValueError(f"{name} must be a datetime or ISO string")


class ClockService:
    """Replay clock state machine owning simulation time t."""

    def __init__(
        self,
        record_start: datetime | str,
        record_end: datetime | str,
        t: datetime | str | None = None,
        speed: float = 60.0,
    ) -> None:
        start_dt = _coerce_utc_datetime(record_start, "record_start")
        end_dt = _coerce_utc_datetime(record_end, "record_end")
        if start_dt > end_dt:
            raise ValueError(f"record_start ({start_dt}) must be <= record_end ({end_dt})")

        if isinstance(speed, bool) or not isinstance(speed, (int, float)):
            raise ValueError("speed must be a numeric value")
        if not (0.1 <= speed <= 3600.0):
            raise ValueError(f"speed {speed} not in [0.1, 3600]")

        self._mode: str = "replay"
        self._record_start: datetime = start_dt
        self._record_end: datetime = end_dt
        self._speed: float = float(speed)
        self._playing: bool = False

        if t is None:
            self._t: datetime = self._record_start
        else:
            t_dt = _coerce_utc_datetime(t, "t")
            t_dt = _snap_to_seconds(t_dt)
            if t_dt < self._record_start:
                t_dt = self._record_start
            elif t_dt > self._record_end:
                t_dt = self._record_end
            self._t = t_dt

        self._subscribers: set[asyncio.Queue] = set()
        self._task: asyncio.Task | None = None

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def t(self) -> datetime:
        return self._t

    @property
    def speed(self) -> float:
        return self._speed

    @property
    def playing(self) -> bool:
        return self._playing

    @property
    def record_start(self) -> datetime:
        return self._record_start

    @property
    def record_end(self) -> datetime:
        return self._record_end

    def state(self) -> dict[str, Any]:
        """Return clock state dictionary."""
        return {
            "mode": self._mode,
            "t": to_iso(self._t),
            "speed": self._speed,
            "playing": self._playing,
            "record_start": to_iso(self._record_start),
            "record_end": to_iso(self._record_end),
        }

    def _broadcast(self, st: dict[str, Any]) -> None:
        """Broadcast state dict to all subscriber queues, dropping any that are full."""
        dead: list[asyncio.Queue] = []
        for q in list(self._subscribers):
            try:
                q.put_nowait(st)
            except asyncio.QueueFull:
                logger.warning("Subscriber queue full; dropping subscriber")
                dead.append(q)
        for q in dead:
            self._subscribers.discard(q)

    def set(
        self,
        t: datetime | str | None = None,
        speed: float | None = None,
        playing: bool | None = None,
    ) -> dict[str, Any]:
        """Update any subset of {t, speed, playing}, snap, clamp, and broadcast."""
        new_speed = self._speed
        if speed is not None:
            if isinstance(speed, bool) or not isinstance(speed, (int, float)):
                raise ValueError("speed must be a numeric value")
            if not (0.1 <= speed <= 3600.0):
                raise ValueError(f"speed {speed} not in [0.1, 3600]")
            new_speed = float(speed)

        new_t = self._t
        if t is not None:
            t_dt = _coerce_utc_datetime(t, "t")
            t_dt = _snap_to_seconds(t_dt)
            if t_dt < self._record_start:
                t_dt = self._record_start
            elif t_dt > self._record_end:
                t_dt = self._record_end
            new_t = t_dt

        new_playing = self._playing
        if playing is not None:
            if not isinstance(playing, bool):
                raise ValueError("playing must be a boolean")
            new_playing = playing

        # Setting playing=True at record_end leaves it paused
        if new_t >= self._record_end and new_playing:
            new_playing = False

        self._speed = new_speed
        self._t = new_t
        self._playing = new_playing

        st = self.state()
        self._broadcast(st)
        return st

    def reset(self) -> dict[str, Any]:
        """Return clock to record_start paused with speed unchanged and broadcast immediately."""
        self._t = self._record_start
        self._playing = False
        st = self.state()
        self._broadcast(st)
        return st

    def tick(self, dt_wall_s: float) -> datetime:
        """Advance t by speed * dt_wall_s while playing, clamp at record_end, and pause on reaching it."""
        if not self._playing or dt_wall_s <= 0.0:
            return self._t

        advance_s = self._speed * dt_wall_s
        new_t = self._t + timedelta(seconds=advance_s)
        if new_t >= self._record_end:
            self._t = self._record_end
            self._playing = False
        else:
            self._t = new_t
        return self._t

    def subscribe(self, maxsize: int = 100) -> asyncio.Queue:
        """Subscribe to clock state broadcasts."""
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        """Unsubscribe from clock state broadcasts."""
        self._subscribers.discard(q)

    def start(self) -> None:
        """Start the background _run task on the running loop."""
        if self._task is None or self._task.done():
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self._run())

    def stop(self) -> None:
        """Cancel the background _run task."""
        if self._task is not None:
            if not self._task.done():
                self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        """Task loop: tick(elapsed) every wall second and broadcast state while playing."""
        loop = asyncio.get_running_loop()
        last_time = loop.time()
        try:
            while True:
                await asyncio.sleep(1.0)
                now = loop.time()
                elapsed = now - last_time
                last_time = now
                if self._playing:
                    self.tick(elapsed)
                    self._broadcast(self.state())
        except asyncio.CancelledError:
            pass
