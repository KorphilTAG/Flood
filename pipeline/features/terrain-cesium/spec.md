# Feature spec

- Slug: terrain-cesium
- Feature: C12. Conditional. Build a Cesium quantized-mesh terrain tileset for the scenario AOI from USGS 3DEP lidar and serve it as static files from the API.
- Status: draft, blocked until the frontend track chooses CesiumJS
- Product refs: `docs/specs/physics-engine-master.md` section 5.4; FeatureBreakdown Physics track item 3; PRD 6.7 item 2.

## Problem

Cesium needs a terrain tileset to drape the flood layer over real ground. deck.gl does not. Only build this if Cesium is chosen.

## In scope

- `flood prep terrain <scenario.json> [--resolution 1|3|10]`: download 3DEP tiles intersecting the AOI, merge and reproject to EPSG:4326, run `cesium-terrain-builder` in Docker, write `data/terrain/<scenario_id>/` with `layer.json`.
- A route `GET /terrain/{scenario_id}/{path:path}` in a new `api/terrain.py` router, mounted by editing one line in `api/app.py` (record as a cross-owner edit).

## Out of scope

Any change to depth products; imagery tiles; Cesium client code.

## Approach

3DEP 1 m tiles from the AWS `usgs-lidar-public` or the 3DEP 1 m DEM bucket via the National Map API listing; fall back to 1/3 arc-second (10 m) if 1 m coverage is incomplete. GDAL merge and warp via rasterio, then `docker run tumgis/ctb-quantized-mesh ctb-tile -f Mesh -C -N -o /out /in/dem.tif` and `ctb-tile -f Mesh -C -N -l -o /out /in/dem.tif` for `layer.json`.

## Files to change

| Path | Action (add/edit) | Why |
|---|---|---|
| `src/flood/ingest/terrain.py` | add | Download, merge, warp, invoke ctb |
| `src/flood/api/terrain.py` | add | Static router |
| `src/flood/api/app.py` | edit, one line | include router |
| `src/flood/cli_prep_terrain.py` | add | `register(sub)` |
| `src/flood/cli.py` | edit | One line under the REGISTER marker |
| `tests/test_terrain.py` | add | Unit tests for tile selection and path safety; network and docker tests marked |

## Acceptance criteria

- [ ] `select_3dep_tiles(aoi_bounds_5070, resolution) -> list[url]` returns the tiles intersecting the AOI reprojected to EPSG:4326.
- [ ] `build_dem(tile_paths, out_path, aoi_bounds)` writes one GeoTIFF in EPSG:4326 covering the AOI with a 1 km buffer.
- [ ] `run_ctb(dem_path, out_dir)` produces `layer.json` and at least one `.terrain` file; skipped with a clear message if Docker is unavailable.
- [ ] `GET /terrain/<scenario_id>/layer.json` returns the file with `Content-Type: application/json`; `.terrain` files return `application/vnd.quantized-mesh` with `Content-Encoding: gzip`; path traversal rejected.
- [ ] Loading the tileset in a Cesium Sandcastle with `CesiumTerrainProvider.fromUrl` shows the corridor terrain.

## Non-goals and constraints

- No scenario literals. Do not start before the frontend decision.

## Assumptions

- Docker is installed on the build machine (it is on the current one).

## Open questions

- Which 3DEP resolution has complete coverage of the corridor; decide at build time.
