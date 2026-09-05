# Feature spec

- Slug: hand-mapping-core
- Feature: C03. Rating lookups, HAND mapping from per-reach discharge to depth, velocity, and hazard rasters, ensemble reduction, time-to-exceedance, and the COG writer with named bands. Plus `flood map` for ad hoc discharge inputs.
- Status: draft
- Product refs: `docs/specs/physics-engine-master.md` sections 6.1, 6.6, 6.7, 7; `docs/contracts/contract-1-physics-products.md` sections 4 and 7; C01 spec.

## Problem

Given a discharge per reach, produce the contract 1 raster product on the cube grid, reproducing NOAA's reference depth algorithm and adding the velocity proxy and ensemble bands.

## In scope

- `engine/rating.py`: interpolation helpers over `RatingTable`.
- `engine/mapping.py`: `map_member`.
- `engine/ensemble.py`: `reduce_members`, `time_to_exceedance`.
- `products/raster.py`: `write_depth_cog`, `write_tte_cog`, `render_overlay_png`.
- `flood map --cube <dir> --q <csv> --out <tif>` where the CSV has columns `feature_id,q_mid_cms[,q_low_cms,q_high_cms]`.

## Out of scope

Routing, forcing, run orchestration, API. Reading real data beyond the cube directory.

## Approach

Vectorised numpy per branch: build a per-catchment stage lookup, gather through the catchment index raster, subtract REM, mask, mosaic with `np.fmax`. Velocity from reach discharge over wetted area distributed by depth ratio. Ensemble statistics are elementwise. COG via `rio_cogeo`.

## Files to change

| Path | Action (add/edit) | Why |
|---|---|---|
| `src/flood/engine/rating.py` | add | Lookups |
| `src/flood/engine/mapping.py` | add | `map_member` |
| `src/flood/engine/ensemble.py` | add | Reduction and TTE |
| `src/flood/products/__init__.py`, `src/flood/products/raster.py` | add | COG and PNG writers |
| `src/flood/cli_map.py` | add | `register(sub)` for `map` |
| `src/flood/cli.py` | edit | One line under the REGISTER marker |
| `tests/test_rating.py`, `tests/test_mapping.py`, `tests/test_ensemble.py`, `tests/test_raster.py` | add | Tests |

## Acceptance criteria

