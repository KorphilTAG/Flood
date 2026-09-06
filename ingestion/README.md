# Ingestion

Loads exposure-layer map data (roads, river network, building footprints,
low-water crossings, camp footprint schema) into PostGIS with stable
`feature_id`s, per `pipeline/features/map-data-ingestion/spec.md`.

## Setup

```bash
cd ingestion
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # edit if not using the default docker-compose values
```

### Local PostGIS (development)

```bash
docker compose up -d postgis
```

This brings up a `postgis/postgis` container and applies `db/schema.sql` on
first start (via `docker-entrypoint-initdb.d`). To (re)apply the schema by
hand against any reachable Postgres:

```bash
psql "$DATABASE_URL" -f db/schema.sql
```

### Environment variables

Either set `DATABASE_URL` directly, or set the individual `PGHOST` /
`PGPORT` / `PGDATABASE` / `PGUSER` / `PGPASSWORD` variables (see
`.env.example`). `lib/db.py` reads these via `python-dotenv`.

## Running the ingestion scripts

Run from the `ingestion/` directory so `lib` and `scripts` resolve as
top-level packages:

```bash
# 1. Fetch and cache the Kerr County boundary (clip mask for everything else)
python -m scripts.fetch_kerr_county_boundary

# 2. Load each automated layer
python -m scripts.ingest_txdot_roads
python -m scripts.ingest_nhd_flowlines
python -m scripts.ingest_osm_buildings
python -m scripts.ingest_osm_crossings

# 3. Camps: generic loader, run only once a real (or test) file exists
python -m scripts.ingest_camps --input <path to GeoJSON/Shapefile> --source <source-name>

# 4. Verify
python -m scripts.verify_exposure_layers
```

All four automated ingestion scripts (`ingest_txdot_roads.py`,
`ingest_nhd_flowlines.py`, `ingest_osm_buildings.py`,
`ingest_osm_crossings.py`) are idempotent: re-running any of them against
unchanged source data upserts in place (`ON CONFLICT (feature_id) DO
UPDATE`) rather than duplicating rows or reassigning `feature_id`.

**Note:** steps 1–4 require network access (Census TIGER, TxDOT ArcGIS,
USGS National Map, the public Overpass API) and a reachable PostGIS
instance. They are not run as part of the automated test suite below.

## Fetch layer (LangChain tools)

Every external-API call in the scripts above is routed through a LangChain
`BaseTool` wrapper in `lib/langchain_tools.py`, instead of each script
calling `requests`/`lib.geo` directly:

| Tool | Wraps | Used by |
|---|---|---|
| `ArcGISFeatureServerTool` | `lib.geo.query_arcgis_feature_server` | `ingest_txdot_roads.py`, `ingest_nhd_flowlines.py` |
| `OverpassApiTool` | `lib.geo.overpass_query` | `ingest_osm_buildings.py`, `ingest_osm_crossings.py` |
| `CensusTigerCountyBoundaryTool` | `lib.geo.fetch_tiger_county_boundary` | `fetch_kerr_county_boundary.py` |

Each tool has a Pydantic `args_schema` and is invoked directly and
synchronously (`Tool().invoke({...})`) by the script that needs it — never
through a LangChain `AgentExecutor` and never bound to a chat model. There is
no LLM anywhere in the fetch path: LangChain is used here strictly for its
`Tool` abstraction (a uniform, schema-validated call interface), not for LLM
reasoning about which source to query. No LLM API key is required to run any
script or test in this directory.

## Live smoke test (manual, opt-in)

```bash
cd ingestion
python -m scripts.live_smoke_test
```

Calls the real TxDOT ArcGIS FeatureServer, the real USGS NHDPlus HR
MapServer, the public Overpass API (buildings and crossings queries), and
Census TIGER, and prints a PASS/FAIL line per source. Requires network
access; does not write to PostGIS. Not run in CI or by the default `pytest`
suite below (it is not a pytest test module, so `pytest --collect-only`
never lists it). Run this at least once before trusting the four live-source
ingestion scripts against production data.

## Tests

```bash
cd ingestion
pytest
```

