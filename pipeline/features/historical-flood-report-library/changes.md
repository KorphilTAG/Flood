# Changes

- Slug: historical-flood-report-library
- Spec: `pipeline/features/historical-flood-report-library/spec.md`
- Status: implemented (local test execution dependency-limited)

## Summary

Added an offline, manually gated PDF-to-FAISS AAR corpus package. It validates
provenance and required source coverage before it can extract, chunk, embed, or
publish any corpus; preserves page-level citations; and exposes validate, build,
and search commands from `ingestion/`.

## Files touched

| Path | Change | Why |
|---|---|---|
| `.gitignore` | added | Keeps manually acquired PDFs, verified manifests, and generated local AAR artifacts out of version control. |
| `ingestion/aar/__init__.py` | added | Defines the offline AAR package surface. |
| `ingestion/aar/models.py` | added | Defines versioned source, annotation, citation, chunk, and error shapes. |
| `ingestion/aar/manifest.py` | added | Validates manual verification fields, source categories, files, checksums, and annotation conflicts. |
| `ingestion/aar/pdf.py` | added | Extracts pypdf text page by page and makes page-bounded deterministic chunks. |
| `ingestion/aar/embeddings.py` | added | Provides the configurable local sentence-transformer embedder interface. |
| `ingestion/aar/corpus.py` | added | Builds normalized FAISS artifacts, JSONL chunks, and corpus provenance metadata. |
| `ingestion/aar/search.py` | added | Loads and validates corpus artifacts before cosine retrieval and metadata filtering. |
| `ingestion/aar/__main__.py` | added | Implements `python -m aar validate`, `build`, and `search`. |
| `ingestion/aar/sources/README.md` | added | Documents the human-only acquisition and verification handoff. |
| `ingestion/aar/sources/manifest.example.json` | added | Supplies a deliberately pending, non-production shape for all nine source categories. |
| `ingestion/tests/test_aar_manifest.py` | added | Tests synthetic source gates, missing categories, checksums, and duplicate IDs. |
| `ingestion/tests/test_aar_corpus.py` | added | Tests synthetic page citations, annotations, stable chunks, conflict rejection, and no-text errors. |
| `ingestion/tests/test_aar_search.py` | added | Tests offline fake-embedder build/search ranking, filters, and index consistency rejection. |
| `ingestion/requirements.txt` | edited | Adds pypdf, sentence-transformers, and faiss-cpu dependencies. |
| `ingestion/README.md` | edited | Documents the manual source gate, commands, output layout, and generated-AAR prohibition. |
| `pipeline/features/historical-flood-report-library/changes.md` | edited | Records this implementation and verification status. |

## Acceptance criteria

| Criterion | Status (done/blocked/skipped) | Where |
|---|---|---|
| Validate complete nine-category manifests and report all provenance/source errors | done | `ingestion/aar/manifest.py`, `ingestion/aar/__main__.py`, `ingestion/tests/test_aar_manifest.py` |
| Build performs the same completeness gate before publishing artifacts | done | `ingestion/aar/corpus.py` |
| Successful builds write FAISS, JSONL, and versioned build metadata | done | `ingestion/aar/corpus.py`, `ingestion/tests/test_aar_search.py` |
| Chunks have stable IDs, nullable analytic fields, and exact page citations | done | `ingestion/aar/models.py`, `ingestion/aar/pdf.py`, `ingestion/tests/test_aar_corpus.py` |
| Unchanged source inputs retain chunk IDs; changed PDFs fail checksum validation | done | `ingestion/aar/manifest.py`, `ingestion/aar/pdf.py`, `ingestion/tests/test_aar_manifest.py`, `ingestion/tests/test_aar_corpus.py` |
| Human annotations are page-bounded and conflicting overlaps are rejected | done | `ingestion/aar/manifest.py`, `ingestion/aar/pdf.py`, `ingestion/tests/test_aar_corpus.py` |
| PDFs without text fail without indexing empty chunks | done | `ingestion/aar/pdf.py`, `ingestion/tests/test_aar_corpus.py` |
| Search returns ordered JSON hits with filters and complete citations | done | `ingestion/aar/search.py`, `ingestion/aar/__main__.py`, `ingestion/tests/test_aar_search.py` |
| Search rejects incompatible schema/model/dimension/index artifacts | done | `ingestion/aar/search.py`, `ingestion/tests/test_aar_search.py` |
| Offline synthetic tests use mocked page text and a deterministic fake embedder | done | `ingestion/tests/test_aar_manifest.py`, `ingestion/tests/test_aar_corpus.py`, `ingestion/tests/test_aar_search.py` |
| Documentation states the manual verification gate and generated-AAR prohibition | done | `ingestion/README.md`, `ingestion/aar/sources/README.md` |

## How to verify

```bash
cd ingestion
pip install -r requirements.txt
pytest
python -m aar validate --manifest ../data/aar/verified-manifest.json
python -m aar build --manifest ../data/aar/verified-manifest.json --output ../data/aar/library
python -m aar search --index ../data/aar/library --query "synthetic query" --limit 3
```

Static verification completed: `python3 -m compileall -q ingestion/aar
ingestion/tests`, JSON parsing of `manifest.example.json`, and `python3 -m aar
--help`. The intentionally pending example also exited non-zero and listed all
nine required categories.

## Residual risk

The current environment has no `pytest`, `numpy`, `pypdf`, `faiss`, or
`sentence-transformers` installed, so the complete test suite and a real FAISS
build could not be executed locally. No real source PDF or verified manifest is
present by design; a human curator must supply and verify those inputs.

## Not done

No real documents were located, downloaded, verified, embedded, or indexed.
OCR, generated AAR ingestion, database/vector-service integration, and critic
integration remain intentionally out of scope.
