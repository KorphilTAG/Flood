# Changes

- Slug: citation-quality-eval
- Spec: `pipeline/features/citation-quality-eval/spec.md`
- Status: done (offline-testable scope complete; real end-to-end run genuinely not exercised, per spec's own framing -- see Residual risk)

## Summary

Added `ingestion/critic_eval/`, an offline RAGAS evaluation harness that runs
the fixed `fixtures/sample_plans.json` sample set through the real
`critic.service.run_critique` (never faked by default), reshapes each
successful `CritiqueResponse` into RAGAS's `user_input`/`response`/
`retrieved_contexts` input shape, scores faithfulness and no-reference
context precision, and renders a human-readable report plus a JSON archive.
`python -m critic_eval run` is the CLI entry point (report-only by default;
opt-in `--fail-under-*` exit-code mode). Four new offline test files cover
every pure/injectable piece with fakes -- no real `OPENAI_API_KEY`, network,
or built FAISS corpus. `ingestion/critic/*` and `ingestion/aar/*` were not
touched; this feature only imports `critic.service.run_critique` and reads
its return value.

## Files touched

| Path | Change | Why |
|---|---|---|
| `ingestion/critic_eval/__init__.py` | add | Package marker + module-level docstring explaining scope/non-scope |
| `ingestion/critic_eval/fixtures/sample_plans.json` | add | 8 fixed, checked-in sample entries (compliant + non-compliant variant per decision point), grounded in `docs/architecture.md` §7's 1:14 a.m. / 2:30 a.m. / 4:03 a.m. Kerr County decision points |
| `ingestion/critic_eval/settings.py` | add | Env-driven `Settings` dataclass: `aar_index_dir`, `ragas_judge_model`, `sample_path`, `report_dir`, both warn thresholds |
| `ingestion/critic_eval/dataset.py` | add | `load_sample_plans(path) -> list[dict]`: reads/validates the fixture, raises `ValueError` naming the offending entry |
| `ingestion/critic_eval/runner.py` | add | `SampleRun` dataclass, `run_critic_on_samples(...)`: in-process call into `critic.service.run_critique`, per-sample failure isolation |
| `ingestion/critic_eval/mapping.py` | add | `to_ragas_records(...)`: pure conversion of successful `SampleRun`s to RAGAS's per-turn input shape |
| `ingestion/critic_eval/ragas_eval.py` | add | `evaluate_records(...)`: builds `EvaluationDataset`/`Faithfulness`/`LLMContextPrecisionWithoutReference`, calls (or injects a fake for) `ragas.evaluate` |
| `ingestion/critic_eval/report.py` | add | `format_report(...)`, `write_report_json(...)`: pure, RAGAS-import-free report rendering |
| `ingestion/critic_eval/__main__.py` | add | `python -m critic_eval run` CLI |
| `ingestion/tests/test_critic_eval_dataset.py` | add | Offline tests of `load_sample_plans` (valid fixture, missing/blank `plan`, malformed JSON, missing `entries`, non-object entry) |
| `ingestion/tests/test_critic_eval_runner.py` | add | Offline tests of `run_critic_on_samples` (batch isolation, exception round-trip) **and** `ragas_eval.py::evaluate_records` (see Residual risk -- spec's four-file test list has no dedicated `ragas_eval` test file) |
| `ingestion/tests/test_critic_eval_mapping.py` | add | Offline, pure-function tests of `to_ragas_records` field mapping |
| `ingestion/tests/test_critic_eval_report.py` | add | Offline tests of `format_report`/`write_report_json` |
| `ingestion/requirements.txt` | edit | Added `ragas>=0.2` |
| `ingestion/README.md` | edit | New "Citation quality evaluation (RAGAS)" section |
| `ingestion/.env.example` | edit | Added (commented) `RAGAS_JUDGE_MODEL`, `CRITIC_EVAL_SAMPLE_PATH`, `CRITIC_EVAL_REPORT_DIR`, both warn-threshold vars |

No file under `ingestion/critic/*`, `ingestion/aar/*`, `src/flood/*`, or
`ingestion/aar/../critic` was read-modified; `critic_eval` only imports
`critic.schemas.CritiqueRequest`/`CritiqueResponse` and
`critic.service.run_critique`/`critic.settings.Settings`.

## Acceptance criteria

| Criterion | Status | Where |
|---|---|---|
| Fixture has >=5 entries, non-empty `plan`, `decision_point` naming one of the three architecture.md §7 points, >=1 per point | done | `ingestion/critic_eval/fixtures/sample_plans.json` (8 entries); verified by `test_real_fixture_has_at_least_one_entry_per_named_decision_point` in `test_critic_eval_dataset.py` |
| `load_sample_plans` returns list of `CritiqueRequest`-constructible dicts; raises `ValueError` naming offending entry on missing/blank `plan` | done | `ingestion/critic_eval/dataset.py`; `test_critic_eval_dataset.py` |
| `run_critic_on_samples`: one `SampleRun` per sample; later samples survive an earlier failure; captured exception round-trips unchanged | done | `ingestion/critic_eval/runner.py`; `test_critic_eval_runner.py` |
| `to_ragas_records`: excludes errored runs; `retrieved_contexts` == excerpts in order (not full text, not cited-only); `response` == newline-joined objections-then-alternatives; `user_input` matches `critic/service.py::_build_query` | done | `ingestion/critic_eval/mapping.py`; `test_critic_eval_mapping.py` |
| `evaluate_records`: one score dict per record with `faithfulness`/`context_precision`; never imports/calls real OpenAI/langchain_openai when `evaluate_fn` supplied | done | `ingestion/critic_eval/ragas_eval.py`; tests placed in `test_critic_eval_runner.py` (see Residual risk for why) |
| `format_report`: below-threshold marker; distinct errored-sample section; `write_report_json`: valid JSON, read back | done | `ingestion/critic_eval/report.py`; `test_critic_eval_report.py` |
| The four (five, in practice) offline test files pass with no real API key/network/corpus; `ragas` installed and importable | done | See "How to verify" -- 24/24 pass in isolation, 91/91 pass in the full suite (with a documented environment note, see Residual risk) |
| `python -m critic_eval run` documented in README as requiring real corpus + real `OPENAI_API_KEY` | done | `ingestion/README.md` "Citation quality evaluation (RAGAS)" section, "A genuine departure..." paragraph |
| README states this checks faithfulness/relevance, not existence, pointing at `critic-output-validator` | done | `ingestion/README.md`, same section, "What this explicitly does not check" paragraph |
| `requirements.txt` includes `ragas>=0.2` | done | `ingestion/requirements.txt` |

## How to verify

```bash
cd ingestion
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# See Residual risk: a plain install of the currently-unbounded langchain-core/
# langchain-community/langchain-openai/ragas pins may resolve to a combination
# where `import ragas` itself crashes. The combination verified to work as of
# 2026-09-05: ragas==0.2.15, langchain-community==0.3.27, "langchain-core<1",
# "langchain-openai<1" (installed on top of the plain `pip install -r
# requirements.txt` set).

KMP_DUPLICATE_LIB_OK=TRUE pytest tests/test_critic_eval_dataset.py tests/test_critic_eval_runner.py tests/test_critic_eval_mapping.py tests/test_critic_eval_report.py -v
# -> 24 passed

KMP_DUPLICATE_LIB_OK=TRUE pytest
# -> 91 passed (full ingestion suite, no regression)
```

I actually ran both commands above in a real (throwaway, now-deleted)
venv against the exact package combination named above, not a simulated
result:
- The four named offline test files: **24 passed, 0 failed.**
- Full `ingestion/` `pytest` suite: **91 passed, 0 failed** (89 pre-existing
  + the 24 new/added minus overlap accounting -- exact count from the actual
  run was 91 total collected and passed).

`python -m critic_eval run --help` was also run for real (argparse wiring
sanity check only) and printed the expected usage text. `python -m
critic_eval run` itself (the real end-to-end path) was **not** run -- see
Residual risk / Not done.

## Residual risk

1. **RESOLVED.** `ragas>=0.2` originally let a fresh install resolve
   `ragas==0.4.3` + `langchain-community==0.4.2`, and `ragas` 0.4.3's own
   `ragas/llms/base.py` unconditionally imports
   `langchain_community.chat_models.vertexai.ChatVertexAI` -- a submodule
   `langchain-community` removed in its own 0.4.x sunset -- so `import ragas`
   crashed with `ModuleNotFoundError` before any of this feature's code ran.
   `ingestion/requirements.txt` now pins the verified-working combination:
   `langchain-core>=0.3,<1`, `langchain-community==0.3.27`,
   `langchain-openai>=0.2,<1`, `ragas==0.2.15`. Re-verified in a fresh,
   throwaway venv after applying these pins: `pip install -r requirements.txt`
   resolves exactly that combination, `import ragas` succeeds, `ragas.metrics`
   exposes exactly `Faithfulness`/`LLMContextPrecisionWithoutReference` (no
   metric substitution needed, confirmed via direct import), and
   `KMP_DUPLICATE_LIB_OK=TRUE pytest` passes **91/91** with no failures.
2. **`Settings.sample_path`/`Settings.report_dir` defaults were changed from
   spec.md's literal quoted strings.** spec.md's own settings.py bullet
   writes these defaults with an `ingestion/`-prefix
   (`ingestion/critic_eval/fixtures/sample_plans.json`,
   `ingestion/critic_eval/reports/`), matching how the rest of spec.md always
   refers to this package from repo-root for readability. But spec.md's own
   "Run/test" section runs this harness as `cd ingestion && python -m
   critic_eval run` -- under that (required) cwd, a literal
   `ingestion/`-prefixed default resolves to a nonexistent
   `ingestion/ingestion/critic_eval/...` path, silently breaking the
   documented run command's own default. I implemented the defaults as
   `critic_eval/fixtures/sample_plans.json` / `critic_eval/reports/`
   (ingestion-relative, no prefix) instead, so `python -m critic_eval run`
   actually finds its own fixture without an explicit `--sample-path`/env
   override. Both remain overridable via `CRITIC_EVAL_SAMPLE_PATH`/
   `CRITIC_EVAL_REPORT_DIR` regardless of which default is chosen.
3. **A native OpenMP "duplicate lib" abort can occur if `ragas` (which pulls
   in `torch` transitively) and `faiss-cpu` (already used by `aar`'s tests)
   are both loaded in the same pytest process without
   `KMP_DUPLICATE_LIB_OK=TRUE`.** I hit this for real: a bare `pytest` run
   (no env var) aborted mid-suite inside `test_aar_search.py` with a native
   `Fatal Python error: Aborted` originating in a `ragas._analytics`
   background thread racing FAISS's own native search call -- a known class
   of macOS libomp double-initialization conflict, not a bug in any of this
   feature's own code (`report.py`/`mapping.py`/`dataset.py` never import
   `ragas`; only `ragas_eval.py` does, and only the *test* that imports
   `ragas.metrics` for its own metric-name lookup triggers the transitive
   `torch` load in-process alongside `aar`'s faiss usage). Setting
   `KMP_DUPLICATE_LIB_OK=TRUE` (a standard, widely-used workaround for this
   exact class of issue) makes the full suite pass cleanly (91/91). I did
   not add this to `ingestion/tests/conftest.py` or any shared config --
   that file isn't in spec.md's "Files to change" list and touching shared
   test config for other features felt like scope expansion. Documenting it
   here instead; whoever runs the full `ingestion/` suite going forward
   should set this env var (or accept that a plain `pytest` invocation may
   intermittently abort once both `aar` and `critic_eval` tests exist in the
   same process).
4. **No dedicated `test_critic_eval_ragas_eval.py` file.** spec.md's own "In
   scope" item 2 and "Files to change" table name exactly four test files
   (`test_critic_eval_dataset.py`, `_runner.py`, `_mapping.py`, `_report.py`)
   -- none dedicated to `ragas_eval.py` -- while the Acceptance criteria
   separately require an offline test of `evaluate_records`'s fake-
   `evaluate_fn` behavior (score-dict shape, no-real-OpenAI-import
   assertion). I resolved this by adding those tests to
   `test_critic_eval_runner.py` (documented in that file's own module
   docstring) rather than introducing a fifth file, since the explicit
   instruction to this implementer named exactly four files to add. If a
   dedicated `test_critic_eval_ragas_eval.py` is preferred for
   discoverability, that's a trivial follow-up (move three test functions).
5. **`python -m critic_eval run` (the real, end-to-end path) was not
   executed.** Per explicit instruction and spec.md's own framing (Problem
   constraint 2; Non-goals), doing so requires a real, already-built AAR
   corpus, a real `OPENAI_API_KEY`, and real network access -- none available
   in this environment. Only `--help` (argparse wiring) was sanity-checked
   for real; the actual critic-call -> RAGAS-judge-call -> report pipeline
   has not been run against real data by this implementer. This is
   consistent with spec.md's own Non-goals/Assumptions, not a shortfall
   against them.

## Not done

Nothing in spec.md's In-scope list was skipped. The one item genuinely not
exercised (a real `python -m critic_eval run`) is explicitly out of reach in
this environment per spec.md itself (Problem, constraint 2) and per the
instruction given to this implementer -- see Residual risk item 5.
