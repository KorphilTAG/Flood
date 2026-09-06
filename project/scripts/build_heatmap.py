"""Section 6 -- disaggregate tract risk onto OSM building footprints.

Fits the winning configuration on the full training table, predicts a risk
score for each Kerr County tract, then splits each tract's score across the
building footprints inside it in proportion to footprint area, and emits one
Point feature per footprint centroid.

Reuses ingestion/lib/geo.py (Overpass client, feature_id convention, TIGER
boundary fetch) rather than re-implementing them.
"""
import json
import os
import sys

import geopandas as gpd
import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "model"))
sys.path.insert(0, os.path.join(HERE, "..", "..", "ingestion"))

from common import LOGS, PROCESSED, RAW, log_block  # noqa: E402
from lib.geo import (fetch_tiger_county_boundary, make_feature_id,  # noqa: E402
                     overpass_bbox, overpass_elements_to_geodataframe,
                     overpass_query)
from train import FEATURE_SETS, make_knn, make_logit, make_mlp, make_ridge  # noqa: E402
from validate import load_table  # noqa: E402

LOG = os.path.join(LOGS, "final_summary.log")
OUT = os.path.join(HERE, "..", "output", "demographic_risk.geojson")
STATE_FP, COUNTY_FP = "48", "265"
KERR_FIPS = STATE_FP + COUNTY_FP
TARGET_DISASTER = 4879
TIGER_TRACT = ("https://www2.census.gov/geo/tiger/TIGER2023/TRACT/"
               "tl_2023_48_tract.zip")
EQUAL_AREA = "EPSG:5070"
# Derived in Test 6 from the injected-null experiment, not chosen in advance.
MAX_MISSING_FEATURES = 0  # CONUS Albers -- areas in m^2, not degrees


def winning_predictor():
    """Rebuild the winning config from model/best.json."""
    with open(os.path.join(HERE, "..", "model", "best.json")) as fh:
        best = json.load(fh)
    rid = best["best_run_id"]
    runs = [json.loads(l) for l in
            open(os.path.join(LOGS, "validation_runs.jsonl"))]
    rec = [r for r in runs if r["run_id"] == rid][-1]
    cfg = rec["model_config"]
    fam = cfg["family"]
    if fam == "logistic":
        fp = make_logit(cfg["C"])
    elif fam == "ridge":
        fp = make_ridge(cfg["alpha"])
    elif fam == "knn_cosine":
        fp = make_knn(cfg["k"])
    elif fam == "mlp":
        fp = make_mlp(cfg["hidden"], cfg["dropout"], cfg["weight_decay"])
    else:
        raise RuntimeError(f"no rebuild path for family {fam!r}")
    return rid, fp, cfg, FEATURE_SETS[cfg["feature_set"]], best, rec


def fetch_tracts():
    import io
    import tempfile
    import zipfile

    import requests
    r = requests.get(TIGER_TRACT, timeout=300,
                     headers={"User-Agent": "Flood-DigitalTwin-Research/0.1"})
    r.raise_for_status()
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            zf.extractall(tmp)
        shp = [f for f in os.listdir(tmp) if f.endswith(".shp")][0]
        g = gpd.read_file(os.path.join(tmp, shp))
    g = g[g["COUNTYFP"] == COUNTY_FP].to_crs("EPSG:4326")
    return g[["GEOID", "geometry"]].rename(columns={"GEOID": "tract_fips"})


OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]


def _overpass(query):
    """Overpass POST with a User-Agent and mirror fallback.

    lib.geo.overpass_query sends no User-Agent, which overpass-api.de now
    rejects with HTTP 406. Kept local rather than changing the shared client,
    which belongs to another feature.
    """
    import requests
    last = None
    for url in OVERPASS_MIRRORS:
        for attempt in range(2):
            try:
                r = requests.post(
                    url, data={"data": query}, timeout=300,
                    headers={"User-Agent": "Flood-DigitalTwin-Research/0.1 "
                                           "(+public-data ingest)"})
                if r.status_code == 200:
                    return r.json()
                last = f"HTTP {r.status_code}"
            except Exception as e:  # noqa: BLE001
                last = repr(e)
            print(f"    overpass {url} attempt {attempt+1}: {last}", flush=True)
    raise RuntimeError(f"all Overpass mirrors failed: {last}")


def fetch_buildings(boundary_geom):
    south, west, north, east = overpass_bbox(boundary_geom)
    q = f"""
    [out:json][timeout:300];
    (
      way["building"]({south},{west},{north},{east});
      relation["building"]({south},{west},{north},{east});
    );
    out geom;
    """
    data = _overpass(q)
    gdf = overpass_elements_to_geodataframe(data.get("elements", []))
    return gdf[gdf.intersects(boundary_geom)].copy()


