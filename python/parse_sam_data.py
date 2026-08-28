#!/usr/bin/env python3
"""
Parse SAM.gov monthly .dat file and match against our companies DB.

Outputs two CSVs:
  output/sam_enrichment.csv    — company-level fields (CAGE, address, etc.)
  output/sam_contacts.csv      — POC contacts (2 per company)

Usage:
  python parse_sam_data.py [--dat path/to/SAM_PUBLIC_MONTHLY.dat]

Then import with:
  bin/rails companies:import_sam[python/output/sam_enrichment.csv]
  bin/rails contacts:import[python/output/sam_contacts.csv]
"""

import csv
import re
import subprocess
import sys
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path

DAT_DEFAULT = Path("/Users/dbarta/leads/SAM_PUBLIC_MONTHLY/SAM_PUBLIC_MONTHLY_V2_20260802.dat")
OUTPUT_DIR  = Path(__file__).parent / "output"

# Column indices (0-based; layout is 1-based so subtract 1)
C_UNIQUE_ENTITY_ID   = 0
C_CAGE_CODE          = 3
C_SAM_EXTRACT_CODE   = 5   # A=active, E=expired
C_EXPIRATION_DATE    = 8
C_LEGAL_NAME         = 11
C_DBA_NAME           = 12
C_ADDR_LINE1         = 15
C_ADDR_LINE2         = 16
C_ADDR_CITY          = 17
C_ADDR_STATE         = 18
C_ADDR_ZIP           = 19
C_ADDR_COUNTRY       = 21
C_ENTITY_START_DATE  = 24
C_ENTITY_URL         = 26
C_ENTITY_STRUCTURE   = 27
C_STATE_OF_INCORP    = 28
C_BUS_TYPE_STRING    = 31
C_PRIMARY_NAICS      = 32
C_NAICS_STRING       = 34
C_SBA_BUS_TYPES      = 117

# POC columns (Govt Business POC)
C_POC1_FIRST   = 46
C_POC1_MIDDLE  = 47
C_POC1_LAST    = 48
C_POC1_TITLE   = 49

# Alt Govt Business POC
C_POC2_FIRST   = 57
C_POC2_MIDDLE  = 58
C_POC2_LAST    = 59
C_POC2_TITLE   = 60


def normalize(name: str) -> str:
    n = name.upper()
    n = re.sub(r"[,\.\-]", " ", n)
    n = re.sub(r"\b(LLC|INC|LTD|CORP|LP|LLP|CO|PLC)\b", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def normalize_url(url: str) -> str:
    u = url.lower().strip()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    u = u.rstrip("/")
    return u


def get(fields: list, idx: int) -> str:
    return fields[idx].strip() if idx < len(fields) else ""


def parse_date(s: str) -> str:
    """Convert YYYYMMDD to YYYY-MM-DD, or '' if invalid."""
    s = s.strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:]}"
    return ""


def load_companies_from_db() -> dict:
    """Returns {company_id: canonical_name} via rails runner."""
    result = subprocess.run(
        ["bin/rails", "runner",
         "puts Company.pluck(:id, :canonical_name, :website).map{|id,n,w| \"#{id}|#{n}|#{w.to_s}\"}.join(\"\\n\")"],
        capture_output=True, text=True, cwd=Path(__file__).parent.parent
    )
    companies = {}
    for line in result.stdout.strip().split("\n"):
        parts = line.split("|", 2)
        if len(parts) >= 2:
            cid = int(parts[0])
            name = parts[1]
            website = parts[2] if len(parts) > 2 else ""
            companies[cid] = {"name": name, "website": website}
    return companies


def load_sam_index(dat_path: Path) -> dict:
    """
    Reads .dat file, returns {normalized_name: fields_list}.
    When multiple records share the same normalized name, keeps all as a list.
    """
    print(f"Loading SAM data from {dat_path} ...")
    index = {}  # norm_name -> list of fields_lists
    count = 0
    with open(dat_path, encoding="utf-8", errors="replace") as f:
        f.readline()  # skip BOF header
        for line in f:
            line = line.strip()
            if line.endswith("!end"):
                line = line[:-4]
            fields = line.split("|")
            if len(fields) < 20:
                continue
            raw_name = get(fields, C_LEGAL_NAME)
            if not raw_name:
                continue
            norm = normalize(raw_name)
            if norm not in index:
                index[norm] = []
            index[norm].append(fields)
            count += 1
    print(f"  Loaded {count:,} records ({len(index):,} unique normalized names)")
    return index


