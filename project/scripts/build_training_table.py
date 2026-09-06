"""Join OpenFEMA IA labels to ACS/SVI/IRS/RUCC features at tract x incident grain.

Grain decision (logged): OpenFEMA's IndividualsAndHouseholdsProgramValidRegistrations
carries a 12-digit `censusGeoid` (block group), so truncating to 11 digits gives a
genuine TRACT-level label -- better than the county fallback the spec allowed for.

Scoping decision: a tract only enters the table for a given disaster if its county
was IA-designated (ihProgramDeclared) for that disaster. Without this, a tract with
zero registrations because it was never declared would be indistinguishable from a
declared tract that generated no claims, and the label would be meaningless.
"""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from common import (LOGS, PROCESSED, RAW, TX_IA_DISASTERS,  # noqa: E402
                    log_block, zero_pad)

# Scope: "tx" reproduces the original Texas-only run; "national" (default) uses
# every US flood declaration with IA since FY2015 that designated >=3 counties.
# More INCIDENTS is what widens the leave-one-incident-out harness.
SCOPE = os.environ.get("SCOPE", "national")
NATIONAL = SCOPE == "national"
MIN_COUNTIES = 3
F = {
    "decl": "openfema_declarations_national.csv" if NATIONAL
            else "openfema_declarations_tx.csv",
    "ia": "openfema_ia_registrations_national.csv" if NATIONAL
          else "openfema_ia_registrations.csv",
    "acs": "acs_tract_national.csv" if NATIONAL else "acs_tract.csv",
    "svi": "svi_national.csv" if NATIONAL else "svi_tx.csv",
    "irs": "irs_soi_national.csv" if NATIONAL else "irs_soi_tx.csv",
    "rucc": "rucc_national.csv" if NATIONAL else "rucc.csv",
}

LOG = os.path.join(LOGS, "join_checkpoint.log")

# Census "jam values" (unavailable / suppressed) and SVI's missing sentinel.
ACS_JAM = -666666600
SVI_NULL = -999

SVI_FEATURES = [
    "RPL_THEMES", "RPL_THEME1", "RPL_THEME2", "RPL_THEME3", "RPL_THEME4",
    "EP_POV150", "EP_UNEMP", "EP_HBURD", "EP_NOHSDP", "EP_UNINSUR",
    "EP_AGE65", "EP_AGE17", "EP_DISABL", "EP_SNGPNT", "EP_LIMENG",
    "EP_MINRTY", "EP_MUNIT", "EP_MOBILE", "EP_CROWD", "EP_NOVEH", "EP_GROUPQ",
]


def load_declarations():
    d = pd.read_csv(os.path.join(RAW, F["decl"]), dtype=str, low_memory=False)
    # ihProgramDeclared arrives as the strings "True"/"False", not 0/1.
    d["ih"] = d["ihProgramDeclared"].astype(str).str.lower().isin(["true", "1"])
    d["fips_county"] = (zero_pad(d["fipsStateCode"], 2).astype(str)
                        + zero_pad(d["fipsCountyCode"], 3).astype(str))
    d["disasterNumber"] = pd.to_numeric(d["disasterNumber"], errors="coerce")
    if NATIONAL:
        ia = d[d["ih"]].copy()
        n = ia.groupby("disasterNumber")["fips_county"].nunique()
        ia = ia[ia["disasterNumber"].isin(n[n >= MIN_COUNTIES].index)]
    else:
        ia = d[d["ih"] & d["disasterNumber"].isin(TX_IA_DISASTERS)]
    return ia[["disasterNumber", "fips_county", "declarationDate",
               "incidentType"]].drop_duplicates()


