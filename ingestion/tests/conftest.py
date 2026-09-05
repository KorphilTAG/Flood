import os
import sys

# Ensure `lib` and `scripts` are importable as top-level packages regardless
# of the directory pytest is invoked from.
INGESTION_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if INGESTION_ROOT not in sys.path:
    sys.path.insert(0, INGESTION_ROOT)
