"""Offline tests for `critic/ipaws.py`: where-clause date validation and
quote-escaping, default/omitted status filter, field projection + date
conversion, pagination behavior and the `max_records` cap, and
`IpawsAlertQueryTool` input validation gating.

Every HTTP call is mocked -- no real network access, no API key.
"""
import pytest
from pydantic import ValidationError

from critic.ipaws import (
    IpawsAlertQueryTool,
    OUT_FIELDS,
    build_where_clause,
    count_ipaws_alerts,
    query_ipaws_alerts,
)


# --- build_where_clause: date validation ------------------------------------


@pytest.mark.parametrize(
    "start_date,end_date",
    [
        ("2025-7-3", "2025-07-05"),       # not zero-padded
        ("07-03-2025", "2025-07-05"),      # wrong order
        ("2025/07/03", "2025-07-05"),      # wrong separator
        ("2025-07-03", "not-a-date"),
        ("", "2025-07-05"),
        ("2025-13-40", "2025-07-05"),      # matches pattern, not a real date
    ],
)
def test_build_where_clause_rejects_invalid_dates(start_date, end_date):
    with pytest.raises(ValueError):
        build_where_clause(start_date, end_date)


def test_build_where_clause_accepts_valid_dates():
    clause = build_where_clause("2025-07-03", "2025-07-05")
    assert "2025-07-03" in clause
    assert isinstance(clause, str)


# --- build_where_clause: quote escaping / injection resistance -------------


def test_build_where_clause_escapes_single_quotes_in_area_contains():
    injection = "Kerr' OR '1'='1"
    clause = build_where_clause("2025-07-03", "2025-07-05", area_contains=injection)

    # The single quote must be doubled, not passed through raw.
    assert "Kerr'' OR ''1''=''1" in clause
    # The raw, unescaped injection string must never appear verbatim.
    assert injection not in clause
    # The LIKE literal must still be properly terminated (an even number of
    # quote characters within the constructed LIKE segment).
    like_segment = clause.split("LIKE")[1]
    assert like_segment.count("'") % 2 == 0


def test_build_where_clause_escapes_single_quotes_in_event_type():
    injection = "Flood' OR '1'='1"
    clause = build_where_clause("2025-07-03", "2025-07-05", event_type=injection)
    assert "Flood'' OR ''1''=''1" in clause
    assert injection not in clause


# --- build_where_clause: no raw pass-through where string -------------------


def test_no_function_accepts_raw_where_string():
    import inspect

    import critic.ipaws as ipaws_module

    for fn in (
        ipaws_module.build_where_clause,
        ipaws_module.query_ipaws_alerts,
        ipaws_module.count_ipaws_alerts,
    ):
        params = inspect.signature(fn).parameters
        assert "where" not in params


# --- build_where_clause: status default / omission --------------------------


def test_build_where_clause_default_status_is_actual():
    clause = build_where_clause("2025-07-03", "2025-07-05")
    assert "status = 'Actual'" in clause


def test_build_where_clause_status_none_omits_status_filter():
    clause = build_where_clause("2025-07-03", "2025-07-05", status=None)
    assert "status" not in clause


# --- query_ipaws_alerts: field projection + date conversion ----------------


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _raw_attrs(identifier: str, sent_ms: int = 1751500800000, **extra):
    attrs = {
        "identifier": identifier,
        "sent": sent_ms,
        "status": "Actual",
        "msgtype": "Alert",
        "info_event": "Flash Flood Warning",
        "info_headline": "Flash Flood Warning issued",
        "info_description": "A flash flood warning has been issued.",
        "info_instruction": "Move to higher ground.",
        "info_sendername": "NWS Austin/San Antonio",
        "info_area_areadesc": "Kerr County",
        # extra raw fields not in OUT_FIELDS -- must never leak through
        "xmlns": "urn:oasis:names:tc:emergency:cap:1.2",
        "resource_uri": "https://example.invalid/resource",
    }
    attrs.update(extra)
    return attrs


def test_query_ipaws_alerts_returns_only_documented_fields_and_converts_sent(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params, timeout))
        return FakeResponse(
            {"features": [{"attributes": _raw_attrs("id-1", sent_ms=1751500800000)}]}
        )

    monkeypatch.setattr("critic.ipaws.requests.get", fake_get)

    records = query_ipaws_alerts("2025-07-03", "2025-07-05")

    assert len(records) == 1
    record = records[0]
    assert set(record.keys()) == set(OUT_FIELDS)
    assert "xmlns" not in record
    assert "resource_uri" not in record
    # sent must be ISO-8601, not the raw epoch-millisecond integer.
    assert record["sent"] == "2025-07-03T00:00:00Z"
    assert isinstance(record["sent"], str)


