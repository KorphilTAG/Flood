"""Idempotent upsert helper shared by every ingestion script.

Re-running any ingestion script against unchanged source data must not create
duplicate rows and must not change any previously assigned feature_id. That
guarantee comes from `INSERT ... ON CONFLICT (feature_id) DO UPDATE`, keyed on
the deterministic feature_id built by lib.geo.make_feature_id.

`rows_from_geodataframe` and `apply_upsert_in_memory` are pure functions (no
DB, no network) so the merge semantics can be unit tested against fixture
GeoDataFrames without a live PostGIS instance -- see tests/test_upsert.py.
`upsert_geodataframe` is the thin wrapper the live ingestion scripts call.
"""
import json
import math

from shapely.geometry import mapping
from sqlalchemy import text

from lib.geo import make_feature_id


def _json_safe(value):
    """Map NaN/Infinity to None: valid JSON has no token for them, but
    `json.dumps`'s default `allow_nan=True` emits the bare words `NaN`/
    `Infinity` anyway, which Postgres's strict JSONB parser then rejects.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value

CORE_COLUMNS = ["feature_id", "source", "source_id", "geom", "attributes"]


def rows_from_geodataframe(
    gdf,
    layer: str,
    source: str,
    id_field: str,
    extra_fields: dict | None = None,
) -> list[dict]:
    """Build a list of upsert-ready row dicts from a GeoDataFrame.

    `id_field` is the column holding each feature's natural source id (used to
    build feature_id and stored verbatim as source_id). `extra_fields` maps
    extra destination columns (e.g. crossings.osm_tag) to a column name in
    `gdf` or a callable(row) -> value.
    """
    rows = []
    for _, row in gdf.iterrows():
        source_id = str(row[id_field])
        feature_id = make_feature_id(layer, source, source_id)
        attributes = {
            col: _json_safe(row[col])
            for col in gdf.columns
            if col not in ("geometry", id_field)
        }
        record = {
            "feature_id": feature_id,
            "source": source,
            "source_id": source_id,
            "geom_geojson": json.dumps(mapping(row.geometry)),
            "attributes": json.dumps(attributes, default=str),
        }
        for dest_col, spec in (extra_fields or {}).items():
            record[dest_col] = spec(row) if callable(spec) else row[spec]
        rows.append(record)
    return rows


def build_upsert_sql(table: str, extra_columns: list[str] | None = None) -> str:
    """Build the `INSERT ... ON CONFLICT (feature_id) DO UPDATE` statement for
    `table`. `extra_columns` are additional destination columns (e.g.
    ["osm_tag"] for crossings) bound by the same-named parameter.
    """
    extra_columns = extra_columns or []
    insert_cols = ["feature_id", "source", "source_id", "geom", "attributes"] + extra_columns
    insert_values = [
        ":feature_id",
        ":source",
        ":source_id",
        "ST_SetSRID(ST_GeomFromGeoJSON(:geom_geojson), 4326)",
        "CAST(:attributes AS JSONB)",
    ] + [f":{col}" for col in extra_columns]
    update_set = ", ".join(
        f"{col} = EXCLUDED.{col}"
        for col in ["source", "source_id", "geom", "attributes"] + extra_columns
    )
    return (
        f"INSERT INTO {table} ({', '.join(insert_cols)}) "
        f"VALUES ({', '.join(insert_values)}) "
        f"ON CONFLICT (feature_id) DO UPDATE SET {update_set}"
    )


def upsert_geodataframe(
    engine,
    gdf,
    table: str,
    layer: str,
    source: str,
    id_field: str,
    extra_fields: dict | None = None,
) -> int:
    """Upsert every row of `gdf` into `table`. Returns the number of rows sent."""
    rows = rows_from_geodataframe(gdf, layer, source, id_field, extra_fields)
    if not rows:
        return 0
    sql = text(build_upsert_sql(table, list(extra_fields.keys()) if extra_fields else None))
    with engine.begin() as conn:
        for row in rows:
            conn.execute(sql, row)
    return len(rows)


# --- Pure in-memory reference implementation (for tests, no DB required) --------


def apply_upsert_in_memory(store: dict, rows: list[dict]) -> dict:
    """Apply the same merge semantics as `build_upsert_sql`'s ON CONFLICT DO
    UPDATE, but against a plain dict keyed by feature_id, so the idempotency
    guarantee can be tested without a live database.

    Mutates and returns `store`. Re-applying the same `rows` twice is a no-op
    beyond refreshing non-key fields; feature_id is never reassigned because
    it is always the dict key.
    """
    for row in rows:
        feature_id = row["feature_id"]
        existing = store.get(feature_id, {})
        merged = dict(existing)
        merged.update({k: v for k, v in row.items() if k != "feature_id"})
        merged["feature_id"] = feature_id
        store[feature_id] = merged
    return store
