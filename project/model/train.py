"""Training loop for the demographic risk model.

Model families in the order the parent PRD (Section 6.4) mandates -- exhaust the
shallow, heavily-regularised options before reaching for anything deeper:

  1. Shallow linear models over hand-engineered features, heavy L2:
       - Ridge on log1p(rate)  -- the continuous analogue
       - Logistic on P(any claim), used as a continuous risk score
  2. Small feed-forward net (<=32 units, dropout >=0.3), only if (1) underfits.

Every configuration is scored by the FROZEN harness in validate.py. Checkpoints
are written only when a config improves on the best mean Spearman so far.

Tripwire: 8 consecutive configurations without improvement stops the search.
"""
import json
import os
import pickle
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from validate import (INCIDENT_COL, leave_one_incident_out,  # noqa: E402
                      load_table)

from sklearn.impute import SimpleImputer  # noqa: E402
from sklearn.linear_model import LogisticRegression, Ridge  # noqa: E402
from sklearn.pipeline import Pipeline  # noqa: E402
from sklearn.preprocessing import StandardScaler  # noqa: E402

HERE = os.path.dirname(__file__)
CKPT = os.path.join(HERE, "checkpoints")
TRIPWIRE = 8

SVI_THEMES = ["RPL_THEMES", "RPL_THEME1", "RPL_THEME2", "RPL_THEME3", "RPL_THEME4"]
SVI_EP = ["EP_POV150", "EP_UNEMP", "EP_HBURD", "EP_NOHSDP", "EP_UNINSUR",
          "EP_AGE65", "EP_AGE17", "EP_DISABL", "EP_SNGPNT", "EP_LIMENG",
          "EP_MINRTY", "EP_MUNIT", "EP_MOBILE", "EP_CROWD", "EP_NOVEH", "EP_GROUPQ"]
ACS = ["acs_median_hh_income", "acs_owner_share", "acs_renter_share",
       "acs_pop65_share"]
GEO = ["pop_density", "hu_density", "daypop_ratio", "AREA_SQMI"]
COUNTY = ["irs_avg_agi", "irs_avg_total_income", "irs_elderly_share",
          "irs_farm_share", "irs_avg_exemptions", "rucc_2023"]

FEATURE_SETS = {
    "svi_themes": SVI_THEMES,
    "core": SVI_THEMES + SVI_EP + ACS + GEO,
    "full": SVI_THEMES + SVI_EP + ACS + GEO + COUNTY,
}


def _prep(X_tr, X_te):
    """Impute + scale, fitted on the training fold only."""
    pipe = Pipeline([("imp", SimpleImputer(strategy="median")),
                     ("sc", StandardScaler())])
    return pipe.fit_transform(X_tr), pipe.transform(X_te), pipe


def make_ridge(alpha):
    def fit_predict(X_tr, y_tr, X_te):
        A, B, _ = _prep(X_tr, X_te)
        m = Ridge(alpha=alpha)
        m.fit(A, np.log1p(np.clip(y_tr, 0, None)))
        return np.expm1(m.predict(B))
    return fit_predict


def make_logit(C):
    def fit_predict(X_tr, y_tr, X_te):
        A, B, _ = _prep(X_tr, X_te)
        cls = (np.asarray(y_tr) > 0).astype(int)
        if len(np.unique(cls)) < 2:
            return np.zeros(len(X_te))
        m = LogisticRegression(C=C, max_iter=2000)  # l2 is the default
        m.fit(A, cls)
        return m.predict_proba(B)[:, 1]
    return fit_predict


def make_knn(k=3):
    """Cosine-similarity retrieval fallback (PRD 6.4 option 2)."""
    def fit_predict(X_tr, y_tr, X_te):
        A, B, _ = _prep(X_tr, X_te)
        An = A / (np.linalg.norm(A, axis=1, keepdims=True) + 1e-9)
        Bn = B / (np.linalg.norm(B, axis=1, keepdims=True) + 1e-9)
        y = np.asarray(y_tr, float)
        out = np.empty(len(Bn))
        step = 512  # chunk the similarity matrix to bound memory
        for i in range(0, len(Bn), step):
            sim = Bn[i:i + step] @ An.T
            idx = np.argpartition(-sim, kth=min(k, sim.shape[1] - 1), axis=1)[:, :k]
            out[i:i + step] = y[idx].mean(axis=1)
        return out
    return fit_predict


