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

## Historical critic API (`ingestion/critic/`)

`critic` is a standalone FastAPI service, run from `ingestion/` the same way
`aar` is, that takes a trainee's proposed plan, retrieves grounded historical
context in-process from the `aar` corpus (a direct `aar.search.search_index`
Python call, never a subprocess), and calls the OpenAI API through LangChain
to return structured, cited objections and alternatives for a human
commander to weigh. It is a critic, not a dispatcher: it never returns an
operational order.

**Prerequisite:** an AAR corpus must already be built with `python -m aar
build` (see above) at the path this service reads. This service only reads
an existing corpus; it never builds, validates, or modifies one.

### Run

```bash
cd ingestion
# AAR_INDEX_DIR default is `data/aar/library` (relative to ingestion/); the
# `aar build` examples above write to `../data/aar/library` instead, so set
# this explicitly to match wherever your corpus actually lives:
export AAR_INDEX_DIR=../data/aar/library
export OPENAI_API_KEY=sk-...   # only required once a real request is made
uvicorn critic.app:app --reload --port 8001
```

The app (`create_app()` in `critic/app.py`) starts and `GET /healthz` (liveness
only) responds without a real `OPENAI_API_KEY` or a built corpus present;
both are only needed once a real, non-faked `POST /v1/critique` request is
made.

### Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `AAR_INDEX_DIR` | no | `data/aar/library` | Path to a corpus already produced by `python -m aar build` |
| `OPENAI_API_KEY` | at request time only | none | Read directly by `langchain_openai.ChatOpenAI`; a missing key fails clearly when a real (non-faked) critique request is made, not at process start |
| `CRITIC_OPENAI_MODEL` | no | `gpt-4o-mini` | OpenAI chat model used for generation (adjust for latency/cost before a live demo) |
| `CRITIC_REQUEST_TIMEOUT` | no | `30` | Seconds before the OpenAI/LangChain call times out |
| `CRITIC_DEFAULT_TOP_K` | no | `5` | Default number of AAR chunks retrieved per request when a request omits `top_k` |
| `CRITIC_MAX_REGENERATION_ATTEMPTS` | no | `2` | Additional regeneration attempts allowed after the output validator (below) rejects a citation, beyond the first generation attempt (default means up to 3 total generation attempts per request) |

### Output validator (`critic/validator.py`)

Every generated critique is independently re-checked before it is returned,
closing the gap between "the schema is supposed to prevent this" and "this
was actually re-verified":

- **What it checks:** for every objection/alternative, (1) every entry in
  the structured `chunk_ids` field, and (2) every bracket-delimited token
  (`[chunk_id]`) found inline in the free-text `text` field, must be a
  member of the set of `chunk_id`s actually retrieved for that request. The
  structured-field check is a deliberate second, independently-testable
  backstop of the same fact the per-request `Enum` in
  `schemas.py::build_structured_response_schema` is already supposed to
  guarantee -- it does not replace that Enum constraint. The inline check
  covers a citation surface the Enum cannot constrain at all: a
  bracket-delimited chunk-ID-looking token written inside a free-text
  string.
- **What it explicitly does not check:** feature IDs or any "current flood
  facts" claim -- no impact-JSON producer exists anywhere in this repository
  yet, so there is nothing to validate feature-ID citations against today
  (the validator's `known_chunk_ids` parameter is written to accept an
  additional set of valid IDs once such a producer exists, without changing
  its interface). It also does not check *faithfulness* -- whether a real,
  correctly-cited chunk's content actually supports the claim next to it.
  That is a distinct failure mode assigned to a separate, later RAGAS-based
  evaluation, not to this rule-checker.
- **Regenerate-then-fail-closed:** a citation violation does not surface a
  fabricated ID to the caller and does not silently pass it through. Instead
  `service.py::run_critique` re-calls the LLM with an added corrective
  instruction (naming the invalid reference(s) and reiterating the exact
  valid `chunk_id` set), then re-runs the validator on the new response, up
  to `CRITIC_MAX_REGENERATION_ATTEMPTS` additional times. If every attempt
  (first call plus all regenerations) still fails validation, the request
  raises `CritiqueGenerationError` (mapped to the existing `502` below) --
  it still fails closed, but only after regeneration was actually attempted.
