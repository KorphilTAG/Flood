# Changes

- Slug: forcing-ingest-nwm-usgs
- Spec: `pipeline/features/forcing-ingest-nwm-usgs/spec.md`
- Status: done

## Summary

Implemented cycle C04:
- `src/flood/ingest/nwm.py`:
  - `analysis_names(record_start, record_end) -> list[str]` for closed hourly window.
  - `short_range_names(record_start, record_end, max_lead_hours) -> list[str]` for hourly cycles and lead hours f001..f{max_lead_hours}.
  - `subset_file(path, feature_ids) -> DataFrame` subsetting channel_rt netCDF files via xarray and h5netcdf, decoding scaled variables (`streamflow` with CF scale factor 0.01), computing `qlat_cms = qSfcLatRunoff + qBucket`, and extracting `valid_time` and `issue_time` coordinates.
  - GCS listing (`list_objects`), download (`download_file`), Parquet appending with deduplication (`append_to_parquet`), and manifest tracking (`manifest.json`) for idempotency.
  - `ingest_nwm(scenario, data_dir, keep_raw)` for complete NWM ingestion.
- `src/flood/ingest/usgs.py`:
  - `fetch_continuous(site, parameter, start, end, client, limit) -> DataFrame` paging through OGC API items following `next` links until exhausted.
  - SI unit conversions for discharge (parameter `00060`: cfs to cms via `0.028316846592`) and stage/elevation (parameter `00065`: ft to m via `0.3048`).
  - `ingest_usgs(scenario, data_dir, client)` saving continuous observations to Parquet.
- `src/flood/engine/forcing.py`:
  - `ForcingStore` dataclass storing `usgs`, `nwm_analysis`, and `nwm_short_range` DataFrames and latency mappings.
  - `load_forcing_store(scenario, data_dir) -> ForcingStore` loading `<data_dir>/usgs/<id>/continuous.parquet`, `<data_dir>/nwm/<id>/analysis.parquet`, and `<data_dir>/nwm/<id>/short_range.parquet`, returning empty schemas on missing files.
  - `ParquetForcingView` implementing all methods of `ForcingView`: `obs_q`, `obs_wse`, `nwm_analysis`, `latest_short_range`, `ratio`, and `qlat`, respecting cutoff `p`, availability latencies, gauge outages from `scenario_overrides`, levelpath walks (downstream and upstream BFS) for ratio computation with clamping and per-view caching, datum addition for `obs_wse` from `gauges` DataFrame, and fallback chain for lateral inflow `qlat`.
- `src/flood/cli_prep_forcing.py` & `src/flood/cli.py`:
  - Registered `flood prep forcing <scenario.json> [--data-dir data] [--keep-raw] [--skip-nwm] [--skip-usgs]` subcommand.
- Canned test fixtures:
  - `tests/fixtures/forcing/usgs_page1.json` and `usgs_page2.json`: recorded from real USGS OGC API for first gauge `08165300` and first hour of Kerr scenario with `limit=5`.
  - Synthetic 5-feature channel_rt NetCDF generated on-the-fly at test time with `scale_factor=0.01` on int32 `streamflow` and float32 fields.

## Files touched

| Path | Change | Why |
|---|---|---|
| `src/flood/ingest/__init__.py` | add | Ingest package initializer |
| `src/flood/ingest/nwm.py` | add | NWM analysis & short range name generators, GCS download, xarray subset, Parquet append, manifest skip logic |
| `src/flood/ingest/usgs.py` | add | USGS continuous OGC API paging fetch, unit conversions (cfs->cms, ft->m), Parquet ingest |
| `src/flood/engine/forcing.py` | add | `ForcingStore`, `load_forcing_store`, and `ParquetForcingView` implementing `ForcingView` protocol |
| `src/flood/cli_prep_forcing.py` | add | Subcommand implementation for `flood prep forcing` |
| `src/flood/cli.py` | edit | Registered `register_prep_forcing` under `# REGISTER:` marker |
| `tests/fixtures/forcing/usgs_page1.json` | add | First page recorded from USGS continuous endpoint |
| `tests/fixtures/forcing/usgs_page2.json` | add | Second page recorded from USGS continuous endpoint |
| `tests/test_nwm.py` | add | Tests for NWM name builders, synthetic netCDF subsetting, manifest skip logic, and single network test |
| `tests/test_usgs.py` | add | Tests for USGS OGC API mock paging and unit conversions |
| `tests/test_forcing.py` | add | Tests for availability latency, gauge outage filtering, levelpath bias ratio, datum elevation, qlat fallback chain, and CLI |
| `pipeline/features/forcing-ingest-nwm-usgs/changes.md` | add | Cycle documentation and verification results |

