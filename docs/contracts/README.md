# Contracts

The data contracts between components. Agree these first, stub them with canned data, then build behind them (architecture doc section 6, PRD section 8, decision [0004](../decisions/0004-shared-backend-services-before-physics.md)).

| # | Contract | Producer | Consumers | Document | Status |
|---|---|---|---|---|---|
| 0 | Scenario file and exposure layer registry | Humans | Every component | [scenario.md](scenario.md) | Drafted 2026-09-05 |
| 1 | Physics products: manifest, rasters, reach and gauge tables, engine API | Physics engine | Impact extractor, run store, verifier UI, product UI | [contract-1-physics-products.md](contract-1-physics-products.md) | Drafted 2026-09-05 |
| 2 | Impact JSON | Impact extractor | LLM layer, UI | [contract-2-impact-products.md](contract-2-impact-products.md) | Defined 2026-09-05 |
| 3 | Overlay JSON | LLM enrichment agent | UI | To be written in the master spec | |
| 4 | Session state | Session state store | LLM layer, UI, training mode, AAR generator | To be written in the master spec | |

Machine-readable schemas are JSON Schema 2020-12 under [schemas/](schemas/). Every schema has at least one example under [examples/](examples/) that validates against it. A change that breaks a consumer bumps `schema_version`'s major number.

## Conventions shared by every contract

**Time.** All timestamps are UTC, ISO 8601, second precision, with a `Z` suffix: `2025-07-04T06:14:00Z`. In file paths the compact form `20250704T0614Z` is used, because colons are illegal in Windows paths. Local time is a display concern only; the scenario file carries the IANA timezone. The engine's time grid is 5 minutes.

**Two times per engine query.** `p` is the knowledge cutoff, `t` the target, `t >= p` (decision [0002](../decisions/0002-information-horizon-p-and-target-t.md)). Only records whose availability time is at or before `p` may inform a product. Hindsight is `p` at the end of the record.

**Feature IDs.** Every reference to a geographic thing is a string `<layer_id>:<source_id>` (decision [0008](../decisions/0008-scenario-is-data-not-code.md)). Reserved layer IDs: `reach` (NWM feature_id, decimal), `gauge` (USGS site number as USGS prints it, leading zero kept), `aar` (corpus citation chunk, defined in contract 2). Every other layer ID is declared in the scenario's exposure registry. Regex for any feature ref: `^[a-z][a-z0-9_]{0,31}:[A-Za-z0-9_.-]{1,64}$`. Nothing downstream of the engine ever emits a raw coordinate for the LLM to read.

**Space.** Rasters are EPSG:5070 (NAD83 Conus Albers) at 10 m, on the grid fixed in the run manifest. Vector exposure data may be stored in any CRS and is reprojected at load. Bounds are `[xmin, ymin, xmax, ymax]`. Affine transforms are in GDAL order `[a, b, c, d, e, f]` meaning `x = a*col + b*row + c`, `y = d*col + e*row + f`.

**Nodata.** Float rasters use `-9999` for outside-domain and `0` for dry. Integer-coded rasters state their nodata in the band metadata.

**Units.** SI in every field name: `_m`, `_cms` (cubic metres per second), `_ms` (metres per second), `_m_per_h`, `_min`. Feet and cfs are converted at ingest and never stored.

**Identifiers.** `run_id`, `scenario_id`: `^[a-z0-9][a-z0-9-]{2,63}$`.

**Scenario is data.** No basin name, site number, HUC code, or date appears in code. All of it comes from the scenario file.
