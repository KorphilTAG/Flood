"""Shared geo helpers: feature_id convention, CRS reprojection, boundary loading,
and thin clients for the ArcGIS REST, Overpass, and Census TIGER APIs used by
the per-source ingestion scripts (invoked directly here, or via the LangChain
tool wrappers in lib/langchain_tools.py).
"""
import io
import os
import sys
import tempfile
import zipfile

import geopandas as gpd
import requests
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, shape

DEFAULT_BOUNDARY_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "kerr_county_boundary.geojson"
)

# overpass-api.de itself is the canonical instance, but its abuse-protection can
# temporarily block a client IP after a burst of requests (observed 2026-09-06);
# Kumi Systems mirrors the same public dataset on separate infrastructure.
# Override with OVERPASS_URL if a different mirror is preferred.
OVERPASS_URL = os.environ.get("OVERPASS_URL", "https://overpass.kumi.systems/api/interpreter")

TIGER_COUNTY_URL = "https://www2.census.gov/geo/tiger/TIGER2022/COUNTY/tl_2022_us_county.zip"


def make_feature_id(layer: str, source: str, source_id) -> str:
    """Build the stable "<layer>:<source>:<source_id>" feature_id.

    Deterministic from source data only -- never a hand-typed or invented
    coordinate/sequence number (PRD Design Principle 3 / Data Contract 1).
    """
    if layer is None or source is None or source_id is None or source_id == "":
        raise ValueError("layer, source, and source_id are all required")
    return f"{layer}:{source}:{source_id}"


def reproject_to_4326(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Reproject a GeoDataFrame to EPSG:4326, the storage CRS for all layers.

    If the GeoDataFrame has no CRS set, it is assumed to already be EPSG:4326.
    """
    if gdf.crs is None:
        return gdf.set_crs(epsg=4326)
    if gdf.crs.to_epsg() == 4326:
        return gdf
    return gdf.to_crs(epsg=4326)


def load_kerr_county_boundary(path: str = DEFAULT_BOUNDARY_PATH) -> gpd.GeoDataFrame:
    """Load the cached Kerr County boundary written by
    scripts/fetch_kerr_county_boundary.py.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Kerr County boundary not found at {path}. "
            "Run scripts/fetch_kerr_county_boundary.py first."
        )
    gdf = gpd.read_file(path)
    return reproject_to_4326(gdf)


def boundary_polygon(path: str = DEFAULT_BOUNDARY_PATH):
    """Return a single shapely (Multi)Polygon covering the Kerr County boundary."""
    gdf = load_kerr_county_boundary(path)
    return gdf.geometry.union_all() if hasattr(gdf.geometry, "union_all") else gdf.unary_union


# --- ArcGIS REST (TxDOT / USGS National Map) -------------------------------------


def query_arcgis_feature_server(
    url: str,
    boundary_geojson: dict,
    where: str = "1=1",
    out_fields: str = "*",
    timeout: int = 120,
    page_size: int = 2000,
) -> dict:
    """Query an ArcGIS FeatureServer/MapServer layer, filtered to a boundary
    polygon, and return the response as a GeoJSON FeatureCollection dict.

    Paginates with resultOffset/resultRecordCount until a page comes back
    shorter than `page_size`: a hosted feature service silently caps a single
    response at its own `maxRecordCount` (2000 for TxDOT's services) rather
    than erroring, so a naive single request can under-report a large area's
    features with no indication anything was dropped.
    """
    base_params = {
        "where": where,
        "outFields": out_fields,
        "geometry": _geojson_geometry_to_esri_json(boundary_geojson),
        "geometryType": "esriGeometryPolygon",
        "spatialRel": "esriSpatialRelIntersects",
        "inSR": 4326,
        "outSR": 4326,
        "f": "geojson",
        "resultRecordCount": page_size,
    }
    features = []
    offset = 0
    while True:
        params = {**base_params, "resultOffset": offset}
        # POST, not GET: the boundary polygon has enough vertices that its ESRI
        # JSON geometry exceeds most servers' URL length limit as a query string.
        resp = requests.post(url, data=params, timeout=timeout)
        resp.raise_for_status()
        page = resp.json()
        page_features = page.get("features", [])
        features.extend(page_features)
        if len(page_features) < page_size:
            break
        offset += page_size
    return {"type": "FeatureCollection", "features": features}


def _geojson_geometry_to_esri_json(geom: dict) -> str:
    import json

    if geom["type"] == "Polygon":
        rings = geom["coordinates"]
    elif geom["type"] == "MultiPolygon":
        rings = [ring for poly in geom["coordinates"] for ring in poly]
    else:
        raise ValueError(f"Unsupported boundary geometry type: {geom['type']}")
    return json.dumps({"rings": rings, "spatialReference": {"wkid": 4326}})


# --- Overpass API ------------------------------------------------------------------


def overpass_bbox(boundary_geom) -> tuple:
    """Return (south, west, north, east) for `boundary_geom`, in the order the
    Overpass API expects for a bbox filter. Derived from the sourced Kerr
    County boundary's bounds, never a hand-typed box.
    """
    minx, miny, maxx, maxy = boundary_geom.bounds
    return (miny, minx, maxy, maxx)


# Public Overpass mirrors rate-limit/reject the bare "python-requests/x.y" default
# User-Agent as unidentifiable traffic (observed 406/429 against overpass-api.de and
# overpass.kumi.systems on 2026-09-06); they ask for a real, identifying string.
OVERPASS_USER_AGENT = "flood-ingestion/1.0 (Kerr County exposure-layer ingestion; contact: see repo README)"