- [ ] `stage_from_q(rt: RatingTable, cidx: np.ndarray, q: np.ndarray) -> (stage_m: np.ndarray, clipped: np.ndarray[bool])`: vectorised linear interpolation per row; `q` above the top row returns the top stage and `clipped` true; `q <= 0` returns stage 0. Test: fixture order-3 catchment with `q = 20 * 2.0**1.5` returns stage 2.0 within 1e-4.
- [ ] `wet_area`, `hyd_radius`, `top_width` `(rt, cidx, stage) -> np.ndarray` interpolate on stage. `celerity(rt, cidx, q)` returns `dQ/dA` by central differences of `q_cms` over `wet_area_m2`, evaluated at `q`, clipped to `[0.1, 10.0]`. Test on the fixture: analytic `c = 1.5 * a * stage**0.5 / 10` within 10 percent at stage 2.0.
- [ ] `apply_n_scale(q, s)` returns `q / s`; `s = 1.0` is identity.
- [ ] `map_member(cube, q_by_feature: Mapping[int, float], n_scale: float = 1.0, with_velocity: bool = True) -> MemberFields`: for each branch, `stage_lut[cidx] = stage` for catchments whose `feature_id` is in `q_by_feature` and `lake_id == -999`, else `NaN`; `depth = stage_lut[catch] - rem` where `catch >= 0`; set `depth = 0` where `rem < 0`, where `depth < MIN_DEPTH_M`, or where `stage_lut` or `rem` is `NaN` but the cell is covered; mosaic with `np.fmax`; cells covered by no branch are `NaN`. `clipped[feature_id]` is true if any catchment of that feature clipped.
- [ ] Exact test on the fixture: with `q = {103: 20 * 1.5**1.5}` and all others 0, cells in the 103 block have `depth = max(0, 1.5 + 0.1 - 0.4*|row-10| - 0.1) = max(0, 1.5 - 0.4*|row-10|)` after the mosaic takes branch 9's `rem + 0.1` into account correctly, i.e. `fmax(branch0_depth, branch9_depth)` equals `1.5 - 0.4*|row-10|` at rows 7 to 13, and 0 elsewhere in the block; other blocks are 0; cells with `depth` between 0 and 0.03 are 0.
- [ ] Velocity: `v_reach = q / wet_area(stage)` per catchment; `v_cell = v_reach * (depth / hyd_radius(stage)) ** (2/3)` clipped to `[0, 3 * v_reach]`; 0 where depth is 0; test asserts the channel-row cell of block 103 equals `v_reach * (1.5 / R) ** (2/3)` within 1e-3.
- [ ] `reduce_members(low, mid, high: MemberFields) -> StateArrays` fields: `depth_*` copied, `velocity_ms` from mid, `hazard_dv = depth_mid * velocity_ms`, `prob_inundated = mean(depth_m >= MIN_DEPTH_M over members)` as float32, `NaN` propagated where all members are `NaN`.
- [ ] `time_to_exceedance(depth_series: Iterable[tuple[int, np.ndarray]]) -> np.ndarray[3, H, W]` where the iterable yields `(minutes_after_p, depth_mid)` ascending; result per threshold is the first `minutes` with `depth > thr`, `0` if exceeded at minute 0, `-1` if never, `NaN` where never covered. Test with three synthetic frames.
- [ ] `write_depth_cog(path, grid, arrays: StateArrays)` writes float32, 6 bands in `RASTER_BANDS` order, band descriptions set, `units` tags `m, m, m, m/s, m2/s, fraction`, nodata `-9999` replacing `NaN`, DEFLATE, 256 blocks, valid COG per `rio_cogeo.cog_validate`. `write_tte_cog(path, grid, tte)` bands `tte_015, tte_030, tte_060`, units `min`. Reading back with rasterio reproduces arrays exactly (nodata aware) and `dataset.transform` equals `grid.transform`.
- [ ] `render_overlay_png(array, grid, max_px=2048, ramp=DEPTH_RAMP) -> (png_bytes, bounds_3857)`: reprojects to EPSG:3857 with `rasterio.warp.reproject`, bilinear, output size scaled so the longer side is `max_px`; RGBA with alpha 0 below `MIN_DEPTH_M` and at nodata; ramp stops `(0.03, "#bfe3ff"), (0.5, "#6fb3ff"), (1.0, "#2a7fff"), (2.0, "#0a4fc0"), (4.0, "#052a66")` linearly interpolated in RGB, saturated above 4.0. Test: output decodes with Pillow, has the expected size, and a dry-only array yields fully transparent pixels.
- [ ] `flood map --cube tests/fixtures/mini_huc/out/cube --q q.csv --out out.tif` writes a valid COG; with only `q_mid_cms` present, low and high equal mid.
- [ ] `pytest -q` green offline.

## Non-goals and constraints

- No I/O inside `mapping.py` or `ensemble.py` except numpy.
- Do not edit `interfaces.py`.
- Memory: work branch by branch; never stack all branches' depth arrays at once beyond the running `fmax`.

## Assumptions

- The cube's `rem` is metres with `NaN` nodata and `catch` is `cidx` with `-1`, as C01 saves it.

## Open questions

- None.

## Implementer notes

- Stage lookup: `lut = np.full(n_catchments, np.nan, np.float32)`; fill for catchments with a feature in `q_by_feature` via `stage_from_q(rt, idx, q_vec)`; then `stage_grid = np.where(catch >= 0, lut[np.clip(catch, 0, None)], np.nan)`.
- Velocity needs per-catchment `v_reach` and `R` arrays gathered through `catch` the same way.
- `DEPTH_RAMP` is a module constant in `products/raster.py`; colours as `(threshold_m, hex)`.
- Overlay reprojection: destination transform from `rasterio.warp.calculate_default_transform(src_crs, "EPSG:3857", width, height, *bounds)` then scale to `max_px`.
