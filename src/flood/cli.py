"""CLI entrypoint for flood."""
from __future__ import annotations

import argparse
import sys
from typing import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flood", description="Flood physics engine CLI")
    sub = parser.add_subparsers(dest="subcommand", required=True)

    # REGISTER: later cycles add exactly one register_* call below this line
    from flood.cli_scenario import register as register_scenario; register_scenario(sub)
    from flood.cli_prep_hand import register as register_prep_hand; register_prep_hand(sub)
    from flood.cli_prep_forcing import register as register_prep_forcing; register_prep_forcing(sub)
    from flood.cli_map import register as register_map; register_map(sub)
    from flood.cli_serve import register as register_serve; register_serve(sub)
    from flood.cli_skill import register as register_skill; register_skill(sub)

    args = parser.parse_args(argv)
    if hasattr(args, "func"):
        return args.func(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