def load_labels():
    ia = pd.read_csv(os.path.join(RAW, F["ia"]),
                     dtype={"censusGeoid": str, "fips": str}, low_memory=False)
    n_total = len(ia)
    ia["tract_fips"] = zero_pad(ia["censusGeoid"].str[:11], 11)
    geo_ok = ia["tract_fips"].notna().sum()
    for c in ("ihpAmount", "haAmount", "onaAmount", "floodDamageAmount"):
        ia[c] = pd.to_numeric(ia[c], errors="coerce").fillna(0)
    ia["eligible"] = ia["ihpEligible"].astype(str).str.lower().isin(["true", "1"])
    ia["flood"] = ia["floodDamage"].astype(str).str.lower().isin(["true", "1"])

    agg = ia.dropna(subset=["tract_fips"]).groupby(
        ["disasterNumber", "tract_fips"]).agg(
        ia_registrations=("id", "count"),
        ia_eligible=("eligible", "sum"),
        ia_flood_damage=("flood", "sum"),
        ia_ihp_amount=("ihpAmount", "sum"),
        ia_ha_amount=("haAmount", "sum"),
    ).reset_index()
    return agg, n_total, geo_ok


def load_features():
    acs = pd.read_csv(os.path.join(RAW, F["acs"]),
                      dtype={"tract_fips": str, "fips_county": str})
    for c in acs.columns:
        if c.startswith("acs_"):
            acs[c] = pd.to_numeric(acs[c], errors="coerce")
            acs.loc[acs[c] <= ACS_JAM, c] = np.nan

    svi = pd.read_csv(os.path.join(RAW, F["svi"]),
                      dtype={"FIPS": str, "STCNTY": str}, low_memory=False)
    svi["tract_fips"] = zero_pad(svi["FIPS"], 11)
    keep = ["tract_fips", "AREA_SQMI", "E_TOTPOP", "E_HU", "E_HH",
            "E_DAYPOP"] + SVI_FEATURES
    svi = svi[[c for c in keep if c in svi.columns]].copy()
    for c in svi.columns:
        if c != "tract_fips":
            svi[c] = pd.to_numeric(svi[c], errors="coerce")
            svi.loc[svi[c] == SVI_NULL, c] = np.nan

    irs = pd.read_csv(os.path.join(RAW, F["irs"]),
                      dtype={"fips_county": str}, low_memory=False)
    for c in ("N1", "A00100", "N02650", "A02650", "ELDERLY", "SCHF", "N2"):
        irs[c] = pd.to_numeric(irs.get(c), errors="coerce")
    irs_f = pd.DataFrame({
        "fips_county": irs["fips_county"],
        "irs_returns": irs["N1"],
        "irs_avg_agi": irs["A00100"] / irs["N1"].replace(0, np.nan),
        "irs_avg_total_income": irs["A02650"] / irs["N02650"].replace(0, np.nan),
        "irs_elderly_share": irs["ELDERLY"] / irs["N1"].replace(0, np.nan),
        "irs_farm_share": irs["SCHF"] / irs["N1"].replace(0, np.nan),
        "irs_avg_exemptions": irs["N2"] / irs["N1"].replace(0, np.nan),
    })

    rucc = pd.read_csv(os.path.join(RAW, F["rucc"]), dtype={"fips_county": str})
    rucc_f = pd.DataFrame({
        "fips_county": rucc["fips_county"],
        "rucc_2023": pd.to_numeric(rucc["RUCC_2023"], errors="coerce"),
        "rucc_pop_2020": pd.to_numeric(rucc["Population_2020"], errors="coerce"),
    })
    return acs, svi, irs_f, rucc_f