def main():
    df = load_table()
    rid, fit_predict, cfg, feats, best, rec = winning_predictor()

    # Fit on every incident except the target, predict the target's tracts --
    # the same train/test separation the harness scored, so the published
    # numbers are the honest held-out ones.
    tr = df[df.disasterNumber != TARGET_DISASTER]
    te = df[(df.disasterNumber == TARGET_DISASTER) &
            (df.fips_county == KERR_FIPS)].copy()
    te["score_raw"] = fit_predict(tr[feats], tr["label_reg_per_1k"], te[feats])

    # Test 6 abstention rule: median imputation is not safe for this model --
    # even one missing feature reordered predictions (rho=0.58) -- so a tract
    # is scored only with a population denominator and COMPLETE features.
    te["n_missing"] = te[feats].isna().sum(axis=1)
    te["abstain"] = (te["n_missing"] > MAX_MISSING_FEATURES) | te["population"].isna()
    tract_scores = te.loc[~te["abstain"]].set_index("tract_fips")["score_raw"].to_dict()
    abstained = set(te.loc[te["abstain"], "tract_fips"])
    print(f"abstention: {len(abstained)} of {len(te)} target tracts "
          f"withheld for incomplete features", flush=True)

    boundary = fetch_tiger_county_boundary(STATE_FP, COUNTY_FP)
    boundary_geom = boundary.union_all()
    tracts = fetch_tracts()
    bld = fetch_buildings(boundary_geom)
    print(f"OSM footprints in Kerr County: {len(bld):,}", flush=True)

    bld = gpd.sjoin(bld, tracts, how="inner", predicate="intersects")
    bld = bld[~bld.index.duplicated(keep="first")].copy()

    bld["area_m2"] = bld.to_crs(EQUAL_AREA).geometry.area
    bld = bld[bld["area_m2"] > 0].copy()
    bld["tract_score"] = bld["tract_fips"].map(tract_scores)
    bld["abstained"] = bld["tract_fips"].isin(abstained)
    # Keep abstained footprints in the output, marked, rather than silently
    # dropping them or rendering a low-confidence guess.
    bld = bld[bld["tract_score"].notna() | bld["abstained"]].copy()

    # Area-weighted split: a tract's footprints carry its score in proportion
    # to their share of built area, so the weights sum back to the tract score.
    share = bld.groupby("tract_fips")["area_m2"].transform("sum")
    bld["weight"] = bld["tract_score"] * bld["area_m2"] / share

    cent = bld.to_crs(EQUAL_AREA).geometry.centroid.to_crs("EPSG:4326")
    bld["osm_ref"] = bld["type"].astype(str) + "/" + bld["id"].astype(str)

    svi_year = "2022"
    feats_out = []
    for (_, row), pt in zip(bld.iterrows(), cent):
        fid = make_feature_id("building", "osm", row["osm_ref"])
        feats_out.append({
            "type": "Feature",
            "geometry": {"type": "Point",
                         "coordinates": [round(pt.x, 7), round(pt.y, 7)]},
            "properties": {
                "weight": (None if row["abstained"]
                           else round(float(row["weight"]), 6)),
                "feature_id": fid,
                "score_source": ("insufficient_data" if row["abstained"]
                                 else f"model:{rid}"),
                "citation_ids": [
                    f"openfema:IndividualsAndHouseholdsProgramValidRegistrations:DR-{TARGET_DISASTER}",
                    f"cdc-svi:{svi_year}:{row['tract_fips']}",
                    f"acs:2019-2023-5yr:{row['tract_fips']}",
                    f"osm:{row['osm_ref']}",
                ],
            },
        })

    gj = {"type": "FeatureCollection",
          "features": feats_out,
          "properties": {
              "generated_for": f"Kerr County, TX (FIPS {KERR_FIPS})",
              "score_source": f"model:{rid}",
              "model_config": cfg,
              "held_out_incident": TARGET_DISASTER,
              "units": "IA registrations per 1,000 residents, "
                       "area-weighted share per footprint",
              "abstention_rule": {
                  "max_missing_features": MAX_MISSING_FEATURES,
                  "derived_from": "Test 6 injected-null experiment",
                  "note": "features with score_source=insufficient_data carry "
                          "weight=null and must not be rendered as zero"},
          }}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(gj, fh)

    w = np.array([f["properties"]["weight"] for f in feats_out
                  if f["properties"]["weight"] is not None])
    n_abstain = sum(1 for f in feats_out
                    if f["properties"]["score_source"] == "insufficient_data")
    body = [
        f"features: {len(feats_out):,} footprint centroids",
        f"tracts covered: {bld.tract_fips.nunique()} of {len(tract_scores)} "
        f"Kerr County tracts with a predicted score",
        f"score_source: model:{rid}",
        f"abstained footprints (insufficient_data): {n_abstain}",
        "",
        f"weight distribution: min={w.min():.6f} max={w.max():.6f} "
        f"mean={w.mean():.6f} sum={w.sum():.4f}",
        f"tract score sum (target): {sum(tract_scores.values()):.4f}",
        "",
        "SPOT-CHECK (5 sample features)",
    ]
    for f in feats_out[:5]:
        body.append(json.dumps(f["properties"]))
    log_block(LOG, "Final checkpoint -- heatmap output", "\n".join(body))
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
