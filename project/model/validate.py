"""FROZEN validation harness -- leave-one-incident-out cross-validation.

Do not modify. Every training attempt in train.py is scored against this file
unmodified, so results in logs/validation_runs.jsonl stay comparable across the
whole run.

Why leave-one-INCIDENT-out rather than random k-fold: tracts within one disaster
share a rainfall field, a declaration boundary, and a single registration drive.
Random k-fold would put neighbouring tracts from the same event on both sides of
the split and score memorisation of that event as generalisation. The question
this model has to answer is "given a NEW flood, which tracts generate claims",
so the fold boundary is the disaster.

Primary metric: mean Spearman rank correlation across folds. OpenFEMA
registration counts are self-reported and driven partly by outreach intensity,
so rank agreement is more meaningful than absolute error. RMSE is reported
alongside for every fold but is not what selection optimises.
"""
import json
import os
import time

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

INCIDENT_COL = "disasterNumber"
DEFAULT_LABEL = "label_reg_per_1k"
LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "logs",
                        "validation_runs.jsonl")


def _rmse(y, p):
    return float(np.sqrt(np.mean((np.asarray(y, float) - np.asarray(p, float)) ** 2)))


def _spearman(y, p):
    y = np.asarray(y, float)
    p = np.asarray(p, float)
    if len(y) < 3 or np.all(p == p[0]) or np.all(y == y[0]):
        return float("nan")
    rho = spearmanr(y, p).statistic
    return float(rho) if np.isfinite(rho) else float("nan")


def leave_one_incident_out(df, features, fit_predict, run_id, model_config,
                           label=DEFAULT_LABEL, log_path=LOG_PATH, notes=None):
    """Score one configuration. `fit_predict(X_tr, y_tr, X_te) -> predictions`.

    fit_predict owns its own imputation/scaling and must fit them on the
    training fold only -- the harness deliberately hands over raw frames so a
    config cannot accidentally leak test-fold statistics through the harness.
    """
    incidents = sorted(df[INCIDENT_COL].unique().tolist())
    fold_scores = []
    for inc in incidents:
        tr = df[df[INCIDENT_COL] != inc]
        te = df[df[INCIDENT_COL] == inc]
        if len(te) < 3 or len(tr) < 10:
            continue
        preds = np.asarray(fit_predict(tr[features], tr[label], te[features]),
                           dtype=float)
        y = te[label].to_numpy(dtype=float)
        fold_scores.append({
            "incident": int(inc),
            "n_train": int(len(tr)),
            "n_test": int(len(te)),
            "rmse": _rmse(y, preds),
            "spearman": _spearman(y, preds),
        })

    sp = np.array([f["spearman"] for f in fold_scores], dtype=float)
    rm = np.array([f["rmse"] for f in fold_scores], dtype=float)
    valid = sp[np.isfinite(sp)]
    record = {
        "run_id": run_id,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "label": label,
        "features_used": list(features),
        "n_features": len(features),
        "model_config": model_config,
        "fold_scores": fold_scores,
        "mean_score": float(valid.mean()) if len(valid) else float("nan"),
        "std_score": float(valid.std(ddof=0)) if len(valid) else float("nan"),
        "mean_rmse": float(np.nanmean(rm)) if len(rm) else float("nan"),
        "std_rmse": float(np.nanstd(rm)) if len(rm) else float("nan"),
        "metric": "mean Spearman rho across leave-one-incident-out folds",
    }
    if notes:
        record["notes"] = notes

    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a") as fh:
        fh.write(json.dumps(record) + "\n")
    return record


def load_table(path=None):
    path = path or os.path.join(os.path.dirname(__file__), "..", "data",
                                "processed", "training_table.csv")
    # A local pipeline run writes the plain .csv and that wins; a fresh clone
    # has only the committed .csv.gz snapshot. Resolved inline rather than via
    # scripts/common.py so the frozen harness keeps no dependency on the pulls.
    if not os.path.exists(path) and os.path.exists(path + ".gz"):
        path = path + ".gz"
    return pd.read_csv(path, dtype={"tract_fips": str, "fips_county": str},
                       low_memory=False)


if __name__ == "__main__":
    # Self-test: a train-mean baseline must score ~0 Spearman. This proves the
    # harness runs and gives every later config a floor to beat.
    df = load_table()
    feats = ["RPL_THEMES", "EP_POV150"]

    def baseline(X_tr, y_tr, X_te):
        return np.full(len(X_te), float(np.mean(y_tr)))

    rec = leave_one_incident_out(df, feats, baseline, "baseline_train_mean",
                                 {"kind": "constant train mean"},
                                 notes="harness self-test floor")
    print(json.dumps({k: rec[k] for k in
                      ("run_id", "mean_score", "std_score", "mean_rmse")}, indent=2))
    for f in rec["fold_scores"]:
        print(f"  DR-{f['incident']}: rmse={f['rmse']:.3f} "
              f"spearman={f['spearman']} n_test={f['n_test']}")
