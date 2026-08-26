#!/usr/bin/env python3
"""
Find aviation service companies near an airport using Apollo.io org search.

Usage:
  python apollo_import_companies.py --airport SFO
  python apollo_import_companies.py --airport SFO --import
  python apollo_import_companies.py --airport SFO OAK SJC --import

Steps per airport:
  1. Look up airport city/state from DB
  2. Search Apollo for aviation + facilities services companies in metro area
  3. Filter to target NAICS codes (488190, 488119, 561720)
  4. Compare to existing DB companies
  5. Report new vs. already-known; --import writes new ones to DB
"""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).parent
RAILS_ROOT = SCRIPT_DIR.parent

APOLLO_KEY = "hwc04Ivj4QleZ3ooZl0Wqw"
APOLLO_URL = "https://api.apollo.io/v1/organizations/search"
APOLLO_HEADERS = {
    "Content-Type": "application/json",
    "X-Api-Key": APOLLO_KEY,
}

# Target NAICS code prefixes
TARGET_NAICS_PREFIXES = ("4881", "4882", "56172")
# NAICS codes that indicate the company IS an airport, not a service provider
AIRPORT_NAICS = {"48111", "488111", "921110", "921190"}
# Industries to search
AVIATION_INDUSTRIES   = ["airlines/aviation"]
FACILITIES_INDUSTRIES = ["facilities services", "outsourcing/offshoring"]

# For each airport code, additional nearby cities to include beyond the airport city
METRO_EXTRAS = {
    "SFO": ["South San Francisco", "Millbrae", "Burlingame", "San Bruno", "San Mateo"],
    "LAX": ["El Segundo", "Inglewood", "Hawthorne", "Long Beach"],
    "ORD": ["Schiller Park", "Rosemont", "Des Plaines", "Elk Grove Village"],
    "MDW": ["Chicago", "Oak Lawn", "Bridgeview"],
    "JFK": ["Jamaica", "Queens", "Valley Stream"],
    "OAK": ["Oakland", "San Leandro", "Alameda"],
    "SJC": ["San Jose", "Santa Clara", "Sunnyvale"],
    "SAN": ["San Diego", "National City", "Chula Vista"],
}


