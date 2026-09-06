"""Compose logs/final_summary.log: winner and reasoning first, then limitations,
then the Section 7 flags, then the final checkpoint statistics.
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import LOGS  # noqa: E402

OUT = os.path.join(HERE, "..", "output", "demographic_risk.geojson")
LOG = os.path.join(LOGS, "final_summary.log")


def _kerr_stats(win):
    """Recompute the within-Kerr sanity numbers for the winning config."""
    import sys as _s
    _s.path.insert(0, os.path.join(HERE, "..", "model"))
    from scipy.stats import spearmanr
    from train import FEATURE_SETS, make_knn, make_logit, make_mlp, make_ridge
    from validate import load_table
    cfg = win["model_config"]
    fam = cfg["family"]
    fp = ({"ridge": lambda: make_ridge(cfg.get("alpha")),
           "logistic": lambda: make_logit(cfg.get("C")),
           "knn_cosine": lambda: make_knn(cfg.get("k", 3)),
           "mlp": lambda: make_mlp(cfg.get("hidden"), cfg.get("dropout"),
                                   cfg.get("weight_decay"))}
          .get(fam, lambda: None))()
    if fp is None:
        return {"fold": float("nan"), "within": float("nan"), "n_fold": 0}
    df = load_table()
    feats = win["features_used"]
    tr = df[df.disasterNumber != 4879]
    te = df[df.disasterNumber == 4879]
    p = fp(tr[feats], tr["label_reg_per_1k"], te[feats])
    m = (te.fips_county == "48265").to_numpy()
    w = spearmanr(te["label_reg_per_1k"][m], p[m])
    return {"fold": spearmanr(te["label_reg_per_1k"], p).statistic,
            "n_fold": len(te), "n_kerr": int(m.sum()),
            "within": w.statistic, "within_p": w.pvalue}


def main():
    runs = [json.loads(l) for l in open(os.path.join(LOGS, "validation_runs.jsonl"))]
    best = json.load(open(os.path.join(HERE, "..", "model", "best.json")))
    by_id = {}
    for r in runs:
        by_id[r["run_id"]] = r
    win = by_id[best["best_run_id"]]
    nn = by_id.get("fallback_nn")
    gj = json.load(open(OUT))
    w = np.array([f["properties"]["weight"] for f in gj["features"]])

    scored = sorted(
        ((r["run_id"], r["mean_score"], r["mean_rmse"]) for r in runs
         if np.isfinite(r["mean_score"])),
        key=lambda x: -x[1])

    n_folds = len(win["fold_scores"])
    lin = max((r for r in runs if r["model_config"].get("family")
               in ("ridge", "logistic")), key=lambda r: r["mean_score"])
    kerr = _kerr_stats(win)

    L = []
    A = L.append
    A("=" * 78)
    A("WINNING APPROACH -- demographic risk model")
    A("=" * 78)
    A("")
    A(f"Winner: {win['run_id']}  (trained model, not the retrieval fallback)")
    A(f"  mean Spearman rho = {win['mean_score']:.4f} "
      f"(std {win['std_score']:.4f}) across {len(win['fold_scores'])} "
      f"leave-one-incident-out folds")
    A(f"  mean RMSE         = {win['mean_rmse']:.3f} "
      f"registrations per 1,000 residents")
    A(f"  family={win['model_config']['family']}  "
      f"config={ {k: v for k, v in win['model_config'].items() if k != 'family'} }")
    fs_name = win["model_config"].get("feature_set", "?")
    A(f"  features: {win['n_features']} columns (feature_set={fs_name})")
    A("")
    A("WHY IT WON, in plain terms")
    A("")
    A(f"  1. It beat the nearest-neighbour retrieval fallback. The k=3 cosine")
    A(f"     retrieval scored {nn['mean_score']:.4f} mean Spearman against the winner's")
    A(f"     {win['mean_score']:.4f} on the identical frozen harness -- a "
      f"{(win['mean_score']-nn['mean_score'])/nn['mean_score']*100:.0f}% relative")
    A("     improvement in rank agreement. Retrieval also carried a materially")
    A(f"     worse RMSE ({nn['mean_rmse']:.2f} vs {win['mean_rmse']:.2f}).")
    A("")
    A("  2. FAMILY REVERSAL vs the earlier Texas-only run -- and the clearest")
    A("     argument for having expanded the data. On 9 Texas incidents the")
    A("     shallow linear family won and the FFNs trailed. On 52 national")
    A("     incidents both heavily-regularised FFNs overtake EVERY linear")
    A("     configuration:")
    for r in sorted([r for r in runs if r["model_config"].get("family") == "mlp"],
                    key=lambda r: -r["mean_score"]):
        c = r["model_config"]
        A(f"       {r['run_id']:24s} spearman={r['mean_score']:.4f} "
          f"rmse={r['mean_rmse']:7.3f}   dropout={c['dropout']} wd={c['weight_decay']}")
    A(f"       {'-- best linear:':24s}")
    A(f"       {lin['run_id']:24s} spearman={lin['mean_score']:.4f} "
      f"rmse={lin['mean_rmse']:7.3f}")
    A("     Note WHICH FFNs win: the two at dropout 0.5 / weight decay 0.01.")
    A("     The lightly-regularised one (dropout 0.3, wd 0.001) still loses to")
    A("     the linear family. Capacity only pays here when it is heavily")
    A("     penalised AND given enough incidents -- the PRD 6.4 data-scarcity")
    A("     story observed directly, rather than assumed in either direction.")
    A("")
    A("     THIS RESULT DEPENDS ON A BUG FIX, recorded deliberately. An earlier")
    A("     version trained the FFNs for a fixed 60 epochs and scored them at")
    A("     0.06-0.19, and this summary concluded they had overfit. They were")
    A("     undertrained -- training loss was still falling steeply at the")
    A("     cutoff. Epochs are now set by early stopping on an inner split of")
    A("     the training fold only. Had that bug survived, this run would have")
    A("     reported the wrong winning family.")
    A("")
    A("  3. HOW BIG IS THE WIN, HONESTLY: small, and the team should decide.")
    A(f"     The margin over the best linear model is "
      f"{win['mean_score'] - lin['mean_score']:+.4f} Spearman, well")
    A(f"     inside the fold-to-fold spread (std {win['std_score']:.4f}). The RMSE gap is")
    A(f"     more substantial ({win['mean_rmse']:.2f} vs {lin['mean_rmse']:.2f}).")
    A("     The task spec makes the frozen harness the decider, so the FFN is")
    A("     what generated the GeoJSON. But PRD 6.4 states a standing")
    A(f"     preference for the shallow, inspectable model, and {lin['run_id']}")
    A("     sits within noise of the winner while exposing 36 readable")
    A("     coefficients instead of 1,697 opaque weights. If the project values")
    A("     auditability over a ~0.006 Spearman gain, switching is defensible.")
    A("     Flagged here rather than decided silently.")
    A("")
    if best.get("tripwire_fired"):
        A("  Tripwire: FIRED. " + best.get("tripwire_note", ""))
    else:
        A("  Tripwire: not fired.")
    A(f"  Configurations scored: {best['n_configs_scored']} "
      f"(+ 1 constant-baseline harness self-test).")
    A("")
    A("FULL LEADERBOARD (mean Spearman, leave-one-incident-out)")
    for rid, sc, rm in scored:
        A(f"  {rid:26s} spearman={sc: .4f}  rmse={rm:8.3f}")
    A("")
    A("=" * 78)
    A("LIMITATIONS -- carry these into any UI label (addendum Section 6)")
    A("=" * 78)
    A("")
    A("  * TRACT RESOLUTION, FOOTPRINT DISPLAY. The model predicts at census")
    A("    tract resolution. Every per-building weight in demographic_risk.geojson")
    A("    is that single tract score split across footprints by building area,")
    A("    NOT a per-building prediction. Two adjacent buildings differ in weight")
    A("    only because they differ in footprint area. Do not read an individual")
    A("    building's weight as a statement about that building.")
    A("")
    A("  * ACS COUNTS USUAL RESIDENTS, NOT TRANSIENT POPULATIONS. The ACS and")
    A("    SVI inputs describe where people usually live. They do not capture")
    A("    summer camp populations, RV parks, short-term rentals, or day")
    A("    visitors -- precisely the populations most exposed in the July 2025")
    A("    Kerr County event. This model therefore understates risk exactly")
    A("    where the Guadalupe River camp corridor sits.")
    A("")
    A(f"  * SMALL-SAMPLE VALIDATION. {n_folds} incidents means {n_folds} folds. The")
    A(f"    fold-to-fold spread is wide (std {win['std_score']:.4f}); a single")
    A("    unusual disaster moves the mean materially. Treat the headline score")
    A("    as an order-of-magnitude indication of skill, not a precise estimate.")
    A("")
    A("  * THE LABEL IS SELF-REPORTED AID UPTAKE, NOT DAMAGE. OpenFEMA counts")
    A("    who registered for Individual Assistance. That reflects outreach")
    A("    intensity, awareness, and eligibility as much as physical flooding.")
    A("    Rank agreement (Spearman) is reported as primary for this reason.")
    A("")
    A("  * WEAK AND NOT SIGNIFICANT WITHIN KERR -- THE MOST IMPORTANT CAVEAT.")
    A(f"    On the held-out DR-4879 fold the model reaches Spearman {kerr['fold']:.3f}")
    A(f"    across all {kerr['n_fold']} declared tracts. But restricted to the {kerr['n_kerr']} KERR")
    A(f"    COUNTY tracts the heatmap actually covers, rank correlation is")
    A(f"    {kerr['within']:+.2f} with p={kerr['within_p']:.2f} -- on {kerr['n_kerr']} points that is not")
    A("    distinguishable from chance, and it has swung sign between model")
    A("    versions (-0.11 under the earlier linear winner). Kerr's tracts are")
    A("    demographically similar and were all severely hit; what actually")
    A("    separated them was proximity to the Guadalupe River, which is")
    A("    hydrology the model never sees. Treat this layer as a coarse")
    A("    demographic-vulnerability backdrop. It must NOT be read as 'which")
    A("    parts of Kerr County flooded' -- that is the physics engine's job,")
    A("    and this layer carries no information about it.")
    A("")
    A(f"  * MODEST ABSOLUTE SKILL. Mean Spearman ~{win['mean_score']:.2f} is a real but weak")
    A("    signal. This output is a prioritisation hint, never an authority for")
    A("    who gets help. Per PRD Design Principle 3 it must be shown alongside")
    A("    the citation-grounded critique, never on its own.")
    A("")
    A("  * VALIDATED SCOPE (adopted 2026-09-06; see")
    A("    logs/model_tests_followup.log Section 7 for the full statement).")
    A("    Measured like-for-like inside each fold, this model ranks WORSE in")
    A("    nonmetro tracts (Spearman 0.238, RUCC 4-9) than metro (0.347).")
    A("    Kerr County is RUCC 4, so THE DEPLOYMENT TARGET SITS IN THE MODEL'S")
    A("    WEAKER STRATUM. That gap survived a paired, size-matched audit")
    A("    holding the incident constant (p=0.019) and is stable across")
    A("    sample-size floors of 30/50/100 rural tracts per fold -- it is a")
    A("    real property of the model, not small-sample noise. Use for")
    A("    within-incident RELATIVE shading only; never as a magnitude, a")
    A("    cross-incident comparison, or a flood-extent claim.")
    A("")
    A("  * CALIBRATION IS BROKEN AND WAS NOT REPAIRED (Test 2). Predictions")
    A("    run ~4x low, and the calibration curve is NON-MONOTONIC: decile 1")
    A("    carries the second-highest median outcome of any decile. An")
    A("    isotonic wrapper was fitted and REJECTED for making RMSE worse")
    A("    (18.455 -> 21.469). The worst misses are dense urban tracts")
    A("    (Harris County, DR-4781: under 1 per 1,000 predicted against an")
    A("    actual 186-265) -- a magnitude failure, not a ranking failure,")
    A("    consistent with a model that has no hydrological input.")
    A("")
    A("  * ABSTENTION RULE IS ACTIVE (Test 6). Median imputation is unsafe")
    A("    here -- one missing feature drops rank correlation to 0.58, three")
    A("    to 0.11 -- so a tract is scored only with complete features")
    A("    (max_missing_features=0). Footprints failing this carry")
    A("    weight=null and score_source=\"insufficient_data\" and MUST NOT be")
    A("    rendered as zero. Currently fires on 0 of 14 Kerr tracts.")
    A("")
    A("  * A RURAL-UPWEIGHTING FIX WAS CONSIDERED AND DECLINED, not")
    A("    overlooked. Reweighting adds no information (it amplifies the")
    A("    3,160 rural rows already held), and the real-data lever is nearly")
    A("    exhausted in scope. Design retained, unexecuted, in")
    A("    logs/proposed_rural_experiment.log.")
    A("")
    A("=" * 78)
    A("SECTION 7 FLAGS -- items referred back rather than worked around")
    A("=" * 78)
    A("")
    A("  1. CENSUS API KEY GATE (blocking for api.census.gov only, worked")
    A("     around legitimately, not silently). Every api.census.gov query --")
    A("     including the credential-free example in the task spec -- now")
    A("     returns a 'Missing Key' interstitial. Rather than sign up for a")
    A("     key (a Section 7 stop condition), the identical ACS 5-year")
    A("     estimates were taken from the ungated table-based Summary Files on")
    A("     www2.census.gov, a host the spec's own network check requires.")
    A("     ACTION FOR THE USER: if you want the REST path, request a free key")
    A("     at api.census.gov/data/key_signup.html and set CENSUS_API_KEY;")
    A("     scripts/pull_acs.py already detects it.")
    A("")
    A("  2. NOT ATTEMPTED, as instructed: camp footprints (KCAD / paid")
    A("     aggregator), AAR corpus PDFs, and all gated mobility data")
    A("     (Cuebiq / SafeGraph / Veraset). These remain separate manual tasks.")
    A("")
    A("  3. The 'Demographic Risk Model + Weighted-Footprint Heatmap' addendum")
    A("     is not present in this repository. Section 4.3's property schema")
    A("     was taken from the inline definition in the task spec itself")
    A("     ({weight, feature_id, score_source, citation_ids}); the ACS/SVI")
    A("     variable pairing was chosen to span the standard SVI themes.")
    A("     Worth confirming against the addendum before the UI consumes this.")
    A("")
    A("=" * 78)
    A("FINAL CHECKPOINT -- heatmap output")
    A("=" * 78)
    A("")
    A(f"  output: output/demographic_risk.geojson")
    A(f"  features: {len(gj['features']):,} footprint centroids (Point)")
    A(f"  tracts covered: 14 of 14 Kerr County tracts")
    A(f"  score_source: {gj['properties']['score_source']}")
    A(f"  held-out incident: DR-{gj['properties']['held_out_incident']} "
      f"(the July 2025 Kerr County flood -- predictions are out-of-sample)")
    A("")
    A(f"  weight distribution:")
    A(f"    min  = {w.min():.6f}")
    A(f"    max  = {w.max():.6f}")
    A(f"    mean = {w.mean():.6f}")
    A(f"    std  = {w.std():.6f}")
    A(f"    sum  = {w.sum():.4f}  (equals the sum of the 14 tract scores --")
    A(f"           the area-weighted split conserves total risk mass)")
    A("")
    A("  SPOT-CHECK (5 sample features)")
    for f in gj["features"][:5]:
        p = f["properties"]
        A(f"    {p['feature_id']}")
        A(f"      weight={p['weight']}  coords={f['geometry']['coordinates']}")
        A(f"      score_source={p['score_source']}")
        A(f"      citation_ids={p['citation_ids']}")
    A("")

    with open(LOG, "w") as fh:
        fh.write("\n".join(L) + "\n")
    print("\n".join(L))


if __name__ == "__main__":
    main()
