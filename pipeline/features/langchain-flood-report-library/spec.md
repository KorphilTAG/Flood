# Feature spec

- Slug: langchain-flood-report-library
- Feature: Migrate the existing verified flood-report library to LangChain PDF loading, recursive chunking, embedding providers, and a LangChain FAISS vector store
- Status: draft
- Product refs: PRD 5 (AAR pipeline/embeddings), PRD 6.1 (manual AAR source acquisition), PRD 6.6 (RAG retrieval and citation validator), PRD 7 principle 3, PRD 8 contract 2, and PRD 9 Milestone 3; FeatureBreakdown “RAG + Human/Landscape Data,” steps 4–7; architecture.md 5.5 and 5.7; decision 0006 (file-first storage); historical-flood-report-library implementation and changes record

## Problem

`ingestion/aar/` now provides a manually gated, local PDF-to-FAISS library, but it uses direct `pypdf`, a hand-written character splitter, a bespoke `SentenceTransformer` wrapper, and the raw `faiss` API. That duplicates the document, split, embedding, and vector-store integration that the requested LangChain stack already provides. It also makes the later critic’s RAG dependency look different from the existing LangChain-based ingestion conventions.

The migration must replace those bespoke processing and retrieval paths without weakening the existing evidence boundary: a human still verifies every local PDF and its checksum; chunks retain exact PDF-page provenance and human annotations; retrieval returns canonical citations. The small hackathon corpus remains file-backed FAISS under decision 0006, rather than adding pgvector or a database service.

## In scope

1. Migrate `ingestion/aar/` from direct PDF parsing to `langchain_community.document_loaders.PyPDFLoader`, configured for page mode with image extraction disabled. Treat each returned page as a separate input so the later splitter cannot create a chunk crossing a PDF-page boundary.
2. Replace `split_page_text` with `langchain_text_splitters.RecursiveCharacterTextSplitter` using the existing 900-character target and 150-character overlap. Normalize page content before splitting, preserve the current deterministic chunk-ID algorithm, and attach the manifest’s document provenance, one-based parsed page number, and only human-reviewed annotations to each chunk.
3. Keep the source-manifest validation gate and all nine required source categories unchanged: no loader, splitter, embedder, or vector-store call may occur until every source is locally present, checksum-matched, and marked verified. Preserve the no-text failure rather than silently indexing empty documents.
4. Replace the bespoke embedding protocol with LangChain `Embeddings` implementations. Default to local `langchain_huggingface.HuggingFaceEmbeddings` backed by `sentence-transformers` (`all-MiniLM-L6-v2`); support an explicit, opt-in `langchain_openai.OpenAIEmbeddings` path for API embeddings. Record the selected provider and model in corpus metadata, construct an API embedder only when that provider is selected, and surface a clear missing-key/configuration error instead of falling back silently.
5. Build and search the index through `langchain_community.vectorstores.FAISS`. Embed `langchain_core.documents.Document` objects whose metadata contains the deterministic `chunk_id`, human annotation fields, and citation identity. Use L2-normalized vectors with maximum-inner-product ranking so scores are cosine similarity; apply optional `hazard` and `phase` metadata filters before enforcing the result limit.
6. Retain portable, citation-preserving file artifacts. In addition to `index.faiss`, retain `chunks.jsonl` as the canonical chunk/citation record and add an `index-map.json` mapping FAISS row IDs to `chunk_id`; use it to reconstruct the LangChain FAISS docstore on search. Do not use LangChain’s pickle-based `save_local`/`load_local` format or enable dangerous deserialization. Publish all artifacts atomically with a corpus build manifest.
7. Split source-manifest and built-corpus schema versions: preserve the current source-manifest schema so verified manifests remain valid, and bump the corpus-artifact schema for this LangChain format. `search` must reject existing v1 raw-FAISS artifacts with an actionable rebuild message; it must never silently mix an old index with the LangChain retrieval path.
8. Preserve the existing CLI verbs. Extend `python -m aar build` with explicit `--embedding-provider {huggingface,openai}` and `--model` options; `search` reads the provider/model recorded in the corpus manifest rather than accepting an incompatible runtime override. Update documentation and offline tests for the LangChain pipeline.

