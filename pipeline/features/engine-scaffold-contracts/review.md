# Review

- Slug: engine-scaffold-contracts
- Spec: `pipeline/features/engine-scaffold-contracts/spec.md`
- Changes: `pipeline/features/engine-scaffold-contracts/changes.md`

## Verdict

PASS

## Summary

Ran `.venv/Scripts/python -m pytest -q` from repo root: **18 passed**. Exercised the CLI directly (`.venv/Scripts/flood.exe scenario validate ...`) for both the valid Kerr scenario and a scenario with `"crs": "EPSG:4326"`, confirming exit codes 0/2 and the printed messages independent of the test suite. Byte-diffed `src/flood/interfaces.py` and `pyproject.toml` against the spec's verbatim blocks (identical) and diffed all 7 copied JSON schemas against `docs/contracts/schemas/*.json` (identical). Read every file named in `changes.md` and confirmed it exists and matches the described content; found no undocumented files added outside the spec's scope other than `src/flood/cli_scenario.py` (implied by the spec's Implementer Notes for `cli.py`, just not listed in the spec's own Files-to-change table) and `tests/test_timing.py`, which `changes.md` explicitly notes as an addition. One implementation quirk noted below (harmless, doesn't affect any criterion).

## Spec coverage

| Criterion | Result | Evidence |
|---|---|---|
| venv + editable install succeeds; `flood --help` lists `scenario` | implemented | `.venv/Scripts/flood.exe --help` prints `usage: flood [-h] {scenario} ...`; `.venv/Scripts/flood.exe` entry point exists and works |
| `flood scenario validate scenarios/kerr-2025-07-04.json` exits 0, prints `OK kerr-2025-07-04`; bad `crs` exits 2 with schema error path | implemented | Ran directly: `OK kerr-2025-07-04` (exit 0); with `crs: EPSG:4326` got `Error at hydrology/aoi/crs (['hydrology', 'aoi', 'crs']): 'EPSG:5070' was expected` (exit 2). `src/flood/cli_scenario.py:11-27` |
| `src/flood/interfaces.py` verbatim | implemented | Byte-diffed against spec's code block — identical |
| `src/flood/contracts/schemas/*.json` byte-identical to `docs/contracts/schemas/*.json` | implemented | `diff` on all 7 files — no differences; also asserted by `tests/test_contracts.py::test_schemas_byte_identical` |
| `tests/test_contracts.py`: examples validate + parse; schemas byte-identical; extra field fails | implemented | `tests/test_contracts.py:19-89`, all pass |
| `pyproject.toml` matches spec block exactly | implemented | Byte-diffed against spec's toml block — identical |
| `.gitignore` has listed entries | implemented | Contains `data/`, `runs/`, `.venv/`, `__pycache__/`, `tests/fixtures/mini_huc/out/`, `*.egg-info/` (plus harmless extras: `*.pyc`, `*.pyo`, `*.pyd`, `.pytest_cache/`) |
| `cli.py` has `# REGISTER:` marker + one register call; `flood scenario validate` | implemented | `src/flood/cli.py:13-14` — marker text and register call match spec verbatim |
| Pydantic models use `extra="forbid"` | implemented | `src/flood/contracts/models.py:33-34` — `BaseContractModel.model_config = ConfigDict(extra="forbid", ...)`, inherited by every model |
| `timegrid.snap_p(06:07:30Z) == 06:05:00Z` | implemented | `tests/test_timegrid.py:19-23`, passes |
| `snap_t(06:07:30Z) == 06:10:00Z` (half rounds up) | implemented | same test, passes; `src/flood/timegrid.py:53-66` rounds `rem_seconds >= half_step` up |
| `snap_t(06:07:29Z) == 06:05:00Z` | implemented | same test, passes |
| `check_pair` codes in order `outside_record`, `t_before_p`, `horizon_exceeded` | implemented | `src/flood/timegrid.py:69-95`; `tests/test_timegrid.py:43-78` covers all three codes plus a valid boundary case (`t-p == 360 min` passes). Implementation's `outside_record` branch also treats `p > record_end` / `t < record_start` as outside-record — a superset of the two conditions the spec names, does not conflict with the required check order or any listed case |
| `to_compact(2025-07-04T06:14:00Z) == "20250704T0614Z"`; round trips | implemented | `tests/test_timegrid.py:30-40`, passes |
| `HandCube.save`/`load` round-trip, NaN-aware, identical `Grid` | implemented | `tests/test_cube.py:10-44`, passes; uses `np.testing.assert_allclose(..., equal_nan=True)` for `rem` |
| File names `meta.json`, `rem_<b>.npy`, `catch_<b>.npy`, `rating_<b>.npz`, `network.parquet`, `gauges.parquet` | implemented | `src/flood/engine/cube.py:64-86`; on-disk output under `tests/fixtures/mini_huc/out/` confirms exact names |
| Fixture: grid 40x20 from bounds (0,0,400,200) | implemented | `tests/fixtures/mini_huc/build.py:23`; `tests/test_fixture.py:15-17` asserts width 40, height 20, crs EPSG:5070 |
| Six-reach topology, orders, levelpath ids 9/8, preferred_branch | implemented | `build.py:31-110`; `test_fixture.py:20-29` asserts topology, orders `[2,2,3,3,3,3]`, levelpath `[9,8,9,9,9,9]`, preferred_branch `[0,0,9,9,9,9]` — all match spec exactly |
| Gauge sites 90000001 (101, boundary), 90000003 (103, interior), 90000005 (105, interior) | implemented | `build.py:113-140`; matches spec's sites/roles/elevations exactly |
| Branch 0 column blocks and `rem = 0.4*|row-10|`; branch 9 for 103-106 with `rem + 0.1` | implemented | `build.py:192-214` — column blocks match spec's col ranges exactly; formulas match verbatim |
| Rating formulas (`q=a*stage**1.5`, a=8 order2/20 order3; top width 10; wet area 10*stage; hyd radius) | implemented | `build.py:142-190` — formulas and `a` values match spec exactly; `hydro_id = 25130000 + reach_id` matches |
| USGS/NWM analysis/short-range series definitions | implemented | `build.py:233-366` — `tri()`, site1/site3/site5 formulas, 00065 formula, analysis `0.5*truth` scaling, short-range `*0.9`/`qlat 0.45` all match spec's stated formulas. Spec does not pin an exact "truth" series for ungauged reaches 104/106; implementer paired 104 with 103's series and 106 with 105's series, a reasonable reading consistent with the topology, not a deviation from anything explicitly stated |
| Junction inference entry | implemented | `build.py:392-400` — `inferred_reach: 102, downstream_gauge: 90000003, subtract_gauges: [90000001], travel_time_minutes: 10` matches spec exactly |
| `exposure_layers: []` | implemented | `build.py:428` |
| `pytest -q` passes with no network access | implemented | Ran locally: `18 passed in 0.63s`; `-m 'not network'` addopts confirmed deselecting a `-m network` run (0 selected) |
| No string in `src/` matches `Kerr\|Hunt\|Guadalupe\|Mystic\|12100201\|0816` | implemented | `tests/test_contracts.py::test_no_scenario_literals_in_src` greps all `*.py` under `src/`; passes. Note: the grep only covers `*.py`, not `src/flood/contracts/schemas/*.json` — but those are generic contract schemas with no scenario-specific literals, so this is not a gap in practice |

## changes.md accuracy

`changes.md`'s "Files touched" table was cross-checked against the actual untracked file set (`git status`, directory listing under `src/`, `tests/`, `scenarios/`). Every file it lists exists with the described purpose, and no source file exists that isn't listed (build artifacts `*.egg-info/`, `__pycache__/`, and the gitignored `tests/fixtures/mini_huc/out/` fixture output are correctly excluded from the table since they are generated, not authored). The quoted `pytest -q` output (18 passed) and CLI output (`OK kerr-2025-07-04`) in "How to verify" were reproduced independently and match.

One inaccuracy: `changes.md` doesn't mention that `build()` (`tests/fixtures/mini_huc/build.py:437-449`) saves the cube twice — once directly into `out_dir` and again into `out_dir/cube` (`cube.save(p)` then `cube.save(p / "cube")`). The second copy is dead output: `conftest.py`'s `mini_huc_dir`/`mini_cube` fixtures only ever read from the root `out/` directory, never `out/cube/`. This is harmless (gitignored, doesn't affect any test or acceptance criterion) but is undocumented redundant behavior worth cleaning up.

## Out-of-scope drift

None found. No download, raster-clipping, physics, API route, or clock code was introduced — `HandCube.save`/`load` only persists/reads arrays already constructed by the fixture builder, consistent with "No downloading or clipping here." Pydantic models and `jsonschema` validation are both present as the spec's two-track approach requires. No scenario-specific literals leaked into `src/`.

## Required follow-ups

None required for PASS. Optional cleanup (does not block the verdict):
- Remove the redundant `cube.save(p / "cube")` call in `tests/fixtures/mini_huc/build.py:444`, or document why the duplicate `out/cube/` copy exists.
