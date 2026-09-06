"""Out-of-fold predictions for the winning model and the k-NN fallback.

Every row is predicted by a model that never saw its incident, using the same
leave-one-incident-out split the frozen harness scores on. Tests 2, 5 and 7 all
read this file, so it is computed once rather than per test.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "model"))
sys.path.insert(0, HERE)
from common import LOGS, PROCESSED  # noqa: E402
from train import FEATURE_SETS, make_knn, make_logit, make_mlp, make_ridge  # noqa: E402
from validate import INCIDENT_COL, load_table  # noqa: E402

OUT = os.path.join(PROCESSED, "oof_predictions.csv")


def predictor(cfg):
    fam = cfg["family"]
    if fam == "mlp":
        return make_mlp(cfg["hidden"], cfg["dropout"], cfg["weight_decay"])
    if fam == "ridge":
        return make_ridge(cfg["alpha"])
    if fam == "logistic":
        return make_logit(cfg["C"])
    return make_knn(cfg.get("k", 3))


def oof(df, feats, fp, label="label_reg_per_1k"):
    out = np.full(len(df), np.nan)
    pos = {ix: i for i, ix in enumerate(df.index)}
    for inc in sorted(df[INCIDENT_COL].unique()):
        tr = df[df[INCIDENT_COL] != inc]
        te = df[df[INCIDENT_COL] == inc]
        p = np.asarray(fp(tr[feats], tr[label], te[feats]), dtype=float)
        for ix, v in zip(te.index, p):
            out[pos[ix]] = v
        print(f"    fold DR-{inc} done", flush=True)
    return out


def main():
    best = json.load(open(os.path.join(HERE, "..", "model", "best.json")))
    runs = {json.loads(l)["run_id"]: json.loads(l)
            for l in open(os.path.join(LOGS, "validation_runs.jsonl"))}
    win = runs[best["best_run_id"]]
    nn = runs["fallback_nn"]
    df = load_table()

    print("model OOF...", flush=True)
    p_model = oof(df, win["features_used"], predictor(win["model_config"]))
    print("knn OOF...", flush=True)
    p_nn = oof(df, nn["features_used"], predictor(nn["model_config"]))

    out = df[["disasterNumber", "tract_fips", "fips_county", "population",
              "ia_registrations", "label_reg_per_1k"]].copy()
    out["pred_model"] = p_model
    out["pred_nn"] = p_nn
    out.to_csv(OUT, index=False)
    print(f"wrote {OUT}  rows={len(out):,}  "
          f"model nulls={np.isnan(p_model).sum()}  nn nulls={np.isnan(p_nn).sum()}")


if __name__ == "__main__":
    main()