`test_geo.py` and `test_upsert.py` are fixture-driven unit tests that run
without network access or a live database. `test_geo.py` includes coverage
for the Overpass `relation` (multipolygon) geometry path, using the synthetic
fixture at `tests/fixtures/overpass_relation_building.json`. `test_ingest_camps.py`
runs `ingest_camps.py`'s real argument-parsing and feature-id-assignment logic
against the synthetic fixture at `tests/fixtures/sample_camps.geojson`,
stubbing out the DB call so it also runs without a live database.
`test_langchain_tools.py` mocks the underlying HTTP/`lib.geo` call for each
LangChain tool and requires no network access or API key.

## Historical flood report library (manual source handoff)

`aar` is an offline, local PDF-to-vector pipeline for a future retrieval
critic. It does not discover, download, evaluate, or authorize documents. A
human curator must save each authoritative, text-extractable PDF locally and
manually verify its title, publisher, canonical URL, SHA-256 checksum, curator
identity, verification time, and verification note before processing it.

Start from `aar/sources/manifest.example.json`, but do not build that
placeholder manifest. Store real PDFs and the corresponding verified manifest
under ignored `data/aar/`. The production manifest must include a verified
entry for every required category: Texas House/Senate committee materials, Kerr
County HMP and EOP, NWS, USGS, and FEMA records, plus Wimberley, Houston, and
Llano AARs. Page-range annotations are optional human-reviewed metadata for
`hazard`, `phase`, `tactic`, `resources`, `outcome`, and `lesson`; absent values
remain `null` and the pipeline never infers them.

From `ingestion/`, validate before building:

```bash
python -m aar validate --manifest ../data/aar/verified-manifest.json
python -m aar build --manifest ../data/aar/verified-manifest.json --output ../data/aar/library
python -m aar build --manifest ../data/aar/verified-manifest.json --output ../data/aar/library --embedding-provider huggingface --model all-MiniLM-L6-v2
# API embeddings are explicit opt-in and require OPENAI_API_KEY; no chat model is used.
OPENAI_API_KEY=... python -m aar build --manifest ../data/aar/verified-manifest.json --output ../data/aar/library-openai --embedding-provider openai --model text-embedding-3-small
python -m aar search --index ../data/aar/library --query "proposed response plan" --hazard flood --phase response --limit 3
```

The pipeline uses LangChain only for deterministic PDF page loading,
recursive page-bounded splitting, embedding adapters, and FAISS retrieval — not
for agents, chat models, generated claims, or document authorization. The build
writes exactly `index.faiss` (L2-normalized maximum-inner-product/cosine
vectors), `index-map.json` (FAISS row to canonical chunk ID), `chunks.jsonl`
(page-bounded chunks with all source provenance), and `corpus-manifest.json`
(v2 schema, selected provider/model, vector dimension, checksums, and build
time). These files avoid LangChain pickle persistence and allow search to
reconstruct and validate its docstore from canonical JSONL. Search returns JSON
hits ordered by cosine similarity with analytic fields, excerpt, and full page
citation; filters are applied before the requested result limit.

Existing v1 raw-FAISS corpus directories must be rebuilt with `python -m aar
build` using the unchanged verified source manifest. Source-manifest schema v1
is deliberately stable. Hugging Face/sentence-transformers is the local,
offline default after the model is available; OpenAI embeddings are opt-in and
fail clearly when their API credential is absent rather than falling back. A
scanned PDF with no extractable text fails for a human-prepared text/OCR
follow-up; OCR is not performed by this pipeline.

This corpus accepts only source documents. Product-generated AARs are
prohibited and must remain in a separate collection so retrieval cannot cite
its own generated output.

## Manual follow-up (not performed by this feature)

These items are genuinely manual per PRD 6.1. No script in this directory
attempts to fake, guess, or hallucinate a substitute for either of them:

- [ ] A person acquires real camp footprint geometry via KCAD parcel search,
      a TNRIS StratMap special request, a ReportAll/Regrid purchase, or
      aerial-imagery tracing, then runs `ingest_camps.py --input
      <acquired-file>` to load it.
- [ ] A person reads the Kerr County 2024 HMP and EOP PDFs, identifies named
      low-water crossings, matches them against rows in `crossings`, and
      updates `hmp_verified_name`/`hmp_cross_checked` (e.g. via a follow-up
      SQL script or a small manual-entry CSV + loader written in a later
      feature).

Until the first item is done, `camps` ships and remains empty except for
whatever a developer loads via the synthetic test fixture into a local/test
database. Until the second item is done, every row in `crossings` has
`hmp_verified_name IS NULL` and `hmp_cross_checked = false`.
