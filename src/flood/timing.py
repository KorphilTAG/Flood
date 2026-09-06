"""Stage timer emitting structured JSON timing logs."""
from __future__ import annotations

from contextlib import contextmanager
import json
import logging
import time
from typing import Any


class StageTimer:
    """Stage timer context manager.

    Example:
        with StageTimer() as st:
            with st.stage("routing"):
                ...
            print(st.as_ms())  # {"routing": 8, "total": 183}
    """

    def __init__(self) -> None:
        self._start = time.perf_counter()
        self._stages: dict[str, float] = {}

    def __enter__(self) -> "StageTimer":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    @contextmanager
    def stage(self, name: str):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            dt = time.perf_counter() - t0
            self._stages[name] = self._stages.get(name, 0.0) + dt

    def as_ms(self) -> dict[str, int]:
        total_ms = round((time.perf_counter() - self._start) * 1000)
        res = {k: round(v * 1000) for k, v in self._stages.items()}
        res["total"] = total_ms
        return res

    def log(self, logger: logging.Logger, **extra: Any) -> str:
        payload = {
            "event": "timing",
            "stages_ms": self.as_ms(),
            **extra,
        }
        line = json.dumps(payload)
        logger.info(line)
        return line
