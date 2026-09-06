# 0000. Verified facts about the source data

Status: findings, verified 2026-09-05 by anonymous HTTP reads. Not a decision, but every later record leans on these.

## HAND FIM 4.9.9.0, HUC8 12100201

Bucket prefix: `https://ciroh-owp-hand-fim.s3.amazonaws.com/hand_fim_4_9_9_0/12100201/`

- Grid is EPSG:5070 at 10 m, tiled 256x256 GeoTIFF, LZW. Branch 0 raster is 15558x6404, about 100 million cells. Each branch has its own extent, so all branches must be clipped to one common grid before mosaicking.
- `rem_zeroed_masked_<branch>.tif` (the HAND raster) is int16 in millimetres, nodata 32767. NOAA's `tools/inundation.py` multiplies stage by 1000 in int16 mode and drops depths under 30 mm. The catchment raster `gw_catchments_reaches_filtered_addedAttributes_<branch>.tif` is int16 HydroID, nodata 0.
- Catchment rasters are int16 and store the HydroID with the branch's `hydroid_prefix.txt` stripped: full HydroID = prefix × 10000 + raster value (prefix is `2513` for every branch of this HUC; value 0 is nodata). The hydrotable's `HydroID Int16` column holds the same stripped value. Found 2026-09-05 when the first Kerr product mapped nothing.
- The HUC-level `hydrotable.parquet` is a reduced table (HUC, branch_id, HydroID and feature_id as strings, stage, discharge_cms, SurfaceArea, LakeID, Bathymetry_source). Slope, roughness, wetted area, hydraulic radius, top width, length and order exist only in `hydrotable.csv` and the per-branch `hydroTable_<b>.csv`.
- HydroIDs repeat across branches. The HUC rating table has 1964 unique (branch_id, HydroID) pairs but only 1683 unique HydroIDs. Every lookup must be keyed by both. 134 NWM feature_ids appear in both branch 0 and a levelpath branch; NOAA's mosaic step takes the per-cell maximum across branches.
- `hydrotable.csv` at HUC level is 67 MB (also `.parquet`, `.feather`). 84 stage rows per catchment at 0.3048 m steps up to 25.3 m. Columns include feature_id, discharge_cms, SLOPE, ManningN (0.06 everywhere), channel_n 0.07, overbank_n 0.11 to 0.13, WetArea, HydraulicRadius, TopWidth, LENGTHKM, LakeID (-999 means not a lake), calb_applied. Only 15 catchments carry a USGS-calibrated curve. 169 catchments have AI-based bathymetry applied.
- 12 branches. Levelpath 1619000006 is the Guadalupe main stem including the North Fork: 144 NWM reaches, 8 gauges. Levelpath 1619000016 is the South Fork: 30 reaches, 31 km, stream order 3, no gauge. Levelpath 1619000015 is Johnson Creek with gauge 08166000.
- Two reaches in the corridor between Hunt and Kerrville (feature IDs 3586198, 412 m, and 3585624, 185 m) plus five short connectors have no HAND catchment (`representative_cidx` -1) and a recorded slope of 0. Routing must not give them a slope-only celerity: at 0.1 m/s they become 69 and 31 minute reservoirs that flatten the whole wave (decision 0010).
- The synthetic rating curves overstate stage at flood flows on the gauged reaches, and the engine inherits this because it uses FIM's final `discharge_cms` column unchanged (`calb_applied` is false on the Hunt, North Fork and Kerrville catchments; 29 of the 1964 (branch, HydroID) pairs carry a USGS calibration). Measured against the observed gauge-height rise from the 07:00Z base on 4 July 2025: Hunt (HydroID 25130197, `SLOPE` exactly 0.001) HAND stage 24.4 m at 8920 cms against a 9.0 m observed rise, 5.9 m at 377 cms against 2.1 m, so about 2.7 times; North Fork 4.4 m at 374 cms against 2.9 m, about 1.5 times; Kerrville 15.7 m (branch 0) or 13.5 m (branch 1619000006) at 8438 cms against an 11.1 m rise, 1.2 to 1.4 times. Below about 30 cms the sign flips and HAND understates the rise by half. Depth rasters at Hunt are therefore too deep and too wide in hindsight by roughly this factor until a gauge-anchored stage correction exists.
- `usgs_elev_table.csv` maps each USGS site to feature_id and (branch, HydroID) with a DEM-adjusted elevation. Sites in the HUC: 08165300 N Fk nr Hunt, 08165500 Hunt, 08166000 Johnson Ck nr Ingram, 08166140 Kerrville abv Bear Ck, 08166200 Kerrville, 08166250 Center Point, 08167000 Comfort, 08167200 Bergheim, 08167500 Spring Branch, 08167700 Canyon Lake.
- Also present at HUC level: `nwm_subset_streams_levelPaths.gpkg` (244 reaches with to-node, order, slope, length, levelpath), `nwm_catchments_proj_subset.gpkg` (catchment polygons per feature_id, useful for zonal rainfall), `osm_roads_subset.gpkg`, `osm_bridges_subset.gpkg`, `nwm_lakes_proj_subset.gpkg`.

## Corridor AOI (EPSG:5070)

Flowline extents from the FIM network, used to set the Kerr scenario AOI to `[-340000, 764000, -274000, 790000]` (6600 by 2600 cells at 10 m):

