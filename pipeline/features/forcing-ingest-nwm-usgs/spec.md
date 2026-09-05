# Feature spec

- Slug: forcing-ingest-nwm-usgs
- Feature: C04. Download and subset NWM analysis and short-range channel output and USGS continuous records to Parquet, and implement `ForcingView`, the object that answers "what is known at cutoff p", including availability latency, outages, and the levelpath bias ratio.
- Status: draft
- Product refs: `docs/specs/physics-engine-master.md` sections 4, 5.2, 5.3, 6.2, 6.3; decision 0002; `docs/decisions/0000-verified-data-findings.md` (endpoints); C01 spec (`ForcingView` protocol, fixture forcing files).

## Problem

The engine must never use a record a responder could not have had at `p`. That requires ingesting the sources with valid and issue times preserved, and a single view object that filters by availability.

## In scope

- `flood prep forcing <scenario.json> [--data-dir data] [--keep-raw] [--skip-nwm] [--skip-usgs]`.
- `ingest/nwm.py`: list, download, subset, append to Parquet, delete raw.
- `ingest/usgs.py`: OGC API paging, unit conversion, Parquet.
- `engine/forcing.py`: `ParquetForcingView` implementing `ForcingView`.

## Out of scope

Routing, mapping, products, API. Rainfall (C14). Any use of the legacy `waterservices.usgs.gov` endpoint.

## Approach

NWM files are listed via the GCS JSON API by prefix, downloaded with `httpx` streaming, opened with `xarray.open_dataset(engine="h5netcdf")`, subset with `.sel(feature_id=ids)` after intersecting with the file's IDs, and appended to a Parquet dataset. USGS is paged with `limit=10000` following `next` links. `ParquetForcingView` loads the three Parquet files once per scenario and applies the cutoff rules in memory.

## Files to change

| Path | Action (add/edit) | Why |
|---|---|---|
| `src/flood/ingest/nwm.py` | add | NWM download and subset |
| `src/flood/ingest/usgs.py` | add | USGS fetch |
| `src/flood/engine/forcing.py` | add | `ParquetForcingView`, `load_forcing_store` |
| `src/flood/cli_prep_forcing.py` | add | `register(sub)` for `prep forcing` |
| `src/flood/cli.py` | edit | One line under the REGISTER marker |
| `tests/test_nwm.py`, `tests/test_usgs.py`, `tests/test_forcing.py` | add | Tests with canned fixtures |
| `tests/fixtures/forcing/` | add | One tiny synthetic channel_rt netCDF written by a test helper; one recorded USGS JSON page pair |

## Acceptance criteria

- [ ] `nwm.analysis_names(record_start, record_end) -> list[str]` yields `nwm.YYYYMMDD/analysis_assim/nwm.tHHz.analysis_assim.channel_rt.tm00.conus.nc` for every hour with `valid_time` in the closed window, where `valid_time` equals the cycle time for `tm00`. `short_range_names(record_start, record_end, max_lead_hours)` yields `f001..f{max_lead_hours:03d}` for every hourly cycle with `issue_time` in the window.
- [ ] `nwm.subset_file(path, feature_ids) -> DataFrame` returns columns `valid_time` (UTC), `feature_id` (int64), `q_cms`, `v_ms`, `qlat_cms = qSfcLatRunoff + qBucket`, reading `time` and `reference_time` coordinates; for short range also `issue_time` from `reference_time`. Test builds a 5-feature netCDF with `xarray` using `scale_factor` 0.01 on `streamflow` and asserts decoded values.
- [ ] Parquet outputs: `data/nwm/<scenario_id>/analysis.parquet` and `short_range.parquet` with the columns of master spec 5.2; re-running skips files already recorded in `data/nwm/<scenario_id>/manifest.json`.
- [ ] `usgs.fetch_continuous(site, parameter, start, end) -> DataFrame` pages until no `next` link; converts `00060` cfs to cms by `0.028316846592` and `00065` ft to m by `0.3048`; columns `site` (str), `valid_time` (UTC), `parameter`, `value_si` (float32), `approval` (str or null). Test uses a recorded two-page fixture served through `httpx.MockTransport`.
- [ ] `ParquetForcingView(scenario, store, p)` implements every method of `ForcingView`:
  - `obs_q(site)`: rows with `parameter == "00060"`, `valid_time + usgs latency <= p`, minus outage windows from `scenario_overrides` of type `gauge_outage` for that site; sorted, UTC index. Empty Series if none.
  - `obs_wse(site)`: same for `00065`, plus `gauge_altitude_m` for the site from the cube gauges table (passed in as `gauges: DataFrame`).
  - `nwm_analysis(feature_id)`: `valid_time + analysis latency <= p`.
  - `latest_short_range(feature_id)`: rows of the single cycle with the greatest `issue_time` satisfying `issue_time + short-range latency <= p`; empty if none.
  - `qlat(feature_id, tau)`: analysis value at the last `valid_time <= tau` if that value is known at `p`; else the latest short-range value at the last `valid_time <= tau`; else the last known analysis value; else 0.0. Multiplied by `ratio(feature_id)`.
  - `ratio(feature_id)`: per master spec 6.3: find the gauge on the same `levelpath_id` nearest downstream (walk `to_feature_id`), else nearest upstream (BFS over reverse edges), with role `interior` or `boundary`; take the latest time where both `obs_q` and `nwm_analysis` are known at `p` and the observation is at least 0.1 cms; `clamp(obs / nwm, ratio_clamp)`; 1.0 when no gauge on the levelpath, when `bias_correction == "none"`, or when either series is empty. Cached per view.
