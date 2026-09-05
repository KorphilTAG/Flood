# Feature spec

- Slug: historical-flood-report-library
- Feature: Digest manually verified Texas flood reports into a local, citation-preserving semantic-search library for the future critic
- Status: draft
- Product refs: PRD 5 (AAR pipeline/embeddings), PRD 6.1 (AAR corpus is manual), PRD 6.6 (RAG retrieval and citation validator), PRD 7 principle 3, PRD 8 contract 2; FeatureBreakdown “RAG + Human/Landscape Data,” step 4; architecture.md 5.5 and 5.7; decision 0006 (file-first storage before database infrastructure)

## Problem

The critic needs a trustworthy corpus of historical outcomes, but the required reports are scattered across agencies and cannot safely be scraped or guessed. The repository has PostGIS exposure-layer ingestion only; it has no AAR documents, document manifest, chunk schema, embeddings, or vector index. Without a corpus that retains source and page provenance, the later critic cannot make citation-grounded comparisons of a trainee plan to prior incidents (PRD 6.6).

## In scope

1. Add an offline Python AAR-corpus package under `ingestion/aar/` that accepts only a manually curated manifest of locally stored, text-extractable PDFs. It never discovers, downloads, or declares a source authoritative.
2. Define and validate a versioned JSON source manifest. A document may be processed only when its entry records `document_id`, required source category, title, publisher, canonical source URL, local PDF path, SHA-256, `verified_by`, `verified_at`, and a human verification note. It must reject duplicate document IDs, invalid hashes, missing files, checksum mismatches, and entries not marked `verified`.
3. Require a verified entry for each requested source category before a production build: `tx_house_senate_committee`, `kerr_hmp_2024`, `kerr_eop`, `nws_service_assessment`, `usgs_post_flood_report`, `fema_ipaws_records`, `wimberley_2015_aar`, `houston_2016_aar`, and `llano_2018_aar`. These respectively cover the Texas House/Senate testimony/reports, Kerr County plans, federal reports/records, and named Texas AARs in the request. The validation command must name every missing category rather than silently producing a corpus labelled complete.
4. Extract text page by page with `pypdf`; normalize whitespace, split only within a page into bounded chunks, and preserve the source document ID, canonical URL, PDF checksum, and exact PDF page number on every chunk. Fail the source with a clear error if no extractable text is present; OCR is not implied.
5. Store every chunk in the common AAR record shape required by architecture.md 5.5: stable `chunk_id`, hazard, phase, tactic, resources, outcome, lesson, text, and source citation. The six analytic fields are nullable until a human adds a page-range annotation in the manifest; the pipeline must never infer them or manufacture an outcome. Apply only non-conflicting, page-bounded human annotations to chunks.
6. Embed the chunk text with a local `sentence-transformers` model and persist a normalized cosine-similarity FAISS index plus a JSONL chunk store and a build manifest under a caller-selected `data/aar/` directory. The build manifest records schema version, embedder model identifier, vector dimension, source checksums, and creation time so an incompatible index cannot be searched accidentally.
7. Provide command-line entry points, runnable from `ingestion/`: `python -m aar validate --manifest <path>`, `python -m aar build --manifest <path> --output <dir> [--model <id>]`, and `python -m aar search --index <dir> --query <text> [--hazard <value>] [--phase <value>] [--limit <n>]`. Search returns JSON hits ordered by cosine similarity, each with `chunk_id`, score, analytic fields, excerpt, and complete page citation.
8. Add offline tests using synthetic manifest entries, mocked PDF-page text, and a deterministic fake embedder. Tests must not download an embedding model, call an API, or contain/report real incident facts.
9. Document the manual acquisition/verification workflow, manifest format, build/search commands, output layout, and the explicit distinction between source documents and generated AARs.

## Out of scope

- Locating, downloading, evaluating, or authorizing any real source document; a person must do that before the build command runs (PRD 6.1).
- OCR, automated extraction of tactical/outcome facts, LLM-based summarization, or any uncited/generated claim. A scanned or ambiguous PDF remains a manual follow-up, not an opportunity to invent a substitute.
- The FastAPI critic/enrichment service, OpenAI generation, output validator, RAGAS evaluation, session state, map overlays, search-area tool, and UI integration. This feature supplies their corpus input only.
- A trained historical-decision scorer, dispatch/evacuation recommendations, raw-coordinate output, or any physics computation.
- pgvector/PostGIS schema or Docker changes. Use FAISS file artifacts for this first local corpus; revisit pgvector only if the storage trigger in decision 0006 is met.
- Adding product-generated AARs to this corpus. Per decision 0007, generated reports must remain separate so the retrieval system cannot cite its own output.

## Approach

Create a small `aar` package beside the existing ingestion scripts, not a new web service. Its manifest validator is the gate between the manual source-discovery work and deterministic processing: it checks all nine source categories and each local file's recorded checksum before parsing.

The builder reads each approved PDF with `pypdf`, produces page-bounded chunks (target 900 characters, 150-character overlap only when remaining on the same page), and assigns a deterministic ID from document ID, page number, in-page sequence, and chunk-text hash. Every stored chunk carries a citation object containing the document ID, title, publisher, canonical URL, PDF SHA-256, and `page_start`/`page_end`; chunks must never span pages, so both values are the parsed PDF page number. Page-range annotations in the same human-reviewed manifest can populate `hazard`, `phase`, `tactic`, `resources`, `outcome`, and `lesson`; overlapping annotations with different values fail validation.

