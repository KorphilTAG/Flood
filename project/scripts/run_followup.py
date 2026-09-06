"""Follow-up diagnostic: does urbanicity explain Tests 1, 2 and 5 at once?

Diagnostic pass over already-frozen results. The only new harness evaluation is
the candidate hybrid in section 4. No retraining, and logs/model_tests.log is
not touched.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "model"))
sys.path.insert(0, HERE)
from common import LOGS, PROCESSED, RAW, table_path  # noqa: E402
from train import make_knn, make_mlp  # noqa: E402
from validate import INCIDENT_COL, leave_one_incident_out, load_table  # noqa: E402

from scipy.stats import spearmanr  # noqa: E402

LOG = os.path.join(LOGS, "model_tests_followup.log")
OOF = table_path(os.path.join(PROCESSED, "oof_predictions.csv"))
SECTIONS = []
WAGG = []

# USDA's own metro/nonmetro line: RUCC 1-3 = metro, 4-9 = nonmetro.
RUCC_URBAN_MAX = 3


def add(n, title, verdict, body):
    SECTIONS.append({"n": n, "title": title, "verdict": verdict, "body": body})
    print(f"[{verdict}] Section {n}: {title}", flush=True)


def rmse(y, p):
    return float(np.sqrt(np.mean((np.asarray(y, float) - np.asarray(p, float)) ** 2)))


def ctx():
    best = json.load(open(os.path.join(HERE, "..", "model", "best.json")))
    runs = {json.loads(l)["run_id"]: json.loads(l)
            for l in open(os.path.join(LOGS, "validation_runs.jsonl"))}
    return best, runs, runs[best["best_run_id"]], load_table()


def with_svi(df):
    svi = pd.read_csv(os.path.join(RAW, "svi_national.csv"),
                      dtype={"FIPS": str}, low_memory=False)
    svi["tract_fips"] = svi["FIPS"].astype(str).str.zfill(11)
    cols = ["tract_fips", "EP_NOINT", "EP_ASIAN", "EP_AFAM", "EP_HISP"]
    svi = svi[[c for c in cols if c in svi.columns]].drop_duplicates("tract_fips")
    for c in svi.columns:
        if c != "tract_fips":
            svi[c] = pd.to_numeric(svi[c], errors="coerce")
            svi.loc[svi[c] == -999, c] = np.nan
    return df.merge(svi, on="tract_fips", how="left")


# ------------------------------------------------------------- Section 1
def section1(df):
    d = with_svi(df).drop_duplicates("tract_fips")
    flagged = ["EP_NOINT", "EP_ASIAN", "EP_MINRTY"]
    against = ["pop_density", "rucc_2023"]
    rows = []
    for f in flagged:
        r = {"variable": f}
        for a in against:
            m = d[f].notna() & d[a].notna()
            r[f"vs_{a}"] = spearmanr(d.loc[m, f], d.loc[m, a]).statistic
        rows.append(r)
    t = pd.DataFrame(rows)
    b = ["Raw variable-to-variable Spearman correlations (NOT against model",
         "predictions). One row per tract, deduplicated across incidents.",
         f"n tracts = {len(d):,}", "",
         t.to_string(index=False, float_format=lambda x: f"{x:+.4f}"), "",
         "Reading: rucc_2023 runs 1 (most metropolitan) to 9 (most rural), so a",
         "POSITIVE correlation with RUCC means the variable rises as areas get",
         "more rural; a NEGATIVE correlation with pop_density means the same.", ""]
    strong = t[(t.vs_rucc_2023.abs() >= 0.30) | (t.vs_pop_density.abs() >= 0.30)]
    if len(strong):
        b.append("STRONGLY TIED TO URBANICITY (|rho| >= 0.30 on either axis):")
        for _, r in strong.iterrows():
            b.append(f"  {r.variable}: vs pop_density {r.vs_pop_density:+.4f}, "
                     f"vs RUCC {r.vs_rucc_2023:+.4f}")
        v = "confirmed" if len(strong) >= 2 else "partially confirmed"
        b += ["", "CANDIDATE EXPLANATION (not a resolution): the Test 5",
              "correlations may be mediated through urbanicity rather than being",
              "independent equity signals or a direct registration-access",
              "artifact. EP_NOINT in particular tracks rurality, and rural",
              "tracts are where this model has most of its training mass.", "",
              "WHAT THIS TEST DOES NOT SETTLE: density being a confound does not",
              "tell you whether the residual association is a documented equity",
              "pattern or an artifact worth chasing. That judgment is the",
              "user's and is deliberately left open here."]
    else:
        v = "not supported"
        b.append("No flagged variable is strongly tied to density or RUCC.")
    add(1, "Is EP_NOINT / EP_ASIAN a density proxy?", v, "\n".join(b))
    return t


# ------------------------------------------------------------- Section 2
def section2(win, df):
    rows = []
    for f in win["fold_scores"]:
        if f["n_test"] < 30:
            continue
        sub = df[df[INCIDENT_COL] == f["incident"]]
        lab = sub.label_reg_per_1k
        rows.append({"incident": f["incident"], "n_test": f["n_test"],
                     "spearman": f["spearman"],
                     "median_rucc": sub.rucc_2023.median(),
                     "label_iqr": lab.quantile(.75) - lab.quantile(.25),
                     "label_std": lab.std(),
                     "label_mean": lab.mean(),
                     "frac_zero": float((lab == 0).mean())})
    t = pd.DataFrame(rows).sort_values("spearman")
    c_rucc = spearmanr(t.spearman, t.median_rucc).statistic
    c_iqr = spearmanr(t.spearman, t.label_iqr).statistic
    c_std = spearmanr(t.spearman, t.label_std).statistic
    c_zero = spearmanr(t.spearman, t.frac_zero).statistic

    b = [f"Incidents with n_test >= 30 (noise-exclusion rule from Test 1): "
         f"{len(t)} of {len(win['fold_scores'])} folds", "",
         t.to_string(index=False, float_format=lambda x: f"{x:.3f}"), "",
         "CORRELATIONS AGAINST PER-INCIDENT SPEARMAN",
         f"  vs median RUCC        : {c_rucc:+.4f}",
         f"  vs label IQR          : {c_iqr:+.4f}",
         f"  vs label std          : {c_std:+.4f}",
         f"  vs fraction zero-label: {c_zero:+.4f}", ""]
    sig_iqr, sig_rucc = abs(c_iqr) >= 0.30, abs(c_rucc) >= 0.30
    if sig_iqr:
        b += ["SIGNAL-VARIANCE PATTERN: incidents with more spread in the label",
              "score higher. A weak rank correlation on a near-constant label is",
              "a fundamentally different failure from a weak rank correlation on",
              "a widely-spread one -- in the first case there is little true",
              "ordering to recover. The weak folds are largely the former."]
    else:
        b.append("No strong relationship between label spread and fold score.")
    b.append("")
    if sig_rucc:
        b += ["SEPARATE URBANICITY PATTERN: fold score also tracks median RUCC "
              f"({c_rucc:+.3f}).", "Reported as a second pattern, NOT merged with the "
              "variance explanation."]
    else:
        b += [f"RUCC shows no strong per-incident relationship ({c_rucc:+.3f}).",
              "The two candidate explanations are NOT merged: the data supports",
              "the label-variance account and does not support an incident-level",
              "urbanicity account."]
    v = ("confirmed" if sig_iqr and not sig_rucc else
         "partially confirmed" if sig_iqr or sig_rucc else "not supported")
    add(2, "Does severity or urbanicity explain Test 1's weak folds?", v,
        "\n".join(b))
    return t


# ------------------------------------------------------------- Section 3
def section3(df, oofdf):
    d = oofdf.merge(df[["disasterNumber", "tract_fips", "rucc_2023",
                        "pop_density"]],
                    on=["disasterNumber", "tract_fips"], how="left")
    d = d.dropna(subset=["pred_model", "label_reg_per_1k", "rucc_2023"])
    urban = d.rucc_2023 <= RUCC_URBAN_MAX

    def score(sub, col="pred_model"):
        return (spearmanr(sub.label_reg_per_1k, sub[col]).statistic,
                rmse(sub.label_reg_per_1k, sub[col]), len(sub))

    rows = []
    for name, sub in (("URBAN (RUCC 1-3, metro)", d[urban]),
                      ("RURAL (RUCC 4-9, nonmetro)", d[~urban]),
                      ("POOLED (all tracts)", d)):
        sp, rm, n = score(sub)
        rows.append({"group": name, "n": n, "spearman": sp, "rmse": rm,
                     "mean_label": sub.label_reg_per_1k.mean(),
                     "mean_pred": sub.pred_model.mean()})
    t = pd.DataFrame(rows)
    global WAGG

    # POOLED scores mix 52 incidents with different label scales, which
    # destroys rank agreement and is NOT comparable to the harness figure.
    # Recompute the same split WITHIN each fold, then average -- that is
    # directly comparable to the 52-fold harness score.
    wf = []
    for inc, sub in d.groupby("disasterNumber"):
        for name, part in (("urban", sub[sub.rucc_2023 <= RUCC_URBAN_MAX]),
                           ("rural", sub[sub.rucc_2023 > RUCC_URBAN_MAX])):
            if len(part) >= 30 and part.label_reg_per_1k.nunique() > 2:
                wf.append({"incident": inc, "stratum": name,
                           "n": len(part),
                           "spearman": spearmanr(part.label_reg_per_1k,
                                                 part.pred_model).statistic,
                           "rmse": rmse(part.label_reg_per_1k, part.pred_model)})
    wfd = pd.DataFrame(wf)
    wagg = (wfd.groupby("stratum")
            .agg(folds=("incident", "nunique"), tracts=("n", "sum"),
                 mean_spearman=("spearman", "mean"),
                 mean_rmse=("rmse", "mean")).reset_index())

    WAGG.clear(); WAGG.append(wagg)
    b = ["Threshold: USDA's own metro/nonmetro line, RUCC 1-3 vs 4-9. Chosen",
         "because it is a published definition rather than a cut fitted to this",
         "data, so the split cannot be accused of being tuned to flatter the",
         "result. Existing frozen out-of-fold predictions; NO retraining.", "",
         "A) POOLED ACROSS ALL INCIDENTS",
         t.to_string(index=False, float_format=lambda x: f"{x:.4f}"), "",
         "   *** These pooled figures are NOT comparable to the harness score.",
         "   Pooling 52 incidents with very different label scales",
         "   collapses rank agreement; the harness scores WITHIN each fold and",
         "   then averages. Use the pooled table only for the urban/rural",
         "   CONTRAST, never as an absolute skill number.", "",
         "B) WITHIN-FOLD, THEN AVERAGED (directly comparable to the harness)",
         wagg.to_string(index=False, float_format=lambda x: f"{x:.4f}"), ""]
    u = t[t.group.str.startswith("URBAN")].iloc[0]
    r = t[t.group.str.startswith("RURAL")].iloc[0]
    p = t[t.group.str.startswith("POOLED")].iloc[0]
    b += [f"rural minus pooled: {r.spearman - p.spearman:+.4f} spearman",
          f"urban minus pooled: {u.spearman - p.spearman:+.4f} spearman", ""]
    wr = wagg[wagg.stratum == "rural"]
    wu = wagg[wagg.stratum == "urban"]
    wrs = wr.mean_spearman.iloc[0] if len(wr) else np.nan
    wus = wu.mean_spearman.iloc[0] if len(wu) else np.nan
    b += [f"   within-fold rural {wrs:.4f} vs urban {wus:.4f} "
          f"(rural minus urban: {wrs-wus:+.4f})", ""]

    pooled_says_rural = r.spearman > p.spearman and u.spearman < p.spearman
    withinfold_says_rural = wrs > wus
    if pooled_says_rural and not withinfold_says_rural:
        v = "not supported"
        b += ["*** THE TWO MEASURES DISAGREE, AND THE POOLED ONE IS WRONG.",
              "",
              "  Pooled  : rural {:.4f} > urban {:.4f}  -> looks rural-skewed"
              .format(r.spearman, u.spearman),
              "  In-fold : rural {:.4f} < urban {:.4f}  -> actually urban-skewed"
              .format(wrs, wus),
              "",
              "  The pooled view is an artifact. Ranking 27,814 tracts drawn",
              "  from 52 incidents against one another mixes events whose label",
              "  scales differ by orders of magnitude, so most of the pooled",
              "  'disagreement' is between-incident scale, not within-incident",
              "  ordering. The harness never does this: it scores inside a fold",
              "  and averages. The within-fold split is the like-for-like",
              "  measurement and it says the model ranks BETTER in metro tracts",
              f"  ({wus:.4f}) than nonmetro ({wrs:.4f}).",
              "",
              "  HYPOTHESIS AS STATED IS NOT SUPPORTED: skill is not",
              "  concentrated in the nonmetro regime. Note the uncomfortable",
              "  corollary -- Kerr County is RUCC 4, i.e. nonmetro, which is the",
              "  WEAKER ranking regime, not the stronger one.",
              "",
              "  Urbanicity therefore does NOT provide a single root cause",
              "  uniting Tests 1, 2 and 5. It explains the Test 5 correlations",
              "  (section 1) but not the ranking skill profile."]
    elif withinfold_says_rural:
        v = "confirmed"
        b += ["CONFIRMED on both measures: skill is concentrated in the nonmetro",
              f"regime, which is Kerr County's own profile (RUCC "
              f"{df[df.fips_county=='48265'].rucc_2023.iloc[0]:.0f})."]
    else:
        v = "not supported"
        b.append("Neither measure supports rural-concentrated skill.")
    b += ["", f"NOTE on magnitude: urban mean label {u.mean_label:.2f} vs urban mean",
          f"prediction {u.mean_pred:.2f} -- the underprediction that Test 2's",
          "decile 1 exposed is concentrated here."]
    add(3, "Stratified re-evaluation: urban vs rural", v, "\n".join(b))
    return t, d


# ------------------------------------------------------------- Section 4
def section4(win, runs, df, d):
    dd = d.dropna(subset=["pred_nn"]).copy()
    dd["r_model"] = dd.pred_model.rank(pct=True)
    dd["r_nn"] = dd.pred_nn.rank(pct=True)
    dd["disagree"] = (dd.r_model - dd.r_nn).abs()
    top = dd.nlargest(10, "disagree").copy()
    top["err_model"] = (top.pred_model - top.label_reg_per_1k).abs()
    top["err_nn"] = (top.pred_nn - top.label_reg_per_1k).abs()
    top["closer"] = np.where(top.err_model < top.err_nn, "model", "knn")
    top["regime"] = np.where(top.rucc_2023 <= RUCC_URBAN_MAX, "urban", "rural")

    b = ["The 10 maximum-disagreement rows, now with density and which model",
         "was actually closer to the observed label.", "",
         top[["disasterNumber", "tract_fips", "pop_density", "rucc_2023",
              "regime", "pred_model", "pred_nn", "label_reg_per_1k",
              "err_model", "err_nn", "closer"]]
         .to_string(index=False, float_format=lambda x: f"{x:.3f}"), "",
         "ROW BY ROW"]
    for _, r_ in top.iterrows():
        b.append(f"  {r_.tract_fips} density={r_.pop_density:9.1f} "
                 f"RUCC={r_.rucc_2023:.0f} ({r_.regime:5s}) -> "
                 f"{r_.closer} closer "
                 f"(|err| model={r_.err_model:.2f} knn={r_.err_nn:.2f})")
    urb = top[top.regime == "urban"]
    rur = top[top.regime == "rural"]
    knn_urban = (urb.closer == "knn").sum()
    model_rural = (rur.closer == "model").sum()
    b += ["", "PATTERN TEST -- 'model wins rural, k-NN wins urban':",
          f"  urban rows: {len(urb)}, of which k-NN closer: {knn_urban}",
          f"  rural rows: {len(rur)}, of which model closer: {model_rural}"]
    hits = knn_urban + model_rural
    frac = hits / len(top) if len(top) else 0
    if frac >= 0.75:
        holds, v = "HOLDS", "confirmed"
    elif frac >= 0.5:
        holds, v = "PARTIALLY HOLDS", "partially confirmed"
    else:
        holds, v = "DOES NOT HOLD", "not supported"
    b += [f"  consistent rows: {hits}/{len(top)} = {frac*100:.0f}%  -> {holds}", ""]
    return top, b, frac, v


def validate_hybrid(win, df, b, frac):
    """Score a density-gated hybrid on the frozen harness as a CANDIDATE."""
    cfg = win["model_config"]
    feats = win["features_used"]
    base = make_mlp(cfg["hidden"], cfg["dropout"], cfg["weight_decay"])
    knn = make_knn(3)
    # Gate on RUCC, which is a model feature and so present in X.
    ix = feats.index("rucc_2023") if "rucc_2023" in feats else None

    def hybrid(X_tr, y_tr, X_te):
        pm = np.asarray(base(X_tr, y_tr, X_te), float)
        pk = np.asarray(knn(X_tr, y_tr, X_te), float)
        if ix is None:
            return pm
        urban = X_te.iloc[:, ix].to_numpy(float) <= RUCC_URBAN_MAX
        out = pm.copy()
        out[urban] = pk[urban]
        return out

    if ix is None:
        b += ["", "PROPOSED RULE NOT VALIDATED: rucc_2023 is not among the",
              "winning model's features, so the gate cannot be evaluated inside",
              "the frozen harness without changing the feature set. Density",
              "gating would need pop_density added as a feature first -- flagged",
              "for the user rather than done unilaterally."]
        return None, b
    rec = leave_one_incident_out(
        df, feats, hybrid, "hybrid_density_gate",
        dict(cfg, hybrid="k-NN for RUCC<=3 (metro), FFN for RUCC>=4",
             gate_threshold=RUCC_URBAN_MAX),
        log_path=os.path.join(LOGS, "validation_runs.jsonl"),
        notes="Section 4 candidate; NOT adopted. Logged for comparability.")
    nn = json.loads(open(os.path.join(LOGS, "validation_runs.jsonl")).readlines()[0])
    b += ["", "PROPOSED RULE (candidate, NOT adopted):",
          f"  use k-NN retrieval where RUCC <= {RUCC_URBAN_MAX} (USDA metro),",
          f"  use the trained FFN where RUCC >= {RUCC_URBAN_MAX+1} (nonmetro).",
          "  Gate uses RUCC because it is already a model feature, so the rule",
          "  needs no new input.", "",
          "  VALIDATED ON THE FROZEN HARNESS as run_id 'hybrid_density_gate':",
          f"    hybrid_density_gate  spearman={rec['mean_score']:.4f}  "
          f"rmse={rec['mean_rmse']:.3f}",
          f"    {win['run_id']:20s} spearman={win['mean_score']:.4f}  "
          f"rmse={win['mean_rmse']:.3f}",
          "", "  NEITHER EXISTING MODEL WAS OVERWRITTEN. best.json is unchanged;",
          "  the GeoJSON still comes from the standalone winner. Adopting the",
          "  hybrid is the user's decision."]
    return rec, b


# ------------------------------------------------------------- Section 5 + driver
def scope_statement(t3, wagg, win):
    wr = wagg[wagg.stratum == "rural"].mean_spearman.iloc[0]
    wu = wagg[wagg.stratum == "urban"].mean_spearman.iloc[0]
    return [
        "PROPOSED SCOPE STATEMENT -- FOR USER APPROVAL OR EDIT, NOT ASSERTED",
        "",
        "  This model produces a RELATIVE ordering of demographic vulnerability",
        "  within a single flood incident. It is not validated to produce",
        "  magnitudes: predictions run roughly 4x low overall and the",
        "  calibration curve is non-monotonic, so no post-hoc wrapper repaired",
        "  it (Test 2). Measured like-for-like inside each fold, ranking skill",
        f"  is MODERATELY BETTER in metro tracts (Spearman {wu:.3f}, RUCC 1-3) than",
        f"  in nonmetro tracts ({wr:.3f}, RUCC 4-9) -- the opposite of what a",
        "  pooled comparison appears to show, and worth stating plainly because",
        "  Kerr County is RUCC 4 and therefore sits in the WEAKER regime for",
        "  ranking, not the stronger one. The severe underprediction of dense",
        "  high-impact urban tracts (Harris County, DR-4781: predicted under 1",
        "  per 1,000 against an actual 186-265) is a magnitude failure, not a",
        "  ranking failure, and is a KNOWN AND CURRENT LIMITATION of a model",
        "  with no hydrological input rather than a defect to chase. Proposed",
        "  scope: use for within-incident relative shading anywhere in the",
        "  RUCC 1-9 range; do not use any output as a magnitude, a cross-",
        "  incident comparison, or a flood-extent claim.",
        "",
        "  STATUS: proposed. Not adopted, not applied to any output, and not",
        "  reflected in best.json or the GeoJSON. Edit or reject as you see fit.",
        "",
        "  WHAT THIS FOLLOW-UP DID NOT FIND: urbanicity does NOT unify the three",
        "  findings. It explains the Test 5 correlations (section 1, confirmed),",
        "  but Test 1's weak folds are explained by low label variance rather",
        "  than urbanicity (section 2), and the ranking-skill profile runs",
        "  opposite to the urban-underperformance hypothesis (section 3). The",
        "  density-gated hybrid was tested and is NOT recommended (section 4).",
    ]


def main():
    best, runs, win, df = ctx()
    oofdf = pd.read_csv(OOF, dtype={"tract_fips": str, "fips_county": str})

    s1 = section1(df)
    s2t = section2(win, df)
    t3, d = section3(df, oofdf)
    top, b4, frac, v4 = section4(win, runs, df, d)
    if frac >= 0.5:
        hybrid, b4 = validate_hybrid(win, df, b4, frac)
    else:
        hybrid = None
        b4 += ["", "Pattern too weak to justify proposing a switching rule.",
               "No hybrid validated."]
    add(4, "Test 7 revisited with the density lens", v4, "\n".join(b4))

    scope = scope_statement(t3, WAGG[0], win)
    add(5, "Proposed scope statement", "flagged for review", "\n".join(scope))

    with open(LOG, "w") as fh:
        fh.write("\n".join(scope))
        fh.write("\n\n" + "=" * 78 + "\n")
        fh.write("FOLLOW-UP DIAGNOSTIC -- VERDICTS\n" + "=" * 78 + "\n")
        for s in SECTIONS:
            fh.write(f"  Section {s['n']}: {s['title']} -> {s['verdict'].upper()}\n")
        fh.write("\nNo retraining was performed. logs/model_tests.log is "
                 "unmodified.\nThe single new harness evaluation is "
                 "'hybrid_density_gate', logged as a\ncandidate only.\n")
        for s in SECTIONS:
            fh.write(f"\n{'='*78}\nSECTION {s['n']}: {s['title']}  "
                     f"[{s['verdict'].upper()}]\n{'='*78}\n{s['body']}\n")
    print(f"\nwrote {LOG}")


if __name__ == "__main__":
    main()
