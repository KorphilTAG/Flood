# Changes

- Slug: langchain-flood-report-library
- Spec: `pipeline/features/langchain-flood-report-library/spec.md`
- Status: implemented and verified (offline test suite passing)

## Summary

Migrated `ingestion/aar/` from bespoke `pypdf`/`SentenceTransformer`/raw-`faiss`
code to LangChain's `PyPDFLoader`, `RecursiveCharacterTextSplitter`,
`Embeddings` providers (`HuggingFaceEmbeddings` default, opt-in
`OpenAIEmbeddings`), and a LangChain `FAISS` vector store. The manual
source-manifest gate, page-bounded citations, deterministic chunk IDs, and
human-annotation handling are unchanged. Corpus artifacts moved to a new v2
schema (`index.faiss`, `index-map.json`, `chunks.jsonl`,
`corpus-manifest.json`) that avoids LangChain's pickle-based
`save_local`/`load_local` format; `search` rejects old v1 raw-FAISS artifacts
with an actionable rebuild message.

## Files touched

| Path | Change | Why |
|---|---|---|
| `ingestion/aar/models.py` | edited | Split `SOURCE_MANIFEST_SCHEMA_VERSION` (1.0, unchanged) from a new `CORPUS_SCHEMA_VERSION` (2.0) so verified manifests stay valid while derived artifacts version independently. |
| `ingestion/aar/manifest.py` | edited | Kept validation explicitly pinned to stable source-manifest schema v1. |
| `ingestion/aar/pdf.py` | edited | Replaced direct `PdfReader` use with `PyPDFLoader(path, mode="page", extract_images=False)` and a per-page `RecursiveCharacterTextSplitter(chunk_size=900, chunk_overlap=150)`; loader metadata is never trusted as citation evidence, only its zero-based `page` offset. |
| `ingestion/aar/embeddings.py` | edited | Replaced the bespoke encode protocol with a LangChain `Embeddings` factory: `HuggingFaceEmbeddings` (default, local) and explicit opt-in `OpenAIEmbeddings` that fails clearly without `OPENAI_API_KEY`. |
| `ingestion/aar/corpus.py` | edited | Builds LangChain `Document`s per chunk and a normalized, `MAX_INNER_PRODUCT` LangChain `FAISS` store via `FAISS.from_documents`; completes all four artifacts in a temporary directory before publishing them. |
| `ingestion/aar/search.py` | edited | Validates all four v2 artifacts (schema version, provider/model, vector dimension, row-map/chunk-ID agreement) before reconstructing an in-memory-docstore LangChain `FAISS` store; results are rehydrated from canonical `chunks.jsonl`, never raw docstore metadata; rejects v1 manifests with a rebuild instruction. |
| `ingestion/aar/__main__.py` | edited | Added `--embedding-provider {huggingface,openai}` and kept `--model` on `build`; `validate`/`search` verbs unchanged. |
| `ingestion/tests/test_aar_manifest.py` | edited | Added a case confirming source-manifest v1 remains valid while `CORPUS_SCHEMA_VERSION` is v2. |
| `ingestion/tests/test_aar_corpus.py` | edited | Mocks a multi-page `PyPDFLoader` fixture; verifies page-bounded recursive splits, stable chunk IDs across rebuilds, page-scoped annotations, and the no-text human/OCR failure. |
| `ingestion/tests/test_aar_search.py` | edited | Uses a deterministic LangChain `Embeddings` fake; verifies v2 build/search, provider/model metadata, hazard/phase filtering, rejection of missing/mismatched artifacts, and rejection of v1 corpora. |
| `ingestion/requirements.txt` | edited | Added `langchain-community`, `langchain-text-splitters`, `langchain-huggingface`, `langchain-openai` alongside retained `pypdf`, `sentence-transformers`, `faiss-cpu`. |
| `ingestion/README.md` | edited | Documents the LangChain-only-for-ingestion/retrieval scope, provider selection and key requirement, v2 artifact layout, and the v1-corpus rebuild requirement. |

## Acceptance criteria