## Out of scope

- Locating, downloading, evaluating, or authorizing real reports. The human-only acquisition, provenance, checksum, and verification workflow remains unchanged (PRD 6.1).
- OCR, automated extraction of tactics/outcomes, LLM summarization, generated claims, or relaxing page-bounded citations. A scanned/non-extractable PDF still requires a human-prepared and re-verified follow-up.
- The FastAPI critic/enrichment service, chat agent, output validator, RAGAS evaluation, session state, overlay/UI work, search-area tool, physics work, or operational recommendations. This is only the critic’s retrieval corpus input (PRD 6.6).
- pgvector/PostGIS, Docker, or another vector database. FAISS files remain the selected local store unless decision 0006’s storage/query trigger is met.
- Changes to the unrelated LangChain HTTP fetch wrappers in `ingestion/lib/langchain_tools.py` or their tests. This migration uses LangChain’s document/RAG components, not an agent or a chat model.
- Automatic conversion of an existing v1 corpus directory. The operator must rebuild from the same verified PDFs and manifest so every new index mapping and provider record is reproducible.

## Approach

Keep `aar.manifest` as the first and mandatory boundary. It continues to validate the manually curated JSON source manifest, all required categories, local files, checksums, verification fields, and annotation conflicts before the build invokes any LangChain component. Separate its stable source-manifest version from a new corpus-artifact version (for example, source manifest `1.0`, LangChain corpus `2.0`) so this migration does not invalidate a curator’s verified input simply because the derived index format changed.

In `aar.pdf`, replace direct `PdfReader` usage with `PyPDFLoader(path, mode="page", extract_images=False)`. Convert each loaded page into a fresh LangChain `Document` with controlled metadata derived from `SourceDocument`; do not trust loader-supplied source metadata as evidence. Require a zero-based integer `page` metadata value from the page loader, convert it to the one-based PDF page number recorded in `Citation`, normalize its content, and run `RecursiveCharacterTextSplitter(chunk_size=900, chunk_overlap=150)` separately for that single page. For each resulting split, assign the existing deterministic ID shape (`document_id`, page, in-page sequence, content hash), resolve only page-bounded human annotations, and emit the same `Chunk`/citation JSON shape. If no non-empty split is produced for a source, fail the build with the current actionable human/OCR follow-up.

In `aar.embeddings`, expose a factory returning LangChain’s `Embeddings` interface. `huggingface` is the default and constructs `HuggingFaceEmbeddings` with the configured sentence-transformers model; `openai` constructs `OpenAIEmbeddings` only when explicitly requested and relies on the provider’s normal API-key configuration. The corpus manifest must persist `embedding_provider`, `embedding_model`, vector dimension, chunk count, corpus schema version, source document IDs/checksums, and build time. Tests inject a deterministic `Embeddings` implementation with `embed_documents` and `embed_query`; they do not instantiate either real provider.

In `aar.corpus`, turn each `Chunk` into a LangChain `Document`: `page_content` is exactly the stored chunk text and metadata includes `chunk_id`, `hazard`, `phase`, `tactic`, `resources`, `outcome`, `lesson`, and the citation identity needed to join back to the canonical JSONL record. Build the vector store with `FAISS.from_documents`, deterministic chunk IDs, normalized vectors, and maximum-inner-product distance. Persist the underlying FAISS index, canonical `chunks.jsonl`, and a JSON `index-map.json` derived from the vector store’s row-to-document IDs. The files are sufficient to rebuild a `FAISS` instance with LangChain `Document`s and an in-memory docstore at query time, avoiding an untrusted pickle. Write all four build outputs (`index.faiss`, `index-map.json`, `chunks.jsonl`, `corpus-manifest.json`) to a temporary directory and publish them only after all checks succeed.

In `aar.search`, validate the new manifest, canonical chunks, index mapping, vector count/dimension, and exact set of mapped chunk IDs before constructing a LangChain `FAISS` store. Build a metadata filter from optional `hazard`/`phase`, fetch enough candidates to evaluate all chunks when filtering, then return results in similarity order. Rehydrate each public result from `chunks.jsonl`, not arbitrary docstore metadata, so the response continues to contain the full canonical analytic fields and exact citation. A missing/corrupt/mismatched map, a model/provider mismatch, or an old corpus schema is an error, never a degraded search.

