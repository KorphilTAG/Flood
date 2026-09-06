import geopandas as gpd
import pytest
from pydantic import ValidationError
from shapely.geometry import Point

from lib.langchain_tools import (
    ArcGISFeatureServerTool,
    CensusTigerCountyBoundaryTool,
    OverpassApiTool,
)


def test_arcgis_tool_passes_arguments_and_returns_wrapped_result(monkeypatch):
    calls = []

    def fake_query(url, boundary_geojson, where="1=1", out_fields="*"):
        calls.append((url, boundary_geojson, where, out_fields))
        return {"type": "FeatureCollection", "features": []}

    monkeypatch.setattr("lib.langchain_tools.query_arcgis_feature_server", fake_query)

    boundary = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
    result = ArcGISFeatureServerTool().invoke(
        {"url": "https://example.com/query", "boundary_geojson": boundary, "where": "OBJECTID > 0"}
    )

    assert result == {"type": "FeatureCollection", "features": []}
    assert calls == [("https://example.com/query", boundary, "OBJECTID > 0", "*")]


def test_arcgis_tool_rejects_missing_required_input(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "lib.langchain_tools.query_arcgis_feature_server",
        lambda *a, **k: calls.append((a, k)),
    )

    with pytest.raises(ValidationError):
        ArcGISFeatureServerTool().invoke({"boundary_geojson": {"type": "Polygon", "coordinates": []}})

    assert calls == []


def test_overpass_tool_passes_query_and_returns_wrapped_result(monkeypatch):
    calls = []

    def fake_overpass_query(query):
        calls.append(query)
        return {"elements": []}

    monkeypatch.setattr("lib.langchain_tools.overpass_query", fake_overpass_query)

    result = OverpassApiTool().invoke({"query": "[out:json]; way[\"building\"]; out geom;"})

    assert result == {"elements": []}
    assert calls == ["[out:json]; way[\"building\"]; out geom;"]


def test_overpass_tool_rejects_missing_query(monkeypatch):
    calls = []
    monkeypatch.setattr("lib.langchain_tools.overpass_query", lambda *a, **k: calls.append((a, k)))

    with pytest.raises(ValidationError):
        OverpassApiTool().invoke({})

    assert calls == []


def test_tiger_boundary_tool_passes_arguments_and_returns_wrapped_result(monkeypatch):
    calls = []
    fake_gdf = gpd.GeoDataFrame({"GEOID": ["48265"]}, geometry=[Point(-99.3, 30.05)], crs="EPSG:4326")

    def fake_fetch(state_fp, county_fp, **kwargs):
        calls.append((state_fp, county_fp, kwargs))
        return fake_gdf

    monkeypatch.setattr("lib.langchain_tools.fetch_tiger_county_boundary", fake_fetch)

    result = CensusTigerCountyBoundaryTool().invoke({"state_fp": "48", "county_fp": "265"})

    assert result is fake_gdf
    assert calls == [("48", "265", {})]


def test_tiger_boundary_tool_rejects_missing_county_fp(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "lib.langchain_tools.fetch_tiger_county_boundary",
        lambda *a, **k: calls.append((a, k)),
    )

    with pytest.raises(ValidationError):
        CensusTigerCountyBoundaryTool().invoke({"state_fp": "48"})

    assert calls == []
