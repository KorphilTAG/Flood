"""NWM download, subsetting, and Parquet persistence."""
from __future__ import annotations

import logging
import time

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Collection, Iterable
import httpx
import numpy as np
import pandas as pd
import xarray as xr

from flood.contracts.models import Scenario

logger = logging.getLogger("flood.ingest.nwm")

GCS_LIST_URL = "https://storage.googleapis.com/storage/v1/b/national-water-model/o"
GCS_OBJECT_URL = "https://storage.googleapis.com/national-water-model/{name}"


def _parse_utc(dt: datetime | str) -> datetime:
    if isinstance(dt, str):
        s = dt.replace("Z", "+00:00")
        res = datetime.fromisoformat(s)
    else:
        res = dt
    if res.tzinfo is None:
        res = res.replace(tzinfo=timezone.utc)
    return res.astimezone(timezone.utc)


def analysis_names(record_start: datetime | str, record_end: datetime | str) -> list[str]:
    """Yield analysis file names for every hour with valid_time in [record_start, record_end]."""
    start = _parse_utc(record_start)
    end = _parse_utc(record_end)
    if start > end:
        return []

    if start.minute > 0 or start.second > 0 or start.microsecond > 0:
        cur = start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        cur = start.replace(minute=0, second=0, microsecond=0)

    end_hour = end.replace(minute=0, second=0, microsecond=0)

    names: list[str] = []
    while cur <= end_hour:
        names.append(
            f"nwm.{cur.strftime('%Y%m%d')}/analysis_assim/"
            f"nwm.t{cur.strftime('%H')}z.analysis_assim.channel_rt.tm00.conus.nc"
        )
        cur += timedelta(hours=1)
    return names


def short_range_names(
    record_start: datetime | str,
    record_end: datetime | str,
    max_lead_hours: int,
) -> list[str]:
    """Yield short-range file names f001..f{max_lead_hours} for hourly cycles in [record_start, record_end]."""
    start = _parse_utc(record_start)
    end = _parse_utc(record_end)
    if start > end or max_lead_hours < 1:
        return []

    if start.minute > 0 or start.second > 0 or start.microsecond > 0:
        cur = start.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        cur = start.replace(minute=0, second=0, microsecond=0)

    end_hour = end.replace(minute=0, second=0, microsecond=0)

    names: list[str] = []
    while cur <= end_hour:
        cycle_str = cur.strftime("%Y%m%d")
        cycle_hour = cur.strftime("%H")
        for lead in range(1, max_lead_hours + 1):
            names.append(
                f"nwm.{cycle_str}/short_range/"
                f"nwm.t{cycle_hour}z.short_range.channel_rt.f{lead:03d}.conus.nc"
            )
        cur += timedelta(hours=1)
    return names