Keep the existing commands and output semantics, with this build interface:

```bash
python -m aar validate --manifest <path>
python -m aar build --manifest <path> --output <dir> [--embedding-provider huggingface|openai] [--model <id>]
python -m aar search --index <dir> --query <text> [--hazard <value>] [--phase <value>] [--limit <n>]
```

The defaults are local Hugging Face/sentence-transformers embeddings and FAISS. An OpenAI embedding build/search is opt-in, requires its configured API credential, and still makes no chat-model or agent call. A former corpus directory must be rebuilt with `build` after updating dependencies; source PDFs/manifests are never rewritten by this migration.

## Files to change

| Path | Action (add/edit) | Why |
|---|---|---|
| `ingestion/aar/models.py` | edit | Split stable source-manifest and versioned corpus-artifact schema constants; retain the existing provenance-bearing chunk/citation shape |
| `ingestion/aar/pdf.py` | edit | Replace direct `pypdf` parsing and custom splitter with page-mode `PyPDFLoader` and per-page `RecursiveCharacterTextSplitter` while preserving page citations, annotations, deterministic IDs, and no-text errors |
| `ingestion/aar/embeddings.py` | edit | Replace the custom `encode` protocol with LangChain embedding-provider construction for local Hugging Face and opt-in OpenAI embeddings |
| `ingestion/aar/corpus.py` | edit | Build LangChain `Document`s and a normalized LangChain `FAISS` store; atomically persist the FAISS index, canonical JSONL, JSON row map, and v2 corpus manifest |
| `ingestion/aar/search.py` | edit | Reconstruct and query the LangChain `FAISS` store from safe artifacts; validate maps/artifacts and return canonical citation-bearing results with metadata filtering |
| `ingestion/aar/__main__.py` | edit | Add explicit embedding-provider/model build options and report clear corpus/provider configuration errors without changing the validate/search verbs |
| `ingestion/tests/test_aar_manifest.py` | edit | Confirm a v2 corpus migration leaves the verified source-manifest validation contract intact |
| `ingestion/tests/test_aar_corpus.py` | edit | Mock `PyPDFLoader` page documents and verify recursive, page-bounded LangChain splits retain IDs, citations, annotations, and the no-text failure |
| `ingestion/tests/test_aar_search.py` | edit | Use a deterministic LangChain `Embeddings` fake to test FAISS build/search, provider metadata, filters, safe index-map reconstruction, and rejection of v1/mismatched artifacts |
| `ingestion/requirements.txt` | edit | Add the LangChain community, text-splitter, Hugging Face, and OpenAI integration packages while retaining required local PDF, sentence-transformers, and FAISS dependencies |
| `ingestion/README.md` | edit | Document the LangChain pipeline, provider selection/key expectation, new artifact layout, v1 rebuild requirement, and unchanged manual source gate |

## Acceptance criteria