- The validator itself (`find_citation_violations`) is a pure,
  dependency-free, standard-library-only function: no LLM call, no network
  call, no embedding/similarity computation.

### `POST /v1/critique`

Request body:

```json
{
  "plan": "Shelter in place near the river crossing.",
  "situation": "Rising water, optional free text from a training-mode decision point",
  "decision_point": "optional label, echoed back",
  "hazard": "flood",
  "phase": "response",
  "top_k": 5
}
```

Only `plan` is required (non-empty, non-whitespace; a missing/blank `plan`
returns `422` before any retrieval or LLM call). `situation`,
`decision_point`, `hazard`, `phase`, and `top_k` are all optional; `hazard`
and `phase` are passed straight through as `aar.search.search_index` filters.

Response body:

```json
{
  "objections": [{"text": "...", "chunk_ids": ["<real chunk_id>"]}],
  "alternatives": [{"text": "...", "chunk_ids": ["<real chunk_id>"]}],
  "citations": [{"chunk_id": "...", "score": 0.83, "excerpt": "...", "citation": {"...": "..."}, "hazard": "...", "phase": "...", "tactic": "...", "resources": "...", "outcome": "...", "lesson": "..."}],
  "decision_point": "optional label, echoed back",
  "model": "gpt-4o-mini"
}
```

`objections` and `alternatives` may both be empty (a plan can align with the
historical record), but any item present always cites at least one real
`chunk_id` drawn from `citations` -- the per-request structured-output schema
constrains the model to exactly the chunk IDs retrieved for that request, so
an invented ID cannot be represented at all, never mind returned.

Error responses are `{"error": {"code": str, "message": str}}`:

| Condition | Status |
|---|---|
| Missing/empty/whitespace-only `plan` | `422` |
| Retrieval found no matching historical context | `422` |
| `aar.search` corpus/index failure (missing/incompatible corpus, missing embedder dependency) | `503` |
| OpenAI/LangChain call failed or its structured output failed validation | `502` |
| Anything else unhandled | `500` |

### Tests

```bash
cd ingestion
pytest tests/test_critic_service.py tests/test_critic_api.py tests/test_critic_validator.py
```

`test_critic_validator.py` is pure unit tests of the rule-checker (no fakes
needed). `test_critic_service.py`/`test_critic_api.py` fake/monkeypatch
`aar.search.search_index` and the LLM generator call -- no real
`OPENAI_API_KEY`, no network access, and no real built FAISS corpus is
required.

## Citation quality evaluation (RAGAS) (`ingestion/critic_eval/`)

`critic_eval` is an offline RAGAS evaluation harness, run from `ingestion/`
the same convention as `aar` and `critic`, that runs a fixed, checked-in
sample of representative trainee plans through the real `critic.service.run_critique`
(real retrieval, real OpenAI generation) and scores the resulting citations
for two properties `critic/validator.py` does not check:

- **Faithfulness** -- does the generated objection/alternative text actually
  follow from the AAR excerpt it cites?
- **Context precision** -- were the chunks retrieval handed the LLM actually
  the relevant ones for this plan, not just whatever came back?

**What this explicitly does not check:** citation *existence* -- whether a
cited `chunk_id` was actually a member of the retrieved set. That is
`critic-output-validator`'s job (`critic/validator.py::find_citation_violations`),
already built, wired into `run_critique`'s regenerate-then-fail-closed loop,
and unchanged by this feature. A response can cite a perfectly real,
perfectly retrieved chunk and still misrepresent what it says (faithfulness),
or the retrieval step can hand the LLM the wrong chunks entirely (context
precision) -- two distinct failure modes existence-checking cannot catch,
which is exactly why both checks exist.