def overpass_query(query: str, timeout: int = 180) -> dict:
    """Run a raw Overpass QL query and return the parsed JSON response."""
    resp = requests.post(
        OVERPASS_URL,
        data={"data": query},
        headers={"User-Agent": OVERPASS_USER_AGENT},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()


def _member_segment(member: dict):
    """Return an Overpass relation member's own `geometry` list as a raw
    (lon, lat) point sequence -- not necessarily closed, since a ring's
    outer/inner boundary is often split across multiple way members that
    must be stitched together at shared endpoints.
    """
    coords = [(pt["lon"], pt["lat"]) for pt in member.get("geometry", [])]
    return coords if len(coords) >= 2 else None


def _assemble_rings(segments: list) -> list:
    """Stitch a list of (possibly disconnected) (lon, lat) point sequences
    into closed rings by chaining segments that share an endpoint, trying
    both orientations. Segments that never join into a closed ring are
    dropped (degenerate input).
    """
    remaining = [seg for seg in segments if seg]
    rings = []
    while remaining:
        ring = list(remaining.pop(0))
        while ring[0] != ring[-1]:
            for i, seg in enumerate(remaining):
                if seg[0] == ring[-1]:
                    ring += seg[1:]
                elif seg[-1] == ring[-1]:
                    ring += list(reversed(seg))[1:]
                elif seg[-1] == ring[0]:
                    ring = seg[:-1] + ring
                elif seg[0] == ring[0]:
                    ring = list(reversed(seg))[:-1] + ring
                else:
                    continue
                remaining.pop(i)
                break
            else:
                break  # no segment joins the ring; stop trying to close it
        if ring[0] == ring[-1] and len(ring) >= 4:
            rings.append(ring)
    return rings


def _relation_to_geometry(element: dict):
    """Build a Polygon/MultiPolygon from an Overpass `relation` element's
    `members` array (each member a "way" with its own `role` and `geometry`,
    the same shape a top-level way element carries). A ring's boundary may be
    split across multiple way members, which are stitched together here.
    """
    outer_segments = []
    inner_segments = []
    for member in element.get("members", []):
        segment = _member_segment(member)
        if segment is None:
            continue
        if member.get("role") == "inner":
            inner_segments.append(segment)
        else:
            outer_segments.append(segment)

    outer_rings = _assemble_rings(outer_segments)
    inner_rings = _assemble_rings(inner_segments)

    if not outer_rings:
        print(
            f"Skipping relation {element.get('id')}: no usable outer ring",
            file=sys.stderr,
        )
        return None

    if len(outer_rings) == 1:
        outer = Polygon(outer_rings[0])
        holes = [ring for ring in inner_rings if outer.contains(Polygon(ring))]
        return Polygon(outer_rings[0], holes=holes) if holes else outer

    polygons = []
    for outer_coords in outer_rings:
        outer = Polygon(outer_coords)
        holes = [ring for ring in inner_rings if outer.contains(Polygon(ring))]
        polygons.append(Polygon(outer_coords, holes=holes) if holes else outer)
    return MultiPolygon(polygons)


def overpass_element_to_geometry(element: dict):
    """Build a shapely geometry from an Overpass element returned by an
    `out geom;` query (nodes carry lat/lon; ways carry a `geometry` list of
    {lat, lon} points; relations carry a `members` array of way-shaped
    members with their own `role`/`geometry`).
    """
    if element.get("type") == "node":
        return Point(element["lon"], element["lat"])

    if element.get("type") == "way":
        coords = [(pt["lon"], pt["lat"]) for pt in element.get("geometry", [])]
        if len(coords) < 2:
            return None
        if coords[0] == coords[-1] and len(coords) >= 4:
            return Polygon(coords)
        return LineString(coords)

    if element.get("type") == "relation":
        return _relation_to_geometry(element)

    return None


def overpass_elements_to_geodataframe(elements: list) -> gpd.GeoDataFrame:
    """Convert a list of Overpass elements (from `out geom;`) into a
    GeoDataFrame with columns: id, type, tags, geometry.
    """
    rows = []
    for el in elements:
        geom = overpass_element_to_geometry(el)
        if geom is None:
            continue
        rows.append(
            {
                "id": el.get("id"),
                "type": el.get("type"),
                "tags": el.get("tags", {}),
                "geometry": geom,
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")


def geometry_from_geojson_dict(geom: dict):
    """Convert a raw GeoJSON geometry dict into a shapely geometry."""
    return shape(geom)


# --- Census TIGER ------------------------------------------------------------------


def fetch_tiger_county_boundary(
    state_fp: str, county_fp: str, url: str = TIGER_COUNTY_URL, timeout: int = 180
) -> gpd.GeoDataFrame:
    """Download the US Census TIGER/Line national county shapefile, extract it,
    and return the single county matching `state_fp`/`county_fp` as a
    GeoDataFrame in EPSG:4326.
    """
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()

    with tempfile.TemporaryDirectory() as tmp_dir:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            zf.extractall(tmp_dir)
        shp_files = [f for f in os.listdir(tmp_dir) if f.endswith(".shp")]
        if not shp_files:
            raise RuntimeError("No .shp file found in TIGER county archive")
        gdf = gpd.read_file(os.path.join(tmp_dir, shp_files[0]))

    county = gdf[(gdf["STATEFP"] == state_fp) & (gdf["COUNTYFP"] == county_fp)]
    if county.empty:
        raise RuntimeError(
            f"County (STATEFP={state_fp}, COUNTYFP={county_fp}) not found in TIGER county file"
        )
    return reproject_to_4326(county)