- [ ] The production build still invokes source-manifest completeness validation before constructing `PyPDFLoader`, a text splitter, embeddings, or a vector store; a missing category, unverified source, missing PDF, checksum mismatch, or conflicting annotation prevents any corpus artifacts from being published.
- [ ] `aar.pdf` uses `PyPDFLoader` in page mode and `RecursiveCharacterTextSplitter`, configured at 900 characters with 150-character overlap. Splitting is performed page by page, so every output chunk has non-empty text and a citation whose one-based `page_start` and `page_end` are the same parsed PDF page.
- [ ] A mocked multi-page loader fixture demonstrates that a split from page N cannot contain text from page N+1, preserves deterministic chunk IDs across unchanged rebuilds, and applies only annotations covering that page. A source whose loaded pages produce no text fails with the documented human/OCR follow-up error.
- [ ] The default build uses `HuggingFaceEmbeddings` with the configured sentence-transformers model; `--embedding-provider openai` selects `OpenAIEmbeddings` only when explicitly passed. The chosen provider and model are persisted in `corpus-manifest.json`, and an unavailable API credential/configuration produces a clear non-zero error rather than a local fallback.
- [ ] The build creates a LangChain `FAISS` vector store over LangChain `Document`s using normalized maximum-inner-product vectors, and a query result’s score is cosine similarity. `--hazard` and `--phase` filters are evaluated before `--limit` truncates results.
- [ ] A successful v2 build atomically publishes exactly `index.faiss`, `index-map.json`, `chunks.jsonl`, and `corpus-manifest.json`. The build manifest records corpus schema version, embedding provider/model, vector dimension, chunk count, source document IDs/checksums, and creation time.
- [ ] `search` validates that `index.faiss`, the JSON row map, and canonical JSONL agree on vector count, dimension, and the full unique set of `chunk_id`s before constructing the LangChain store. It does not use `FAISS.save_local`/`load_local`, pickle persistence, or `allow_dangerous_deserialization=True`.
- [ ] `python -m aar search --index <dir> --query <text> --limit 3` returns descending similarity hits with canonical `chunk_id`, score, analytic fields, excerpt, and complete page citation. Tampered/missing JSONL, index-map, dimension, provider/model, or row mapping is rejected rather than returning uncited results.
- [ ] A v1 corpus artifact manifest is rejected with an actionable instruction to rerun `python -m aar build` using the verified source manifest; source-manifest v1 inputs remain accepted and are not modified.
- [ ] `cd ingestion && pytest` passes without a real PDF, a model download, network access, an API key, or a live database. Tests mock the PDF loader and inject a deterministic LangChain `Embeddings` fake; no test instantiates an OpenAI client or chat model.
- [ ] `ingestion/README.md` explains that LangChain is used for deterministic document ingestion, splitting, embeddings, and vector retrieval only; real PDFs still require manual verification; generated AARs remain excluded; and OpenAI embeddings are opt-in rather than required for the local default.

## Non-goals and constraints

- This is a retrieval-library migration, not a critic or dispatcher. A human commander remains the operational decision owner (PRD 2), and semantic similarity is not evidence for an operational claim.
- Preserve PRD 7 principle 3: all retrievable content must retain its source document, canonical URL, verified PDF checksum, and exact page citation. The later output validator remains responsible for validating LLM citations; this feature must not invent claims or citations.
- No raw coordinates, geometry, hydrology, tactical scoring, map outputs, or search-area predictions belong in this corpus.
- Default behavior must remain local and offline after dependencies/model are available. Do not require an OpenAI key, a chat model, an agent executor, or a hosted database to validate, build, or search with the default Hugging Face provider.
- FAISS files remain local first per decision 0006. Do not add pgvector, a `vector` extension, schema changes, or Docker service changes for this small manually curated corpus.
- Existing source manifests, verified PDFs, human annotations, chunk public fields, CLI verbs, and the exclusion of product-generated AARs are compatibility obligations. Only derived corpus artifacts deliberately break to the new schema and must be rebuilt.

## Assumptions

- The existing `ingestion/aar/` package and historical-flood-report-library changes are the migration baseline; no real corpus has been committed, so a rebuild does not discard checked-in evidence.
- `langchain-community` supplies `PyPDFLoader` and `FAISS`, `langchain-text-splitters` supplies `RecursiveCharacterTextSplitter`, and `langchain-huggingface`/`langchain-openai` supply the two selected embedding adapters. The project continues to depend on `pypdf`, `sentence-transformers`, and `faiss-cpu` as their required local implementations.
- `PyPDFLoader` page metadata remains sufficient to derive the one-based parsed PDF page number. If a supported LangChain version changes that metadata contract, the implementation should pin/adapt the loader at this boundary and add a regression test rather than emitting an uncertain citation.
- Locally generated artifacts are considered trusted local files for normal search, but the implementation will avoid pickle-based LangChain persistence regardless by storing/revalidating a JSON index map and canonical JSONL.
- The default `all-MiniLM-L6-v2` model can be downloaded once in a build environment. Unit tests must inject deterministic embeddings, and an operator who selects the OpenAI provider supplies its credential outside the repository.

## Open questions

None. The migration selects local Hugging Face embeddings plus LangChain FAISS as the default implementation, preserves the manual evidence gate, and exposes API embeddings as an explicit opt-in rather than blocking the offline corpus workflow.