| Feature | x range | y range |
|---|---|---|
| South Fork Guadalupe (levelpath 1619000016) | -337119 to -320758 | 769624 to 782893 |
| Lower Johnson Creek (levelpath 1619000015) | -331199 to -312408 | 782588 to 796533 |
| Main stem, North Fork gauge to Comfort | -327108 to -277117 | 766762 to 784148 |
| Gauges: N Fk nr Hunt (-326128, 782343), Hunt (-320189, 782866), Johnson Ck (-315599, 786145), Kerrville abv Bear Ck (-307704, 782204), Kerrville (-304128, 779990), Center Point (-299526, 773134), Comfort (-278306, 769720) | | |

## National Water Model on GCS

Bucket `national-water-model`, public.

- `nwm.20250704/analysis_assim/nwm.tHHz.analysis_assim.channel_rt.tm00.conus.nc`: 24 files per day, about 14 MB each. Variables per feature_id include `streamflow`, `velocity`, `qSfcLatRunoff`, `qBucket`, `nudge`. Also `tm01`, `tm02` lookbacks.
- `nwm.20250704/short_range/nwm.tHHz.short_range.channel_rt.fNNN.conus.nc`: 18 forecast hours per hourly cycle, same size. Only f001 to f006 are needed for horizons up to 4 hours.
- Both must be subset to the 646 feature_ids in the HUC.
- Ingested 2026-09-05 for the Kerr record (2025-07-03T12Z to 2025-07-05T12Z): 49 analysis hours and 49 short-range cycles of 6 leads each (about 4 GB raw, subset to 62 k rows). NWM analysis peak on the Hunt reach is 4476 cms against the USGS peak of 8920 cms at 10:05Z, so NWM carries about half the observed peak: the bias-ratio correction in the engine is not optional for this event.
- Transient network errors abort a naive download loop; the ingest retries each file and skips it with a warning after three failures. Files are netCDF4 (HDF5), so `xarray` with `h5netcdf` or `netCDF4` is required.
- The short-range forecasts carried no warning of this flood. Every cycle issued at or before 06Z on 4 July (usable from 07:30Z after the 90-minute latency) forecast 0 cms at Hunt, the North Fork and the South Fork for all six leads. The 07Z cycle forecast 4 cms at Hunt for 10Z; the 08Z cycle (usable from 09:30Z) forecast 212 cms for 10Z and 524 cms for 11Z against 8920 and about 8000 observed. Only the analysis (which assimilates observed precipitation, 60-minute latency) tracks the rise, and at a third of the magnitude: Hunt 16, 1271, 2890 cms at 08Z, 09Z, 10Z against 44, 1274, 8920 observed. Consequence: before about 08:30Z no ingested source contained a signal, and the engine's forecasts before then are correct extrapolations of quiet inputs, not predictions of the flood.
- Lateral inflow (`qSfcLatRunoff` plus `qBucket`) in the analysis peaks at 70 cms per hour on the North Fork reach and 98 on the South Fork reach at 09Z to 10Z; the short-range lateral inflow at the same reaches is 0 in cycles before 08Z and 6 to 18 cms afterwards.

## USGS gauge data

- The legacy `waterservices.usgs.gov/nwis/iv` endpoint returns a 301 with no JSON body. It is unusable.
- The replacement works: `https://api.waterdata.usgs.gov/ogcapi/v0/collections/continuous/items?monitoring_location_id=USGS-08165500&parameter_code=00065&datetime=2025-07-04T08:00:00Z/2025-07-04T10:00:00Z&f=json&limit=...`. Parameter 00065 is gage height in feet, 00060 is discharge in cfs. Values are at 5-minute resolution for the event.
- Sample: Hunt read 10.10 ft at 08:00Z (3:00 am CDT) and 14.94 ft at 08:25Z. Roughly one foot every five minutes on the rising limb.
- The Hunt gauge is reported to have stopped transmitting near the peak. Check the record for a gap before relying on it for the 4:00 to 5:00 am window.
- Confirmed in the record (15-minute data after 09Z): Hunt's gauge height ends at 10:00Z (last 3511 cms pair) while its discharge continues to the 8920 cms peak (USGS estimated); above Bear Creek (08166140) discharge ends at 09:45Z at 2 cms while its gauge height rises to 10 m; Center Point (08166250) discharge ends at 11:30Z at 15 cms and its gauge height at 12:00Z. Kerrville and Comfort are complete. The scenario declares the two stalled gauges as outages from 09:00Z and 10:30Z so they stop acting as routing controls.

## NOAA reference algorithm

From `NOAA-OWP/inundation-mapping`, `tools/inundation.py`:

- Stage per catchment is `np.interp(Q, discharge_cms, stage)` on that catchment's rows of the hydrotable.
- Depth is `stage - REM` where `REM >= 0` and the result is at least 30 mm (int16) or 0.03048 m (float). Catchments with LakeID other than -999 are excluded. Catchments with no flow value get no inundation.

## Local environment

Python 3.14 with numpy and pandas only. No rasterio, GDAL, pyarrow, xarray, or geopandas. Docker is installed. Rasterio and GDAL wheels for 3.14 on Windows may not exist yet; pin Python 3.12 or use a GDAL Docker base image.
