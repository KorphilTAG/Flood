-- Exposure-layer schema for the Flood digital twin (map-data-ingestion feature).
--
-- Every table carries a stable, human-legible feature_id built as
-- "<layer>:<source>:<source_id>" (e.g. road:txdot:1023481, crossing:osm:way/38291029,
-- river:nhd:12345600001234, camp:<source>:<row-index>). feature_id is derived from
-- source data, never a hand-typed or invented coordinate, per PRD Design Principle 3 /
-- Data Contract 1: the LLM layer may only ever reference geometry by this opaque ID.

CREATE EXTENSION IF NOT EXISTS postgis;

-- Road centerlines (TxDOT open data), clipped to the Kerr County boundary.
CREATE TABLE IF NOT EXISTS roads (
    feature_id  TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    geom        GEOMETRY(Geometry, 4326) NOT NULL,
    attributes  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS roads_geom_gix ON roads USING GIST (geom);

-- River network (USGS NHD flowlines, HUC8 12100201).
CREATE TABLE IF NOT EXISTS river_network (
    feature_id  TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    geom        GEOMETRY(Geometry, 4326) NOT NULL,
    attributes  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS river_network_geom_gix ON river_network USING GIST (geom);

-- Building footprints (FEMA USA Structures), clipped to the Kerr County boundary.
CREATE TABLE IF NOT EXISTS buildings (
    feature_id  TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    geom        GEOMETRY(Geometry, 4326) NOT NULL,
    attributes  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS buildings_geom_gix ON buildings USING GIST (geom);

-- USGS road--stream crossing candidates. They are not a verified low-water
-- crossing inventory; ``crossing_type`` remains in attributes for review.
-- hmp_verified_name / hmp_cross_checked are placeholders for the manual HMP/EOP
-- cross-check (PRD 6.1) and are NOT populated by this feature's ingestion scripts.
CREATE TABLE IF NOT EXISTS crossings (
    feature_id          TEXT PRIMARY KEY,
    source              TEXT NOT NULL,
    source_id           TEXT NOT NULL,
    geom                GEOMETRY(Geometry, 4326) NOT NULL,
    attributes          JSONB NOT NULL DEFAULT '{}'::jsonb,
    osm_tag             TEXT, -- retained for legacy OSM rows; NULL for USGS records
    hmp_verified_name   TEXT,
    hmp_cross_checked   BOOLEAN NOT NULL DEFAULT false,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS crossings_geom_gix ON crossings USING GIST (geom);

-- Camp footprints. Ships EMPTY from this feature -- real camp geometry acquisition
-- (KCAD / TNRIS / ReportAll / Regrid / aerial tracing) is manual, out of scope
-- (PRD 6.1). The loader script is tested only against a synthetic fixture.
CREATE TABLE IF NOT EXISTS camps (
    feature_id  TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    source_id   TEXT NOT NULL,
    geom        GEOMETRY(Geometry, 4326) NOT NULL,
    attributes  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS camps_geom_gix ON camps USING GIST (geom);