**A genuine departure from every other test/run path in `ingestion/`:**
running this for real (`python -m critic_eval run`) requires a real, already-
built AAR corpus (`python -m aar build`, see above) and a real
`OPENAI_API_KEY` with network access -- both for the critic's own generation
step and for the RAGAS judge LLM call that scores it. Unlike `test_geo.py`,
`test_upsert.py`, `test_aar_*.py`, and `test_critic_*.py`, there is no faked
path to a meaningful score here: faithfulness and context precision are
themselves LLM-judged, so faking the judge would just report whatever the
fake was built to report. This is stated plainly, not glossed over.

### The fixed sample set

There is no impact-JSON producer, session-state store, or training-mode UI
in this repository, so there is no live traffic to sample critique outputs
from. `critic_eval/fixtures/sample_plans.json` is therefore a small (8-entry),
checked-in, human-authored set of illustrative trainee plans, grounded in
the real, documented Kerr County / Guadalupe River flash-flood timeline
(`docs/architecture.md` Section 7): the 1:14 a.m. flash flood warning, the
2:30 a.m. rising-gauge/camp-egress decision, and the 4:03 a.m. flash flood
emergency. Each decision point has at least one plan variant written to
align with documented best practice and at least one written to plausibly
conflict with it, so both an "objections expected" and an "objections may be
empty" path get exercised. None of this text is a transcript of any real
trainee session -- no such session exists yet.

### Run

```bash
cd ingestion
export AAR_INDEX_DIR=../data/aar/library   # a real, already-built corpus
export OPENAI_API_KEY=sk-...
python -m critic_eval run
# Optional, opt-in CI-style exit code (default is report-only, exit 0):
python -m critic_eval run --fail-under-faithfulness 0.7 --fail-under-context-precision 0.7
```

Prints a human-readable table (decision point, plan excerpt, faithfulness
score, context-precision score, a `below threshold` flag per the warn
thresholds below) plus a section listing any sample that errored during the
critic call, by exception message. Also writes a timestamped JSON report to
`settings.report_dir` for archiving that specific run. Exits `0` unless a
`--fail-under-*` flag was explicitly passed and a score fell below it -- the
default is a human reads this before a demo, not a CI gate.

### Environment variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `RAGAS_JUDGE_MODEL` | no | `gpt-4o-mini` | OpenAI chat model used as the RAGAS judge LLM (separate from `CRITIC_OPENAI_MODEL` so it can be tuned independently) |
| `CRITIC_EVAL_SAMPLE_PATH` | no | `critic_eval/fixtures/sample_plans.json` | Path to the fixed sample-plan fixture |
| `CRITIC_EVAL_REPORT_DIR` | no | `critic_eval/reports/` | Directory a timestamped JSON report is written to |
| `CRITIC_EVAL_FAITHFULNESS_WARN_THRESHOLD` | no | `0.7` | Informational report-only flag (RAGAS scores are 0-1), not a hard gate |
| `CRITIC_EVAL_CONTEXT_PRECISION_WARN_THRESHOLD` | no | `0.7` | Informational report-only flag, not a hard gate |

Also reads `AAR_INDEX_DIR` and `OPENAI_API_KEY` (see the critic service's own
table above) -- this harness calls the critic in-process, so it needs the
same corpus and credential the critic itself does.

### Tests

```bash
cd ingestion
pytest tests/test_critic_eval_dataset.py tests/test_critic_eval_runner.py tests/test_critic_eval_mapping.py tests/test_critic_eval_report.py
```

Runs fully offline: no real `OPENAI_API_KEY`, no network access, and no real
built FAISS corpus. `critic.service.run_critique` and RAGAS's `evaluate` are
always injected/faked in these four files. `ragas` itself must be installed
(it is imported by these tests to build the metric objects/dataset schema),
but no network call or API key is exercised by importing or constructing it.
Only `python -m critic_eval run` itself (not exercised by any test) makes a
real critic call and a real RAGAS judge call.

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
