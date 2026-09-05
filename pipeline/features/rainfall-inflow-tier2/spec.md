# Feature spec

- Slug: rainfall-inflow-tier2
- Feature: C14. Stretch. Radar rainfall (MRMS QPE) aggregated per NWM catchment through a simple runoff model to replace or scale lateral inflow on ungauged reaches, extending lead time upstream of the first gauge.
- Status: draft, do not start before C13 merges and the MRMS archive check passes
- Product refs: decision 0001 Tier 2; `docs/specs/physics-engine-master.md` section 6.2 (`qlat`).

## Problem

The South Fork and similar ungauged tributaries are only inferred once their water reaches a gauge. Rainfall over their catchments is observable an hour or more earlier.

## In scope

- Archive check: confirm MRMS `MultiSensor_QPE_01H_Pass2` (or `RadarOnly_QPE_01H`) GRIB2 for the record window is retrievable from the Iowa State mesonet archive; record the URL pattern and sizes in `changes.md`. Stop if not available.
- `ingest/mrms.py`: download hourly QPE for the record, clip to the HUC, aggregate mean rainfall per NWM catchment polygon (`nwm_catchments_proj_subset.gpkg`), write `data/mrms/<scenario_id>/catchment_rain.parquet` with `valid_time, feature_id, rain_mm`.
- `engine/runoff.py`: SCS curve-number runoff with a single scenario-level `curve_number` and a triangular unit hydrograph with `time_to_peak_minutes` from catchment area; produces `qlat_rain(feature_id, tau)`.
- `forcing.py`: when `config.state_estimation.lateral_source == "rain"`, `qlat` uses the runoff series instead of NWM; when `"blend"`, the mean of both. Schema and model additions recorded as cross-owner edits.

## Out of scope

Calibration beyond a single curve number; any 2D hydraulics.

## Approach

Keep it small: one curve number, one unit hydrograph shape, mass-conserving. Judge success only by the skill table at the interior gauges and the South Fork inferred series.

## Files to change

| Path | Action (add/edit) | Why |
|---|---|---|
| `src/flood/ingest/mrms.py`, `src/flood/engine/runoff.py` | add | Ingest and model |
| `src/flood/engine/forcing.py` | edit | `lateral_source` dispatch |
| `docs/contracts/schemas/forcing-config.schema.json`, packaged copy, `src/flood/contracts/models.py` | edit | New keys |
| `src/flood/cli_prep_forcing.py` | edit | `--mrms` flag |
| `tests/test_runoff.py`, `tests/test_mrms.py` | add | Tests |

## Acceptance criteria

- [ ] Runoff test: a 10 mm per hour rainfall for 3 hours on a 100 km2 catchment with `CN = 80` produces a hydrograph whose volume equals the SCS runoff depth times area within 1 percent.
- [ ] Aggregation test on a synthetic raster and two polygons gives exact means.
- [ ] Kerr: `changes.md` reports skill with and without rainfall inflow at 60 and 120 minutes and the South Fork inferred series comparison.
- [ ] `pytest -q` green offline; MRMS download marked `network`.

## Non-goals and constraints

- No scenario literals; curve number and unit hydrograph parameters live in the scenario's forcing config.

## Assumptions

- `cfgrib` or `pygrib` can read MRMS GRIB2 on Windows; if not, use the mesonet's netCDF or PNG products and record the choice.

## Open questions

- Which MRMS product has complete coverage for the record window.