- [ ] Availability tests on the fixture forcing: with `p = 03:00Z` and latency 5, `obs_q("90000001").index.max() == 02:55Z`; with analysis latency 60, `nwm_analysis(103).index.max() == 02:00Z`; with short-range latency 90, `latest_short_range(103)` at `p = 07:29Z` comes from the `00:00Z` cycle and at `p = 07:30Z` from the `06:00Z` cycle. A `gauge_outage` from `02:30Z` removes rows at and after `02:30Z` for that site only.
- [ ] Ratio test on the fixture: analysis is `0.5 * truth`, so `ratio(103)` equals 2.0 within 1e-6 and `ratio(102)` (levelpath 8, no gauge) equals 1.0.
- [ ] `pytest -q` green offline; `pytest -m network tests/test_nwm.py::test_list_kerr_day` lists 24 analysis names for a single day and confirms the first exists with a HEAD request.

## Non-goals and constraints

- Do not edit `interfaces.py`.
- No hardcoded sites, dates, or HUCs; the scenario supplies them. Hosts live in module constants `GCS_LIST_URL`, `GCS_OBJECT_URL`, `USGS_CONTINUOUS_URL`.
- Delete each raw NWM file after subsetting unless `--keep-raw`.

## Assumptions

- `channel_rt` files carry variables `streamflow`, `velocity`, `qSfcLatRunoff`, `qBucket` with CF `scale_factor`, dimension `feature_id`, coordinates `time` and `reference_time`.
- The OGC `continuous` collection returns `features[].properties` with `time`, `value`, `parameter_code`, `approval_status` (optional) and `links` with `rel == "next"`.

## Open questions

- None.

## Implementer notes

- `GCS_LIST_URL = "https://storage.googleapis.com/storage/v1/b/national-water-model/o"` with params `prefix`, `fields=items(name,size),nextPageToken`; `GCS_OBJECT_URL = "https://storage.googleapis.com/national-water-model/{name}"`.
- `USGS_CONTINUOUS_URL = "https://api.waterdata.usgs.gov/ogcapi/v0/collections/continuous/items"`; params `monitoring_location_id=USGS-{site}`, `parameter_code`, `datetime=start/end`, `f=json`, `limit=10000`.
- Store loader: `load_forcing_store(scenario, data_dir) -> ForcingStore` dataclass with three DataFrames and the latency map built from `scenario.forcing_defaults.sources`.
- Outage removal: `valid_time >= from` and, if `to` present, `valid_time < to`.
- Downstream walk for `ratio`: follow `to_feature_id` while the next reach has the same `levelpath_id`; stop at 0.
