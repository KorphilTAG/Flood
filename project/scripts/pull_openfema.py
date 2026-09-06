"""Pull OpenFEMA Individual Assistance registrations + disaster declarations.

Entity names and versions are confirmed against the live dataset-metadata
endpoint before pulling, because OpenFEMA renames and re-versions datasets.
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from common import RAW, TX_IA_DISASTERS, describe, get, log_block, LOGS  # noqa: E402

BASE = "https://www.fema.gov/api/open"
PAGE = 10000
LOG = os.path.join(LOGS, "pull_checkpoint.log")

# Only the fields the model needs -- keeps 384k rows to a manageable payload.
IA_FIELDS = [
    "id", "disasterNumber", "censusGeoid", "fips", "county", "damagedZipCode",
    "ihpAmount", "ihpEligible", "haAmount", "onaAmount", "ownRent",
    "grossIncome", "occupants65andOver", "floodDamage", "floodDamageAmount",
    "waterLevel", "destroyed", "residenceType", "primaryResidence",
]


def confirm_entities():
    """Confirm live entity names/versions before pulling (spec Section 2.1)."""
    r = get(f"{BASE}/v1/OpenFemaDataSets")
    rows = r.json()["OpenFemaDataSets"]
    want = {
        "IndividualsAndHouseholdsProgramValidRegistrations",
        "DisasterDeclarationsSummaries",
        "HousingAssistanceOwners",
    }
    found = {}
    for x in rows:
        if x["name"] in want:
            found.setdefault(x["name"], []).append(
                (x["version"], x.get("depracated"), x.get("deprecated"))
            )
    lines = [f"{k}: versions/deprecation={v}" for k, v in sorted(found.items())]
    log_block(LOG, "2.0 OpenFEMA entity confirmation", "\n".join(lines))
    return found


def pull_declarations():
    """Paginate -- Texas has >5,000 declaration rows (one per county per
    disaster), so a single capped request silently drops the highest disaster
    numbers, i.e. exactly the recent events this model targets."""
    frames, skip = [], 0
    while True:
        r = get(f"{BASE}/v2/DisasterDeclarationsSummaries", params={
            "$filter": "state eq 'TX'", "$top": str(PAGE), "$skip": str(skip),
            "$orderby": "id",
        })
        recs = r.json()["DisasterDeclarationsSummaries"]
        if not recs:
            break
        frames.append(pd.DataFrame(recs))
        skip += PAGE
        if len(recs) < PAGE:
            break
    df = pd.concat(frames, ignore_index=True)
    out = os.path.join(RAW, "openfema_declarations_tx.csv")
    df.to_csv(out, index=False)
    return df, out


def pull_registrations():
    frames = []
    for dn in TX_IA_DISASTERS:
        skip, got = 0, 0
        while True:
            r = get(f"{BASE}/v2/IndividualsAndHouseholdsProgramValidRegistrations",
                    params={"$filter": f"disasterNumber eq {dn}",
                            "$select": ",".join(IA_FIELDS),
                            "$top": str(PAGE), "$skip": str(skip),
                            "$orderby": "id"})
            recs = r.json()["IndividualsAndHouseholdsProgramValidRegistrations"]
            if not recs:
                break
            frames.append(pd.DataFrame(recs))
            got += len(recs)
            skip += PAGE
            if len(recs) < PAGE:
                break
        print(f"  DR-{dn}: pulled {got:,} registrations", flush=True)
    df = pd.concat(frames, ignore_index=True)
    out = os.path.join(RAW, "openfema_ia_registrations.csv")
    df.to_csv(out, index=False)
    return df, out


def main():
    os.makedirs(RAW, exist_ok=True)
    confirm_entities()

    decl, decl_path = pull_declarations()
    log_block(LOG, "2.1a OpenFEMA disaster declarations (TX)",
              describe(decl, decl_path))

    if os.environ.get("SKIP_REGISTRATIONS"):
        ia_path = os.path.join(RAW, "openfema_ia_registrations.csv")
        ia = pd.read_csv(ia_path, dtype={"censusGeoid": str}, low_memory=False)
    else:
        ia, ia_path = pull_registrations()
    geoid_cov = ia["censusGeoid"].notna().mean() * 100
    body = describe(ia, ia_path)
    body += (f"\ncensusGeoid coverage: {geoid_cov:.1f}% "
             f"({ia['censusGeoid'].notna().sum():,}/{len(ia):,} rows)\n")
    body += "per-disaster counts:\n"
    body += ia.groupby("disasterNumber").size().to_string()
    log_block(LOG, "2.1b OpenFEMA IA valid registrations", body)


if __name__ == "__main__":
    main()
