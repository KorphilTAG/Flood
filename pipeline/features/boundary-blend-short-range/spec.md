# Feature spec

- Slug: boundary-blend-short-range
- Feature: C13. Stretch. Implement the `nwm_short_range` and `blend` boundary forecast methods and compare them with `trend_relax` in the skill table.
- Status: draft, do not start before C10 merges
- Product refs: `docs/specs/physics-engine-master.md` section 6.5; decision 0001 stage 2; contract 1 section 8.

## Problem

Trend continuation ignores forecast rainfall. NWM short range carries it, with a known low bias. Blending the two, scaled by the observed ratio, may extend skill beyond the travel-time horizon.

## In scope

- `boundary.py`: `nwm_short_range(view, feature_id, tau, ratio)` returning the latest known cycle's discharge at `tau` times `ratio`; `blend(series, view, feature_id, tau, m, weights, ...)` returning `w * trend_relax + (1 - w) * nwm_short_range` with `w = exp(-d / blend_minutes)`, `blend_minutes` default 120.
- `routing.py`: dispatch on `config.boundary_forecast.method` for boundary gauges and inferred reaches.
- Forcing config: `blend_minutes` optional key added to the schema and models (cross-owner edit of `docs/contracts/schemas/forcing-config.schema.json` and C01 models; record it).
- A `flood skill --compare <run_id_a> <run_id_b>` option printing side-by-side summaries.

## Out of scope

Rainfall ingestion (C14). Any change to mapping.

## Approach

Create two runs with identical configuration except the method, compute skill for both, compare.

## Files to change

| Path | Action (add/edit) | Why |
|---|---|---|
| `src/flood/engine/boundary.py` | edit | New methods |
| `src/flood/engine/routing.py` | edit | Dispatch |
| `docs/contracts/schemas/forcing-config.schema.json`, `src/flood/contracts/schemas/forcing-config.schema.json`, `src/flood/contracts/models.py` | edit | `blend_minutes` |
| `src/flood/cli_skill.py` | edit | `--compare` |
| `tests/test_boundary.py`, `tests/test_routing.py` | edit | New cases |

## Acceptance criteria

- [ ] `nwm_short_range` returns the short-range value at `tau` from the latest cycle known at `p`, interpolated in time, times `ratio`; falls back to `trend_relax` when no cycle is known and records source `forecast_trend`; otherwise source `forecast_nwm_sr`.
- [ ] `blend` equals `trend_relax` at `d = 0` and approaches `nwm_short_range` for large `d`.
- [ ] Fixture: with `method = nwm_short_range` and `p = 07:00Z`, reach 101 after `t_last` equals `0.9 * analysis * ratio` from the 06:00Z cycle within 1e-3.
- [ ] Kerr comparison recorded in `changes.md`: skill at 60 and 120 minutes for `trend_relax`, `nwm_short_range`, and `blend`.
- [ ] `pytest -q` green.

## Non-goals and constraints

- Do not change the default method in the Kerr scenario unless the comparison shows a clear improvement; then change the scenario file, not code.

## Assumptions

- C04 `latest_short_range` exists and is filtered by availability.

## Open questions

- None.
