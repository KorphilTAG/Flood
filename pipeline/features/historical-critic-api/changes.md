# Changes

- Slug: historical-critic-api
- Spec: `pipeline/features/historical-critic-api/spec.md`
- Status: done

## Summary

Added `ingestion/critic/`, a new standalone FastAPI service run from
`ingestion/` (same convention as `aar`). It retrieves grounded AAR context
via a direct in-process call to `aar.search.search_index` (never a
subprocess), then calls the OpenAI API through
`langchain_openai.ChatOpenAI.with_structured_output` to produce a
structured, cited critique. The citation fields on every objection/
alternative are constrained, per request, to an `Enum` built from exactly
that request's retrieved `chunk_id`s, so an invented chunk ID cannot be
represented in the model's structured output at all. Failure modes (empty
plan, no retrieved context, corpus/index errors, LLM/schema failures) each
map to a distinct, clearly-labeled error response rather than a silent or
fabricated answer. Two new offline test files cover the orchestration layer
and the HTTP layer with a fake `search_index` and a fake LLM `generator`;
no real `OPENAI_API_KEY`, network access, or built FAISS corpus is used or
required.

## Files touched

| Path | Change | Why |
|---|---|---|
| `ingestion/critic/__init__.py` | add | Package marker for the new critic service |
| `ingestion/critic/settings.py` | add | Env-driven `Settings` dataclass: `AAR_INDEX_DIR`, `CRITIC_OPENAI_MODEL`, `CRITIC_REQUEST_TIMEOUT`, `CRITIC_DEFAULT_TOP_K`, mirroring `src/flood/api/settings.py`'s pattern |
| `ingestion/critic/schemas.py` | add | `CritiqueRequest` (validates non-empty/non-whitespace `plan`), `CritiqueResponse`/`RetrievedChunk`/`CitationDetail`, and `build_structured_response_schema(chunk_ids)` — the per-request `Enum`+`create_model` structured-output schema builder |
| `ingestion/critic/prompts.py` | add | `SYSTEM_PROMPT` (critic role, cite-only-given-IDs rule, no-dispatch-order rule, empty-objections-allowed rule) and `build_human_message(...)` (renders plan/situation/decision_point plus every retrieved chunk as `[chunk_id] excerpt (hazard=..., phase=..., tactic=..., outcome=...)`) |
| `ingestion/critic/llm.py` | add | `generate_critique(...)`: default generator constructs `ChatOpenAI(model=settings.openai_model, ...)` + `.with_structured_output(...)`, imported lazily so app construction/import never needs `langchain_openai`; accepts an injectable `generator` for tests |
| `ingestion/critic/service.py` | add | `run_critique(...)`: builds the retrieval query, calls `search_index` (default) or an injected fake, raises `NoHistoricalContextError` on zero hits (before any LLM call), lets `aar.models.IndexError`/`RuntimeError` propagate untouched, wraps any LLM/schema failure in `CritiqueGenerationError`, assembles `CritiqueResponse` |
| `ingestion/critic/app.py` | add | `create_app() -> FastAPI`, module-level `app` (for `uvicorn critic.app:app`), `GET /healthz`, `POST /v1/critique`, and exception handlers mapping `NoHistoricalContextError`→422, `aar.models.IndexError`→503, `RuntimeError`→503, `CritiqueGenerationError`→502, anything else→500, each as `{"error": {"code": str, "message": str}}` |
| `ingestion/tests/test_critic_service.py` | add | Offline orchestration tests: query building (with/without `situation`), hazard/phase/top_k pass-through, settings default `top_k`, per-request schema built from exactly the retrieved chunk IDs (with `min_length=1` on both objection/alternative `chunk_ids`, and a rejection test for an invented chunk ID), `NoHistoricalContextError` on empty retrieval (generator never called), `aar.models.IndexError`/`RuntimeError` propagation (generator never called), and generator-failure wrapping into `CritiqueGenerationError` |
| `ingestion/tests/test_critic_api.py` | add | `TestClient` tests: `/healthz` touches neither fake; success path returns `objections`/`alternatives`/`citations`/`model` with all `chunk_ids` drawn from `citations`; missing/whitespace-only `plan` → 422 with zero fake calls; empty retrieval → 4xx with generator never called; `aar.models.IndexError` → 5xx with the underlying message present; `RuntimeError` from search → 5xx; generator failure → 5xx (never a 200 with fabricated content) |
| `ingestion/requirements.txt` | edit | Added `fastapi>=0.115` and `uvicorn[standard]>=0.30` (not previously listed under `ingestion/`; `langchain-openai`/`langchain-core` were already present) |
| `ingestion/README.md` | edit | New "Historical critic API (`ingestion/critic/`)" section: how to run it, the `python -m aar build` prerequisite, the env-var table, the `POST /v1/critique` request/response shapes, the error-mapping table, and how to run its tests |
| `ingestion/.env.example` | edit | Added a commented critic section: `OPENAI_API_KEY`, `AAR_INDEX_DIR` (set to `../data/aar/library` to match where the existing `aar build` examples actually write the corpus from `ingestion/`), `CRITIC_OPENAI_MODEL` |

