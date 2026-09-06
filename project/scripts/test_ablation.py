"""Test 3 -- leave-one-feature-out ablation of the winning configuration.

Each run drops exactly one feature and is re-scored by the FROZEN harness.
Results go to logs/ablation_runs.jsonl, kept separate from
logs/validation_runs.jsonl so the training-loop leaderboard stays exactly what
the task spec asked for: every attempted training CONFIG, nothing else.

Parallel across features, one torch thread per worker: these tiny models spend
more time in thread coordination than in arithmetic, so 10 single-threaded
workers beat one multi-threaded process by roughly an order of magnitude. The
full-feature BASELINE is recomputed under the identical worker setup, so the
deltas are apples-to-apples rather than compared against a run made with
different threading.
"""
import json
import multiprocessing as mp
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "model"))
sys.path.insert(0, HERE)
from common import LOGS  # noqa: E402

OUT = os.path.join(LOGS, "ablation_runs.jsonl")
WORKERS = 10


def _job(args):
    drop, cfg, feats, run_id = args
    import torch
    torch.set_num_threads(1)
    from train import make_knn, make_logit, make_mlp, make_ridge
    from validate import leave_one_incident_out, load_table

    fam = cfg["family"]
    fp = ({"mlp": lambda: make_mlp(cfg["hidden"], cfg["dropout"],
                                   cfg["weight_decay"]),
           "ridge": lambda: make_ridge(cfg.get("alpha")),
           "logistic": lambda: make_logit(cfg.get("C"))}
          .get(fam, lambda: make_knn(cfg.get("k", 3))))()

    kept = [f for f in feats if f != drop] if drop else list(feats)
    tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    tmp.close()
    rec = leave_one_incident_out(
        load_table(), kept, fp, run_id,
        dict(cfg, ablated_feature=drop), log_path=tmp.name,
        notes=("Test 3 baseline, single-thread workers" if drop is None
               else f"Test 3 ablation: dropped {drop}"))
    os.unlink(tmp.name)
    return rec


def main():
    best = json.load(open(os.path.join(HERE, "..", "model", "best.json")))
    runs = {json.loads(l)["run_id"]: json.loads(l)
            for l in open(os.path.join(LOGS, "validation_runs.jsonl"))}
    win = runs[best["best_run_id"]]
    cfg, feats = win["model_config"], list(win["features_used"])

    jobs = [(None, cfg, feats, "ablate__BASELINE_all_features")]
    jobs += [(f, cfg, feats, f"ablate__{f}") for f in feats]
    print(f"{len(jobs)} runs ({len(feats)} ablations + 1 baseline) "
          f"on {WORKERS} workers", flush=True)

    with mp.Pool(WORKERS) as pool, open(OUT, "w") as fh:
        for i, rec in enumerate(pool.imap_unordered(_job, jobs), 1):
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            d = rec["model_config"]["ablated_feature"] or "BASELINE"
            print(f"  [{i}/{len(jobs)}] -{d:22s} "
                  f"spearman={rec['mean_score']:.4f}", flush=True)


if __name__ == "__main__":
    mp.set_start_method("spawn", force=True)
    main()
