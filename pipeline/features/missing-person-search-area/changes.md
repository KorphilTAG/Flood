# Changes

- Slug: `missing-person-search-area`
- Spec: `pipeline/features/missing-person-search-area/spec.md`
- Status: complete

## Summary

Added a deterministic, direct-Physics-Engine missing-person search-area estimator.
It resolves only scripted scenario LKP IDs, advects through provable downstream
flowline topology using in-memory wet/positive velocity samples, and returns
three nested WGS84 polygon bands with explicitly uncalibrated relative weights.
Added an injected LangChain tool boundary with no HTTP or LLM path.

## Files touched

| Path | Change | Why |
|---|---|---|
| `pyproject.toml` | Edited | Declares root `langchain-core>=0.3` support. |
| `src/flood/search_area/__init__.py` | Added | Exports the estimator types, function, tool, and factory. |
| `src/flood/search_area/estimator.py` | Added | Implements direct state-array sampling, projected topology-constrained advection, validated GeoJSON polygon bands, provenance, and safe unavailable/truncated outcomes. |
| `src/flood/search_area/tool.py` | Added | Adds the injected resolver `estimate_missing_person_search_area` LangChain `BaseTool`. |
| `tests/test_search_area.py` | Added | Supplies offline mini-run tests for transport, output shape, safety boundaries, and tool invocation. |
| `pipeline/features/missing-person-search-area/changes.md` | Edited | Records the implemented feature and verification. |

## Acceptance criteria

| Criterion | Status (done/blocked/skipped) | Where |
|---|---|---|
| Root package declares `langchain-core`; ingestion tool layer remains untouched. | done | `pyproject.toml` |
| Inputs are restricted to run context, `p`, `t`, and opaque scenario LKP ID; unknown IDs and extra coordinate arguments are rejected. | done | `src/flood/search_area/estimator.py`, `src/flood/search_area/tool.py`, `tests/test_search_area.py` |
| Uses one direct `run.state(p, t, write=False)` call and network flowline WKB; no product, HTTP, LLM, or velocity-calculation path. | done | `src/flood/search_area/estimator.py`, `tests/test_search_area.py` |
| Computes in projected grid CRS and emits exactly three named WGS84 Polygon/MultiPolygon bands, never points. | done | `src/flood/search_area/estimator.py`, `tests/test_search_area.py` |
| Moves only along declared, provably oriented downstream links and safely stops when continuation direction cannot be proven. | done | `src/flood/search_area/estimator.py`, `tests/test_search_area.py` |
| Requires finite wet depth and positive velocity at every movement sample; dry/distant starts are unavailable and topology failures are truncated with machine-readable reasons. | done | `src/flood/search_area/estimator.py`, `tests/test_search_area.py` |
| Result includes deterministic ID, canonical/requested time and LKP provenance, reach refs, proxy disclosure, configuration, literal uncalibrated-weight limitation, and normalized weights. | done | `src/flood/search_area/estimator.py`, `tests/test_search_area.py` |
| `SearchAreaTool` is an injected LangChain `BaseTool` named `estimate_missing_person_search_area`, validates arguments, resolves a run, and delegates unchanged. | done | `src/flood/search_area/tool.py`, `tests/test_search_area.py` |
| Offline fixture tests cover direct state use, downstream transport, polygons, weights, safe failures, argument rejection, and successful `.invoke(...)`. | done | `tests/test_search_area.py` |

## How to verify

Run `python -m pytest -q` in a Python 3.12 environment with the project and
development dependencies installed. Verified during implementation: `141
passed, 2 deselected`.

## Residual risk

The deliberate safety rule cannot orient a terminal reach with no declared
downstream geometry. If transport reaches such a continuation before the
target time, the result retains the bounded partial corridor and reports
`downstream_direction_unproven` rather than inferring a direction.

## Not done

No FastAPI route, persistence, UI integration, LLM/critic registration, or
calibrated drift/search-effectiveness model was added; these are out of scope.