## Acceptance criteria

| Criterion | Status (done/blocked/skipped) | Where |
|---|---|---|
| `create_app() -> FastAPI` importable from `ingestion/`; `uvicorn critic.app:app` starts without a real `OPENAI_API_KEY` or built corpus (construction only) | done | `ingestion/critic/app.py`; verified live: ran `uvicorn critic.app:app --port 8099` with `OPENAI_API_KEY` unset and no corpus present, `GET /healthz` returned 200 |
| `GET /healthz` returns 200, no call to `aar.search` or any LLM client | done | `ingestion/critic/app.py` (`healthz` handler makes no calls); `test_healthz_returns_200_without_touching_search_or_llm` in `ingestion/tests/test_critic_api.py` asserts zero fake calls |
| `POST /v1/critique` success path: 200 with `objections`/`alternatives`/`citations`/`model`, every `chunk_ids` entry drawn from `citations` | done | `ingestion/critic/service.py` (`run_critique`), `ingestion/critic/schemas.py` (`CritiqueResponse`); `test_critique_success_returns_grounded_response` in `test_critic_api.py`; `test_run_critique_success_grounds_response_in_retrieved_chunks` in `test_critic_service.py` |
| Missing/empty/whitespace-only `plan` → 422 before any fake is invoked | done | `ingestion/critic/schemas.py` (`CritiqueRequest._plan_must_be_non_empty`); `test_critique_missing_plan_returns_422_before_any_fake_is_called`, `test_critique_empty_plan_returns_422_before_any_fake_is_called` in `test_critic_api.py` |
| Empty retrieval → 4xx naming lack of historical context, generator never called | done | `ingestion/critic/service.py` (`NoHistoricalContextError`), `ingestion/critic/app.py` (422 handler); `test_run_critique_raises_no_historical_context_error_and_never_calls_generator` (service), `test_critique_no_historical_context_returns_4xx_and_never_calls_generator` (API) |
| `aar.models.IndexError` from search → 5xx with underlying message | done | `ingestion/critic/app.py` (`AarIndexError` handler, 503); `test_run_critique_propagates_aar_index_error_and_never_calls_generator` (service), `test_critique_aar_index_error_returns_5xx_with_underlying_message` (API) |
| Generator raises (OpenAI/LangChain/schema failure) → 5xx/502, not a 200 with fabricated content | done | `ingestion/critic/service.py` (`CritiqueGenerationError` wrapping), `ingestion/critic/app.py` (502 handler); `test_run_critique_wraps_generator_failure_in_critique_generation_error` (service), `test_critique_generator_failure_returns_5xx_not_200` (API) |
| Per-request structured-output schema built from exactly the retrieved chunk IDs; each objection/alternative field requires ≥1 citation | done | `ingestion/critic/schemas.py` (`build_structured_response_schema`); `test_structured_schema_is_built_from_exactly_the_retrieved_chunk_ids` asserts the schema's JSON-schema enum equals the retrieved chunk-ID set, `minItems: 1` on both objection/alternative `chunk_ids`, and that an invented chunk ID is structurally rejected |
| Retrieval is a direct Python call, no `subprocess`/`os.system`/shell-out anywhere in `ingestion/critic/` | done | `ingestion/critic/service.py` (`from aar.search import search_index`); verified via `grep -rnE "subprocess\|os\.system\|python -m aar" critic/` — no matches outside comments |
| `cd ingestion && pytest` passes with the new tests, no real API key/network/corpus | done | Actually ran (see How to verify) — 59 passed (17 new: 9 in `test_critic_service.py`, 8 in `test_critic_api.py`; 42 pre-existing), `OPENAI_API_KEY` unset throughout |
| `ingestion/README.md` documents run instructions, `AAR_INDEX_DIR` prerequisite, `OPENAI_API_KEY` required at request time not process start, and the `POST /v1/critique` shape | done | `ingestion/README.md`, new "Historical critic API" section |

## How to verify

```bash
cd ingestion
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # fastapi/uvicorn now included

# Run just the new tests:
pytest tests/test_critic_service.py tests/test_critic_api.py -v

# Run the whole ingestion suite (includes the two files above):
pytest
```

