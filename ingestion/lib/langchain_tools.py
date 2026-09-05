"""LangChain `Tool` wrappers around the ingestion fetch layer.

Each tool below is a thin, schema-validated call interface over one external
data source's existing `lib.geo` function -- it does not reimplement the HTTP
logic, reshape the returned payload, or introduce any LLM. Ingestion scripts
invoke these tools directly and synchronously (`.invoke({...})`), never
through a LangChain `AgentExecutor` and never bound to a chat model, per
pipeline/features/langchain-datagrabber/spec.md's Out of scope section.
"""
from typing import Optional, Type

import geopandas as gpd
from langchain_core.tools import BaseTool
from pydantic import BaseModel, Field

from lib.geo import fetch_tiger_county_boundary, overpass_query, query_arcgis_feature_server


class ArcGISQueryInput(BaseModel):
    url: str = Field(..., description="ArcGIS FeatureServer/MapServer layer query URL")
    boundary_geojson: dict = Field(..., description="GeoJSON Polygon/MultiPolygon to filter by")
    where: str = Field("1=1", description="ArcGIS SQL WHERE clause")
    out_fields: str = Field("*", description="Comma-separated fields to return, or '*'")


class ArcGISFeatureServerTool(BaseTool):
    """Wraps `lib.geo.query_arcgis_feature_server` -- used by TxDOT roads and
    USGS NHD flowlines, each pointed at their own FeatureServer URL/filter.
    """

    name: str = "arcgis_feature_server_query"
    description: str = (
        "Query an ArcGIS FeatureServer/MapServer layer, filtered to a boundary "
        "polygon, and return the response as a GeoJSON FeatureCollection dict."
    )
    args_schema: Type[BaseModel] = ArcGISQueryInput

    def _run(self, url: str, boundary_geojson: dict, where: str = "1=1", out_fields: str = "*") -> dict:
        return query_arcgis_feature_server(url, boundary_geojson, where=where, out_fields=out_fields)


class OverpassQueryInput(BaseModel):
    query: str = Field(..., description="Raw Overpass QL query string")


class OverpassApiTool(BaseTool):
    """Wraps `lib.geo.overpass_query` -- used by OSM buildings and OSM
    low-water crossings, each with their own Overpass QL query.
    """

    name: str = "overpass_api_query"
    description: str = "Run a raw Overpass QL query and return the parsed JSON response."
    args_schema: Type[BaseModel] = OverpassQueryInput

    def _run(self, query: str) -> dict:
        return overpass_query(query)


class TigerBoundaryInput(BaseModel):
    state_fp: str = Field(..., description="Two-digit Census STATEFP code")
    county_fp: str = Field(..., description="Three-digit Census COUNTYFP code")
    url: Optional[str] = Field(None, description="Override the TIGER county shapefile URL")


class CensusTigerCountyBoundaryTool(BaseTool):
    """Wraps `lib.geo.fetch_tiger_county_boundary` -- downloads and extracts
    the Census TIGER national county shapefile and filters to one county.
    """

    name: str = "census_tiger_county_boundary"
    description: str = (
        "Download the Census TIGER county shapefile and return the single "
        "county matching state_fp/county_fp as a GeoDataFrame in EPSG:4326."
    )
    args_schema: Type[BaseModel] = TigerBoundaryInput

    def _run(self, state_fp: str, county_fp: str, url: Optional[str] = None) -> gpd.GeoDataFrame:
        kwargs = {"url": url} if url else {}
        return fetch_tiger_county_boundary(state_fp, county_fp, **kwargs)