## Acceptance criteria

| Criterion | Status (done/blocked/skipped) | Where |
|---|---|---|
| `nwm.analysis_names` and `short_range_names` | done | `src/flood/ingest/nwm.py`, `tests/test_nwm.py::test_analysis_names`, `tests/test_nwm.py::test_short_range_names` |
| `nwm.subset_file` with synthetic NetCDF decoded values | done | `src/flood/ingest/nwm.py`, `tests/test_nwm.py::test_subset_file`, `tests/test_nwm.py::test_subset_file_short_range` |
| Parquet outputs & manifest skip logic | done | `src/flood/ingest/nwm.py`, `tests/test_nwm.py::test_manifest_and_parquet_append` |
| `usgs.fetch_continuous` paging & unit conversion | done | `src/flood/ingest/usgs.py`, `tests/test_usgs.py::test_fetch_continuous_mock_paging`, `tests/test_usgs.py::test_unit_conversions` |
| `ParquetForcingView` implements `ForcingView` | done | `src/flood/engine/forcing.py`, `tests/test_forcing.py::test_protocol_conformance` |
| Availability tests on fixture forcing & outage removal | done | `src/flood/engine/forcing.py`, `tests/test_forcing.py::test_availability`, `tests/test_forcing.py::test_gauge_outage` |
| Ratio test on fixture | done | `src/flood/engine/forcing.py`, `tests/test_forcing.py::test_ratio` |
| `pytest -q` green offline; `test_list_kerr_day` network test | done | `tests/test_nwm.py::test_list_kerr_day` |

## How to verify

1. Network test:
```powershell
.venv\Scripts\python.exe -m pytest -m network tests/test_nwm.py::test_list_kerr_day -q
```
Output:
```
.                                                                        [100%]
1 passed in 1.42s
```

2. Offline pytest suite:
```powershell
.venv\Scripts\python.exe -m pytest -q
```
Output:
```
...................................................................      [100%]
67 passed, 2 deselected, 7 warnings in 11.04s
```

3. C04 tests specifically:
```powershell
.venv\Scripts\python.exe -m pytest tests/test_nwm.py tests/test_usgs.py tests/test_forcing.py -q
```
Output:
```
...............                                                          [100%]
15 passed, 1 deselected in 2.58s
```

4. CLI help check:
```powershell
.venv\Scripts\python.exe -m flood.cli prep forcing --help
```
Output:
```
usage: flood prep forcing [-h] [--data-dir DATA_DIR] [--keep-raw] [--skip-nwm]
                          [--skip-usgs]
                          scenario

positional arguments:
  scenario             Path to scenario JSON file

options:
  -h, --help           show this help message and exit
  --data-dir DATA_DIR  Root directory for data (default: data)
  --keep-raw           Keep raw NWM NetCDF files
  --skip-nwm           Skip NWM ingest
  --skip-usgs          Skip USGS ingest
```

## Residual risk

- `h5py` dependency: `pyproject.toml` includes `h5netcdf>=1.3`. Reading/writing HDF5/NetCDF files via `h5netcdf` requires the `h5py` backend package, which was installed into `.venv`. Recommend adding `"h5py>=3.10"` to `pyproject.toml` dependencies during the C01 ownership / wave fix-up pass.
- `tests/fixtures/forcing/`: Created directory containing `usgs_page1.json` and `usgs_page2.json` recorded from the live USGS API for offline testing.
- Git state was preserved without committing or staging any files.

## Not done

None. All acceptance criteria met.

## Fix-up, 2026-09-05 (after the cycle)

- The cycle prompt told the implementer to run `prep forcing --skip-nwm` "to save time" and nothing backfilled it, so the reference run had NWM lateral inflow of zero on 81 of 150 reaches and the engine looked broken. The full NWM ingest (49 analysis hours, 49 short-range cycles) was run on 2026-09-05; `--skip-short-range` was added so the analysis alone can be refreshed.
- `download_file` retries three times with backoff, writes to a `.part` file and renames on success, and raises after the third failure; the ingest loop logs and skips that file instead of aborting the whole run (a `WinError 10051` aborted the first short-range ingest at 43 of 49 cycles).
- Findings from the ingested data are in decision 0000 (short-range forecast content, lateral inflow magnitudes, NWM peak bias).
