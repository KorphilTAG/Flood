# Changes

- Slug: ipaws-alert-tool
- Spec: `pipeline/features/ipaws-alert-tool/spec.md`
- Status: done

## Summary

Added a standalone, deterministic query capability over FEMA's public
IPAWS Archive ArcGIS REST table (`IPAWS_ARCHIVE_EVENTS`, MapServer layer
id `1`): a safety-focused `build_where_clause`/`query_ipaws_alerts`/
`count_ipaws_alerts` module, a Pydantic `IpawsAlertQueryInput` + LangChain
`IpawsAlertQueryTool` wrapper, a CLI entry point for direct curator
invocation, an offline test suite mocking every HTTP call, and a new
`ingestion/README.md` section. Nothing was wired into the critic's
automatic `POST /v1/critique` flow, no `AgentExecutor`/tool-binding was
added, and no file in the spec's "do not touch" list was edited.

## Files touched

| Path | Change | Why |
|---|---|---|
| `ingestion/critic/ipaws.py` | add | Core module: `build_where_clause` (strict date validation + quote-doubling escape), `query_ipaws_alerts` (paginated, field-projected to the fixed 10-field set, epoch-ms-to-ISO8601 `sent` conversion), `count_ipaws_alerts` (shares `build_where_clause`, `returnCountOnly=true`), `IpawsAlertQueryInput` (Pydantic, with a `field_validator` reusing the same strict-date check so invalid input is rejected before `_run` is reached), `IpawsAlertQueryTool` (LangChain `BaseTool`) |
| `ingestion/scripts/query_ipaws_alerts.py` | add | CLI entry point (`python -m scripts.query_ipaws_alerts --start ... --end ... [--area] [--event-type] [--status] [--max-records] [--count-only]`), prints JSON array or integer count to stdout |
| `ingestion/tests/test_ipaws.py` | add | 20 offline tests (all HTTP calls mocked via `monkeypatch.setattr("critic.ipaws.requests.get", ...)`): date validation, quote-escaping/injection resistance, no-raw-where-parameter check, status default/omission, field projection + date conversion, two-page pagination, `max_records` cap, `count_ipaws_alerts` sharing `build_where_clause`, `IpawsAlertQueryTool` valid-input pass-through and invalid/missing-input validation gating |
| `ingestion/README.md` | edit | New "IPAWS alert query tool" section: purpose, why it's separate from `ArcGISFeatureServerTool`, safety property, fixed field set, default `status="Actual"` (and how to disable it), pagination/cap behavior, curator invocation pattern (never agentic, never auto-called by the critic endpoint), retention-accuracy caveat, and a Tests subsection |

No other file was added, edited, or deleted.

## Acceptance criteria

| Criterion | Status | Where |
|---|---|---|
| `ipaws.py` defines `build_where_clause`, `query_ipaws_alerts`, `count_ipaws_alerts`, `IpawsAlertQueryInput`, `IpawsAlertQueryTool` matching In-scope signatures | done | `ingestion/critic/ipaws.py` |
| `build_where_clause` raises `ValueError` for non-strict-`YYYY-MM-DD` dates before building any clause string | done | `ingestion/critic/ipaws.py::_validate_date` (called first, before any clause construction); `ingestion/tests/test_ipaws.py::test_build_where_clause_rejects_invalid_dates` (6 parametrized cases, including a pattern-matching-but-invalid calendar date) |
| Single quotes in `area_contains`/`event_type` doubled; injection-style test (`Kerr' OR '1'='1`) asserts doubled-quote escape and that the literal isn't terminated early | done | `ingestion/critic/ipaws.py::_escape_sql_string`; `test_ipaws.py::test_build_where_clause_escapes_single_quotes_in_area_contains` / `..._in_event_type` |
| No function accepts a raw pass-through `where` string | done | None of `build_where_clause`/`query_ipaws_alerts`/`count_ipaws_alerts` has a `where` parameter; asserted by `test_ipaws.py::test_no_function_accepts_raw_where_string` (introspects each signature) |
| `query_ipaws_alerts` returns exactly the documented 10-field subset, `sent` as ISO-8601 UTC (not raw epoch int) | done | `ingestion/critic/ipaws.py::_project_record`/`_epoch_ms_to_iso8601`; `test_ipaws.py::test_query_ipaws_alerts_returns_only_documented_fields_and_converts_sent` (raw attrs include extra fields like `xmlns`/`resource_uri` that are asserted absent from the result) |
| Two-page pagination test (full page then smaller page) combines results; separate `max_records`-cap test stops pagination at the cap | done | `test_ipaws.py::test_query_ipaws_alerts_combines_full_page_and_partial_page`, `::test_query_ipaws_alerts_max_records_cap_stops_pagination` (both monkeypatch `MAX_RECORD_COUNT` down to 2 for a fast, small-scale test) |
| `status="Actual"` default appears in built clause; `status=None` omits it | done | `test_ipaws.py::test_build_where_clause_default_status_is_actual`, `::test_build_where_clause_status_none_omits_status_filter` |
| `count_ipaws_alerts` uses `returnCountOnly=true`, shares `build_where_clause`, returns `int` from mocked `count` field | done | `ingestion/critic/ipaws.py::count_ipaws_alerts`; `test_ipaws.py::test_count_ipaws_alerts_uses_return_count_only_and_shared_where_clause` (asserts the request's `where` param equals a direct `build_where_clause(...)` call's output, not a second implementation) |
| `IpawsAlertQueryTool().invoke({...})` valid input reaches mocked HTTP call with expected `where`/`outFields`/pagination params, same shape as direct call | done | `test_ipaws.py::test_ipaws_alert_query_tool_valid_input_reaches_mocked_http_call` |
| `IpawsAlertQueryTool().invoke({...})` invalid/missing input raises validation error before any network call, zero mock calls asserted | done | `IpawsAlertQueryInput`'s `field_validator` on `start_date`/`end_date` (raises `ValueError`, which Pydantic wraps into a `pydantic.ValidationError`) gates before `_run` executes; `test_ipaws.py::test_ipaws_alert_query_tool_rejects_invalid_input_before_network_call` (malformed `start_date`) and `::test_ipaws_alert_query_tool_rejects_missing_required_input` (missing `end_date`), both asserting the mock recorded zero calls |
| CLI script runs via `python -m scripts.query_ipaws_alerts --start ... --end ...` (+ optional flags), prints JSON/count to stdout; not collected by `pytest --collect-only` | done | `ingestion/scripts/query_ipaws_alerts.py`; manually verified `python -m scripts.query_ipaws_alerts --help` prints correct usage (see How to verify), and `pytest --collect-only -q` output (111 collected items, none from this file) confirmed by grep |
| `cd ingestion && pytest` passes with `test_ipaws.py` included, no network/API key | done, with a noted pre-existing unrelated flake | See Residual risk below — `test_ipaws.py`'s own 20 tests pass every time; the full-suite run intermittently segfaults inside `test_aar_search.py` (faiss/torch/ragas native code), reproduced with `--ignore=tests/test_ipaws.py` too, proving it predates this feature |
| `ingestion/README.md` documents purpose, fixed field set, default `status="Actual"` + how to disable, curator invocation pattern, stale-6-month-retention caveat | done | `ingestion/README.md`, new "IPAWS alert query tool" section |
| No diff touches any of the listed forbidden files/dirs | done | `git status --porcelain` shows only `ingestion/README.md` (edit) plus the three new files and this feature's own `pipeline/features/ipaws-alert-tool/` folder — verified below |