def best_match(our_name: str, our_website: str, sam_index: dict) -> tuple:
    """
    Returns (fields, match_type) or (None, None).
    match_type: 'normalized' | 'normalized+url' | 'none'
    When multiple SAM records share the same normalized name, uses address
    to disambiguate (prefer same state as our website domain hint, or first).
    """
    norm = normalize(our_name)

    if norm in sam_index:
        candidates = sam_index[norm]
        if len(candidates) == 1:
            return candidates[0], "normalized"
        # Multiple — try to disambiguate by website
        if our_website:
            our_domain = normalize_url(our_website)
            for c in candidates:
                sam_url = normalize_url(get(c, C_ENTITY_URL))
                if sam_url and our_domain and (sam_url in our_domain or our_domain in sam_url):
                    return c, "normalized+url"
        # Fall back to first (active preferred)
        active = [c for c in candidates if get(c, C_SAM_EXTRACT_CODE) == "A"]
        return (active[0] if active else candidates[0]), "normalized"

    return None, "none"


def make_poc(fields: list, first_col: int, mid_col: int, last_col: int, title_col: int,
             company_id: int, company_name: str, poc_label: str):
    first = get(fields, first_col)
    last  = get(fields, last_col)
    title = get(fields, title_col)
    if not (first or last):
        return None
    mid   = get(fields, mid_col)
    full  = " ".join(p for p in [first, mid, last] if p)
    return {
        "company_id":   company_id,
        "company_name": company_name,
        "full_name":    full,
        "first_name":   first,
        "last_name":    last,
        "title":        title,
        "email":        "",
        "phone":        "",
        "linkedin_url": "",
        "source":       "sam_gov",
        "notes":        f"SAM.gov {poc_label}",
    }


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dat", default=str(DAT_DEFAULT))
    args = parser.parse_args()

    dat_path = Path(args.dat)
    if not dat_path.exists():
        print(f"ERROR: .dat file not found: {dat_path}")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading companies from DB ...")
    companies = load_companies_from_db()
    print(f"  {len(companies)} companies")

    sam_index = load_sam_index(dat_path)

    enrichment_rows = []
    contact_rows    = []
    website_mismatches = []
    no_match_names  = []

    for cid, info in sorted(companies.items()):
        our_name    = info["name"]
        our_website = info["website"]

        fields, match_type = best_match(our_name, our_website, sam_index)

        if fields is None:
            no_match_names.append((cid, our_name))
            continue

        sam_name   = get(fields, C_LEGAL_NAME)
        cage       = get(fields, C_CAGE_CODE)
        status     = get(fields, C_SAM_EXTRACT_CODE)
        dba        = get(fields, C_DBA_NAME)
        addr1      = get(fields, C_ADDR_LINE1)
        addr2      = get(fields, C_ADDR_LINE2)
        city       = get(fields, C_ADDR_CITY)
        state      = get(fields, C_ADDR_STATE)
        zipcode    = get(fields, C_ADDR_ZIP)
        country    = get(fields, C_ADDR_COUNTRY)
        start_date = parse_date(get(fields, C_ENTITY_START_DATE))
        entity_url = get(fields, C_ENTITY_URL)
        structure  = get(fields, C_ENTITY_STRUCTURE)
        state_incorp = get(fields, C_STATE_OF_INCORP)
        bus_types  = get(fields, C_BUS_TYPE_STRING)
        sba_types  = get(fields, C_SBA_BUS_TYPES)
        naics_str  = get(fields, C_NAICS_STRING)
        primary_naics = get(fields, C_PRIMARY_NAICS)

        # Merge business types
        all_bus_types = "~".join(filter(None, [bus_types, sba_types]))

        # NAICS — extract codes only (strip Y/N suffix from each code)
        naics_codes = ""
        if naics_str:
            codes = [c.rstrip("YN") for c in naics_str.split("~") if c.strip()]
            if primary_naics and primary_naics not in codes:
                codes.insert(0, primary_naics)
            naics_codes = ", ".join(codes)

        # Website comparison
        website_action = ""
        if entity_url:
            sam_norm_url = normalize_url(entity_url)
            if our_website:
                our_norm_url = normalize_url(our_website)
                if sam_norm_url != our_norm_url:
                    website_action = "mismatch"
                    website_mismatches.append({
                        "company_id": cid,
                        "company_name": our_name,
                        "db_website": our_website,
                        "sam_website": entity_url,
                    })
            else:
                website_action = "fill"  # DB has none, use SAM's

        enrichment_rows.append({
            "company_id":              cid,
            "sam_name":                sam_name,
            "match_type":              match_type,
            "dba":                     dba,
            "sam_cage_code":           cage,
            "sam_registration_status": status,
            "entity_start_date":       start_date,
            "entity_structure":        structure,
            "state_of_incorporation":  state_incorp,
            "sam_business_types":      all_bus_types,
            "physical_address_line1":  addr1,
            "physical_address_line2":  addr2,
            "physical_address_city":   city,
            "physical_address_state":  state,
            "physical_address_zip":    zipcode,
            "physical_address_country": country,
            "sam_website":             entity_url,
            "website_action":          website_action,
            "naics_codes":             naics_codes,
        })

        # POC contacts
        poc1 = make_poc(fields, C_POC1_FIRST, C_POC1_MIDDLE, C_POC1_LAST, C_POC1_TITLE,
                        cid, our_name, "Govt Business POC")
        poc2 = make_poc(fields, C_POC2_FIRST, C_POC2_MIDDLE, C_POC2_LAST, C_POC2_TITLE,
                        cid, our_name, "Alt Govt Business POC")
        if poc1:
            contact_rows.append(poc1)
        if poc2:
            contact_rows.append(poc2)

    # Write enrichment CSV
    enrich_file = OUTPUT_DIR / "sam_enrichment.csv"
    enrich_fields = [
        "company_id", "sam_name", "match_type", "dba", "sam_cage_code",
        "sam_registration_status", "entity_start_date", "entity_structure",
        "state_of_incorporation", "sam_business_types",
        "physical_address_line1", "physical_address_line2", "physical_address_city",
        "physical_address_state", "physical_address_zip", "physical_address_country",
        "sam_website", "website_action", "naics_codes",
    ]
    with open(enrich_file, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=enrich_fields)
        w.writeheader()
        w.writerows(enrichment_rows)
    print(f"\nWrote {len(enrichment_rows)} matched companies to {enrich_file}")

    # Write contacts CSV
    contacts_file = OUTPUT_DIR / "sam_contacts.csv"
    contact_fields = [
        "company_id", "company_name", "full_name", "first_name", "last_name",
        "title", "email", "phone", "linkedin_url", "source", "notes",
    ]
    with open(contacts_file, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=contact_fields)
        w.writeheader()
        w.writerows(contact_rows)
    print(f"Wrote {len(contact_rows)} POC contacts to {contacts_file}")

    # Website mismatch report
    if website_mismatches:
        mismatch_file = OUTPUT_DIR / "sam_website_mismatches.csv"
        with open(mismatch_file, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["company_id", "company_name", "db_website", "sam_website"])
            w.writeheader()
            w.writerows(website_mismatches)
        print(f"Website mismatches: {len(website_mismatches)} — see {mismatch_file}")

    print(f"No SAM match: {len(no_match_names)} companies")

    print("\nSummary:")
    print(f"  Matched:       {len(enrichment_rows)}")
    print(f"  With CAGE:     {sum(1 for r in enrichment_rows if r['sam_cage_code'])}")
    print(f"  Active (A):    {sum(1 for r in enrichment_rows if r['sam_registration_status'] == 'A')}")
    print(f"  Expired (E):   {sum(1 for r in enrichment_rows if r['sam_registration_status'] == 'E')}")
    print(f"  POC contacts:  {len(contact_rows)}")
    print(f"  URL mismatches:{len(website_mismatches)}")
    print(f"  No match:      {len(no_match_names)}")
    print(f"\nImport with:")
    print(f"  cd /Users/dbarta/leads/leads && bin/rails companies:import_sam[{enrich_file}]")
    print(f"  bin/rails contacts:import[{contacts_file}]")


if __name__ == "__main__":
    main()
