"""National expansion: IA registrations for every US flood declaration with
Individual Assistance since FY2015 that designated >=3 counties.

Replaces the Texas-only pull. More INCIDENTS is what widens the
leave-one-incident-out harness; more rows per incident would not.
"""
import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from common import LOGS, RAW, describe, get, log_block  # noqa: E402

BASE = "https://www.fema.gov/api/open"
PAGE = 10000
LOG = os.path.join(LOGS, "pull_checkpoint.log")
MIN_COUNTIES = 3

IA_FIELDS = [
    "id", "disasterNumber", "censusGeoid", "fips", "county", "damagedZipCode",
    "ihpAmount", "ihpEligible", "haAmount", "onaAmount", "ownRent",
    "grossIncome", "occupants65andOver", "floodDamage", "floodDamageAmount",
    "waterLevel", "destroyed", "residenceType", "primaryResidence",
]


def pull_declarations():
    frames, skip = [], 0
    while True:
        r = get(f"{BASE}/v2/DisasterDeclarationsSummaries", params={
            "$filter": "incidentType eq 'Flood' and ihProgramDeclared eq true "
                       "and fyDeclared ge 2015",
            "$top": str(PAGE), "$skip": str(skip), "$orderby": "id"})
        recs = r.json()["DisasterDeclarationsSummaries"]
        if not recs:
            break
        frames.append(pd.DataFrame(recs))
        skip += PAGE
        if len(recs) < PAGE:
            break
    df = pd.concat(frames, ignore_index=True)
    out = os.path.join(RAW, "openfema_declarations_national.csv")
    df.to_csv(out, index=False)
    return df, out


def main():
    os.makedirs(RAW, exist_ok=True)
    decl, decl_path = pull_declarations()
    decl["fips_county"] = (decl["fipsStateCode"].astype(str).str.zfill(2)
                           + decl["fipsCountyCode"].astype(str).str.zfill(3))
    counts = decl.groupby("disasterNumber")["fips_county"].nunique()
    incidents = sorted(counts[counts >= MIN_COUNTIES].index.tolist())
    log_block(LOG, "N.1 National flood declarations with IA (FY2015+)",
              describe(decl, decl_path) +
              f"\nincidents with >={MIN_COUNTIES} IA counties: {len(incidents)}\n"
              f"{incidents}\n")

    frames = []
    for i, dn in enumerate(incidents, 1):
        skip, got = 0, 0
        while True:
            r = get(f"{BASE}/v2/IndividualsAndHouseholdsProgramValidRegistrations",
                    params={"$filter": f"disasterNumber eq {dn}",
                            "$select": ",".join(IA_FIELDS),
                            "$top": str(PAGE), "$skip": str(skip),
                            "$orderby": "id"}, timeout=180)
            recs = r.json()["IndividualsAndHouseholdsProgramValidRegistrations"]
            if not recs:
                break
            frames.append(pd.DataFrame(recs))
            got += len(recs)
            skip += PAGE
            if len(recs) < PAGE:
                break
        print(f"  [{i}/{len(incidents)}] DR-{dn}: {got:,}", flush=True)

    ia = pd.concat(frames, ignore_index=True)
    out = os.path.join(RAW, "openfema_ia_registrations_national.csv")
    ia.to_csv(out, index=False)
    body = describe(ia, out)
    body += (f"\ncensusGeoid coverage: "
             f"{ia['censusGeoid'].notna().mean()*100:.1f}%\n"
             f"incidents: {ia.disasterNumber.nunique()}\n")
    log_block(LOG, "N.2 National IA valid registrations", body)


if __name__ == "__main__":
    main()