## How to verify

```bash
cd ingestion
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# Feature's own tests (all pass, every run):
python -m pytest tests/test_ipaws.py -v
# -> 20 passed

# Full suite excluding the pre-existing flaky file (all pass, no regression):
python -m pytest --ignore=tests/test_aar_search.py -q
# -> 105 passed

# CLI wiring sanity check (no network call):
python -m scripts.query_ipaws_alerts --help

# Confirm the CLI script is not collected as a pytest module:
python -m pytest --collect-only -q | grep query_ipaws_alerts
# -> no output (0 matches)

# Confirm no forbidden file was touched:
git status --porcelain
```

## Residual risk

- **Pre-existing, unrelated full-suite flake in `tests/test_aar_search.py`.**
  Running the entire `ingestion/` suite in one `pytest` invocation
  intermittently aborts with a native (C-level) crash inside
  `faiss`/`torch`/`ragas` during `test_aar_search.py`'s FAISS
  `similarity_search_with_score_by_vector` call. This was independently
  reproduced with `python -m pytest --ignore=tests/test_ipaws.py -q`
  (crash still occurs) and `python -m pytest --ignore=tests/test_aar_search.py -q`
  (105 tests, all pass, including all 20 in `test_ipaws.py`), and
  `test_aar_search.py` alone (and combined with only
  `test_aar_corpus.py`/`test_aar_manifest.py`) passes every time in
  isolation. This is a native-library/threading interaction (freshly
  installed `faiss-cpu 1.15.0` + `torch 2.14.0` + `ragas`'s background
  analytics thread on Python 3.13.7/macOS arm64) that predates this
  feature: none of `ipaws.py`/`test_ipaws.py`/`query_ipaws_alerts.py`
  import `faiss`, `torch`, `ragas`, or `sentence_transformers`, and the
  crash is reproducible with `test_ipaws.py` excluded entirely. Not fixed
  here — out of scope (touching `aar/`/`critic_eval/`/environment/pinned
  dependency versions is explicitly forbidden by this spec), and doing so
  would not be "implementing the spec" but debugging an unrelated
  environment issue.
- **RESOLVED — both live-verified after implementation, against the real
  service, not just mocks.** The exact `where` clause this code generates
  for `start_date="2025-07-03", end_date="2025-07-05", status="Actual"`
  (`sent >= DATE '2025-07-03' AND sent < DATE '2025-07-06' AND status =
  'Actual'`) was sent as a real `curl` request to
  `.../MapServer/1/query` with the code's exact `outFields`/pagination
  param names — it returned exactly the documented 10 fields, no error.
  Pagination was verified independently of the code by issuing two real
  requests (`resultOffset=0`/`resultRecordCount=3`, then
  `resultOffset=3`/`resultRecordCount=3`) against the same `where` clause:
  the two pages returned six distinct, non-overlapping `identifier`
  values, confirming `resultOffset` genuinely advances server-side rather
  than being ignored or returning duplicates. Both items the implementer
  flagged as spec-time assumptions are now empirically confirmed correct;
  no fallback/guard behavior was needed.

## Not done

Nothing in scope was skipped. Out-of-scope items (per spec.md's Out of
scope section) were left untouched, as required: no change to
`ingestion/critic/service.py`/`llm.py`/`app.py`/`schemas.py`/
`validator.py`/`settings.py`, no `AgentExecutor`/tool-binding, no
retrofit of `lib/geo.py`/`lib/langchain_tools.py`, no `aar/manifest.py`
schema change, no PostGIS persistence, no `originalmessage`/CAP-XML
follow, and no addition to `scripts/live_smoke_test.py`.
