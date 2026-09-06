"""Time grid helpers for the physics engine."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from flood.interfaces import STEP_MINUTES, TimeGridError

ISO_REGEX = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})Z$")
COMPACT_REGEX = re.compile(r"^([0-9]{8})T([0-9]{4})Z$")


def parse_iso(s: str) -> datetime:
    """Parse ISO 8601 string in contract format (YYYY-MM-DDTHH:MM:SSZ)."""
    if not isinstance(s, str) or not ISO_REGEX.match(s):
        raise ValueError(f"Invalid contract ISO timestamp: {s!r}")
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def to_iso(dt: datetime) -> str:
    """Format tz-aware UTC datetime to ISO 8601 contract string."""
    if dt.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware")
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")


def to_compact(dt: datetime) -> str:
    """Format tz-aware UTC datetime to compact path string (YYYYMMDDTHHMMZ)."""
    if dt.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware")
    dt_utc = dt.astimezone(timezone.utc)
    return dt_utc.strftime("%Y%m%dT%H%MZ")


def from_compact(s: str) -> datetime:
    """Parse compact path string (YYYYMMDDTHHMMZ) into tz-aware UTC datetime."""
    if not isinstance(s, str) or not COMPACT_REGEX.match(s):
        raise ValueError(f"Invalid compact timestamp: {s!r}")
    return datetime.strptime(s, "%Y%m%dT%H%MZ").replace(tzinfo=timezone.utc)


def snap_p(dt: datetime) -> datetime:
    """Floor tz-aware UTC datetime to 5-minute grid."""
    if dt.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware")
    dt_utc = dt.astimezone(timezone.utc)
    total_seconds = int(dt_utc.timestamp())
    rem_seconds = total_seconds % (STEP_MINUTES * 60)
    floored_seconds = total_seconds - rem_seconds
    return datetime.fromtimestamp(floored_seconds, tz=timezone.utc)


def snap_t(dt: datetime) -> datetime:
    """Round tz-aware UTC datetime to nearest 5 minutes, exact halves rounding up."""
    if dt.tzinfo is None:
        raise ValueError("Datetime must be timezone-aware")
    dt_utc = dt.astimezone(timezone.utc)
    total_seconds = int(dt_utc.timestamp())
    step_seconds = STEP_MINUTES * 60
    rem_seconds = total_seconds % step_seconds
    half_step = step_seconds // 2  # 150 seconds
    if rem_seconds >= half_step:
        rounded_seconds = total_seconds - rem_seconds + step_seconds
    else:
        rounded_seconds = total_seconds - rem_seconds
    return datetime.fromtimestamp(rounded_seconds, tz=timezone.utc)


def check_pair(
    p: datetime,
    t: datetime,
    record_start: datetime,
    record_end: datetime,
    max_horizon_minutes: int,
) -> None:
    """Validate (p, t) pair against record window and horizon.

    Raises TimeGridError with codes in order:
    1. outside_record
    2. t_before_p
    3. horizon_exceeded
    """
    if p < record_start or t > record_end or p > record_end or t < record_start:
        raise TimeGridError(
            code="outside_record",
            message=f"Query ({p}, {t}) is outside record [{record_start}, {record_end}]",
        )
    if t < p:
        raise TimeGridError(code="t_before_p", message=f"t ({t}) is before p ({p})")
    horizon_seconds = (t - p).total_seconds()
    if horizon_seconds > max_horizon_minutes * 60:
        raise TimeGridError(
            code="horizon_exceeded",
            message=f"Horizon {horizon_seconds / 60:.1f} min exceeds max {max_horizon_minutes} min",
        )


def grid_range(start: datetime, end: datetime) -> list[datetime]:
    """Return inclusive list of 5-minute grid timestamps from start to end."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("Start and end must be timezone-aware")
    curr = start.astimezone(timezone.utc)
    stop = end.astimezone(timezone.utc)
    step = timedelta(minutes=STEP_MINUTES)
    result = []
    while curr <= stop:
        result.append(curr)
        curr += step
    return result
