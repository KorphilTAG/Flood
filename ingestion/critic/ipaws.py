"""Safe, attribute-only query tool over FEMA's public IPAWS Archive ArcGIS
REST table (`IPAWS_ARCHIVE_EVENTS`, MapServer layer/table id 1) -- historical
CAP alert records (who alerted whom, when, with what message), for a human
curator to use directly when gathering facts to ground a critic claim about
actual alert timing/content during a historical event.

This is a plain Python module wrapped in a LangChain `BaseTool` shape for
interface consistency with `lib/langchain_tools.py`'s existing tool
convention, invoked directly (`.invoke({...})` or the CLI script at
`scripts/query_ipaws_alerts.py`), never through an `AgentExecutor` and never
bound to a chat model. It lives here, in `ingestion/critic/`, rather than in
`ingestion/lib/`, because its only real consumer is the critic/curator
workflow -- see `pipeline/features/ipaws-alert-tool/spec.md`'s Approach
section for the full reasoning, including why the existing
`lib/geo.py::query_arcgis_feature_server` / `lib/langchain_tools.py`
wrapper is not reused (it requires a `boundary_geojson` polygon and
unconditionally sends `geometry`/`geometryType`/`spatialRel`, but
`IPAWS_ARCHIVE_EVENTS` is a non-spatial ArcGIS *table* with no geometry
field at all).

**Safety: structured inputs only, never a raw `where` string.** Every
parameter that reaches the SQL-like `where` clause is one of: a
strictly-validated `YYYY-MM-DD` date, a substring matched via `LIKE` with
embedded single quotes doubled, or a fixed status string. No function in
this module accepts a raw, pass-through `where` string.

**Retention caveat (do not restate the service's stale "6-Month" claim).**
This service's own `serviceDescription` metadata claims "latest 6-Month"
retention with a 24-hour publish delay. That claim has been directly
verified as stale/inaccurate: `MIN(sent)` across the table is 2020-11-01,
and `MAX(sent)` was 2026-09-04 when checked on 2026-09-05 -- a multi-year
rolling archive, not six months. Nothing in this module should repeat the
"6-month" claim as fact, and nothing here asserts this is a guaranteed
permanent archive either -- FEMA could change or prune retention at any
time without updating that description, and this tool's output should not
be relied on as a durable system of record.
"""
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Type

import requests
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field, field_validator

IPAWS_ARCHIVE_MAPSERVER_URL = (
    "https://gis.fema.gov/arcgis/rest/services/FEMA/IPAWS_Archive/MapServer"
)
IPAWS_ARCHIVE_EVENTS_URL = f"{IPAWS_ARCHIVE_MAPSERVER_URL}/1/query"

# Confirmed live against `.../MapServer/1?f=json`: this table's maxRecordCount.
MAX_RECORD_COUNT = 2000

# The practically useful field subset (confirmed live against the service),
# not the full raw schema (which also carries `xmlns`, `restriction`,
# `resource_*`, `references_*`, `area_altitude`/`ceiling`, etc.). `outFields`
# below is always this fixed list, never `*`.
OUT_FIELDS = [
    "identifier",
    "sent",
    "status",
    "msgtype",
    "info_event",
    "info_headline",
    "info_description",
    "info_instruction",
    "info_sendername",
    "info_area_areadesc",
]

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _validate_date(label: str, value: str) -> None:
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ValueError(f"{label} must be a strict YYYY-MM-DD date string, got: {value!r}")
    # Also reject strings that match the pattern but are not real calendar
    # dates (e.g. 2025-13-40).
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError(f"{label} must be a valid YYYY-MM-DD date, got: {value!r}") from exc


def _escape_sql_string(value: str) -> str:
    """Double every embedded single quote so caller-supplied text cannot
    terminate a `LIKE '%...%'` string literal early.
    """
    return value.replace("'", "''")


