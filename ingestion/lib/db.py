"""Shared DB connection helper for ingestion scripts.

Reads connection info from environment variables (optionally loaded from a
local .env file). Either DATABASE_URL is set directly, or the individual
PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD variables are used to build one.
"""
import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

load_dotenv()


def get_database_url() -> str:
    """Return a SQLAlchemy-compatible DB URL from the environment."""
    url = os.environ.get("DATABASE_URL")
    if url:
        return url

    host = os.environ.get("PGHOST", "localhost")
    port = os.environ.get("PGPORT", "5432")
    dbname = os.environ.get("PGDATABASE", "flood")
    user = os.environ.get("PGUSER", "flood")
    password = os.environ.get("PGPASSWORD", "")

    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}"


def get_engine() -> Engine:
    """Create a SQLAlchemy engine for the configured PostGIS database."""
    return create_engine(get_database_url())