def rails(code: str) -> str:
    result = subprocess.run(
        ["bin/rails", "runner", code],
        capture_output=True, text=True, cwd=RAILS_ROOT
    )
    stderr = "\n".join(
        line for line in result.stderr.splitlines()
        if not any(x in line for x in ["VIPS", "libheif", "x265", "dlopen", "Referenced", "Cellar"])
    )
    if result.returncode != 0:
        print(f"Rails error: {stderr[:500]}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def get_airport_info(iata: str) -> dict:
    """Return {city, state, name, id} for an airport IATA code."""
    out = rails(f"""
a = Airport.find_by(iata_code: '{iata.upper()}')
if a
  puts [a.id, a.name, a.city, a.state].join('||')
else
  puts 'NOT_FOUND'
end
""")
    if out == "NOT_FOUND" or not out:
        return {}
    parts = out.split("||")
    return {"id": int(parts[0]), "name": parts[1], "city": parts[2], "state": parts[3]}


def get_existing_companies() -> dict[str, int]:
    """Return {normalized_name: company_id} for all companies in DB."""
    out = rails("Company.all.each { |c| puts [c.id, c.canonical_name].join('||') }")
    result = {}
    for line in out.splitlines():
        parts = line.split("||", 1)
        if len(parts) == 2:
            result[normalize(parts[1])] = int(parts[0])
    return result


def normalize(name: str) -> str:
    """Normalize company name for dedup comparison."""
    name = name.lower().strip()
    name = re.sub(r"\b(inc|llc|ltd|corp|co|lp|plc|dba|the)\b\.?", "", name)
    name = re.sub(r"[^a-z0-9 ]", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def is_target_naics(naics_list: list[str]) -> bool:
    """Return True if any NAICS code matches our targets."""
    for n in naics_list:
        if any(n.startswith(p) for p in TARGET_NAICS_PREFIXES):
            return True
    return False


def is_airport_itself(org: dict) -> bool:
    """Filter out airports and government entities."""
    naics = set(org.get("naics_codes") or [])
    if naics & AIRPORT_NAICS:
        return True
    name = (org.get("name") or "").lower()
    if any(x in name for x in ["international airport", "regional airport", "airport authority"]):
        return True
    return False


def apollo_search(locations: list[str], industries: list[str], pages: int = 3) -> list[dict]:
    """Search Apollo for orgs, return all results across pages."""
    results = []
    for page in range(1, pages + 1):
        payload = {
            "page": page,
            "per_page": 25,
            "organization_locations": locations,
            "organization_industries": industries,
            "organization_num_employees_ranges": ["1,5000"],
        }
        try:
            r = requests.post(APOLLO_URL, headers=APOLLO_HEADERS, json=payload, timeout=30)
            if not r.ok:
                print(f"  Apollo error {r.status_code}: {r.text[:200]}", file=sys.stderr)
                break
            data = r.json()
            orgs = data.get("organizations") or []
            results.extend(orgs)
            total_pages = data.get("pagination", {}).get("total_pages", 1)
            if page >= total_pages:
                break
            time.sleep(0.3)
        except Exception as e:
            print(f"  Apollo request failed: {e}", file=sys.stderr)
            break
    return results


def process_airport(iata: str, existing: dict[str, int], do_import: bool, run_id: int) -> dict:
    iata = iata.upper()
    info = get_airport_info(iata)
    if not info:
        print(f"  Airport {iata} not found in DB")
        return {"found": 0, "new": 0, "existing": 0}

    city  = info["city"].title()
    state = info["state"]
    name  = info["name"]

    # Build location list: airport city + metro extras
    extras = METRO_EXTRAS.get(iata, [])
    locations = list({f"{city}, {state}, United States"} | {f"{c}, {state}, United States" for c in extras})

    print(f"\n{'='*60}")
    print(f"  {iata} — {name}")
    print(f"  Searching near: {', '.join([city] + extras)}")
    print(f"{'='*60}")

    # Search 1: aviation companies
    print("  [1/2] Searching aviation industry...")
    aviation_orgs = apollo_search(locations, AVIATION_INDUSTRIES, pages=5)

    # Search 2: facilities services (for 561720 janitorial)
    print("  [2/2] Searching facilities services industry...")
    facilities_orgs = apollo_search(locations, FACILITIES_INDUSTRIES, pages=3)

    # Combine and deduplicate by Apollo ID
    seen_ids: set[str] = set()
    all_orgs = []
    for org in aviation_orgs + facilities_orgs:
        oid = org.get("id")
        if oid and oid not in seen_ids:
            seen_ids.add(oid)
            all_orgs.append(org)

    print(f"  Total candidates from Apollo: {len(all_orgs)}")

    # Filter: target NAICS + not the airport itself
    filtered = [
        o for o in all_orgs
        if is_target_naics(o.get("naics_codes") or []) and not is_airport_itself(o)
    ]
    print(f"  After NAICS filter (488190/488119/561720): {len(filtered)}")

    new_companies   = []
    known_companies = []

    for org in filtered:
        norm = normalize(org.get("name", ""))
        if norm in existing:
            known_companies.append((org, existing[norm]))
        else:
            new_companies.append(org)

    # Report
    print(f"\n  ALREADY IN DB ({len(known_companies)}):")
    for org, cid in known_companies:
        naics = ", ".join(org.get("naics_codes") or [])
        print(f"    ✓ {org['name']} (db id={cid}) | NAICS: {naics}")

    print(f"\n  NEW COMPANIES ({len(new_companies)}):")
    for org in new_companies:
        naics = ", ".join(org.get("naics_codes") or [])
        emp   = org.get("estimated_num_employees", "?")
        dom   = org.get("primary_domain", "")
        print(f"    + {org['name']} | NAICS: {naics} | {emp} emp | {dom}")

    if do_import and new_companies:
        print(f"\n  Importing {len(new_companies)} new companies...")
        airport_id = info["id"]
        for org in new_companies:
            naics_list = [n for n in (org.get("naics_codes") or [])
                          if any(n.startswith(p) for p in TARGET_NAICS_PREFIXES)]
            naics_str = json.dumps(naics_list[0] if naics_list else "")
            name_str  = json.dumps(org.get("name", ""))
            website   = json.dumps(org.get("primary_domain") or org.get("website_url") or "")

            cid_raw = rails(f"""
c = Company.find_or_initialize_by(canonical_name: {name_str})
if c.new_record?
  c.assign_attributes(
    naics_codes: {naics_str},
    website: {website},
    run_id: {run_id},
    is_airline: false,
  )
  c.save!
  AirportCompanyRelationship.find_or_create_by!(airport_id: {airport_id}, company_id: c.id) do |r|
    r.active = true
    r.source_url = 'apollo_import'
    r.evidence_notes = 'Found via Apollo org search'
  end
  puts c.id
else
  puts "exists:{{c.id}}"
end
""")
            if cid_raw.startswith("exists:"):
                print(f"    (already existed) {org['name']}")
            else:
                print(f"    ✓ Imported: {org['name']} (id={cid_raw.strip()})")
        # Also link already-known companies to this airport
        for org, cid in known_companies:
            rails(f"""
AirportCompanyRelationship.find_or_create_by!(airport_id: {info['id']}, company_id: {cid}) do |r|
  r.active = true
  r.source_url = 'apollo_import'
  r.evidence_notes = 'Found via Apollo org search'
end
""")

    return {"found": len(filtered), "new": len(new_companies), "existing": len(known_companies)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--airport", nargs="+", required=True, help="Airport IATA code(s)")
    parser.add_argument("--import",  dest="do_import", action="store_true",
                        help="Write new companies to DB")
    parser.add_argument("--run-id",  type=int, default=2, help="Run ID to tag new companies (default: 2)")
    args = parser.parse_args()

    print("Loading existing companies from DB...")
    existing = get_existing_companies()
    print(f"  {len(existing)} companies already in DB")

    totals = {"found": 0, "new": 0, "existing": 0}
    for iata in args.airport:
        result = process_airport(iata, existing, args.do_import, args.run_id)
        for k in totals:
            totals[k] += result[k]

    print(f"\n{'='*60}")
    print(f"SUMMARY across {len(args.airport)} airport(s):")
    print(f"  Candidates matching target NAICS: {totals['found']}")
    print(f"  Already in DB:                    {totals['existing']}")
    print(f"  New companies:                    {totals['new']}")
    if not args.do_import and totals["new"]:
        print(f"\n  Re-run with --import to add new companies to DB")
    print()


if __name__ == "__main__":
    main()