def subset_file(path: str | Path, feature_ids: Iterable[int]) -> pd.DataFrame:
    """Subset an NWM channel_rt netCDF file to the requested feature_ids."""
    path = Path(path)
    requested_ids = set(int(x) for x in feature_ids)

    with xr.open_dataset(path, engine="h5netcdf") as ds:
        time_coord = ds["time"].values if "time" in ds else None
        ref_coord = ds["reference_time"].values if "reference_time" in ds else None

        valid_time = pd.to_datetime(time_coord, utc=True)
        if hasattr(valid_time, "__len__") and len(valid_time) > 0:
            valid_time = valid_time[0]

        if ref_coord is not None:
            issue_time = pd.to_datetime(ref_coord, utc=True)
            if hasattr(issue_time, "__len__") and len(issue_time) > 0:
                issue_time = issue_time[0]
        else:
            issue_time = valid_time

        is_short_range = (
            "short_range" in str(path).lower()
            or ("f0" in str(path).lower())
            or (ref_coord is not None and np.any(ds["time"].values != ds["reference_time"].values))
        )

        file_fids = ds["feature_id"].values
        matched_ids = [fid for fid in file_fids if int(fid) in requested_ids]

        cols = ["valid_time", "feature_id", "q_cms"]
        if is_short_range:
            cols.insert(0, "issue_time")
        if "velocity" in ds:
            cols.append("v_ms")
        cols.append("qlat_cms")

        if not matched_ids:
            empty_df = pd.DataFrame(columns=cols)
            if "valid_time" in empty_df:
                empty_df["valid_time"] = pd.to_datetime(empty_df["valid_time"], utc=True)
            if "issue_time" in empty_df:
                empty_df["issue_time"] = pd.to_datetime(empty_df["issue_time"], utc=True)
            return empty_df

        sub = ds.sel(feature_id=matched_ids)

        q_cms = np.atleast_1d(np.asarray(sub["streamflow"].values, dtype=np.float32).squeeze())

        v_ms = None
        if "velocity" in sub:
            v_ms = np.atleast_1d(np.asarray(sub["velocity"].values, dtype=np.float32).squeeze())

        q_sfc = 0.0
        if "qSfcLatRunoff" in sub:
            q_sfc = np.atleast_1d(np.asarray(sub["qSfcLatRunoff"].values, dtype=np.float32).squeeze())

        q_bkt = 0.0
        if "qBucket" in sub:
            q_bkt = np.atleast_1d(np.asarray(sub["qBucket"].values, dtype=np.float32).squeeze())

        qlat_cms = (q_sfc + q_bkt).astype(np.float32)

        n = len(matched_ids)
        data: dict[str, object] = {
            "valid_time": pd.to_datetime([valid_time] * n, utc=True),
            "feature_id": np.asarray(matched_ids, dtype=np.int64),
            "q_cms": q_cms.astype(np.float32),
        }
        if is_short_range:
            data["issue_time"] = pd.to_datetime([issue_time] * n, utc=True)
        if v_ms is not None:
            data["v_ms"] = v_ms.astype(np.float32)
        data["qlat_cms"] = qlat_cms

        df = pd.DataFrame(data)[cols]
        return df


