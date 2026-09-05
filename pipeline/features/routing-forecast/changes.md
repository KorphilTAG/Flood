# Changes

- Slug: routing-forecast
- Spec: `pipeline/features/routing-forecast/spec.md`
- Status: complete

## Summary

Implemented Muskingum-Cunge routing over the reach network with gauge controls by role (boundary, interior), junction inference with mass-balance tracking, and ensemble boundary forecasting using trend relaxation (`trend_relax` and `persistence`). Produces a `RoutedSeries` for a cutoff `p` and ensemble members ("low", "mid", "high").

## Files touched

| Path | Change | Why |
|---|---|---|
| `src/flood/engine/boundary.py` | add | Implement `trend_relax` and `persistence` forecast extrapolation functions |
| `src/flood/engine/routing.py` | add | Implement Muskingum-Cunge step (`mc_step`), parameters (`mc_params`), rating helpers (`_stage_from_q`, `_wet_area`, `_top_width`, `_celerity`), topological sorting, gauge controls, junction inferences, and `route()` |
| `tests/test_boundary.py` | add | Unit tests for `trend_relax` and `persistence` (asymptote, d=0, m=0, tau <= t_last, clipping) |
| `tests/test_routing.py` | add | `FixtureForcingView` and fixture tests covering `mc_step`, controls reproduction, lag & celerity, member ordering, junction inference, source codes, hindsight behavior, and runtime |
| `pipeline/features/routing-forecast/changes.md` | add | Feature implementation tracking and verification |

## Acceptance criteria

| Criterion | Status (done/blocked/skipped) | Where |
|---|---|---|
| `trend_relax` and `persistence` | done | `src/flood/engine/boundary.py`, `tests/test_boundary.py` |
| `mc_params` with rating lookup / fallback | done | `src/flood/engine/routing.py`, `tests/test_routing.py` |
| `mc_step` with sub-stepping for C2 >= 0 | done | `src/flood/engine/routing.py`, `tests/test_routing.py::test_mc_step_properties` |
| `route()` with topological sorting and cycle detection | done | `src/flood/engine/routing.py` |
| Gauge controls by role (boundary, interior, validation_only) | done | `src/flood/engine/routing.py`, `tests/test_routing.py::test_controls_reproduction` |
| Junction inference mass balance and trend extrapolation | done | `src/flood/engine/routing.py`, `tests/test_routing.py::test_junction_inference` |
| Ensemble member ordering and downsampling to 5-min grid | done | `src/flood/engine/routing.py`, `tests/test_routing.py::test_member_ordering` |
| Source code assignment across reaches | done | `src/flood/engine/routing.py`, `tests/test_routing.py::test_source_codes` |
| Hindsight behavior with no `forecast_trend` | done | `src/flood/engine/routing.py`, `tests/test_routing.py::test_hindsight` |
| Hydrograph lag vs celerity at peak | done | `tests/test_routing.py::test_lag_and_celerity` |
| Fast runtime (< 2s on fixture) | done | `src/flood/engine/routing.py`, `tests/test_routing.py::test_runtime` |

## How to verify

```
$ .venv\Scripts\python.exe -m pytest -q
...................................................................      [100%]
============================== warnings summary ===============================
.venv\Lib\site-packages\fastapi\testclient.py:1
  C:\Users\splat\Desktop\Flood-hand-ingest-cube\.venv\Lib\site-packages\fastapi\testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

.venv\Lib\site-packages\starlette\testclient.py:53
  C:\Users\splat\Desktop\Flood-hand-ingest-cube\.venv\Lib\site-packages\starlette\testclient.py:53: DeprecationWarning: The anyio.abc.BlockingPortal alias is deprecated, use anyio.from_thread.BlockingPortal instead.
    _PortalFactoryType = Callable[[], AbstractContextManager[anyio.abc.BlockingPortal]]

tests/test_ingest_hand.py::test_clip_branch_tiny_geotiffs
  C:\Users\splat\Desktop\Flood-hand-ingest-cube\.venv\Lib\site-packages\rasterio\transform.py:178: PendingDeprecationWarning: Use `@` matmul instead of `*` mul operator for matrix multiplication
    return Affine.translation(west, north) * Affine.scale(xsize, -ysize)

tests/test_ingest_hand.py::test_clip_branch_tiny_geotiffs
tests/test_ingest_hand.py::test_clip_branch_tiny_geotiffs
  C:\Users\splat\Desktop\Flood-hand-ingest-cube\.venv\Lib\site-packages\rasterio\windows.py:360: PendingDeprecationWarning: Use `@` matmul instead of `*` mul operator for matrix multiplication
    x, y = transform * (window.col_off or 0.0, window.row_off or 0.0)

tests/test_ingest_hand.py::test_clip_branch_tiny_geotiffs
tests/test_ingest_hand.py::test_clip_branch_tiny_geotiffs
  C:\Users\splat\Desktop\Flood-hand-ingest-cube\.venv\Lib\site-packages\rasterio\windows.py:361: PendingDeprecationWarning: Use `@` matmul instead of `*` mul operator for matrix multiplication
    return Affine.translation(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
67 passed, 2 deselected, 7 warnings in 9.77s
```

## Residual risk

- Private rating helpers `_stage_from_q`, `_wet_area`, `_top_width`, and `_celerity` in `src/flood/engine/routing.py` are kept as fast scalar versions after the fix-up pass (the vectorised `flood.engine.rating` calls slowed the per-step loop about tenfold); `tests/test_routing.py::test_scalar_helpers_match_rating` pins them to `flood.engine.rating`.
- `FixtureForcingView` in `tests/test_routing.py` is a lightweight test double adhering to `ForcingView` protocol; will be superseded by `ParquetForcingView` once C04 merges.

## Not done

None.
