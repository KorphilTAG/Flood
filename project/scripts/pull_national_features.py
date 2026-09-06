"""National feature pulls: SVI (per state), ACS tracts, IRS SOI, RUCC.

Same ungated sources as the Texas run, with the state filters removed.
"""
import io
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from common import LOGS, RAW, describe, get, log_block, zero_pad  # noqa: E402

LOG = os.path.join(LOGS, "pull_checkpoint.log")
SVI_URL = "https://svi.cdc.gov/Documents/Data/2022/csv/states/{name}.csv"
ACS_SF = ("https://www2.census.gov/programs-surveys/acs/summary_file/2023"
          "/table-based-SF/data/5YRData/acsdt5y2023-{table}.dat")
IRS_URL = "https://www.irs.gov/pub/irs-soi/23incyallnoagi.csv"
RUCC_URL = "https://www.ers.usda.gov/media/5768/2023-rural-urban-continuum-codes.csv"

STATE_NAME = {
    "AK": "Alaska", "AL": "Alabama", "AR": "Arkansas", "AZ": "Arizona",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DC": "DistrictofColumbia",
    "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "IA": "Iowa", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "MA": "Massachusetts",
    "MD": "Maryland", "ME": "Maine", "MI": "Michigan", "MN": "Minnesota",
    "MO": "Missouri", "MS": "Mississippi", "MT": "Montana", "NC": "NorthCarolina",
    "ND": "NorthDakota", "NE": "Nebraska", "NH": "NewHampshire", "NJ": "NewJersey",
    "NM": "NewMexico", "NV": "Nevada", "NY": "NewYork", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "PR": "PuertoRico",
    "RI": "RhodeIsland", "SC": "SouthCarolina", "SD": "SouthDakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VA": "Virginia",
    "VT": "Vermont", "WA": "Washington", "WI": "Wisconsin", "WV": "WestVirginia",
    "WY": "Wyoming",
}
AGE65 = [f"B01001_E{n:03d}" for n in list(range(20, 26)) + list(range(44, 50))]


def pull_svi(states):
    frames, missing = [], []
    for ab in sorted(states):
        name = STATE_NAME.get(ab)
        if not name:
            missing.append(ab)
            continue
        try:
            r = get(SVI_URL.format(name=name), tries=2)
        except RuntimeError:
            missing.append(ab)
            continue
        frames.append(pd.read_csv(io.BytesIO(r.content), dtype={"FIPS": str,
                                  "STCNTY": str}, low_memory=False))
        print(f"  SVI {ab} ok", flush=True)
    df = pd.concat(frames, ignore_index=True)
    out = os.path.join(RAW, "svi_national.csv")
    df.to_csv(out, index=False)
    return df, out, missing


def acs_table(table):
    r = get(ACS_SF.format(table=table))
    df = pd.read_csv(io.StringIO(r.content.decode("utf-8-sig", errors="replace")),
                     sep="|", dtype=str)
    df = df[df["GEO_ID"].str.startswith("1400000US", na=False)].copy()
    df["tract_fips"] = df["GEO_ID"].str.replace("1400000US", "", regex=False)
    return df


def num(df, cols):
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def pull_acs():
    inc = num(acs_table("b19013"), ["B19013_E001"])[["tract_fips", "B19013_E001"]] \
        .rename(columns={"B19013_E001": "acs_median_hh_income"})
    ten = num(acs_table("b25003"), ["B25003_E001", "B25003_E002", "B25003_E003"])
    ten = ten[["tract_fips", "B25003_E001", "B25003_E002", "B25003_E003"]].rename(
        columns={"B25003_E001": "acs_occupied_units",
                 "B25003_E002": "acs_owner_occupied",
                 "B25003_E003": "acs_renter_occupied"})
    pop = num(acs_table("b01003"), ["B01003_E001"])[["tract_fips", "B01003_E001"]] \
        .rename(columns={"B01003_E001": "acs_total_pop"})
    age = acs_table("b01001")
    have = [c for c in AGE65 if c in age.columns]
    age = num(age, have)
    age["acs_pop_65plus"] = age[have].sum(axis=1)
    age = age[["tract_fips", "acs_pop_65plus"]]

    df = inc.merge(ten, on="tract_fips", how="outer") \
            .merge(pop, on="tract_fips", how="outer") \
            .merge(age, on="tract_fips", how="outer")
    df["tract_fips"] = zero_pad(df["tract_fips"], 11)
    df["fips_county"] = df["tract_fips"].str[:5]
    out = os.path.join(RAW, "acs_tract_national.csv")
    df.to_csv(out, index=False)
    return df, out


def pull_irs():
    r = get(IRS_URL)
    df = pd.read_csv(io.BytesIO(r.content), dtype=str, low_memory=False)
    df.columns = [c.upper() for c in df.columns]
    df = df[df["COUNTYFIPS"].astype(str).str.zfill(3) != "000"]
    df["fips_county"] = (zero_pad(df["STATEFIPS"], 2).astype(str)
                         + zero_pad(df["COUNTYFIPS"], 3).astype(str))
    out = os.path.join(RAW, "irs_soi_national.csv")
    df.to_csv(out, index=False)
    return df, out


def pull_rucc():
    r = get(RUCC_URL, params={"v": "43782"})
    long = pd.read_csv(io.StringIO(r.content.decode("utf-8-sig", errors="replace")),
                       dtype=str)
    long["FIPS"] = zero_pad(long["FIPS"], 5)
    wide = long.pivot_table(index=["FIPS", "State", "County_Name"],
                            columns="Attribute", values="Value",
                            aggfunc="first").reset_index()
    wide.columns.name = None
    wide = wide.rename(columns={"FIPS": "fips_county"})
    out = os.path.join(RAW, "rucc_national.csv")
    wide.to_csv(out, index=False)
    return wide, out


def main():
    meta = json.load(open(os.path.join(RAW, "national_incidents.json")))
    states = set(meta["state_of"].values())
    svi, p, missing = pull_svi(states)
    log_block(LOG, "N.3 CDC/ATSDR SVI 2022 (national, per-state files)",
              describe(svi, p) + f"\nstates pulled: {len(states)-len(missing)}"
              f"  missing: {missing}\n")
    acs, p = pull_acs()
    log_block(LOG, "N.4 ACS 5-year tract estimates (national)", describe(acs, p))
    irs, p = pull_irs()
    log_block(LOG, "N.5 IRS SOI county (national, TY2023)", describe(irs, p))
    rucc, p = pull_rucc()
    log_block(LOG, "N.6 USDA RUCC 2023 (national)", describe(rucc, p))


if __name__ == "__main__":
    main()
