# Changes

- Slug: critic-output-validator
- Spec: `pipeline/features/critic-output-validator/spec.md`
- Status: done

## Summary

Added an independent, deterministic rule-checking output validator inside
`ingestion/critic/` that re-verifies every AAR `chunk_id` citation a
critique response contains -- both in the structured `chunk_ids` fields and
inline bracketed tokens in free-text `text` fields -- against that
request's own retrieved chunk-ID set, and wired it into a bounded
reject-and-regenerate loop in `run_critique`. A citation violation now
triggers up to `CRITIC_MAX_REGENERATION_ATTEMPTS` (default 2) additional
LLM calls with a corrective instruction before failing closed with the
existing `CritiqueGenerationError` -> `502` mapping. No change to the
existing per-request `Enum` constraint in `schemas.py`, no impact-JSON /
feature-ID integration (none exists yet), no RAGAS-style faithfulness
checking, and no new HTTP route/status code.

## Files touched

| Path | Change | Why |
|---|---|---|
| `ingestion/critic/validator.py` | added | New `CitationViolation` dataclass and `find_citation_violations(objections, alternatives, known_chunk_ids)` -- pure, dependency-free (stdlib `re` only) rule-check of both the structured `chunk_ids` field and inline `[bracketed]` tokens in `text`, against a request's retrieved-chunk-ID set. Backstops, does not replace, the `Enum` constraint in `schemas.py`. |
| `ingestion/critic/prompts.py` | edited | Added `build_correction_message(violations, valid_ids) -> str` (deterministic string builder, no LLM call). Added an optional keyword-only `correction: str | None = None` parameter to `build_human_message`, appended as a trailing section when present. |
| `ingestion/critic/llm.py` | edited | Added optional keyword-only `correction: str | None = None` to `_default_generator` and `generate_critique`; threaded into `build_human_message`. `generate_critique` forwards `correction` to the injected/default generator only when it is not `None`, so every pre-existing fake `generator` signature (none of which declare a `correction` parameter) remains valid, unmodified, on the always-uncorrected first attempt. |
| `ingestion/critic/settings.py` | edited | Added `DEFAULT_MAX_REGENERATION_ATTEMPTS = 2` and `Settings.max_regeneration_attempts: int`, read from `CRITIC_MAX_REGENERATION_ATTEMPTS` via the same `field(default_factory=...)` pattern as `default_top_k`. |
| `ingestion/critic/service.py` | edited | `run_critique` now computes `retrieved_ids`, then wraps `generate_critique` in a `while attempt <= settings.max_regeneration_attempts: ... else: raise` loop (matching spec.md's Approach pseudocode exactly): after each attempt, `find_citation_violations` re-checks the response; on success it builds and returns `CritiqueResponse` as before; on failure it builds a correction message via `build_correction_message` and retries; if the loop is exhausted without ever validating cleanly, `CritiqueGenerationError` is raised (unchanged existing exception handling for non-citation generation/schema failures is preserved inside the loop, unchanged). |
| `ingestion/tests/test_critic_validator.py` | added | 5 unit tests for `find_citation_violations`: fully valid response (empty violations); structured `chunk_ids` entry outside retrieved set; inline bracketed `text` token outside retrieved set; inline bracketed `text` token *inside* retrieved set (not a violation); empty `objections`/`alternatives` (empty violations). |
| `ingestion/tests/test_critic_service.py` | edited | Added `_invalid_response` helper (constructs a schema-valid structured response whose free-text `text` contains an out-of-retrieved-set bracketed token -- see Residual risk for why the *structured* `chunk_ids` field cannot be used to construct this fake) and 3 new tests: (1) invalid-then-valid fake generator, asserting `run_critique` returns the second (valid) response and the generator was called exactly twice, with the first call's `correction` argument `None` and the second's non-`None` and mentioning the offending token; (2) always-invalid fake generator, asserting `CritiqueGenerationError` is raised only after exactly `settings.max_regeneration_attempts + 1` (3, default) calls; (3) same always-invalid fake with `Settings(max_regeneration_attempts=0)`, asserting exactly 1 call before failing closed. |
| `ingestion/README.md` | edited | Added `CRITIC_MAX_REGENERATION_ATTEMPTS` row to the critic env-var table; added a new "Output validator (`critic/validator.py`)" subsection documenting what it checks, what it explicitly does not check (feature IDs/impact JSON -- no producer exists; faithfulness -- RAGAS's job), and the regenerate-then-fail-closed behavior; updated the `pytest` command in the Tests section to include `tests/test_critic_validator.py`. |
| `ingestion/.env.example` | edited | Added a commented `CRITIC_MAX_REGENERATION_ATTEMPTS=2` line with a one-line explanation, alongside the other commented critic env vars. |

No files outside `ingestion/critic/`, `ingestion/tests/`, `ingestion/README.md`, and `ingestion/.env.example` were touched. `src/flood/*`, `ingestion/aar/`, `ingestion/critic/app.py`, and `ingestion/critic/schemas.py` are unchanged.

## Acceptance criteria

| Criterion | Status (done/blocked/skipped) | Where |
|---|---|---|
| `find_citation_violations` returns `[]` when every `chunk_ids` entry and every bracketed `text` token is in the retrieved set | done | `ingestion/critic/validator.py`; `ingestion/tests/test_critic_validator.py::test_find_citation_violations_returns_empty_for_fully_valid_response` |
| `find_citation_violations` returns a `field="chunk_ids"` violation for an out-of-set structured entry (independent backstop of the schema `Enum`) | done | `ingestion/critic/validator.py`; `test_critic_validator.py::test_find_citation_violations_flags_structured_chunk_id_outside_retrieved_set` |
| `find_citation_violations` returns a `field="text"` violation for an out-of-set bracketed inline token, and no violation for an in-set one | done | `ingestion/critic/validator.py`; `test_critic_validator.py::test_find_citation_violations_flags_inline_bracketed_token_outside_retrieved_set` and `test_find_citation_violations_does_not_flag_inline_bracketed_token_in_retrieved_set` |
| `find_citation_violations` returns `[]` for empty `objections`/`alternatives` | done | `ingestion/critic/validator.py`; `test_critic_validator.py::test_find_citation_violations_returns_empty_for_empty_objections_and_alternatives` |
| Fake generator invalid-then-valid: `run_critique` returns the valid (second) response, generator called exactly twice | done | `ingestion/critic/service.py` (regenerate loop); `ingestion/tests/test_critic_service.py::test_run_critique_regenerates_once_on_invalid_then_valid_response` |
| Fake generator invalid on every call: `CritiqueGenerationError` raised only after exactly `max_regeneration_attempts + 1` calls (3 by default) | done | `ingestion/critic/service.py`; `test_critic_service.py::test_run_critique_raises_after_exhausting_regeneration_attempts` |
| `run_critique` never returns a response with an out-of-set citation, under any exercised fake-generator behavior (`find_citation_violations` actually invoked every attempt) | done | `ingestion/critic/service.py`; covered by the passing case (`test_run_critique_regenerates_once_on_invalid_then_valid_response`, asserting no `WIM-2015-07` token or out-of-set id in the returned response) and the failing case (`test_run_critique_raises_after_exhausting_regeneration_attempts`, which never returns a response at all) |
| `CritiqueGenerationError` after exhausted regeneration still maps to the existing `502` in `app.py`; no new exception type/route/status code | done (verified via existing, unchanged test; no new API-level test added -- see Residual risk) | `ingestion/critic/app.py` (unchanged); `ingestion/tests/test_critic_api.py::test_critique_generator_failure_returns_5xx_not_200` (pre-existing, still passing, exercises the same unchanged `CritiqueGenerationError` -> `502` handler that the exhausted-regeneration path also raises through) |
| `max_regeneration_attempts` read from `CRITIC_MAX_REGENERATION_ATTEMPTS`, defaults to 2; a test sets it to a different value and confirms the retry count honors it | done | `ingestion/critic/settings.py`; `test_critic_service.py::test_run_critique_honors_max_regeneration_attempts_setting_of_zero` (set to `0`, confirms exactly 1 total call) |
| `cd ingestion && pytest` passes with new/updated tests, no real API key/network/corpus | done | Ran for real in a fresh venv -- see How to verify. `67 passed` |
| `ingestion/README.md` documents what the validator checks/does not check, regenerate-then-fail-closed behavior, and `CRITIC_MAX_REGENERATION_ATTEMPTS` with its default | done | `ingestion/README.md`, new "Output validator" subsection and env-var table row |

## How to verify

```bash
cd /Users/chiemeka/DNHacks/Flood/ingestion
python -m venv /path/to/venv && source /path/to/venv/bin/activate
pip install -r requirements.txt
pytest -v
```

Actually executed (not assumed) in this session, in a freshly built venv
(`/private/tmp/.../scratchpad/venv`, Python 3.13.7, all of
`ingestion/requirements.txt` installed via `pip install -r requirements.txt`):

```
======================= 67 passed, 6 warnings in 40.74s ========================
```

All 67 tests in `ingestion/tests/` passed, including:
- the 5 new `test_critic_validator.py` tests,
- the 3 new regeneration tests added to `test_critic_service.py`,
- all pre-existing `test_critic_service.py` and `test_critic_api.py` tests (unchanged, still green -- confirming the regenerate loop did not regress the existing success/error-mapping paths),
- every other pre-existing `ingestion/tests/*` test (aar corpus/manifest/search, geo, ingest_camps, langchain_tools, upsert) -- unaffected by this change, run here only to confirm nothing was broken.

No real `OPENAI_API_KEY`, no network access, and no built FAISS corpus were used; `aar.search.search_index` and the LLM `generator` remain fully faked/monkeypatched in every critic test, per the existing convention.

## Residual risk

- **Structured-field violations can't be exercised end-to-end through a real `response_schema` instance.** `schemas.py::build_structured_response_schema` types `chunk_ids` as `list[Enum]` where the `Enum` contains exactly the retrieved IDs (unchanged, per spec). This means a fake `generator` cannot construct a `response_schema(...)` instance with a fabricated `chunk_ids` entry at all -- pydantic raises before `find_citation_violations` would ever see it. `test_critic_validator.py` proves the structural check works as a unit (passing raw dicts, bypassing the schema entirely, per spec.md's own function signature `find_citation_violations(objections: Sequence[dict], ...)`), and the `test_critic_service.py` regeneration tests instead exercise the *inline bracketed-text* violation path end-to-end (the one citation surface the schema Enum structurally cannot constrain), since that's the only violation type an otherwise-schema-valid fake response can carry. This is not a spec conflict -- spec.md's own In scope item 5 lists "a fabricated `chunk_id` **or** an inline bracketed reference" for the service-level tests, and the structural check is independently unit-tested -- but it's worth flagging that the service-level regeneration tests exercise the inline path, not the structured-field path, for this structural reason.
- **No new API-level (`test_critic_api.py`) test was added for the exhausted-regeneration -> 502 mapping.** The task's explicit "Files to edit" list (and spec.md's own Files to change table) does not include `test_critic_api.py`, so it was left untouched per the instruction to keep changes minimal and stick to the named file list. The acceptance criterion asking to "verify via an API-level test reusing the exhausted-regeneration fake generator" is satisfied only indirectly: `app.py`'s `CritiqueGenerationError` -> `502` handler is completely unchanged, and the pre-existing `test_critique_generator_failure_returns_5xx_not_200` in `test_critic_api.py` already proves that exact handler maps `CritiqueGenerationError` to `502` regardless of what raised it. If a literal new API-level test reusing the exhausted-regeneration fake is required, that is a one-file addition to `test_critic_api.py` that was intentionally not made here given the scoping instruction; flagging it rather than silently expanding the touched-file list.
- No real OpenAI/`langchain_openai` API call has been exercised against the new `correction` parameter or the regenerate loop (matches the pre-existing residual risk already recorded in `historical-critic-api/changes.md` -- this feature does not change that fact, it only adds a second, equally-untested-against-a-live-API code path). All tests here remain fully offline/faked, per spec.md's own acceptance criteria and non-goals.

## Not done

Nothing in-scope was skipped. Out-of-scope items (feature-ID/impact-JSON checking, RAGAS faithfulness checking, changes to `schemas.py`'s Enum, `app.py` route/error-mapping changes, `src/flood/api`, `ingestion/aar/`) were left untouched, per spec.md's Out of scope section.
