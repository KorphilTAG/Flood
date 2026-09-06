import os
import sys

# faiss and torch each bring their own OpenMP runtime. On macOS, loading both into one
# interpreter aborts the process inside `faiss.search` (the AAR search tests run after
# the ragas-importing critic_eval tests, so the whole suite dies mid-run). Allowing the
# duplicate runtime is the standard workaround and must be set before either library is
# imported -- conftest is imported first, and both are imported lazily inside tests.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

# Ensure `lib` and `scripts` are importable as top-level packages regardless
# of the directory pytest is invoked from.
INGESTION_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if INGESTION_ROOT not in sys.path:
    sys.path.insert(0, INGESTION_ROOT)
