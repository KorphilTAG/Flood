"""Rebuild the regional DEM. Requires rasterio and numpy in the active Python environment."""
import json, hashlib
import rasterio, numpy as np
from rasterio.windows import from_bounds as window_bounds
from rasterio.transform import from_bounds
from rasterio.warp import reproject, Resampling
from pathlib import Path
root=Path(__file__).resolve().parents[1]
existing=json.loads((root/'data/terrain.json').read_text())
items=existing['sources']
bounds=[-99.46,29.90,-99.08,30.14]; width=3800; height=2400
dest=np.full((height,width),np.nan,dtype='float32')
transform=from_bounds(*bounds,width,height)
with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR',CPL_VSIL_CURL_ALLOWED_EXTENSIONS='.tif',GDAL_HTTP_TIMEOUT='60'):
 for item in items:
  print('Reading historical tile',item['title'],flush=True)
  with rasterio.open(item['downloadURL']) as src:
   b=[max(bounds[0],src.bounds.left),max(bounds[1],src.bounds.bottom),min(bounds[2],src.bounds.right),min(bounds[3],src.bounds.top)]
   win=window_bounds(*b,transform=src.transform).round_offsets().round_lengths()
   data=src.read(1,window=win)
   print('Subset',data.shape,'range',float(data.min()),float(data.max()),flush=True)
   reproject(data,dest,src_transform=src.window_transform(win),src_crs=src.crs,src_nodata=src.nodata,dst_transform=transform,dst_crs='EPSG:4326',dst_nodata=np.nan,resampling=Resampling.bilinear,init_dest_nodata=False)
assert np.isfinite(dest).all(), 'DEM contains missing cells'
assert 100<float(dest.min())<float(dest.max())<1200
packed=np.rint(dest*10).astype('<u2').tobytes()
out=root/'public/terrain/guadalupe-2021.u16';out.write_bytes(packed)
meta={'name':'USGS 3DEP historical Guadalupe River DEM','publicationDate':'2021-11-03','retrieved':'2026-09-05','bounds':bounds,'width':width,'height':height,'encoding':'uint16 little-endian, decimeters, north-to-south rows, pixel centers','verticalDatum':'NAVD88','horizontalDatum':'WGS84 (reprojected from NAD83)','sourceResolution':'1/3 arc-second (approximately 10 m)','gridSpacingDegrees':0.0001,'minMeters':round(float(dest.min()),1),'maxMeters':round(float(dest.max()),1),'sha256':hashlib.sha256(packed).hexdigest(),'sources':[{k:i[k] for k in ['title','publicationDate','downloadURL','metaUrl','vendorMetaUrl']} for i in items]}
assert meta['sha256'] == existing['sha256'], 'Extracted grid differs from the pinned historical version'
(root/'data/terrain.json').write_text(json.dumps(meta,indent=2)+'\n')
print(json.dumps(meta,indent=2),flush=True)
