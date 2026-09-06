"""CDC/ATSDR Social Vulnerability Index -- Texas tract-level bulk CSV.

Keyless bulk download (spec Section 2.3). SVI is itself ACS-derived, so it
also supplies the ACS-equivalent socioeconomic estimates (E_* columns) and the
E_TOTPOP denominator used to normalize the IA label per capita.
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from common import LOGS, RAW, describe, get, log_block  # noqa: E402

LOG = os.path.join(LOGS, "pull_checkpoint.log")
URL = "https://svi.cdc.gov/Documents/Data/{year}/csv/states/Texas.csv"


def main():
    os.makedirs(RAW, exist_ok=True)
    for year in (2022, 2020, 2018):
        try:
            r = get(URL.format(year=year), tries=2)
        except RuntimeError:
            print(f"  SVI {year}: unavailable", flush=True)
            continue
        out = os.path.join(RAW, f"svi_tx_{year}.csv")
        with open(out, "wb") as fh:
            fh.write(r.content)
        df = pd.read_csv(out, dtype={"FIPS": str, "STCNTY": str})
        body = describe(df, out)
        body += f"\ntract FIPS width: {df['FIPS'].astype(str).str.len().value_counts().to_dict()}\n"
        log_block(LOG, f"2.3 CDC/ATSDR SVI {year} (Texas tracts)", body)
        if year == 2022:  # canonical copy at the spec's path
            df.to_csv(os.path.join(RAW, "svi_tx.csv"), index=False)


if __name__ == "__main__":
    main()
