import geopandas as gpd
from shapely.geometry import Point, Polygon

from scripts import ingest_fema_buildings, ingest_usgs_crossings


def test_fema_loader_normalizes_occupancy_for_structure_contract():
    gdf = gpd.GeoDataFrame(
        {
            "GlobalID": ["a8ee1d45-0725-4d53-8de4-3183ad01b720", "d596a8a8-e0c0-4b8d-aec6-afcd6b2c2b29"],
            "OCC_CLS": ["Residential", None],
        },
        geometry=[
            Polygon([(-99.4, 30.0), (-99.39, 30.0), (-99.39, 30.01), (-99.4, 30.0)]),
            Polygon([(-99.38, 30.0), (-99.37, 30.0), (-99.37, 30.01), (-99.38, 30.0)]),
        ],
        crs="EPSG:4326",
    )

    normalized = ingest_fema_buildings.normalize_building_attributes(gdf)

    assert normalized["building"].tolist() == ["Residential", "Unknown"]
    assert normalized["OCC_CLS"].iloc[0] == "Residential"


def test_fema_loader_repairs_an_invalid_building_polygon():
    # A hole inside another hole is a nested-shell geometry, which PostGIS
    # rejects as invalid.  FEMA occasionally publishes that shape.
    invalid_polygon = Polygon(
        [(-99.4, 30.0), (-99.3, 30.0), (-99.3, 30.1), (-99.4, 30.1), (-99.4, 30.0)],
        [
            [(-99.38, 30.02), (-99.32, 30.02), (-99.32, 30.08), (-99.38, 30.08), (-99.38, 30.02)],
            [(-99.37, 30.03), (-99.33, 30.03), (-99.33, 30.07), (-99.37, 30.07), (-99.37, 30.03)],
        ],
    )
    gdf = gpd.GeoDataFrame({"GlobalID": ["a8ee1d45-0725-4d53-8de4-3183ad01b720"]}, geometry=[invalid_polygon], crs="EPSG:4326")

    repaired = ingest_fema_buildings.repair_invalid_geometries(gdf)

    assert not gdf.geometry.is_valid.all()
    assert repaired.geometry.is_valid.all()


def test_fema_loader_matches_static_osm_identity_to_containing_fema_polygon():
    buildings = gpd.GeoDataFrame(
        {
            "GlobalID": ["fema-a", "fema-b"],
            "OCC_CLS": ["Residential", "Commercial"],
        },
        geometry=[
            Polygon([(-99.4, 30.0), (-99.3, 30.0), (-99.3, 30.1), (-99.4, 30.1), (-99.4, 30.0)]),
            Polygon([(-99.2, 30.0), (-99.1, 30.0), (-99.1, 30.1), (-99.2, 30.1), (-99.2, 30.0)]),
        ],
        crs="EPSG:4326",
    )
    static_points = gpd.GeoDataFrame(
        {"feature_id": ["building:osm:way/46203177"], "weight": [0.42]},
        geometry=[Point(-99.35, 30.05)],
        crs="EPSG:4326",
    )

    matched = ingest_fema_buildings.match_buildings_to_vulnerability(buildings, static_points)

    assert len(matched) == 1
    assert matched["GlobalID"].tolist() == ["fema-a"]
    assert matched["static_model_feature_id"].tolist() == ["building:osm:way/46203177"]
    assert matched["static_feature_ref"].tolist() == ["osm.way.46203177"]
    assert matched.geometry.iloc[0].geom_type == "Polygon"


def test_usgs_loader_normalizes_tiger_road_name_for_crossing_view():
    gdf = gpd.GeoDataFrame(
        {
            "stream_crossing_id": [5276059],
            "tiger2020_feature_names": ["Bobcat Trl"],
            "crossing_type": ["tiger2020 road"],
        },
        geometry=[Point(-99.2193, 30.1753)],
        crs="EPSG:4326",
    )

    normalized = ingest_usgs_crossings.normalize_crossing_attributes(gdf)

    assert normalized["name"].tolist() == ["Bobcat Trl"]
    assert normalized["crossing_type"].tolist() == ["tiger2020 road"]


def test_fema_fetch_uses_arcgis_tool_and_returns_wgs84_features(monkeypatch):
    calls = []

    class FakeTool:
        def invoke(self, payload):
            calls.append(payload)
            return {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"GlobalID": "a8ee1d45-0725-4d53-8de4-3183ad01b720", "OCC_CLS": "Residential"},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [[[-99.4, 30.0], [-99.39, 30.0], [-99.39, 30.01], [-99.4, 30.0]]],
                        },
                    }
                ],
            }

    monkeypatch.setattr(ingest_fema_buildings, "ArcGISFeatureServerTool", FakeTool)

    result = ingest_fema_buildings.fetch_buildings({"type": "Polygon", "coordinates": []})

    assert result.crs.to_epsg() == 4326
    assert result["GlobalID"].tolist() == ["a8ee1d45-0725-4d53-8de4-3183ad01b720"]
    assert calls == [{"url": ingest_fema_buildings.FEMA_BUILDINGS_FEATURE_SERVER_URL, "boundary_geojson": {"type": "Polygon", "coordinates": []}}]


def test_usgs_fetch_uses_arcgis_tool_and_returns_wgs84_features(monkeypatch):
    calls = []

    class FakeTool:
        def invoke(self, payload):
            calls.append(payload)
            return {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"stream_crossing_id": 5276059, "tiger2020_feature_names": "Bobcat Trl"},
                        "geometry": {"type": "Point", "coordinates": [-99.2193, 30.1753]},
                    }
                ],
            }

    monkeypatch.setattr(ingest_usgs_crossings, "ArcGISFeatureServerTool", FakeTool)

    result = ingest_usgs_crossings.fetch_crossings({"type": "Polygon", "coordinates": []})

    assert result.crs.to_epsg() == 4326
    assert result["stream_crossing_id"].tolist() == [5276059]
    assert calls == [{"url": ingest_usgs_crossings.USGS_CROSSINGS_FEATURE_SERVER_URL, "boundary_geojson": {"type": "Polygon", "coordinates": []}}]
