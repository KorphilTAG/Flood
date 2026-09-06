"""HandCube representation on disk and in memory."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import numpy as np
import pandas as pd
from flood.interfaces import (
    BranchArrays,
    GAUGE_COLUMNS,
    Grid,
    NETWORK_COLUMNS,
    RatingTable,
)


class HandCube:
    def __init__(
        self,
        grid: Grid,
        branches: list[BranchArrays],
        network: pd.DataFrame,
        gauges: pd.DataFrame,
        meta: dict,
    ) -> None:
        self.grid = grid
        self.branches = branches
        self.network = network
        self.gauges = gauges
        self.meta = meta
        self._branches_by_id = {b.branch_id: b for b in branches}

    def branch(self, branch_id: int) -> BranchArrays:
        if branch_id not in self._branches_by_id:
            raise KeyError(f"Branch {branch_id} not in cube")
        return self._branches_by_id[branch_id]

    def catchments_for_feature(self, feature_id: int) -> list[tuple[int, int]]:
        results: list[tuple[int, int]] = []
        for b in self.branches:
            matches = np.where(b.rating.feature_id == feature_id)[0]
            for cidx in matches:
                results.append((b.branch_id, int(cidx)))
        return results

    def save(self, cube_dir: Path | str) -> None:
        p = Path(cube_dir)
        p.mkdir(parents=True, exist_ok=True)

        meta_out = dict(self.meta)
        meta_out["grid"] = {
            "crs": self.grid.crs,
            "resolution_m": self.grid.resolution_m,
            "width": self.grid.width,
            "height": self.grid.height,
            "transform": list(self.grid.transform),
            "bounds": list(self.grid.bounds),
        }
        meta_out["branches"] = [b.branch_id for b in self.branches]
        if "created_at" not in meta_out:
            meta_out["created_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        (p / "meta.json").write_text(json.dumps(meta_out, indent=2), encoding="utf-8")

        for b in self.branches:
            np.save(p / f"rem_{b.branch_id}.npy", b.rem)
            np.save(p / f"catch_{b.branch_id}.npy", b.catch)
            np.savez_compressed(
                p / f"rating_{b.branch_id}.npz",
                hydro_id=b.rating.hydro_id,
                feature_id=b.rating.feature_id,
                lake_id=b.rating.lake_id,
                stream_order=b.rating.stream_order,
                length_km=b.rating.length_km,
                slope=b.rating.slope,
                manning_n=b.rating.manning_n,
                stage_m=b.rating.stage_m,
                q_cms=b.rating.q_cms,
                wet_area_m2=b.rating.wet_area_m2,
                hyd_radius_m=b.rating.hyd_radius_m,
                top_width_m=b.rating.top_width_m,
            )

        self.network.to_parquet(p / "network.parquet", index=False)
        self.gauges.to_parquet(p / "gauges.parquet", index=False)

    @classmethod
    def load(cls, cube_dir: Path | str) -> "HandCube":
        p = Path(cube_dir)
        meta = json.loads((p / "meta.json").read_text(encoding="utf-8"))
        g = meta["grid"]
        grid = Grid(
            crs=g["crs"],
            resolution_m=float(g["resolution_m"]),
            width=int(g["width"]),
            height=int(g["height"]),
            transform=tuple(g["transform"]),
            bounds=tuple(g["bounds"]),
        )

        branches: list[BranchArrays] = []
        for bid in meta["branches"]:
            rem = np.load(p / f"rem_{bid}.npy")
            catch = np.load(p / f"catch_{bid}.npy")
            with np.load(p / f"rating_{bid}.npz") as r:
                rating = RatingTable(
                    hydro_id=r["hydro_id"],
                    feature_id=r["feature_id"],
                    lake_id=r["lake_id"],
                    stream_order=r["stream_order"],
                    length_km=r["length_km"],
                    slope=r["slope"],
                    manning_n=r["manning_n"],
                    stage_m=r["stage_m"],
                    q_cms=r["q_cms"],
                    wet_area_m2=r["wet_area_m2"],
                    hyd_radius_m=r["hyd_radius_m"],
                    top_width_m=r["top_width_m"],
                )
            branches.append(BranchArrays(branch_id=bid, rem=rem, catch=catch, rating=rating))

        network = pd.read_parquet(p / "network.parquet")
        gauges = pd.read_parquet(p / "gauges.parquet")

        return cls(grid=grid, branches=branches, network=network, gauges=gauges, meta=meta)
