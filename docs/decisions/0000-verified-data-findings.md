# 0000. Verified facts about the source data

Status: findings, verified 2026-09-05 by anonymous HTTP reads. Not a decision, but every later record leans on these.

## HAND FIM 4.9.9.0, HUC8 12100201

Bucket prefix: `https://ciroh-owp-hand-fim.s3.amazonaws.com/hand_fim_4_9_9_0/12100201/`

- Grid is EPSG:5070 at 10 m, tiled 256x256 GeoTIFF, LZW. Branch 0 raster is 15558x6404, about 100 million cells. Each branch has its own extent, so all branches must be clipped to one common grid before mosaicking.
- `rem_zeroed_masked_<branch>.tif` (the HAND raster) is int16 in millimetres, nodata 32767. NOAA's `tools/inundation.py` multiplies stage by 1000 in int16 mode and drops depths under 30 mm. The catchment raster `gw_catchments_reaches_filtered_addedAttributes_<branch>.tif` is int16 HydroID, nodata 0.
- HydroIDs repeat across branches. The HUC rating table has 1964 unique (branch_id, HydroID) pairs but only 1683 unique HydroIDs. Every lookup must be keyed by both. 134 NWM feature_ids appear in both branch 0 and a levelpath branch; NOAA's mosaic step takes the per-cell maximum across branches.
- `hydrotable.csv` at HUC level is 67 MB (also `.parquet`, `.feather`). 84 stage rows per catchment at 0.3048 m steps up to 25.3 m. Columns include feature_id, discharge_cms, SLOPE, ManningN (0.06 everywhere), channel_n 0.07, overbank_n 0.11 to 0.13, WetArea, HydraulicRadius, TopWidth, LENGTHKM, LakeID (-999 means not a lake), calb_applied. Only 15 catchments carry a USGS-calibrated curve. 169 catchments have AI-based bathymetry applied.
- 12 branches. Levelpath 1619000006 is the Guadalupe main stem including the North Fork: 144 NWM reaches, 8 gauges. Levelpath 1619000016 is the South Fork: 30 reaches, 31 km, stream order 3, no gauge. Levelpath 1619000015 is Johnson Creek with gauge 08166000.
- `usgs_elev_table.csv` maps each USGS site to feature_id and (branch, HydroID) with a DEM-adjusted elevation. Sites in the HUC: 08165300 N Fk nr Hunt, 08165500 Hunt, 08166000 Johnson Ck nr Ingram, 08166140 Kerrville abv Bear Ck, 08166200 Kerrville, 08166250 Center Point, 08167000 Comfort, 08167200 Bergheim, 08167500 Spring Branch, 08167700 Canyon Lake.
- Also present at HUC level: `nwm_subset_streams_levelPaths.gpkg` (244 reaches with to-node, order, slope, length, levelpath), `nwm_catchments_proj_subset.gpkg` (catchment polygons per feature_id, useful for zonal rainfall), `osm_roads_subset.gpkg`, `osm_bridges_subset.gpkg`, `nwm_lakes_proj_subset.gpkg`.

## National Water Model on GCS

Bucket `national-water-model`, public.

- `nwm.20250704/analysis_assim/nwm.tHHz.analysis_assim.channel_rt.tm00.conus.nc`: 24 files per day, about 14 MB each. Variables per feature_id include `streamflow`, `velocity`, `qSfcLatRunoff`, `qBucket`, `nudge`. Also `tm01`, `tm02` lookbacks.
- `nwm.20250704/short_range/nwm.tHHz.short_range.channel_rt.fNNN.conus.nc`: 18 forecast hours per hourly cycle, same size. Only f001 to f006 are needed for horizons up to 4 hours.
- Both must be subset to the 646 feature_ids in the HUC. Files are netCDF4 (HDF5), so `xarray` with `h5netcdf` or `netCDF4` is required.

## USGS gauge data

- The legacy `waterservices.usgs.gov/nwis/iv` endpoint returns a 301 with no JSON body. It is unusable.
- The replacement works: `https://api.waterdata.usgs.gov/ogcapi/v0/collections/continuous/items?monitoring_location_id=USGS-08165500&parameter_code=00065&datetime=2025-07-04T08:00:00Z/2025-07-04T10:00:00Z&f=json&limit=...`. Parameter 00065 is gage height in feet, 00060 is discharge in cfs. Values are at 5-minute resolution for the event.
- Sample: Hunt read 10.10 ft at 08:00Z (3:00 am CDT) and 14.94 ft at 08:25Z. Roughly one foot every five minutes on the rising limb.
- The Hunt gauge is reported to have stopped transmitting near the peak. Check the record for a gap before relying on it for the 4:00 to 5:00 am window.

## NOAA reference algorithm

From `NOAA-OWP/inundation-mapping`, `tools/inundation.py`:

- Stage per catchment is `np.interp(Q, discharge_cms, stage)` on that catchment's rows of the hydrotable.
- Depth is `stage - REM` where `REM >= 0` and the result is at least 30 mm (int16) or 0.03048 m (float). Catchments with LakeID other than -999 are excluded. Catchments with no flow value get no inundation.

## Local environment

Python 3.14 with numpy and pandas only. No rasterio, GDAL, pyarrow, xarray, or geopandas. Docker is installed. Rasterio and GDAL wheels for 3.14 on Windows may not exist yet; pin Python 3.12 or use a GDAL Docker base image.
