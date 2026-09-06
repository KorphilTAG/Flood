"""Shared helpers for the demographic-risk data pulls.

Every source here is public and credential-free (PRD Section 12, "Agent-pullable"
rows). Network failures are retried with backoff rather than aborting the whole
run, so one flaky host does not kill the pull.
"""
import io
import os
import sys
import time
import zipfile

import pandas as pd
import requests

RAW = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
PROCESSED = os.path.join(os.path.dirname(__file__), "..", "data", "processed")
LOGS = os.path.join(os.path.dirname(__file__), "..", "logs")

USER_AGENT = "Flood-DigitalTwin-Research/0.1 (+public-data ingest)"

# The nine Texas flood/storm declarations carrying Individual Assistance that
# make up the leave-one-incident-out training set. DR-4879 (2025-07-06) is the
# July 2025 Kerr County event this project targets.
TX_IA_DISASTERS = [4879, 4871, 4781, 4466, 4454, 4377, 4272, 4269, 4266]
TARGET_DISASTER = 4879
KERR_COUNTY_FIPS = "48265"


def table_path(path):
    """Resolve a derived-table path to the plain .csv, else the committed .csv.gz.

    A local pipeline run writes uncompressed .csv and that wins. Only the
    gzipped frozen snapshot is committed (see .gitignore), so a fresh clone
    reads that instead and reproduces the recorded scores. pandas decompresses
    by extension, so callers need no other change.
    """
    if os.path.exists(path):
        return path
    gz = path + ".gz"
    if os.path.exists(gz):
        return gz
    raise FileNotFoundError(f"neither {path} nor {gz} exists")


def get(url, params=None, tries=4, timeout=120, stream_bytes=False):
    """GET with exponential backoff. Returns Response, or raises after `tries`."""
    last = None
    for i in range(tries):
        try:
            r = requests.get(
                url, params=params, timeout=timeout,
                headers={"User-Agent": USER_AGENT},
            )
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001 - retry on any transport error
            last = repr(e)
        wait = 2 ** i
        print(f"    retry {i+1}/{tries} after {last} (sleep {wait}s)", flush=True)
        time.sleep(wait)
    raise RuntimeError(f"GET failed after {tries} tries: {url} ({last})")


def zero_pad(series, width):
    """Normalize a FIPS/GEOID column to a zero-padded string of fixed width.

    The single most common join failure in this pipeline: FIPS codes arrive as
    ints from some sources (dropping Texas's leading '4' is impossible, but
    county '007' becomes 7) and as strings from others.
    """
    s = series.astype("string").str.strip()
    s = s.str.replace(r"\.0$", "", regex=True)
    s = s.str.replace(r"[^0-9]", "", regex=True)
    return s.str.zfill(width).where(s.notna() & (s != ""), pd.NA)


def log_block(path, title, body):
    """Append a titled block to a checkpoint log and echo it to stdout."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    text = f"\n{'='*78}\n{title}\n{'='*78}\n{body}\n"
    with open(path, "a") as fh:
        fh.write(text)
    print(text, flush=True)


def describe(df, name):
    """Row count, column list and head sample -- the Checkpoint 1 contract."""
    buf = io.StringIO()
    buf.write(f"rows={len(df):,}  cols={len(df.columns)}\n")
    buf.write(f"columns: {list(df.columns)}\n")
    buf.write("head:\n")
    buf.write(df.head(5).to_string()[:3000])
    buf.write("\n")
    return f"--- {name} ---\n{buf.getvalue()}"
