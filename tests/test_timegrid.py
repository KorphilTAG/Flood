"""Acceptance tests for time grid functions."""
from __future__ import annotations

from datetime import datetime, timezone
import pytest
from flood.interfaces import TimeGridError
from flood.timegrid import (
    check_pair,
    from_compact,
    grid_range,
    parse_iso,
    snap_p,
    snap_t,
    to_compact,
    to_iso,
)


def test_snapping_exact_cases() -> None:
    # 06:07:30Z -> snap_p is 06:05:00Z, snap_t is 06:10:00Z
    dt1 = datetime(2025, 7, 4, 6, 7, 30, tzinfo=timezone.utc)
    assert snap_p(dt1) == datetime(2025, 7, 4, 6, 5, 0, tzinfo=timezone.utc)
    assert snap_t(dt1) == datetime(2025, 7, 4, 6, 10, 0, tzinfo=timezone.utc)

    # 06:07:29Z -> snap_t is 06:05:00Z
    dt2 = datetime(2025, 7, 4, 6, 7, 29, tzinfo=timezone.utc)
    assert snap_t(dt2) == datetime(2025, 7, 4, 6, 5, 0, tzinfo=timezone.utc)


def test_compact_format() -> None:
    dt = datetime(2025, 7, 4, 6, 14, 0, tzinfo=timezone.utc)
    assert to_compact(dt) == "20250704T0614Z"


def test_round_trips() -> None:
    dt = datetime(2025, 7, 4, 6, 14, 0, tzinfo=timezone.utc)
    # Compact round-trip
    assert from_compact(to_compact(dt)) == dt
    # ISO round-trip
    assert parse_iso(to_iso(dt)) == dt


def test_check_pair_error_codes() -> None:
    rec_start = datetime(2025, 7, 4, 0, 0, 0, tzinfo=timezone.utc)
    rec_end = datetime(2025, 7, 4, 12, 0, 0, tzinfo=timezone.utc)
    max_h = 360  # 6 hours

    # 1. outside_record: p < record_start
    p_early = datetime(2025, 7, 3, 23, 55, 0, tzinfo=timezone.utc)
    t_ok = datetime(2025, 7, 4, 1, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(TimeGridError) as exc:
        check_pair(p_early, t_ok, rec_start, rec_end, max_h)
    assert exc.value.code == "outside_record"

    # 1b. outside_record: t > record_end
    p_ok = datetime(2025, 7, 4, 6, 0, 0, tzinfo=timezone.utc)
    t_late = datetime(2025, 7, 4, 12, 5, 0, tzinfo=timezone.utc)
    with pytest.raises(TimeGridError) as exc:
        check_pair(p_ok, t_late, rec_start, rec_end, max_h)
    assert exc.value.code == "outside_record"

    # 2. t_before_p
    p_now = datetime(2025, 7, 4, 6, 0, 0, tzinfo=timezone.utc)
    t_prev = datetime(2025, 7, 4, 5, 55, 0, tzinfo=timezone.utc)
    with pytest.raises(TimeGridError) as exc:
        check_pair(p_now, t_prev, rec_start, rec_end, max_h)
    assert exc.value.code == "t_before_p"

    # 3. horizon_exceeded
    p_start = datetime(2025, 7, 4, 2, 0, 0, tzinfo=timezone.utc)
    t_far = datetime(2025, 7, 4, 8, 5, 0, tzinfo=timezone.utc)  # 365 min > 360 min
    with pytest.raises(TimeGridError) as exc:
        check_pair(p_start, t_far, rec_start, rec_end, max_h)
    assert exc.value.code == "horizon_exceeded"

    # Valid pair
    t_valid = datetime(2025, 7, 4, 8, 0, 0, tzinfo=timezone.utc)  # exactly 360 min
    check_pair(p_start, t_valid, rec_start, rec_end, max_h)


def test_grid_range() -> None:
    t0 = datetime(2025, 7, 4, 6, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2025, 7, 4, 6, 15, 0, tzinfo=timezone.utc)
    steps = grid_range(t0, t1)
    assert len(steps) == 4
    assert steps[0] == t0
    assert steps[-1] == t1
