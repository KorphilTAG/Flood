"""Tests for stage timing logger."""
from __future__ import annotations

import json
import logging
import time
from flood.timing import StageTimer


def test_stage_timer_as_ms() -> None:
    with StageTimer() as st:
        with st.stage("routing"):
            time.sleep(0.01)
        with st.stage("mapping"):
            time.sleep(0.01)

    timings = st.as_ms()
    assert "routing" in timings
    assert "mapping" in timings
    assert "total" in timings
    assert timings["routing"] >= 5
    assert timings["mapping"] >= 5
    assert timings["total"] >= timings["routing"] + timings["mapping"]


def test_stage_timer_log() -> None:
    logger = logging.getLogger("test_timing")
    logs: list[str] = []

    class Handler(logging.Handler):
        def emit(self, record):
            logs.append(record.getMessage())

    handler = Handler()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    st = StageTimer()
    with st.stage("step1"):
        pass
    log_str = st.log(logger, scenario="test")

    payload = json.loads(log_str)
    assert payload["event"] == "timing"
    assert "stages_ms" in payload
    assert payload["scenario"] == "test"
    assert len(logs) == 1