Use `sentence-transformers` with `all-MiniLM-L6-v2` as the default configurable local model. Normalize vectors and use `faiss.IndexFlatIP`, making inner-product ranking cosine similarity. Persist `index.faiss`, `chunks.jsonl`, and `corpus-manifest.json` atomically into the output directory. At search time, load all three, reject a missing/mismatched schema or FAISS dimension, embed the query with the recorded model, score all stored vectors, then apply optional hazard/phase filters before truncating to the requested limit. Keep the embedder behind a small protocol/factory so tests inject a deterministic fake without network or model downloads.

Use a scaffolded `sources/README.md` and `manifest.example.json` to make the human handoff explicit. Actual PDFs, verified manifests, and generated index artifacts live under ignored `data/aar/`; they are not committed to the repository. Extend the existing ingestion requirements and README rather than adding a parallel dependency setup.

## Files to change

| Path | Action (add/edit) | Why |
|---|---|---|
| `ingestion/aar/{__init__.py, models.py, manifest.py, pdf.py, corpus.py, embeddings.py, search.py, __main__.py}` | add | Offline manifest validation, PDF/page chunking, provenance-preserving AAR records, embedding/index build, and search CLI |
| `ingestion/aar/sources/{README.md, manifest.example.json}` | add | Human-only document verification checklist and a non-production manifest shape for the nine required source categories |
| `ingestion/tests/{test_aar_manifest.py, test_aar_corpus.py, test_aar_search.py}` | add | Offline tests for source gates/checksums, deterministic page citations/annotations, and semantic ranking/filtering |
| `ingestion/requirements.txt` | edit | Add `pypdf`, `sentence-transformers`, and `faiss-cpu` for the local PDF-to-vector pipeline |
| `ingestion/README.md` | edit | Document the manual source handoff and validate/build/search workflow alongside existing ingestion commands |
| `.gitignore` | add | Exclude manually acquired PDFs, verified manifests, and generated `data/aar/` index artifacts while retaining source instructions/examples |

## Acceptance criteria

- [ ] `python -m aar validate --manifest <path>` accepts a complete synthetic manifest only when all nine required source categories have a `verified` entry with required provenance fields; it exits non-zero and lists each missing category, invalid status, missing file, duplicate ID, malformed checksum, or checksum mismatch.
- [ ] The production `build` command invokes the same completeness validation first and never writes a corpus that can be mistaken for a complete requested library when any required source remains unverified.
- [ ] A successful build from the synthetic fixture creates `index.faiss`, `chunks.jsonl`, and `corpus-manifest.json`; the manifest records the schema version, chosen model ID, vector dimension, source document IDs/checksums, and build timestamp.
- [ ] Every JSONL chunk has a deterministic, unique `chunk_id`; non-empty `text`; nullable `hazard`, `phase`, `tactic`, `resources`, `outcome`, and `lesson`; and a citation with document ID, canonical URL, PDF SHA-256, and exact parsed PDF page number. No chunk crosses a PDF-page boundary.
- [ ] Rebuilding unchanged synthetic inputs produces the same chunk IDs and chunk ordering. Modifying a source PDF after manifest verification fails the checksum gate rather than silently replacing evidence.
- [ ] Page-range annotations populate only chunks on those pages; a conflicting overlap is rejected. Unannotated analytic fields remain `null`, never model-generated text.
- [ ] A PDF whose pages yield no extractable text fails with an actionable message that it needs a human-prepared text/OCR follow-up; the pipeline does not index empty chunks.
- [ ] `python -m aar search --index <dir> --query <text> --limit 3` returns JSON ordered by descending similarity with score, chunk ID, excerpt, analytic fields, and citation. `--hazard` and `--phase` restrict returned hits to matching human-annotated metadata.
- [ ] Search refuses an index whose recorded schema/model/vector dimension is inconsistent with its FAISS artifacts, instead of returning untraceable or invalid results.
- [ ] The new tests use only synthetic source metadata, mocked page text, and a deterministic fake embedder; `cd ingestion && pytest` passes without network access, an embedding download, API credentials, or a live database.
- [ ] `ingestion/README.md` states that the source manifest must be manually verified before processing and that product-generated AARs are prohibited from the retrieval corpus.

## Non-goals and constraints

- This is a retrieval corpus, not a critic. It makes no operational recommendation; a human commander remains the decision owner (PRD 2).
- Every future factual claim must remain traceable to this library's page citation or a current twin feature ID (PRD 7 principle 3). Semantic similarity is retrieval metadata, not proof of a claim.
- Do not emit raw geometry or coordinates; this feature handles report text and citations only.
- Preserve provenance through every stage. The authoritative URL, checksum, and page number cannot be discarded when chunking, embedding, or searching.
- The initial index is intentionally local FAISS/file storage. It must not add a `vector` extension to the existing PostGIS container or introduce a database/service dependency for a small, manually curated corpus (decision 0006).
- The local default embedder may be replaced later by an API embedding implementation behind the same interface, but this pass must not require an API key or use an LLM.

## Assumptions

- A designated human curator will locate the authoritative versions, save each PDF locally, calculate/record its SHA-256, and complete the verification fields. This developer pass does not establish document authenticity.
- The required source set can be represented as text-extractable PDFs; any scanned-only source will be transcribed/OCRed and re-verified by a human before it is admitted, outside this scope.
- The default `sentence-transformers` model can be installed and downloaded once in the build environment. Tests inject a fake embedder, and users may configure another compatible local model at build time.
- `data/aar/` is suitable local/demo storage for a small corpus. The later critic can consume the persisted chunk store and FAISS index through a separately specified interface.

## Open questions

None. The choice of authoritative copies is intentionally assigned to the required manual curation step, not left for the implementation agent to guess.
