"""Command line interface for offline AAR corpus validation, build, and search."""

from __future__ import annotations

import argparse
import json
import sys

from .corpus import build_corpus
from .manifest import validate_manifest
from .models import ExtractionError, IndexError, ManifestError
from .search import search_index


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m aar")
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="validate a manually verified source manifest")
    validate.add_argument("--manifest", required=True)
    build = commands.add_parser("build", help="build a local FAISS corpus")
    build.add_argument("--manifest", required=True)
    build.add_argument("--output", required=True)
    build.add_argument(
        "--embedding-provider", choices=("huggingface", "openai"), default="huggingface",
        help="embedding provider (default: local Hugging Face/sentence-transformers)",
    )
    build.add_argument("--model", default="all-MiniLM-L6-v2")
    search = commands.add_parser("search", help="search a built local corpus")
    search.add_argument("--index", required=True)
    search.add_argument("--query", required=True)
    search.add_argument("--hazard")
    search.add_argument("--phase")
    search.add_argument("--limit", type=int, default=10)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "validate":
            manifest = validate_manifest(args.manifest)
            print(json.dumps({"valid": True, "documents": len(manifest.documents)}))
        elif args.command == "build":
            print(json.dumps(build_corpus(
                args.manifest, args.output, embedding_provider=args.embedding_provider, model_id=args.model,
            ), sort_keys=True))
        else:
            print(json.dumps(search_index(args.index, args.query, hazard=args.hazard, phase=args.phase, limit=args.limit)))
    except (ManifestError, ExtractionError, IndexError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
