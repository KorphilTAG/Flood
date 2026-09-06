"""IRS Statistics of Income (county) and USDA Rural-Urban Continuum Codes.

Both are keyless bulk downloads (spec Sections 2.4, 2.5).
"""
import io
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from common import LOGS, RAW, describe, get, log_block, zero_pad  # noqa: E402

LOG = os.path.join(LOGS, "pull_checkpoint.log")
IRS_URL = "https://www.irs.gov/pub/irs-soi/{yy}incyallnoagi.csv"
RUCC_URL = "https://www.ers.usda.gov/media/5768/2023-rural-urban-continuum-codes.csv"


def pull_irs():
    """Most recent available tax year, county level, Texas only."""
    for yy in ("23", "22", "21"):
        try:
            r = get(IRS_URL.format(yy=yy), tries=2)
        except RuntimeError:
            continue
        df = pd.read_csv(io.BytesIO(r.content), dtype=str, low_memory=False)
        df.columns = [c.upper() for c in df.columns]
        tx = df[df["STATE"].str.upper() == "TX"].copy()
        # COUNTYFIPS 000 is the state rollup row, not a county.
        tx = tx[tx["COUNTYFIPS"].astype(str).str.zfill(3) != "000"]
        tx["fips_county"] = (zero_pad(tx["STATEFIPS"], 2).astype(str)
                             + zero_pad(tx["COUNTYFIPS"], 3).astype(str))
        out = os.path.join(RAW, "irs_soi_tx.csv")
        tx.to_csv(out, index=False)
        return tx, out, f"20{yy}"
    raise RuntimeError("no IRS SOI county file available")


def pull_rucc():
    r = get(RUCC_URL, params={"v": "43782"})
    # The ERS file carries a BOM and a stray non-UTF8 byte; decode defensively
    # rather than handing raw bytes to the C parser.
    text = r.content.decode("utf-8-sig", errors="replace")
    long = pd.read_csv(io.StringIO(text), dtype=str)
    long["FIPS"] = zero_pad(long["FIPS"], 5)
    wide = long.pivot_table(index=["FIPS", "State", "County_Name"],
                            columns="Attribute", values="Value",
                            aggfunc="first").reset_index()
    wide.columns.name = None
    tx = wide[wide["State"] == "TX"].copy()
    tx = tx.rename(columns={"FIPS": "fips_county"})
    out = os.path.join(RAW, "rucc.csv")
    tx.to_csv(out, index=False)
    return tx, out


def main():
    os.makedirs(RAW, exist_ok=True)
    irs, irs_path, yr = pull_irs()
    log_block(LOG, f"2.4 IRS SOI county data (TX, tax year {yr})",
              describe(irs, irs_path))
    rucc, rucc_path = pull_rucc()
    log_block(LOG, "2.5 USDA Rural-Urban Continuum Codes 2023 (TX)",
              describe(rucc, rucc_path))


if __name__ == "__main__":
    main()
