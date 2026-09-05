# Feature spec

- Slug: second-scenario-smoke
- Feature: C11. Prove decision 0008 by adding a second real scenario file for a different HUC8 and running prep and hindsight with zero code changes.
- Status: draft
- Product refs: decision 0008 (generality acceptance test); `docs/specs/physics-engine-master.md` acceptance criterion 5; `docs/contracts/scenario.md`.

## Problem

If Kerr County assumptions leaked into code, the product claim is false. The cheapest proof is a second basin.

## In scope

- `scenarios/llano-2018-10-16.json`: Llano River flood, 16 October 2018, which is within the NWM operational archive on GCS and appears in the AAR corpus list.
- Running `flood prep hand`, `flood prep forcing`, `flood run create`, `flood run state --p hindsight` and recording results in `changes.md`.
- A test that loads every file in `scenarios/` and validates it.

## Out of scope

Any change under `src/`. If a change is needed, this cycle stops and reports the leak as a `FAIL` item for the fix-up pass.

## Approach

Look up the HUC8 and NWM `feature_id` for gauge 08151500 (Llano River at Llano) from the USGS monitoring-locations API and the HAND `usgs_elev_table.csv` for the candidate HUC. Set the AOI to a corridor around Llano and Kingsland with bounds that are multiples of 10 in EPSG:5070. Record 2018-10-15T00:00:00Z to 2018-10-18T00:00:00Z. Declare gauges with roles, no junction inferences unless an ungauged tributary at a gauged confluence is obvious, an empty exposure registry, and no decision points.

## Files to change

| Path | Action (add/edit) | Why |
|---|---|---|
| `scenarios/llano-2018-10-16.json` | add | Second scenario |
| `tests/test_scenarios_dir.py` | add | Validates every scenario file |

## Acceptance criteria

- [ ] The scenario validates with `flood scenario validate`.
- [ ] `flood prep hand scenarios/llano-2018-10-16.json` completes; the cube has at least two branches; the network contains the reach carrying gauge 08151500.
- [ ] `flood prep forcing` completes for USGS and NWM analysis within the record; short range may be skipped with `--skip-nwm-short-range` if that flag exists, otherwise included.
- [ ] `flood run create` then `flood run state <run_id> --p hindsight --t 2018-10-16T18:00:00Z --write` produces a valid `depth.tif` and `reaches.parquet` whose rows validate.
- [ ] `git diff --stat master -- src/` is empty at the end of the cycle.
- [ ] `changes.md` records the HUC8 used, the gauge feature IDs, the AOI bounds, product sizes, and `compute_ms`.

## Non-goals and constraints

- No exposure data, no decision points; this is a physics-only smoke test.
- Network access required; mark any pytest as `network`.

## Assumptions

- HAND FIM 4.9.9.0 exists for the Llano HUC8 on the same bucket (expected HUC8 `12090204`; confirm from the monitoring-locations record `hydrologic_unit_code`).
- The GCS NWM archive contains `nwm.20181015` to `nwm.20181018`.

## Open questions

- None.

## Implementer notes

- Monitoring locations: `https://api.waterdata.usgs.gov/ogcapi/v0/collections/monitoring-locations/items?id=USGS-08151500&f=json`.
- Use the HAND `usgs_elev_table.csv` for the HUC to get `feature_id` for each gauge, exactly as C02 does.