This was actually run (not assumed) in a throwaway venv
(`/tmp/critic-venv`, Python 3.13.7) built from `ingestion/requirements.txt`
plus the newly-added `fastapi`/`uvicorn`/`httpx` (the latter already comes
in transitively via `langchain-core`/`huggingface_hub`, so it was not added
to `requirements.txt`), with `OPENAI_API_KEY` unset and no network access
used by any test:

- `pytest tests/test_critic_service.py tests/test_critic_api.py -v` → **17
  passed** (9 service-level, 8 API-level).
- `pytest` (full `ingestion/` suite) → **59 passed** (the 17 new plus 42
  pre-existing), 0 failed.
- Live-started `uvicorn critic.app:app --port 8099` with `OPENAI_API_KEY`
  unset and no `data/aar/library` directory present: server started, `GET
  /healthz` returned `200 {"status": "ok"}`.

## Residual risk

- **Real OpenAI structured-output path is untested.** Per spec.md's own
  Assumptions, "if the installed `langchain-openai` version's
  structured-output path does not support a dynamically constructed enum
  type as expected, ... note the deviation." I verified the dynamic
  `Enum` + `pydantic.create_model` construction works correctly in
  isolation (enum validation, `min_length=1` enforcement, JSON-schema enum
  values, and rejection of an invented ID — all confirmed with plain
  `pydantic`), and confirmed `langchain-openai`/`langchain-core` install and
  import cleanly in the test venv, but a real call to
  `ChatOpenAI(...).with_structured_output(...)` against the live OpenAI API
  was never made (no API key, no network use for this feature, per spec's
  own constraints). If OpenAI's structured-output/JSON-schema path rejects a
  dynamically-named `Enum` in some edge case, the fallback described in the
  spec's Assumptions (post-hoc validation against the retrieved set,
  rejecting to 5xx rather than silently filtering) would need to be added;
  it was not needed for anything exercised here.
- **`AAR_INDEX_DIR` default vs. existing `aar build` convention.** spec.md's
  Approach/Assumptions state the default index directory is literally
  `data/aar/library`, so `ingestion/critic/settings.py` uses that literal
  string. But `ingestion/README.md`'s own existing `aar build` examples
  write to `../data/aar/library` (relative to `ingestion/`, i.e.
  `<repo-root>/data/aar/library`) — a directory one level up from the
  code-default. Running the critic service from `ingestion/` with
  `AAR_INDEX_DIR` unset would therefore look in
  `ingestion/data/aar/library`, not where `aar build`'s own documented
  examples put the corpus. I implemented the spec's literal default (per
  developer-agent instructions: implement the spec, record the conflict
  here) and made the mismatch unmissable by documenting the correct
  override (`AAR_INDEX_DIR=../data/aar/library`) directly in both
  `ingestion/README.md`'s new critic section and `ingestion/.env.example`,
  rather than silently changing the code default away from what spec.md
  states.
- **`generate_critique`'s signature gained an extra `settings` keyword.**
  spec.md's Approach shows `generate_critique(plan, situation,
  decision_point, chunks, response_schema, *, generator=None)` with no
  `settings` parameter, but the same paragraph requires the *default*
  generator to read `settings.openai_model`/timeout. I added an optional
  `settings: Settings | None = None` keyword (defaulting to a fresh
  `Settings()` if omitted) so the actual `Settings` instance the service was
  constructed with flows through to the default `ChatOpenAI(...)` call
  instead of every default-generator invocation re-reading `os.environ`
  independently. This is additive (every literally-specified positional/
  keyword-only parameter is unchanged) and necessary to satisfy the
  Approach text's own requirement; noted here rather than treated as silent
  scope creep.
- **`CritiqueResponse` gained a `decision_point` field beyond spec.md's
  item-5 enumeration.** Item 5 of "In scope" lists the response contract as
  `objections`, `alternatives`, `citations`, `model` only, but the Approach
  section's request-flow narrative says `decision_point` is "passed through
  into the prompt and echoed back for the caller's own logging." I added
  `decision_point: str | None = None` to `CritiqueResponse` to satisfy the
  "echoed back" text without contradicting item 5 or any acceptance
  criterion (none require the response to contain *only* those four
  fields; all check that they are *present*). Flagging the internal
  tension here per instructions.

## Not done

None of the in-scope acceptance criteria were skipped. Everything listed
under spec.md's "Out of scope" (the output validator, RAGAS evaluation,
impact-JSON/session-state integration, the enrichment agent/overlay JSON,
the chat agent, the historical-decision scorer, session-state persistence,
auth/rate-limiting/deployment config, and any change to `src/flood/api` or
to `ingestion/aar/` itself) was left untouched, as instructed.
