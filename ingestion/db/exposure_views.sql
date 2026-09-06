-- Contract 0 exposure views for the Kerr County scenario.
--
-- The scenario's registry (scenarios/kerr-2025-07-04.json) declares each exposure
-- layer as flood_exposure.kerr_2025_07_04_<layer_id> with geometry column "geometry"
-- and a per-layer id_field/attribute allow-list. The ingestion tables in schema.sql
-- are shaped for loading instead: one row shape for every layer, a "geom" column, and
-- free-form JSONB attributes. These views are the adapter between the two, so neither
-- side has to adopt the other's naming and schema.sql stays untouched.
--
-- Apply after schema.sql:
--     psql "$FLOOD_POSTGIS_DSN" -f ingestion/db/exposure_views.sql
--
-- Each view:
--   * derives the layer's declared id_field from the ingest feature_id. The ingest
--     convention is "<layer>:<source>:<source_id>" (schema.sql), but a Contract 2
--     feature_ref is "<layer_id>:<source_id>" with the source half restricted to
--     [A-Za-z0-9_.-] (common.schema.json feature_ref). So the redundant layer prefix
--     is stripped -- the extractor re-adds the registry's layer_id -- and ":" and "/"
--     (OSM ids look like "node/1") become ".". The mapping is deterministic and
--     stable; it is not reversible, so trace a fact back via source + source_id;
--   * projects exactly the attributes the registry allow-lists, out of JSONB;
--   * renames geom to geometry and re-asserts the typmod, so the declared SRID
--     survives into the view and the extractor can align it to the raster CRS;
--   * filters to the geometry kind the layer declares, so a stray row of the wrong
--     kind is excluded here rather than failing the whole extraction.

CREATE SCHEMA IF NOT EXISTS flood_exposure;

-- crossing: point, id_field "crossing_id", attributes ["road_name"].
-- road_name prefers the manually verified HMP name when a curator has supplied one
-- (schema.sql hmp_verified_name), falling back to the normalized source road name.
CREATE OR REPLACE VIEW flood_exposure.kerr_2025_07_04_crossing AS
SELECT
    translate(regexp_replace(feature_id, '^[a-z_]+:', ''), ':/', '..') AS crossing_id,
    COALESCE(hmp_verified_name, attributes ->> 'name')  AS road_name,
    geom::geometry(Geometry, 4326)                      AS geometry
FROM public.crossings
WHERE GeometryType(geom) IN ('POINT', 'MULTIPOINT');

-- road: line, id_field "segment_id", attributes ["name", "functional_class"].
-- egress_for_site is the registry's egress join column. Nothing populates it yet, so
-- it is projected as NULL: every site's egress resolves to "unknown" rather than to a
-- fabricated route. Point it at a real column once camp-to-route joins are curated.
CREATE OR REPLACE VIEW flood_exposure.kerr_2025_07_04_road AS
SELECT
    translate(regexp_replace(feature_id, '^[a-z_]+:', ''), ':/', '..') AS segment_id,
    attributes ->> 'name'               AS name,
    attributes ->> 'functional_class'   AS functional_class,
    NULL::text                          AS egress_for_site,
    geom::geometry(Geometry, 4326)      AS geometry
FROM public.roads
WHERE GeometryType(geom) IN ('LINESTRING', 'MULTILINESTRING');

-- structure: polygon, id_field "osm_id", attributes ["building"].  FEMA
-- polygons are matched at ingest time to the frozen model's OSM centroid IDs.
-- That source-derived alias is the matched row's ``source_id``; use it so
-- Contract 2 facts join the static weights.
CREATE OR REPLACE VIEW flood_exposure.kerr_2025_07_04_structure AS
SELECT
    source_id                           AS osm_id,
    attributes ->> 'building'       AS building,
    geom::geometry(Geometry, 4326)  AS geometry
FROM public.buildings
WHERE source = 'fema_static_match'
  AND GeometryType(geom) IN ('POLYGON', 'MULTIPOLYGON');

-- site: polygon, id_field "site_id", attributes ["name", "site_type", "occupancy_est"].
-- public.camps ships empty (schema.sql): this view is correct and returns zero rows
-- until real camp footprints are curated, so the extractor emits no site facts.
CREATE OR REPLACE VIEW flood_exposure.kerr_2025_07_04_site AS
SELECT
    translate(regexp_replace(feature_id, '^[a-z_]+:', ''), ':/', '..') AS site_id,
    attributes ->> 'name'               AS name,
    attributes ->> 'site_type'          AS site_type,
    attributes ->> 'occupancy_est'      AS occupancy_est,
    geom::geometry(Geometry, 4326)      AS geometry
FROM public.camps
WHERE GeometryType(geom) IN ('POLYGON', 'MULTIPOLYGON');