def main():
    os.makedirs(PROCESSED, exist_ok=True)
    decl = load_declarations()
    labels, n_reg_total, n_geo_ok = load_labels()
    acs, svi, irs, rucc = load_features()

    # Universe: every TX tract whose county was IA-designated, per disaster.
    universe = decl.merge(acs[["tract_fips", "fips_county"]],
                          on="fips_county", how="inner")

    df = universe.merge(labels, on=["disasterNumber", "tract_fips"], how="left")
    n_with_claims = df["ia_registrations"].notna().sum()
    for c in ("ia_registrations", "ia_eligible", "ia_flood_damage",
              "ia_ihp_amount", "ia_ha_amount"):
        df[c] = df[c].fillna(0)

    df = (df.merge(acs.drop(columns=["fips_county"]), on="tract_fips", how="left")
            .merge(svi, on="tract_fips", how="left")
            .merge(irs, on="fips_county", how="left")
            .merge(rucc, on="fips_county", how="left"))

    # Population denominator: SVI's ACS-derived E_TOTPOP, falling back to the
    # ACS B01003 pull where SVI is missing.
    df["population"] = df["E_TOTPOP"].fillna(df["acs_total_pop"])
    pop = df["population"].where(df["population"] > 0)

    df["label_reg_per_1k"] = df["ia_registrations"] / pop * 1000
    df["label_ihp_per_capita"] = df["ia_ihp_amount"] / pop
    df["label_any_claim"] = (df["ia_registrations"] > 0).astype(int)

    # Derived features
    df["acs_owner_share"] = df["acs_owner_occupied"] / df["acs_occupied_units"].replace(0, np.nan)
    df["acs_renter_share"] = df["acs_renter_occupied"] / df["acs_occupied_units"].replace(0, np.nan)
    df["acs_pop65_share"] = df["acs_pop_65plus"] / pop
    df["pop_density"] = df["population"] / df["AREA_SQMI"].replace(0, np.nan)
    df["hu_density"] = df["E_HU"] / df["AREA_SQMI"].replace(0, np.nan)
    df["daypop_ratio"] = df["E_DAYPOP"] / pop

    df = df[df["population"].notna() & (df["population"] > 0)].copy()

    out = os.path.join(PROCESSED, "training_table.csv")
    df.to_csv(out, index=False)

    # ---- Checkpoint 2 ----
    geo_rate = n_geo_ok / n_reg_total * 100
    claim_rate = n_with_claims / len(df) * 100
    feat_cols = [c for c in df.columns if c.startswith(("acs_", "irs_", "rucc_",
                 "EP_", "RPL_", "pop_", "hu_", "daypop_"))]
    nulls = df[feat_cols].isna().mean().mul(100).round(2).sort_values(ascending=False)
    body = [
        f"output: {out}",
        f"final shape: {df.shape[0]:,} rows x {df.shape[1]} cols",
        f"grain: tract x disaster (TRACT-level label available -- censusGeoid[:11])",
        f"incidents: {df.disasterNumber.nunique()} -> "
        f"{sorted(df.disasterNumber.unique().tolist())}",
        f"states: {df.tract_fips.str[:2].nunique()}",
        f"distinct tracts: {df.tract_fips.nunique():,}   "
        f"distinct counties: {df.fips_county.nunique()}",
        "",
        "JOIN-MATCH RATES",
        f"  registrations with a usable censusGeoid: {n_geo_ok:,}/{n_reg_total:,} "
        f"= {geo_rate:.1f}%",
        f"  rows with a feature join (ACS+SVI non-null RPL_THEMES): "
        f"{df['RPL_THEMES'].notna().mean()*100:.1f}%",
        f"  rows with population denominator: 100.0% (rows without one dropped)",
        f"  rows carrying >=1 IA registration: {n_with_claims:,}/{len(df):,} "
        f"= {claim_rate:.1f}%  (the rest are declared-but-no-claim true zeros)",
        "",
        "LABEL SUMMARY",
        df[["ia_registrations", "label_reg_per_1k", "label_ihp_per_capita",
            "label_any_claim"]].describe().to_string(),
        "",
        "ROWS PER INCIDENT",
        df.groupby("disasterNumber").agg(
            rows=("tract_fips", "size"),
            tracts_with_claims=("label_any_claim", "sum"),
            mean_reg_per_1k=("label_reg_per_1k", "mean")).to_string(),
        "",
        "NULL RATE PER FEATURE COLUMN (%)",
        nulls.to_string(),
    ]
    log_block(LOG, f"Checkpoint 2 -- join + feature engineering (scope={SCOPE})",
              "\n".join(body))


if __name__ == "__main__":
    main()
