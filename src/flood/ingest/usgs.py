"""USGS OGC API continuous observation ingest and unit conversion."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import httpx
import numpy as np
import pandas as pd

from flood.contracts.models import Scenario

USGS_CONTINUOUS_URL = "https://api.waterdata.usgs.gov/ogcapi/v0/collections/continuous/items"

CFS_TO_CMS: float = 0.028316846592
FT_TO_M: float = 0.3048

CONVERSION_FACTORS: dict[str, float] = {
    "00060": CFS_TO_CMS,
    "00065": FT_TO_M,
}


def _format_iso(dt: datetime | str) -> str:
    if isinstance(dt, str):
        if not dt.endswith("Z"):
            d = datetime.fromisoformat(dt.replace("Z", "+00:00"))
            if d.tzinfo is None:
                d = d.replace(tzinfo=timezone.utc)
            else:
                d = d.astimezone(timezone.utc)
            return d.strftime("%Y-%m-%dT%H:%M:%SZ")
        return dt
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_continuous(
    site: str,
    parameter: str,
    start: datetime | str,
    end: datetime | str,
    client: httpx.Client | None = None,
    limit: int = 10000,
) -> pd.DataFrame:
    """Fetch continuous observations from the USGS OGC API, paging until no next link."""
    close_client = False
    if client is None:
        client = httpx.Client(timeout=60.0, follow_redirects=True)
        close_client = True

    start_str = _format_iso(start)
    end_str = _format_iso(end)
    factor = CONVERSION_FACTORS.get(parameter, 1.0)

    url = USGS_CONTINUOUS_URL
    params: dict[str, str | int] | None = {
        "monitoring_location_id": f"USGS-{site}",
        "parameter_code": parameter,
        "datetime": f"{start_str}/{end_str}",
        "f": "json",
        "limit": limit,
    }

    rows: list[dict[str, object]] = []

    try:
        while url:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

            for feat in data.get("features", []):
                props = feat.get("properties", {})
                raw_val = props.get("value")
                if raw_val is None or raw_val == "":
                    val_si = np.nan
                else:
                    try:
                        val_si = float(raw_val) * factor
                    except ValueError:
                        val_si = np.nan

                t_str = props.get("time")
                if not t_str:
                    continue

                approval = props.get("approval_status") or props.get("approval")

                rows.append({
                    "site": str(site),
                    "valid_time": pd.to_datetime(t_str, utc=True),
                    "parameter": str(parameter),
                    "value_si": np.float32(val_si),
                    "approval": approval,
                })

            # Check next link
            next_url = None
            for link in data.get("links", []):
                if link.get("rel") == "next":
                    next_url = link.get("href")
                    break

            if next_url:
                url = next_url
                params = None  # query params already encoded in next URL
            else:
                break
    finally:
        if close_client:
            client.close()

    cols = ["site", "valid_time", "parameter", "value_si", "approval"]
    if not rows:
        empty_df = pd.DataFrame(columns=cols)
        empty_df["valid_time"] = pd.to_datetime(empty_df["valid_time"], utc=True)
        empty_df["value_si"] = empty_df["value_si"].astype(np.float32)
        return empty_df

    df = pd.DataFrame(rows)[cols]
    df = df.sort_values(by="valid_time").reset_index(drop=True)
    return df


def ingest_usgs(
    scenario: Scenario,
    data_dir: Path | str,
    client: httpx.Client | None = None,
) -> None:
    """Ingest continuous USGS observations for all sites and parameters in scenario."""
    data_dir = Path(data_dir)
    scenario_id = scenario.scenario_id
    usgs_dir = data_dir / "usgs" / scenario_id
    usgs_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = usgs_dir / "continuous.parquet"

    start_dt = datetime.fromisoformat(scenario.hydrology.record.start.replace("Z", "+00:00")) - timedelta(days=1)
    end_dt = datetime.fromisoformat(scenario.hydrology.record.end.replace("Z", "+00:00")) + timedelta(days=1)

    usgs_sources = [s for s in scenario.forcing_defaults.sources if s.type == "usgs_continuous"]
    frames: list[pd.DataFrame] = []

    for src in usgs_sources:
        for site in src.sites:
            for param in src.parameters:
                df = fetch_continuous(site, param, start_dt, end_dt, client=client)
                if not df.empty:
                    frames.append(df)

    if frames:
        combined = pd.concat(frames, ignore_index=True)
        if parquet_path.exists():
            existing = pd.read_parquet(parquet_path)
            combined = pd.concat([existing, combined], ignore_index=True)
        combined = combined.drop_duplicates(subset=["site", "valid_time", "parameter"])
        combined = combined.sort_values(by=["site", "parameter", "valid_time"]).reset_index(drop=True)
        combined.to_parquet(parquet_path, index=False)
    elif not parquet_path.exists():
        empty_df = pd.DataFrame(columns=["site", "valid_time", "parameter", "value_si", "approval"])
        empty_df["valid_time"] = pd.to_datetime(empty_df["valid_time"], utc=True)
        empty_df["value_si"] = empty_df["value_si"].astype(np.float32)
        empty_df.to_parquet(parquet_path, index=False)
