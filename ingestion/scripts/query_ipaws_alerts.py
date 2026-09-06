"""CLI entry point for a curator to query FEMA's public IPAWS Archive
directly, without booting the FastAPI critic service.

Prints the resulting JSON array to stdout (or, with `--count-only`, the
integer count). Never wired into an agent loop and never automatically
called by `POST /v1/critique`; see `ingestion/critic/ipaws.py` and
`ingestion/README.md` for the tool's fixed field set, default
`status="Actual"` filter, and the retention-accuracy caveat.

Usage:
    python -m scripts.query_ipaws_alerts --start YYYY-MM-DD --end YYYY-MM-DD \\
        [--area TEXT] [--event-type TEXT] [--status TEXT|none] \\
        [--max-records N] [--count-only]
"""
import argparse
import json
import sys

from critic.ipaws import count_ipaws_alerts, query_ipaws_alerts


def _status_arg(value: str):
    if value is None:
        return "Actual"
    if value.strip().lower() == "none":
        return None
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Query FEMA's public IPAWS Archive for historical CAP alert records"
    )
    parser.add_argument("--start", required=True, dest="start_date", help="Strict YYYY-MM-DD start of the date range")
    parser.add_argument("--end", required=True, dest="end_date", help="Strict YYYY-MM-DD end of the date range")
    parser.add_argument("--area", default=None, dest="area_contains", help="Substring to match against info_area_areadesc")
    parser.add_argument("--event-type", default=None, dest="event_type", help="Substring to match against info_event")
    parser.add_argument(
        "--status",
        default="Actual",
        type=_status_arg,
        help="CAP status filter (default: Actual). Pass 'none' to omit the status filter entirely.",
    )
    parser.add_argument("--max-records", type=int, default=2000, dest="max_records", help="Maximum rows to return")
    parser.add_argument("--count-only", action="store_true", help="Print only the integer count, no records")
    args = parser.parse_args(argv)

    if args.count_only:
        count = count_ipaws_alerts(
            start_date=args.start_date,
            end_date=args.end_date,
            area_contains=args.area_contains,
            event_type=args.event_type,
            status=args.status,
        )
        print(count)
        return 0

    records = query_ipaws_alerts(
        start_date=args.start_date,
        end_date=args.end_date,
        area_contains=args.area_contains,
        event_type=args.event_type,
        status=args.status,
        max_records=args.max_records,
    )
    print(json.dumps(records, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
