"""Direct PostGIS reads for configured exposure layers.

The store knows nothing about any particular layer: every schema, table, geometry
column, ID column, and attribute name arrives from the Contract 0 registry entry.
Identifiers are quoted and composed with psycopg's identifier API; only the raster
bounds are ever passed as SQL parameters.
"""
from __future__ import annotations

import os
from typing import Any

import geopandas as gpd
from psycopg import sql

from flood.contracts.models import ExposureLayer

# The registry declares one of these three; anything else is a configuration error.
_ALLOWED_GEOM_TYPES: dict[str, tuple[str, ...]] = {
    "point": ("Point", "MultiPoint"),
    "line": ("LineString", "MultiLineString", "LinearRing"),
    "polygon": ("Polygon", "MultiPolygon"),
}


class ExposureConfigError(ValueError):
    """A layer's registry entry cannot support an extraction."""


class ExposureDataError(ValueError):
    """The configured relation exists but its rows are unusable."""


def resolve_dsn(explicit: str | None = None) -> str:
    """CLI argument wins over FLOOD_POSTGIS_DSN; neither is a configuration error."""
    dsn = explicit or os.environ.get("FLOOD_POSTGIS_DSN")
    if not dsn:
        raise ExposureConfigError(
            "No PostGIS DSN: pass --postgis-dsn or set FLOOD_POSTGIS_DSN"
        )
    return dsn


def require_postgis(layer: ExposureLayer) -> None:
    """Every layer the extractor reads must carry an explicit relation mapping."""
    if layer.postgis is None:
        raise ExposureConfigError(
            f"Exposure layer '{layer.layer_id}' has no 'postgis' mapping; "
            "the impact extractor reads exposure features from PostGIS only"
        )


class PostGISExposureStore:
    """Reads one configured relation per layer, bounded to the raster extent."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def _build_query(self, layer: ExposureLayer) -> sql.Composed:
        """SELECT id, <allow-listed attributes>, geom FROM schema.table WHERE geom && bounds.

        Column and relation names are composed as quoted identifiers, never interpolated.
        The bounding box arrives as five bound parameters (four ordinates plus the SRID).
        """
        pg = layer.postgis
        geom_col = sql.Identifier(pg.geometry_column)
        relation = sql.Identifier(pg.schema_, pg.table)

        selected = [sql.Identifier(layer.id_field)]
        selected += [sql.Identifier(a) for a in layer.attributes]
        selected.append(geom_col)

        return sql.SQL("SELECT {cols} FROM {rel} WHERE {geom} && ST_MakeEnvelope(%s, %s, %s, %s, %s)").format(
            cols=sql.SQL(", ").join(selected),
            rel=relation,
            geom=geom_col,
        )

    def load(
        self,
        layer: ExposureLayer,
        bounds: tuple[float, float, float, float],
        bounds_crs: str,
        target_crs: str,
    ) -> gpd.GeoDataFrame:
        """Return ID + allow-listed attributes + geometry, reprojected to ``target_crs``.

        ``bounds`` is the raster extent expressed in ``bounds_crs``; it is converted to the
        stored layer's own CRS before the query so the server-side index can be used.
        """
        require_postgis(layer)
        pg = layer.postgis

        import psycopg

        with psycopg.connect(self.dsn) as conn:
            srid = self._geometry_srid(conn, layer)
            query = self._build_query(layer)
            params = (*self._bounds_in_srid(bounds, bounds_crs, srid), srid)
            gdf = gpd.read_postgis(
                query.as_string(conn),
                conn,
                geom_col=pg.geometry_column,
                params=params,
            )

        return self._validate(gdf, layer, srid, target_crs)

    @staticmethod
    def _geometry_srid(conn: Any, layer: ExposureLayer) -> int:
        """Ask PostGIS for the column's declared SRID; 0 means 'not declared'."""
        pg = layer.postgis
        with conn.cursor() as cur:
            cur.execute(
                "SELECT Find_SRID(%s, %s, %s)",
                (pg.schema_, pg.table, pg.geometry_column),
            )
            row = cur.fetchone()
        if not row or row[0] in (None, 0):
            raise ExposureConfigError(
                f"Exposure layer '{layer.layer_id}': {pg.schema_}.{pg.table}."
                f"{pg.geometry_column} has no declared SRID, so it cannot be aligned "
                "to the raster CRS"
            )
        return int(row[0])

    @staticmethod
    def _bounds_in_srid(
        bounds: tuple[float, float, float, float], bounds_crs: str, srid: int
    ) -> tuple[float, float, float, float]:
        """Reproject the raster extent into the stored layer's CRS for the index scan."""
        from pyproj import CRS, Transformer

        src = CRS.from_user_input(bounds_crs)
        dst = CRS.from_epsg(srid)
        if src.equals(dst):
            return bounds
        tf = Transformer.from_crs(src, dst, always_xy=True)
        xs, ys = tf.transform(
            [bounds[0], bounds[2], bounds[0], bounds[2]],
            [bounds[1], bounds[3], bounds[3], bounds[1]],
        )
        return (min(xs), min(ys), max(xs), max(ys))

    @staticmethod
    def _validate(
        gdf: gpd.GeoDataFrame, layer: ExposureLayer, srid: int, target_crs: str
    ) -> gpd.GeoDataFrame:
        """Reject anything that would produce an unattributable or unusable fact."""
        lid = layer.layer_id
        missing = [c for c in [layer.id_field, *layer.attributes] if c not in gdf.columns]
        if missing:
            raise ExposureDataError(
                f"Exposure layer '{lid}': configured column(s) {missing} not returned"
            )

        ids = gdf[layer.id_field]
        if ids.isna().any():
            raise ExposureDataError(f"Exposure layer '{lid}': null value in id_field '{layer.id_field}'")
        dupes = ids[ids.duplicated()].unique().tolist()
        if dupes:
            raise ExposureDataError(
                f"Exposure layer '{lid}': duplicate source IDs {dupes[:5]} in '{layer.id_field}'"
            )

        if gdf.geometry.isna().any() or gdf.geometry.is_empty.any():
            raise ExposureDataError(f"Exposure layer '{lid}': null or empty geometry")
        if not gdf.geometry.is_valid.all():
            bad = gdf.loc[~gdf.geometry.is_valid, layer.id_field].tolist()
            raise ExposureDataError(f"Exposure layer '{lid}': invalid geometry for {bad[:5]}")

        allowed = _ALLOWED_GEOM_TYPES[layer.geometry]
        actual = set(gdf.geometry.geom_type.unique())
        unsupported = actual - set(allowed)
        if unsupported:
            raise ExposureDataError(
                f"Exposure layer '{lid}' is declared '{layer.geometry}' but the relation "
                f"returned {sorted(unsupported)}"
            )

        if gdf.crs is None:
            gdf = gdf.set_crs(epsg=srid)
        return gdf.to_crs(target_crs)
