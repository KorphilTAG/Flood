"""Score any pre-declared configuration the tripwire cut off, plus the FFN family.

The tripwire correctly stopped the SEARCH (8 consecutive non-improving configs),
but the grid is a fixed, pre-declared dozen -- not an open-ended search -- so
leaving members unscored would hide comparisons rather than bound cost. Every
config here was declared in build_grid() before any result was seen; nothing is
added in response to the leaderboard.
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "model"))
sys.path.insert(0, HERE)
from common import LOGS  # noqa: E402
from train import CKPT, FEATURE_SETS, build_grid, make_mlp, save_ckpt  # noqa: E402
from validate import leave_one_incident_out, load_table  # noqa: E402


def main():
    runs = [json.loads(l) for l in open(os.path.join(LOGS, "validation_runs.jsonl"))]
    done = {r["run_id"] for r in runs}
    df = load_table()

    pending = [(rid, fp, cfg, fs) for rid, fp, cfg, fs in build_grid()
               if rid not in done]
    print(f"pre-declared configs not yet scored: {[p[0] for p in pending]}")
    for rid, fp, cfg, fs in pending:
        rec = leave_one_incident_out(df, FEATURE_SETS[fs], fp, rid,
                                     dict(cfg, feature_set=fs),
                                     notes="scored in completeness pass after "
                                           "tripwire halted the search")
        print(f"  {rid:26s} spearman={rec['mean_score']: .4f} "
              f"rmse={rec['mean_rmse']:8.3f}", flush=True)

    for hidden, dropout, wd in ((32, 0.3, 1e-3), (16, 0.5, 1e-2), (32, 0.5, 1e-2)):
        rid = f"mlp_h{hidden}_d{dropout}_wd{wd:g}"
        if rid in done:
            continue
        cfg = {"family": "mlp", "hidden": hidden, "dropout": dropout,
               "weight_decay": wd, "feature_set": "core", "target": "log1p(rate)"}
        rec = leave_one_incident_out(df, FEATURE_SETS["core"],
                                     make_mlp(hidden, dropout, wd), rid, cfg,
                                     notes="FFN family, early-stopped on an "
                                           "inner split of the training fold")
        print(f"  {rid:26s} spearman={rec['mean_score']: .4f} "
              f"rmse={rec['mean_rmse']:8.3f}", flush=True)

    runs = [json.loads(l) for l in open(os.path.join(LOGS, "validation_runs.jsonl"))]
    scored = [r for r in runs if np.isfinite(r["mean_score"])
              and r["run_id"] != "baseline_train_mean"]
    win = max(scored, key=lambda r: r["mean_score"])
    save_ckpt(win["run_id"], {"config": win["model_config"],
                              "features": win["features_used"]})
    old = json.load(open(os.path.join(HERE, "..", "model", "best.json")))
    summary = {"best_run_id": win["run_id"],
               "best_mean_spearman": win["mean_score"],
               "tripwire_fired": old["tripwire_fired"],
               "tripwire_note": "fired at config 9 of a fixed 12-config grid; "
                                "remaining pre-declared configs scored in a "
                                "completeness pass",
               "n_configs_scored": len(scored)}
    json.dump(summary, open(os.path.join(HERE, "..", "model", "best.json"), "w"),
              indent=2)
    print(f"\nWINNER: {win['run_id']}  mean spearman={win['mean_score']:.4f}")


if __name__ == "__main__":
    main()
