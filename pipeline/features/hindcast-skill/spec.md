# Feature spec

- Slug: hindcast-skill
- Feature: C10. Hindcast skill: for a grid of cutoffs and horizons, error of predicted discharge at each gauge against observation and against a persistence baseline, and extent overlap against hindsight; written to `skill.parquet` and served by the existing `/skill` route.
- Status: draft
- Product refs: `docs/specs/physics-engine-master.md` section 10 and acceptance criterion 2; decision 0001 stage 5.

## Problem

Decision 0001 requires the engine to demonstrate that it predicts. Without a measured, displayed skill number the claim is untestable.

## In scope

- `skill/hindcast.py`: `compute_skill(run, cutoffs, horizons, iou_threshold_m=0.15) -> DataFrame`.
- `flood skill <run_id> [--cutoff-step-min 30] [--horizons 0,30,60,120,240]`.
- Writing `runs/<run_id>/skill.parquet` and a summary block appended to the run's `limitations` in `run.json` when the target is not met.

## Out of scope

The HTTP route (C07 already serves the file), the verifier table (C09), any model change.

## Approach

For each cutoff `p` on the grid inside the record, take the routed series for `p` from `Run.routed` and the hindsight series. For each gauge with an observation at `p + h`: predicted mid discharge from the `p` series at `p + h`, persistence as the observed value at the last time known at `p`, truth as the observed value at `p + h`. Extent IoU compares `depth_mid >= threshold` from `Run.state(p, p + h)` against `Run.state("hindsight", p + h)`; computed only for horizons `60` and `120` to bound cost.

## Files to change

| Path | Action (add/edit) | Why |
|---|---|---|
| `src/flood/skill/__init__.py`, `src/flood/skill/hindcast.py` | add | Computation |
| `src/flood/cli_skill.py` | add | `register(sub)` for `skill` |
| `src/flood/cli.py` | edit | One line under the REGISTER marker |
| `tests/test_skill.py` | add | Fixture tests |

## Acceptance criteria

- [ ] `skill_rows(run, p, horizons) -> list[dict]`: one row per gauge per horizon with keys `gauge_ref, site, feature_id, p, horizon_minutes, t, observed_q_cms, predicted_q_mid_cms, predicted_q_low_cms, predicted_q_high_cms, persistence_q_cms, abs_error_cms, persistence_abs_error_cms, within_band (observed between low and high)`; rows skipped when no observation exists at `t` in the full record.
- [ ] `compute_skill(run, cutoffs, horizons, iou_threshold_m) -> DataFrame` concatenates rows for all cutoffs and adds `iou_015` (null except at horizons 60 and 120) computed as `intersection / union` of `depth_mid >= threshold` masks between the forecast and hindsight states at `t`, ignoring `NaN` cells.
- [ ] `summarise(df) -> DataFrame` groups by `gauge_ref, horizon_minutes` with `mae_cms, persistence_mae_cms, bias_cms, coverage (mean within_band), n, skill = 1 - mae_cms / persistence_mae_cms, iou_015 (mean)`.
- [ ] `write_skill(run, df, summary)` writes `runs/<run_id>/skill.parquet` with the summary rows (this is what `/skill` serves) and `skill_detail.parquet` with the full rows.
- [ ] Target check: for gauges with role `interior` and horizons 60 and 120, if `skill <= 0` for any, append to `run.json` `limitations` one line per failing pair: `"Hindcast skill at <gauge_ref> for <h> min horizon did not beat persistence (MAE <x> vs <y> cms)."` and rewrite `run.json` validating against the manifest schema. If all pass, append one line stating the median skill at 60 and 120 minutes.
- [ ] Fixture test: run `compute_skill` on `mini-huc` with cutoffs every 60 minutes from 01:00Z to 09:00Z and horizons `0, 30, 60`; horizon 0 rows have `abs_error_cms < 1e-3` at controlled gauges; `summarise` returns rows for each gauge and horizon; `skill.parquet` is written; the `/skill` route returns its rows when the API tests import.
- [ ] `flood skill <run_id> --runs-dir <dir> --data-dir <dir>` prints the summary table.
- [ ] `pytest -q` green offline.

## Non-goals and constraints

- Do not change routing or mapping to improve a number. Report it.
- Do not edit `interfaces.py`, C06 files, or C07 files.

## Assumptions

- `Run.routed(p_internal)` and `Run.state` exist per the C06 spec; the `Run` exposes `scenario` and `cube`.

## Open questions

- None.

## Implementer notes

- Observations for truth come from the full record: construct a `ParquetForcingView` at `record_end` for the run and use `obs_q(site)`.
- Persistence: `obs_q` from the view at `p`, last value.
- Keep IoU cost bounded: reuse `Run.state` (which caches routed series) and compute only the two horizons.