def make_mlp(hidden, dropout, wd, max_epochs=3000, patience=200):
    """Small FFN with early stopping on an inner split of the TRAINING fold.

    An earlier version used a fixed 60-epoch budget, which stopped while the
    training loss was still falling steeply and made the family look like it
    overfit when it had simply not converged. Epochs are now chosen by inner
    validation drawn entirely from the training fold, so the budget never sees
    the held-out incident.
    """
    import torch
    import torch.nn as nn

    def fit_predict(X_tr, y_tr, X_te):
        A, B, _ = _prep(X_tr, X_te)
        torch.manual_seed(0)
        y = np.log1p(np.clip(np.asarray(y_tr, float), 0, None))

        rng = np.random.RandomState(0)
        idx = rng.permutation(len(A))
        cut = max(1, int(0.15 * len(A)))
        va, tr_i = idx[:cut], idx[cut:]
        Xt = torch.tensor(A[tr_i], dtype=torch.float32)
        yt = torch.tensor(y[tr_i], dtype=torch.float32).unsqueeze(1)
        Xv = torch.tensor(A[va], dtype=torch.float32)
        yv = torch.tensor(y[va], dtype=torch.float32).unsqueeze(1)

        net = nn.Sequential(
            nn.Linear(A.shape[1], hidden), nn.ReLU(), nn.Dropout(dropout),
            nn.Linear(hidden, hidden // 2), nn.ReLU(), nn.Dropout(dropout),
            nn.Linear(hidden // 2, 1))
        opt = torch.optim.Adam(net.parameters(), lr=1e-3, weight_decay=wd)
        lossf = nn.MSELoss()

        best_v, best_state, bad = float("inf"), None, 0
        for _ in range(max_epochs):
            net.train()
            opt.zero_grad()
            lossf(net(Xt), yt).backward()
            opt.step()
            net.eval()
            with torch.no_grad():
                v = lossf(net(Xv), yv).item()
            if v < best_v - 1e-5:
                best_v, bad = v, 0
                best_state = {k: t.clone() for k, t in net.state_dict().items()}
            else:
                bad += 1
                if bad >= patience:
                    break
        if best_state is not None:
            net.load_state_dict(best_state)
        net.eval()
        with torch.no_grad():
            p = net(torch.tensor(B, dtype=torch.float32)).squeeze(1).numpy()
        return np.expm1(p)
    return fit_predict


def build_grid():
    """A dozen explicit configurations -- not a large random search."""
    g = []
    for a in (1.0, 10.0, 100.0, 1000.0):
        g.append((f"ridge_a{a:g}_core", make_ridge(a),
                  {"family": "ridge", "alpha": a, "target": "log1p(rate)"}, "core"))
    for fs in ("svi_themes", "full"):
        g.append((f"ridge_a100_{fs}", make_ridge(100.0),
                  {"family": "ridge", "alpha": 100.0, "target": "log1p(rate)"}, fs))
    for C in (0.01, 0.1, 1.0):
        g.append((f"logit_C{C:g}_core", make_logit(C),
                  {"family": "logistic", "C": C, "target": "P(any claim)"}, "core"))
    for C in (0.01, 0.1):
        g.append((f"logit_C{C:g}_full", make_logit(C),
                  {"family": "logistic", "C": C, "target": "P(any claim)"}, "full"))
    g.append(("logit_C0.1_svi_themes", make_logit(0.1),
              {"family": "logistic", "C": 0.1, "target": "P(any claim)"},
              "svi_themes"))
    return g


def save_ckpt(run_id, obj):
    os.makedirs(CKPT, exist_ok=True)
    with open(os.path.join(CKPT, f"{run_id}.pkl"), "wb") as fh:
        pickle.dump(obj, fh)


def main():
    df = load_table()
    results = []
    best, best_id, stale = -np.inf, None, 0

    print(f"training table: {df.shape[0]:,} rows, "
          f"{df[INCIDENT_COL].nunique()} incidents\n")

    for run_id, fp, cfg, fs in build_grid():
        feats = FEATURE_SETS[fs]
        cfg = dict(cfg, feature_set=fs)
        rec = leave_one_incident_out(df, feats, fp, run_id, cfg)
        results.append(rec)
        score = rec["mean_score"]
        improved = np.isfinite(score) and score > best
        if improved:
            best, best_id, stale = score, run_id, 0
            save_ckpt(run_id, {"config": cfg, "features": feats})
        else:
            stale += 1
        print(f"  {run_id:26s} spearman={score: .4f} rmse={rec['mean_rmse']:8.3f}"
              f"  {'** best' if improved else f'(stale {stale})'}")
        if stale >= TRIPWIRE:
            print(f"\nTRIPWIRE: {TRIPWIRE} consecutive configs without "
                  f"improvement -- stopping grid search.")
            break

    tripwire_fired = stale >= TRIPWIRE
    # Family 2 (small FFN) is attempted only if the shallow family underfits.
    underfit = best < 0.30
    # The FFN is mandated only when the shallow family underfits badly. It is
    # also run when FORCE_MLP is set, as a confirmatory check that the extra
    # capacity genuinely buys nothing -- evidence rather than assumption.
    forced = bool(os.environ.get("FORCE_MLP"))
    if (underfit or forced) and not tripwire_fired:
        why = ("scored below 0.30 -- escalating" if underfit
               else "cleared 0.30; running FFN as a confirmatory check only")
        print(f"\nShallow family {why} (PRD 6.4 step 2).")
        for hidden, dropout, wd in ((32, 0.3, 1e-3), (16, 0.5, 1e-2), (32, 0.5, 1e-2)):
            run_id = f"mlp_h{hidden}_d{dropout}_wd{wd:g}"
            cfg = {"family": "mlp", "hidden": hidden, "dropout": dropout,
                   "weight_decay": wd, "feature_set": "core",
                   "target": "log1p(rate)"}
            rec = leave_one_incident_out(df, FEATURE_SETS["core"],
                                         make_mlp(hidden, dropout, wd),
                                         run_id, cfg)
            results.append(rec)
            score = rec["mean_score"]
            if np.isfinite(score) and score > best:
                best, best_id, stale = score, run_id, 0
                save_ckpt(run_id, {"config": cfg, "features": FEATURE_SETS["core"]})
                print(f"  {run_id:26s} spearman={score: .4f}  ** best")
            else:
                stale += 1
                print(f"  {run_id:26s} spearman={score: .4f}  (stale {stale})")
    else:
        print(f"\nShallow family reached spearman={best:.4f} "
              f"(>= 0.30 threshold) -- no escalation to the FFN needed.")

    # Nearest-neighbour retrieval, always scored so the comparison exists.
    print("\nScoring nearest-neighbour retrieval fallback (k=3, cosine):")
    for fs in ("core", "full"):
        rid = "fallback_nn" if fs == "core" else "fallback_nn_full"
        rec = leave_one_incident_out(
            df, FEATURE_SETS[fs], make_knn(3), rid,
            {"family": "knn_cosine", "k": 3, "feature_set": fs},
            notes="PRD 6.4 option 2 -- zero-training retrieval fallback")
        results.append(rec)
        print(f"  {rid:26s} spearman={rec['mean_score']: .4f} "
              f"rmse={rec['mean_rmse']:8.3f}")
        if np.isfinite(rec["mean_score"]) and rec["mean_score"] > best:
            best, best_id = rec["mean_score"], rid
            save_ckpt(rid, {"config": rec["model_config"],
                            "features": FEATURE_SETS[fs]})

    summary = {"best_run_id": best_id, "best_mean_spearman": best,
               "tripwire_fired": bool(tripwire_fired),
               "n_configs_scored": len(results)}
    with open(os.path.join(HERE, "best.json"), "w") as fh:
        json.dump(summary, fh, indent=2)
    print(f"\nWINNER: {best_id}  mean spearman={best:.4f}")
    return summary


if __name__ == "__main__":
    main()