def test_query_ipaws_alerts_sends_expected_request_params(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params, timeout))
        return FakeResponse({"features": []})

    monkeypatch.setattr("critic.ipaws.requests.get", fake_get)

    query_ipaws_alerts("2025-07-03", "2025-07-05", area_contains="Kerr")

    assert len(calls) == 1
    url, params, _timeout = calls[0]
    assert url.endswith("/MapServer/1/query")
    assert params["f"] == "json"
    assert params["outFields"] == ",".join(OUT_FIELDS)
    assert "Kerr" in params["where"]
    assert params["resultOffset"] == 0


# --- query_ipaws_alerts: pagination ------------------------------------------


def test_query_ipaws_alerts_combines_full_page_and_partial_page(monkeypatch):
    monkeypatch.setattr("critic.ipaws.MAX_RECORD_COUNT", 2)

    pages = [
        {"features": [{"attributes": _raw_attrs("id-1")}, {"attributes": _raw_attrs("id-2")}]},
        {"features": [{"attributes": _raw_attrs("id-3")}]},
    ]
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return FakeResponse(pages[len(calls) - 1])

    monkeypatch.setattr("critic.ipaws.requests.get", fake_get)

    records = query_ipaws_alerts("2025-07-03", "2025-07-05", max_records=100)

    assert [r["identifier"] for r in records] == ["id-1", "id-2", "id-3"]
    assert len(calls) == 2
    assert calls[0]["resultOffset"] == 0
    assert calls[1]["resultOffset"] == 2


def test_query_ipaws_alerts_max_records_cap_stops_pagination(monkeypatch):
    monkeypatch.setattr("critic.ipaws.MAX_RECORD_COUNT", 2)

    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        # Always return a full page -- an endless supply of rows, to prove
        # the cap (not exhaustion of data) is what stops pagination.
        return FakeResponse(
            {"features": [{"attributes": _raw_attrs("id-a")}, {"attributes": _raw_attrs("id-b")}]}
        )

    monkeypatch.setattr("critic.ipaws.requests.get", fake_get)

    records = query_ipaws_alerts("2025-07-03", "2025-07-05", max_records=3)

    assert len(records) == 3
    # First page of 2 (full), second page requested at size 1 (remaining cap).
    assert len(calls) == 2
    assert calls[1]["resultRecordCount"] == 1


# --- count_ipaws_alerts -------------------------------------------------------


def test_count_ipaws_alerts_uses_return_count_only_and_shared_where_clause(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return FakeResponse({"count": 41})

    monkeypatch.setattr("critic.ipaws.requests.get", fake_get)

    result = count_ipaws_alerts("2025-07-03", "2025-07-05", area_contains="Kerr")

    assert result == 41
    assert isinstance(result, int)
    assert len(calls) == 1
    params = calls[0]
    assert params["returnCountOnly"] == "true"
    expected_where = build_where_clause("2025-07-03", "2025-07-05", area_contains="Kerr")
    assert params["where"] == expected_where


# --- IpawsAlertQueryTool -------------------------------------------------------


def test_ipaws_alert_query_tool_valid_input_reaches_mocked_http_call(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(params)
        return FakeResponse({"features": [{"attributes": _raw_attrs("id-1")}]})

    monkeypatch.setattr("critic.ipaws.requests.get", fake_get)

    result = IpawsAlertQueryTool().invoke(
        {"start_date": "2025-07-03", "end_date": "2025-07-05", "area_contains": "Kerr"}
    )

    assert len(calls) == 1
    params = calls[0]
    assert "Kerr" in params["where"]
    assert params["outFields"] == ",".join(OUT_FIELDS)
    assert params["resultOffset"] == 0

    direct_result = query_ipaws_alerts("2025-07-03", "2025-07-05", area_contains="Kerr")
    assert result == direct_result


def test_ipaws_alert_query_tool_rejects_invalid_input_before_network_call(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "critic.ipaws.requests.get",
        lambda *a, **k: calls.append((a, k)),
    )

    with pytest.raises(ValidationError):
        IpawsAlertQueryTool().invoke({"start_date": "not-a-date", "end_date": "2025-07-05"})

    assert calls == []


def test_ipaws_alert_query_tool_rejects_missing_required_input(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "critic.ipaws.requests.get",
        lambda *a, **k: calls.append((a, k)),
    )

    with pytest.raises(ValidationError):
        IpawsAlertQueryTool().invoke({"start_date": "2025-07-03"})

    assert calls == []