def list_objects(prefix: str, client: httpx.Client | None = None) -> list[str]:
    """List object names from the National Water Model GCS bucket matching prefix."""
    close_client = False
    if client is None:
        client = httpx.Client(timeout=30.0, follow_redirects=True)
        close_client = True

    names: list[str] = []
    page_token = None
    try:
        while True:
            params: dict[str, str] = {
                "prefix": prefix,
                "fields": "items(name,size),nextPageToken",
            }
            if page_token:
                params["pageToken"] = page_token
            resp = client.get(GCS_LIST_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("items", []):
                if "name" in item:
                    names.append(item["name"])
            page_token = data.get("nextPageToken")
            if not page_token:
                break
    finally:
        if close_client:
            client.close()
    return names


def download_file(name: str, target_path: Path | str, client: httpx.Client | None = None) -> Path:
    """Download a single NWM file from GCS."""
    target_path = Path(target_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    url = GCS_OBJECT_URL.format(name=name)

    close_client = False
    if client is None:
        client = httpx.Client(timeout=60.0, follow_redirects=True)
        close_client = True

    try:
        last_exc: Exception | None = None
        for attempt in range(1, 4):
            try:
                with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    tmp_path = target_path.with_suffix(target_path.suffix + ".part")
                    with open(tmp_path, "wb") as f:
                        for chunk in resp.iter_bytes(chunk_size=65536):
                            f.write(chunk)
                    tmp_path.replace(target_path)
                return target_path
            except (httpx.TransportError, OSError) as exc:
                # transient network failures (unreachable network, reset, timeout): retry with backoff
                last_exc = exc
                logger.warning("download %s attempt %d failed: %s", name, attempt, exc)
                time.sleep(2 * attempt)
        raise RuntimeError(f"download failed after 3 attempts: {name}") from last_exc
    finally:
        if close_client:
            client.close()


def load_manifest(manifest_path: Path | str) -> set[str]:
    """Load the set of already processed files from manifest.json."""
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        return set()
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return set(data.get("files", []))
        if isinstance(data, list):
            return set(data)
        return set()
    except Exception:
        return set()


def save_manifest(manifest_path: Path | str, files: Iterable[str]) -> None:
    """Save the set of processed files to manifest.json."""
    manifest_path = Path(manifest_path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"files": sorted(list(set(files)))}
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def append_to_parquet(df: pd.DataFrame, parquet_path: Path | str, key_cols: list[str]) -> None:
    """Append rows to a Parquet file, deduplicating on key_cols and sorting."""
    parquet_path = Path(parquet_path)
    if df.empty:
        return

    if parquet_path.exists():
        existing = pd.read_parquet(parquet_path)
        combined = pd.concat([existing, df], ignore_index=True)
        combined = combined.drop_duplicates(subset=key_cols).sort_values(by=key_cols).reset_index(drop=True)
    else:
        parquet_path.parent.mkdir(parents=True, exist_ok=True)
        combined = df.drop_duplicates(subset=key_cols).sort_values(by=key_cols).reset_index(drop=True)

    combined.to_parquet(parquet_path, index=False)


def ingest_nwm(
    scenario: Scenario,
    data_dir: Path | str,
    keep_raw: bool = False,
    client: httpx.Client | None = None,
    include_short_range: bool = True,
) -> None:
    """Download, subset, and append NWM analysis and (optionally) short-range files for a scenario.

    Short range is about six times the analysis volume (one file per lead hour per cycle);
    pass include_short_range=False to get lateral inflow for ungauged reaches quickly.
    """
    data_dir = Path(data_dir)
    scenario_id = scenario.scenario_id
    nwm_dir = data_dir / "nwm" / scenario_id
    nwm_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = nwm_dir / "raw"

    manifest_path = nwm_dir / "manifest.json"
    manifest = load_manifest(manifest_path)

    # Determine feature_ids: prefer network.parquet from cube
    cube_network = data_dir / "cube" / scenario_id / "network.parquet"
    if cube_network.exists():
        feature_ids = set(pd.read_parquet(cube_network)["feature_id"].astype(int))
    else:
        feature_ids = set(int(g.feature_id) for g in scenario.hydrology.gauges)

    record_start = scenario.hydrology.record.start
    record_end = scenario.hydrology.record.end

    analysis_files = analysis_names(record_start, record_end)
    for name in analysis_files:
        if name in manifest:
            continue
        raw_path = raw_dir / Path(name).name
        download_file(name, raw_path, client=client)
        sub_df = subset_file(raw_path, feature_ids)
        if not keep_raw:
            raw_path.unlink(missing_ok=True)

        cols = ["valid_time", "feature_id", "q_cms", "v_ms", "qlat_cms"]
        keep_cols = [c for c in cols if c in sub_df.columns]
        append_to_parquet(sub_df[keep_cols], nwm_dir / "analysis.parquet", ["valid_time", "feature_id"])
        manifest.add(name)
        save_manifest(manifest_path, manifest)

    # Short range
    sr_source = next((s for s in scenario.forcing_defaults.sources if s.type == "nwm_short_range"), None)
    if sr_source is not None and include_short_range:
        sr_files = short_range_names(record_start, record_end, sr_source.max_lead_hours)
        for name in sr_files:
            if name in manifest:
                continue
            raw_path = raw_dir / Path(name).name
            try:
                download_file(name, raw_path, client=client)
            except RuntimeError as exc:
                logger.warning("skipping %s: %s", name, exc)
                continue
            sub_df = subset_file(raw_path, feature_ids)
            if not keep_raw:
                raw_path.unlink(missing_ok=True)

            cols = ["issue_time", "valid_time", "feature_id", "q_cms", "qlat_cms"]
            keep_cols = [c for c in cols if c in sub_df.columns]
            append_to_parquet(sub_df[keep_cols], nwm_dir / "short_range.parquet", ["issue_time", "valid_time", "feature_id"])
            manifest.add(name)
            save_manifest(manifest_path, manifest)

    if not keep_raw and raw_dir.exists():
        try:
            if not any(raw_dir.iterdir()):
                raw_dir.rmdir()
        except Exception:
            pass
