# 0006. Start with files and in-process serving; adopt PostGIS or TiTiler only on stated triggers

Status: accepted, 2026-09-05.

## Context

The PRD names PostGIS for exposure layers and TiTiler for tile serving. Both are good tools and both are new to the team. Standing up, configuring, and debugging unfamiliar infrastructure during a hackathon costs time that the forecasting layer needs more. The simpler alternatives meet the requirements as currently understood.

## Decision

Start simple. Escalate only when a listed trigger fires.

Storage and serving to start with:

| Need | Start with | Instead of |
|---|---|---|
| Depth, velocity, probability rasters | Cloud-Optimized GeoTIFF files on disk under `runs/<run_id>/`, served as static files by the API | TiTiler |
| Map overlays for the verifier | PNG images in Web Mercator rendered by the engine, served by the API | Tile server |
| Tiles for the product UI, if needed | `rio-tiler` called in-process from a FastAPI route | TiTiler as a separate service |
| Exposure layers with stable feature IDs | GeoPackage or GeoParquet files read with geopandas, spatial index in memory | PostGIS |
| Reach tables, forcing series, hydrotable | Parquet files | Database |
| Run manifests and session state | JSON files, or SQLite via the standard library if concurrent writes appear | Postgres, Redis |
| Real-time push to the UI | WebSocket from the FastAPI process | Redis pub/sub |

Triggers for escalation:

- Adopt TiTiler when the product UI needs dynamic tiles across many zoom levels and in-process `rio-tiler` cannot keep tile latency acceptable, or when more than one process must serve tiles.
- Adopt PostGIS when exposure intersection queries over the corridor take more than a second or two with in-memory spatial indexes, when the exposure dataset grows beyond what fits comfortably in memory, or when the UI needs ad-hoc spatial queries the API does not already expose.
- Adopt Postgres or Redis for state when more than one session runs concurrently or more than one process must write state.

The legacy USGS endpoint is retired ([0000](0000-verified-data-findings.md)). Gauge ingestion uses the new OGC API from the start.

## Consequences

- The whole backend runs as one Python process plus files, which is easy to develop, easy to demo from a laptop, and easy to explain.
- The file layout under `runs/` becomes part of contract 1, since consumers read it directly. It is fixed early ([0004](0004-shared-backend-services-before-physics.md)).
- If a trigger fires, the switch is local: the same COGs are what TiTiler would serve, and the same GeoPackage can be loaded into PostGIS with one command. Nothing upstream changes.

## Open questions

- Whether the product UI's 3D terrain draping needs true XYZ tiles at all, or whether a single overlay image per timestep at the corridor's extent is enough for the demo. The UI owner should decide once Cesium is running.
