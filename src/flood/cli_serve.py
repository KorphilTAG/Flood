"""Serve CLI subcommand."""
from __future__ import annotations

import argparse
import uvicorn
from flood.api.app import create_app


def run_serve(args: argparse.Namespace) -> int:
    """Run uvicorn server with create_app()."""
    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    """Register serve subcommand."""
    serve_parser = subparsers.add_parser("serve", help="Start engine API server")
    serve_parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    serve_parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    serve_parser.set_defaults(func=run_serve)