def build_where_clause(
    start_date: str,
    end_date: str,
    area_contains: Optional[str] = None,
    event_type: Optional[str] = None,
    status: Optional[str] = "Actual",
) -> str:
    """Build a safe ArcGIS SQL `where` clause from structured inputs only.

    `start_date`/`end_date` must match strict `YYYY-MM-DD` and are rejected
    (`ValueError`) otherwise, before any string is built. `area_contains`/
    `event_type`, if given, are matched as `UPPER(...) LIKE '%...%'`
    substrings against `info_area_areadesc`/`info_event` respectively, with
    every embedded single quote escaped by doubling. `status` defaults to
    `"Actual"` (excludes FEMA/CAP `Test`/`Exercise`/`Draft`/`System` records);
    passing `status=None` omits the status filter entirely.
    """
    _validate_date("start_date", start_date)
    _validate_date("end_date", end_date)

    # `sent` is an epoch-millisecond date field; ArcGIS SQL accepts a DATE
    # literal for a date-typed column comparison. `end_date` is treated as
    # inclusive of the whole calendar day, so the upper bound is computed as
    # the next calendar day (in Python, from the already-validated end_date,
    # never via SQL date arithmetic) and used as an exclusive upper bound.
    end_exclusive = (datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
    clauses = [
        f"sent >= DATE '{start_date}'",
        f"sent < DATE '{end_exclusive}'",
    ]

    if area_contains:
        escaped = _escape_sql_string(area_contains)
        clauses.append(f"UPPER(info_area_areadesc) LIKE UPPER('%{escaped}%')")

    if event_type:
        escaped = _escape_sql_string(event_type)
        clauses.append(f"UPPER(info_event) LIKE UPPER('%{escaped}%')")

    if status is not None:
        escaped_status = _escape_sql_string(status)
        clauses.append(f"status = '{escaped_status}'")

    return " AND ".join(clauses)


def _epoch_ms_to_iso8601(epoch_ms) -> Optional[str]:
    if epoch_ms is None:
        return None
    return (
        datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _project_record(raw_attrs: dict) -> dict:
    record = {field: raw_attrs.get(field) for field in OUT_FIELDS}
    record["sent"] = _epoch_ms_to_iso8601(raw_attrs.get("sent"))
    return record


def query_ipaws_alerts(
    start_date: str,
    end_date: str,
    area_contains: Optional[str] = None,
    event_type: Optional[str] = None,
    status: Optional[str] = "Actual",
    max_records: int = 2000,
    base_url: str = IPAWS_ARCHIVE_EVENTS_URL,
    session=None,
) -> List[dict]:
    """Query `.../MapServer/1/query` for IPAWS alert records matching the
    given structured filters, paginating with `resultOffset`/
    `resultRecordCount` while a page returns a full page's worth of rows
    (this service's confirmed cap is 2000 rows per request), stopping when a
    page returns fewer rows than requested or when `max_records` is reached.

    Returns only the fixed ten-field projection in `OUT_FIELDS`, with `sent`
    converted from an ArcGIS epoch-millisecond integer to an ISO-8601 UTC
    string.
    """
    where = build_where_clause(start_date, end_date, area_contains, event_type, status)
    http = session or requests

    results: List[dict] = []
    offset = 0
    while len(results) < max_records:
        page_size = min(MAX_RECORD_COUNT, max_records - len(results))
        params = {
            "where": where,
            "outFields": ",".join(OUT_FIELDS),
            "f": "json",
            "resultOffset": offset,
            "resultRecordCount": page_size,
        }
        resp = http.get(base_url, params=params, timeout=60)
        resp.raise_for_status()
        payload = resp.json()
        features = payload.get("features", [])

        page_records = [_project_record(f.get("attributes", {})) for f in features]
        results.extend(page_records)

        if len(features) < page_size:
            break
        offset += len(features)

    return results[:max_records]


def count_ipaws_alerts(
    start_date: str,
    end_date: str,
    area_contains: Optional[str] = None,
    event_type: Optional[str] = None,
    status: Optional[str] = "Actual",
    base_url: str = IPAWS_ARCHIVE_EVENTS_URL,
    session=None,
) -> int:
    """Return the integer count of IPAWS alert records matching the given
    structured filters (`returnCountOnly=true`), built from the same
    `build_where_clause` function `query_ipaws_alerts` uses. Useful for a
    curator to check whether a query is empty before pulling records.
    """
    where = build_where_clause(start_date, end_date, area_contains, event_type, status)
    http = session or requests

    params = {
        "where": where,
        "returnCountOnly": "true",
        "f": "json",
    }
    resp = http.get(base_url, params=params, timeout=60)
    resp.raise_for_status()
    payload = resp.json()
    return int(payload["count"])


class IpawsAlertQueryInput(BaseModel):
    start_date: str = Field(..., description="Strict YYYY-MM-DD start of the date range (inclusive)")
    end_date: str = Field(..., description="Strict YYYY-MM-DD end of the date range (inclusive)")
    area_contains: Optional[str] = Field(
        None, description="Substring to match against info_area_areadesc (e.g. a county name)"
    )
    event_type: Optional[str] = Field(
        None, description="Substring to match against info_event (e.g. 'Flash Flood Warning')"
    )
    status: Optional[str] = Field(
        "Actual", description="CAP status filter; defaults to 'Actual'. Pass null to omit the filter."
    )
    max_records: int = Field(2000, description="Maximum rows to return across all pages")

    @field_validator("start_date", "end_date")
    @classmethod
    def _validate_strict_date(cls, value: str) -> str:
        # Reuses the same strict YYYY-MM-DD check `build_where_clause` uses,
        # so an invalid date is rejected at input-validation time (a Pydantic
        # `ValidationError`, since Pydantic wraps a `ValueError` raised inside
        # a field validator) -- before `_run`/`query_ipaws_alerts` is ever
        # reached, and therefore before any network call.
        _validate_date("date", value)
        return value


class IpawsAlertQueryTool(BaseTool):
    """Wraps `query_ipaws_alerts` -- a safe, attribute-only query over the
    FEMA IPAWS Archive's non-spatial alert-record table. Invoked directly
    (`.invoke({...})`) by a curator or script, never through an
    `AgentExecutor` and never bound to a chat model.
    """

    name: str = "ipaws_alert_query"
    description: str = (
        "Query FEMA's public IPAWS Archive for historical CAP alert records "
        "(who alerted whom, when, with what message) filtered by date range "
        "and, optionally, area/event-type substrings."
    )
    args_schema: Type[BaseModel] = IpawsAlertQueryInput

    def _run(
        self,
        start_date: str,
        end_date: str,
        area_contains: Optional[str] = None,
        event_type: Optional[str] = None,
        status: Optional[str] = "Actual",
        max_records: int = 2000,
    ) -> List[dict]:
        return query_ipaws_alerts(
            start_date=start_date,
            end_date=end_date,
            area_contains=area_contains,
            event_type=event_type,
            status=status,
            max_records=max_records,
        )
