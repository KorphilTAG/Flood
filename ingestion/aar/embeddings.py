"""LangChain embedding-provider selection for the local AAR corpus."""

from __future__ import annotations

import os
from typing import Literal

from langchain_core.embeddings import Embeddings

DEFAULT_MODEL = "all-MiniLM-L6-v2"
DEFAULT_PROVIDER = "huggingface"
EmbeddingProvider = Literal["huggingface", "openai"]


def load_embedder(
    provider: EmbeddingProvider = DEFAULT_PROVIDER,
    model_id: str = DEFAULT_MODEL,
) -> Embeddings:
    """Construct only the explicitly selected LangChain embedding provider."""
    if not isinstance(model_id, str) or not model_id.strip():
        raise RuntimeError("An embedding model identifier is required")
    if provider == "huggingface":
        try:
            from langchain_huggingface import HuggingFaceEmbeddings
        except ImportError as exc:  # pragma: no cover - installation configuration
            raise RuntimeError(
                "langchain-huggingface and sentence-transformers are required for "
                "the local Hugging Face AAR embedding provider"
            ) from exc
        return HuggingFaceEmbeddings(model_name=model_id)
    if provider == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError(
                "OpenAI embeddings were selected but OPENAI_API_KEY is not configured; "
                "set it or rebuild with --embedding-provider huggingface"
            )
        try:
            from langchain_openai import OpenAIEmbeddings
        except ImportError as exc:  # pragma: no cover - installation configuration
            raise RuntimeError("langchain-openai is required for --embedding-provider openai") from exc
        return OpenAIEmbeddings(model=model_id)
    raise RuntimeError(
        f"Unsupported embedding provider {provider!r}; choose 'huggingface' or 'openai'"
    )
