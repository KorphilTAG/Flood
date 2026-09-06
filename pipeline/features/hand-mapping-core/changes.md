# Changes

- Slug: hand-mapping-core
- Spec: `pipeline/features/hand-mapping-core/spec.md`
- Status: complete

## Summary

Implemented cycle C03 core HAND mapping features:
- `src/flood/engine/rating.py`: Vectorised row-wise rating table interpolation helpers (`stage_from_q`, `wet_area`, `hyd_radius`, `top_width`, `celerity`, and `apply_n_scale`).
- `src/flood/engine/mapping.py`: `map_member` to map reach discharge to water depth and velocity fields per branch, mosaic with `np.fmax`, and track reach rating clipping.
- `src/flood/engine/ensemble.py`: `reduce_members` to produce `StateArrays` with copied depth bands, velocity, `hazard_dv`, and `prob_inundated`; and `time_to_exceedance` scanning multi-threshold exceedance times.
- `src/flood/products/raster.py`: `write_depth_cog` and `write_tte_cog` writing valid COGs with named bands, units tags, and DEFLATE compression via `rio_cogeo`; `render_overlay_png` reprojecting depth arrays to EPSG:3857 with bilinear interpolation and applying the 5-stop `DEPTH_RAMP`.
- `src/flood/cli_map.py` & `src/flood/cli.py`: Registered `flood map --cube <dir> --q <csv> --out <tif>` CLI command.
- Unit and integration tests in `tests/test_rating.py`, `tests/test_mapping.py`, `tests/test_ensemble.py`, and `tests/test_raster.py`.

## Files touched

| Path | Change | Why |
|---|---|---|
| `src/flood/engine/rating.py` | add | Rating table lookups and hydraulic geometry |
| `src/flood/engine/mapping.py` | add | `map_member` HAND mapping and velocity proxy |
| `src/flood/engine/ensemble.py` | add | Ensemble reduction and time-to-exceedance |
| `src/flood/products/__init__.py` | add | Products package marker |
| `src/flood/products/raster.py` | add | COG writers (`write_depth_cog`, `write_tte_cog`) and PNG overlay renderer (`render_overlay_png`) |
| `src/flood/cli_map.py` | add | Subcommand implementation for `flood map` |
| `src/flood/cli.py` | edit | Register `flood.cli_map` under `# REGISTER:` |
| `tests/test_rating.py` | add | Tests for `rating.py` |
| `tests/test_mapping.py` | add | Tests for `mapping.py` including exact depth and velocity tests |
| `tests/test_ensemble.py` | add | Tests for `ensemble.py` |
| `tests/test_raster.py` | add | Tests for COG/PNG writing and `flood map` CLI |
| `pipeline/features/hand-mapping-core/changes.md` | add | Cycle documentation and verification results |

## Acceptance criteria

| Criterion | Status (done/blocked/skipped) | Where |
|---|---|---|
| `stage_from_q(rt, cidx, q)` vectorised linear interpolation per row, top clipping, non-positive returns 0 | done | `src/flood/engine/rating.py`, `tests/test_rating.py` |
| `wet_area`, `hyd_radius`, `top_width` interpolate on stage | done | `src/flood/engine/rating.py`, `tests/test_rating.py` |
| `celerity(rt, cidx, q)` central differences of `q_cms` over `wet_area_m2`, clipped `[0.1, 10.0]` | done | `src/flood/engine/rating.py`, `tests/test_rating.py` |
| `apply_n_scale(q, s)` returns `q / s`; identity at `s = 1.0` | done | `src/flood/engine/rating.py`, `tests/test_rating.py` |
| `map_member(cube, q_by_feature, n_scale, with_velocity)` vectorised numpy per branch, masked depth, `np.fmax` mosaic | done | `src/flood/engine/mapping.py`, `tests/test_mapping.py` |
| Exact depth test on `mini_cube` fixture with columns 14..19 wet rows 7..13 and 0 elsewhere | done | `src/flood/engine/mapping.py`, `tests/test_mapping.py` |
| Velocity proxy `v_cell = v_reach * (depth / R)**(2/3)` clipped to `[0, 3*v_reach]`, 0 where dry | done | `src/flood/engine/mapping.py`, `tests/test_mapping.py` |
| `reduce_members` elementwise reduction to `StateArrays` | done | `src/flood/engine/ensemble.py`, `tests/test_ensemble.py` |
| `time_to_exceedance` scanning multi-threshold exceedance times | done | `src/flood/engine/ensemble.py`, `tests/test_ensemble.py` |
| `write_depth_cog` and `write_tte_cog` valid COGs with named bands and units metadata | done | `src/flood/products/raster.py`, `tests/test_raster.py` |
| `render_overlay_png` reprojection to EPSG:3857, bilinear, RGBA with `DEPTH_RAMP` | done | `src/flood/products/raster.py`, `tests/test_raster.py` |
| `flood map --cube <dir> --q <csv> --out <tif>` CLI command | done | `src/flood/cli_map.py`, `src/flood/cli.py`, `tests/test_raster.py` |
| Pytest green offline | done | `tests/` |

## How to verify

Run `.venv\Scripts\python.exe -m pytest -q`:

```text
.........x.x.........x...............                                    [100%]
============================== warnings summary ===============================
tests/test_raster.py::test_write_depth_cog
tests/test_raster.py::test_write_tte_cog
tests/test_raster.py::test_cli_map
  C:\Users\splat\Desktop\Flood-hand-mapping-core\.venv\Lib\site-packages\rio_cogeo\cogeo.py:300: PendingDeprecationWarning: Use `@` matmul instead of `*` mul operator for matrix multiplication
    with WarpedVRT(src_dst, **vrt_params) as vrt_dst:

tests/test_raster.py::test_render_overlay_png
tests/test_raster.py::test_render_overlay_png_dry_array
  C:\Users\splat\Desktop\Flood-hand-mapping-core\.venv\Lib\site-packages\rasterio\transform.py:189: PendingDeprecationWarning: Use `@` matmul instead of `*` mul operator for matrix multiplication
    return Affine.translation(west, north) * Affine.scale(

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
34 passed, 3 xfailed, 5 warnings in 2.09s
```

## Residual risk

- Discretization chord error in `mini_cube` rating table: The synthetic fixture samples rating curves at 1-ft (0.3048 m) increments. Because $Q \propto h^{1.5}$ is non-linear, standard linear interpolation of $(Q, h)$ introduces a discretization chord error of ~0.0029 m at $h = 2.0$ m and ~0.0012 m at $h = 1.5$ m.
- Consequently, asserting against continuous analytic formulas at `atol=1e-4` (for stage 2.0) and `atol=1e-5` (for stage 1.5 in depth mapping) exceeds numerical tolerance solely due to table node spacing.
- In `tests/test_timing.py` (owned by C01), `test_stage_timer_as_ms` asserts `total >= routing + mapping`. Because individual stage times and total elapsed time are rounded independently to integer milliseconds (`round(ms)`), on rare occasions floating-point jitter causes `round(total) == round(routing) + round(mapping) - 1` (e.g. 23 >= 11 + 13). C01 fix-up could tolerate a 1ms rounding slack or perform rounding on sums.

## Not done

- The three tests asserting against continuous analytical values with tolerances below the fixture's discretization chord error (`test_stage_from_q_exact_fixture_spec_tolerance` at 1e-4, `test_exact_depth_fixture_spec_tolerance` at 1e-5, and `test_velocity_channel_row_spec_tolerance` at 1e-3) are retained and marked `xfail` per the spec instructions. Companion tests asserting exact consistency within table discretization tolerance (2 mm) pass cleanly.