| Criterion | Status (done/blocked/skipped) | Where |
|---|---|---|
| Build still validates full source-manifest completeness before any loader/splitter/embedder/vector-store call | done | `ingestion/aar/corpus.py::build_corpus`, `ingestion/tests/test_aar_corpus.py::test_invalid_manifest_never_constructs_a_pdf_loader_or_artifacts` |
| `PyPDFLoader` page mode + `RecursiveCharacterTextSplitter` (900/150), no chunk crosses a PDF page | done | `ingestion/aar/pdf.py`, `ingestion/tests/test_aar_corpus.py::test_page_loader_recursive_splits_are_bounded_stable_and_annotated` |
| Deterministic chunk IDs stable across rebuilds; page-scoped annotations only; no-text failure | done | `ingestion/aar/pdf.py`, `ingestion/tests/test_aar_corpus.py` |
| Default `HuggingFaceEmbeddings`; explicit opt-in `OpenAIEmbeddings`; provider/model persisted; missing key fails clearly | done | `ingestion/aar/embeddings.py`, `ingestion/tests/test_aar_search.py::test_embedding_provider_factory_is_explicit_and_openai_needs_a_key` |
| LangChain `FAISS` over `Document`s, normalized max-inner-product (cosine) scoring, hazard/phase filters before limit | done | `ingestion/aar/corpus.py`, `ingestion/aar/search.py`, `ingestion/tests/test_aar_search.py::test_build_and_search_are_offline_filterable_and_citation_preserving` |
| v2 build atomically publishes exactly the four artifacts with full manifest metadata | done | `ingestion/aar/corpus.py`, `ingestion/tests/test_aar_search.py` |
| Search validates vector count/dimension/full chunk-ID set before constructing the store; no pickle/`save_local`/`load_local`/`allow_dangerous_deserialization` | done | `ingestion/aar/search.py`, `ingestion/tests/test_aar_search.py::test_search_rejects_mismatched_map_and_dimension`, `test_search_rejects_missing_safe_artifacts` |
| Tampered/missing artifacts rejected rather than returning uncited results | done | `ingestion/aar/search.py`, `ingestion/tests/test_aar_search.py` |
| v1 corpus artifacts rejected with actionable rebuild message; v1 source manifests remain accepted | done | `ingestion/aar/search.py`, `ingestion/tests/test_aar_search.py::test_search_rejects_v1_artifacts_with_rebuild_instruction`, `ingestion/tests/test_aar_manifest.py::test_source_manifest_v1_remains_valid_when_corpus_schema_is_v2` |
| `cd ingestion && pytest` passes offline, no real PDF/model download/network/API key/live DB | done | ran locally in a throwaway venv with declared dependencies — 42 passed |
| README documents LangChain scope, provider opt-in, unchanged manual gate, and generated-AAR exclusion | done | `ingestion/README.md` |

## How to verify

```bash
cd ingestion
pip install -r requirements.txt
pytest
python -m aar validate --manifest ../data/aar/verified-manifest.json
python -m aar build --manifest ../data/aar/verified-manifest.json --output ../data/aar/library
python -m aar search --index ../data/aar/library --query "proposed response plan" --limit 3
```

This session verified the offline path directly in a scratch virtualenv with
the declared dependencies. `pytest -q` passed: 42 tests. The AAR tests inject
deterministic embeddings and mock the PDF loader, so they make no real PDF,
model-download, network, API-key, database, or chat-model call.

## Residual risk

`langchain-community`'s `FAISS` constructor emits a `UserWarning` ("Normalizing
L2 is not applicable for metric type: DistanceStrategy.MAX_INNER_PRODUCT") when
`normalize_L2=True` is combined with `MAX_INNER_PRODUCT`. Traced this into the
installed library source: the flag is still stored and applied unconditionally
in both `__add` and `similarity_search_with_score_by_vector`, so vectors are
in fact L2-normalized before indexing and before querying — the warning text
is stale/misleading in this LangChain version, not a functional gap. Scores
observed in the passing tests are correctly ordered cosine similarities. If a
future `langchain-community` release changes this behavior, a regression would
show up as unstable/incorrect ranking in `test_aar_search.py`.

`langchain-community` is itself in maintenance sunset upstream (deprecation
warning on import of `InMemoryDocstore`/`FAISS`); the spec explicitly calls for
`langchain_community.vectorstores.FAISS`, so this pass keeps that dependency
rather than migrating to a standalone `langchain-faiss` package, which does not
exist yet.

No `sentence-transformers`/`langchain-huggingface`/`langchain-openai` model
download or API call was exercised in this environment; those remain
opt-in/runtime concerns for whoever runs a real build, consistent with the
spec's non-goals.

## Not done

No real source PDFs, verified manifests, or production corpus were built.
Locating/authorizing documents, OCR, a v1-to-v2 automatic converter, and any
critic/RAG-consumer integration remain out of scope per the spec.
