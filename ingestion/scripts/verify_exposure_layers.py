"""Post-ingestion smoke check for the exposure layers.

For every table, asserts: the table exists, every row's geometry is valid
(ST_IsValid), feature_id is non-null and unique. For the four automated
tables (roads, river_network, buildings, crossings), also asserts row count
> 0, confirming Milestone 1's PostGIS half is satisfied. `camps` ships empty
by design (see README) so its row count is reported but not required > 0.

Usage:
    python -m scripts.verify_exposure_layers
"""
import sys

from sqlalchemy import text

from lib.db import get_engine

TABLES_REQUIRING_ROWS = ["roads", "river_network", "buildings", "crossings"]
ALL_TABLES = TABLES_REQUIRING_ROWS + ["camps"]


def table_exists(conn, table: str) -> bool:
    result = conn.execute(
        text("SELECT to_regclass(:table) IS NOT NULL AS exists"),
        {"table": table},
    ).scalar()
    return bool(result)


def verify_table(conn, table: str, require_rows: bool) -> list:
    errors = []

    if not table_exists(conn, table):
        return [f"{table}: table does not exist"]

    row_count = conn.execute(text(f"SELECT count(*) FROM {table}")).scalar()

    if require_rows and row_count == 0:
        errors.append(f"{table}: row count is 0, expected > 0")

    if row_count > 0:
        invalid_count = conn.execute(
            text(f"SELECT count(*) FROM {table} WHERE NOT ST_IsValid(geom)")
        ).scalar()
        if invalid_count > 0:
            errors.append(f"{table}: {invalid_count} row(s) with invalid geometry")

        null_id_count = conn.execute(
            text(f"SELECT count(*) FROM {table} WHERE feature_id IS NULL")
        ).scalar()
        if null_id_count > 0:
            errors.append(f"{table}: {null_id_count} row(s) with null feature_id")

        distinct_id_count = conn.execute(
            text(f"SELECT count(DISTINCT feature_id) FROM {table}")
        ).scalar()
        if distinct_id_count != row_count:
            errors.append(
                f"{table}: feature_id is not unique ({distinct_id_count} distinct "
                f"of {row_count} rows)"
            )

    print(f"{table}: {row_count} row(s), {len(errors)} check failure(s)")
    return errors


def main() -> int:
    engine = get_engine()
    all_errors = []

    with engine.connect() as conn:
        for table in ALL_TABLES:
            require_rows = table in TABLES_REQUIRING_ROWS
            all_errors.extend(verify_table(conn, table, require_rows))

    if all_errors:
        print("\nFAILED checks:")
        for err in all_errors:
            print(f"  - {err}")
        return 1

    print("\nAll exposure layer checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
