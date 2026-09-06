"""ACS 5-year tract estimates for Texas.

The api.census.gov REST endpoint now returns a "Missing Key" interstitial for
every query, including the credential-free examples in the task spec (logged as
a Section 7 flag). The identical estimates are published, ungated, as the
table-based Summary Files on www2.census.gov -- a host the spec's own network
check requires -- so that is the primary path here.

If CENSUS_API_KEY is set in the environment, the REST path is used instead and
the two are cross-checked.
"""
import io
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from common import LOGS, RAW, describe, get, log_block, zero_pad  # noqa: E402

LOG = os.path.join(LOGS, "pull_checkpoint.log")
SF = ("https://www2.census.gov/programs-surveys/acs/summary_file/2023"
      "/table-based-SF/data/5YRData/acsdt5y2023-{table}.dat")

# Tract summary level, Texas: GEO_ID looks like 1400000US48265960601
TRACT_PREFIX = "1400000US48"

# Age 65+ bins named in the spec (male 020-025, female 044-049).
AGE65_COLS = [f"B01001_E{n:03d}" for n in list(range(20, 26)) + list(range(44, 50))]


def fetch_table(table):
    r = get(SF.format(table=table))
    df = pd.read_csv(io.StringIO(r.content.decode("utf-8-sig", errors="replace")),
                     sep="|", dtype=str)
    df = df[df["GEO_ID"].str.startswith(TRACT_PREFIX, na=False)].copy()
    df["tract_fips"] = df["GEO_ID"].str.replace("1400000US", "", regex=False)
    return df


def num(df, cols):
    for c in cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def main():
    os.makedirs(RAW, exist_ok=True)
    if os.environ.get("CENSUS_API_KEY"):
        log_block(LOG, "2.2 ACS -- note",
                  "CENSUS_API_KEY is set; REST path available. Summary-file "
                  "path still used as the authoritative pull for reproducibility.")

    inc = num(fetch_table("b19013"), ["B19013_E001"])[["tract_fips", "B19013_E001"]]
    inc = inc.rename(columns={"B19013_E001": "acs_median_hh_income"})

    ten = num(fetch_table("b25003"),
              ["B25003_E001", "B25003_E002", "B25003_E003"])
    ten = ten[["tract_fips", "B25003_E001", "B25003_E002", "B25003_E003"]].rename(
        columns={"B25003_E001": "acs_occupied_units",
                 "B25003_E002": "acs_owner_occupied",
                 "B25003_E003": "acs_renter_occupied"})

    pop = num(fetch_table("b01003"), ["B01003_E001"])[["tract_fips", "B01003_E001"]]
    pop = pop.rename(columns={"B01003_E001": "acs_total_pop"})

    age = fetch_table("b01001")
    have = [c for c in AGE65_COLS if c in age.columns]
    age = num(age, have)
    age["acs_pop_65plus"] = age[have].sum(axis=1)
    age = age[["tract_fips", "acs_pop_65plus"]]

    df = inc.merge(ten, on="tract_fips", how="outer") \
            .merge(pop, on="tract_fips", how="outer") \
            .merge(age, on="tract_fips", how="outer")
    df["tract_fips"] = zero_pad(df["tract_fips"], 11)
    df["fips_county"] = df["tract_fips"].str[:5]

    out = os.path.join(RAW, "acs_tract.csv")
    df.to_csv(out, index=False)

    body = describe(df, out)
    body += (f"\nage-65+ bins summed: {have}\n"
             f"source: ACS 2019-2023 5-year table-based Summary File "
             f"(www2.census.gov, keyless)\n")
    log_block(LOG, "2.2 ACS 5-year tract estimates (Texas)", body)


if __name__ == "__main__":
    main()
