#!/usr/bin/env python3
"""
Find local management contacts at SFO-linked companies via Apollo people search.

For each company tied to the SFO airport, searches Apollo for people who are:
  - Employed at that company (by domain)
  - Located in the SF Bay Area
  - Holding a decision-maker / station-management title

Prints results for review. No DB writes (add --import to write contacts).

Usage:
  python apollo_find_sfo_contacts.py
  python apollo_find_sfo_contacts.py --import
  python apollo_find_sfo_contacts.py --airport-id 1671
"""

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

RAILS_ROOT = Path(__file__).parent.parent

APOLLO_KEY = "hwc04Ivj4QleZ3ooZl0Wqw"
APOLLO_PEOPLE_URL = "https://api.apollo.io/v1/people/search"
APOLLO_HEADERS = {
    "Content-Type": "application/json",
    "X-Api-Key": APOLLO_KEY,
}

# Bay Area locations covering SFO and surrounding cities
SFO_LOCATIONS = [
    "San Francisco, California, United States",
    "South San Francisco, California, United States",
    "San Mateo, California, United States",
    "Burlingame, California, United States",
    "Millbrae, California, United States",
    "San Bruno, California, United States",
    "Brisbane, California, United States",
    "Daly City, California, United States",
]

# Titles we care about — station/airport operations management level
TARGET_TITLES = [
    "station manager",
    "station director",
    "airport manager",
    "airport director",
    "general manager",
    "managing director",
    "country manager",
    "regional manager",
    "regional director",
    "district manager",
    "director of operations",
    "operations director",
    "vp operations",
    "vice president operations",
    "director of ground",
    "ground operations manager",
    "ramp manager",
    "cargo manager",
    "cargo director",
    "president",
    "ceo",
    "chief executive",
    "owner",
    "founder",
    "principal",
]

# Exclude clearly junior / non-decision titles even if Apollo returns them
EXCLUDE_TITLE_PATTERNS = [
    r"\bagent\b", r"\bhandler\b", r"\bloader\b", r"\bclerk\b",
    r"\btechnician\b", r"\bspecialist\b", r"\bcoordinator\b",
    r"\bsupervisor\b", r"\blead\b", r"\brepresentative\b",
    r"\bstaff\b", r"\bteam member\b", r"\bassociate\b",
]
_EXCLUDE = [re.compile(p, re.IGNORECASE) for p in EXCLUDE_TITLE_PATTERNS]
_TARGET  = [re.compile(re.escape(t), re.IGNORECASE) for t in TARGET_TITLES]


def is_keeper(title: str) -> bool:
    t = (title or "").strip()
    if not t:
        return True  # unknown — let human decide
    if any(p.search(t) for p in _TARGET):
        return True
    if any(p.search(t) for p in _EXCLUDE):
        return False
    return True  # unknown title — keep


def rails(code: str) -> str:
    result = subprocess.run(
        ["bin/rails", "runner", code],
        capture_output=True, text=True, cwd=RAILS_ROOT
    )
    stderr = "\n".join(
        l for l in result.stderr.splitlines()
        if not any(x in l for x in ["VIPS", "libheif", "x265", "dlopen", "Referenced", "Cellar"])
    )
    if result.returncode != 0:
        print(f"Rails error: {stderr[:500]}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def get_sfo_companies(airport_id: int) -> list[dict]:
    """Return companies linked to the given airport that have a website/domain."""
    out = rails(f"""
AirportCompanyRelationship
  .where(airport_id: {airport_id}, active: true)
  .joins(:company)
  .where.not(companies: {{website: [nil, '']}})
  .where(companies: {{is_airline: false}})
  .each do |r|
    c = r.company
    puts [c.id, c.canonical_name, c.website].join('||')
  end
""")
    companies = []
    for line in out.splitlines():
        parts = line.split("||", 2)
        if len(parts) == 3:
            companies.append({
                "id":     int(parts[0]),
                "name":   parts[1],
                "domain": strip_domain(parts[2]),
            })
    return companies


def strip_domain(url: str) -> str:
    u = (url or "").lower().strip()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.split("/")[0]


def apollo_people_search(domain: str) -> list[dict]:
    """Search Apollo for decision-makers at domain in the SFO Bay Area."""
    payload = {
        "page": 1,
        "per_page": 25,
        "organization_domains": [domain],
        "person_locations": SFO_LOCATIONS,
        "person_titles": TARGET_TITLES[:10],  # Apollo accepts up to ~10
    }
    try:
        r = requests.post(APOLLO_PEOPLE_URL, headers=APOLLO_HEADERS, json=payload, timeout=30)
        if not r.ok:
            print(f"    Apollo error {r.status_code}: {r.text[:200]}")
            return []
        data = r.json()
        return data.get("people") or []
    except Exception as e:
        print(f"    Request failed: {e}")
        return []


def format_person(p: dict) -> dict:
    org = (p.get("organization") or {})
    return {
        "full_name":    p.get("name", ""),
        "first_name":   p.get("first_name", ""),
        "last_name":    p.get("last_name", ""),
        "title":        p.get("title", ""),
        "email":        p.get("email", ""),
        "email_status": p.get("email_status", ""),
        "phone":        p.get("sanitized_phone", ""),
        "linkedin_url": p.get("linkedin_url", ""),
        "city":         p.get("city", ""),
        "state":        p.get("state", ""),
        "company_name": org.get("name", ""),
    }


def write_contact(company_id: int, p: dict):
    full  = json.dumps(p["full_name"])
    first = json.dumps(p["first_name"])
    last  = json.dumps(p["last_name"])
    title = json.dumps(p["title"])
    email = json.dumps(p["email"])
    li    = json.dumps(p["linkedin_url"])
    phone = json.dumps(p["phone"])
    lookup = f"linkedin_url: {li}" if p["linkedin_url"] else f"full_name: {full}"
    rails(f"""
c = Contact.find_or_initialize_by(company_id: {company_id}, {lookup})
c.assign_attributes(
  full_name:    {full},
  first_name:   {first},
  last_name:    {last},
  title:        {title},
  email:        {email},
  phone:        {phone},
  linkedin_url: {li},
  source:       'apollo_sfo',
)
c.save!
""")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--airport-id", type=int, default=1671,
                        help="Airport DB id (default: 1671 = SFO)")
    parser.add_argument("--import", dest="do_import", action="store_true",
                        help="Write found contacts to DB")
    args = parser.parse_args()

    print(f"Loading SFO-linked companies (airport_id={args.airport_id})...")
    companies = get_sfo_companies(args.airport_id)
    print(f"  {len(companies)} companies with a domain\n")

    total_kept    = 0
    total_skipped = 0
    no_results    = []

    for c in companies:
        print(f"  {c['name']}  ({c['domain']})")
        people = apollo_people_search(c["domain"])
        time.sleep(0.4)

        if not people:
            print(f"    → no results from Apollo")
            no_results.append(c["name"])
            continue

        formatted = [format_person(p) for p in people]
        kept    = [p for p in formatted if is_keeper(p["title"])]
        skipped = [p for p in formatted if not is_keeper(p["title"])]

        if skipped:
            print(f"    ✂ excluded ({len(skipped)}): "
                  + ", ".join(f"{p['full_name']} ({p['title']})" for p in skipped[:3]))

        if not kept:
            print(f"    → 0 keepers after title filter")
            no_results.append(c["name"])
            continue

        total_kept += len(kept)
        total_skipped += len(skipped)

        for p in kept:
            loc   = f"{p['city']}, {p['state']}" if p["city"] else ""
            email = f" <{p['email']}>" if p["email"] else ""
            print(f"    + {p['full_name']:<30} {p['title']:<40} {loc}{email}")

        if args.do_import:
            for p in kept:
                write_contact(c["id"], p)
            print(f"    → {len(kept)} written to DB")

    print(f"\n{'='*60}")
    print(f"SUMMARY:")
    print(f"  Companies searched: {len(companies)}")
    print(f"  Contacts kept:      {total_kept}")
    print(f"  Contacts excluded:  {total_skipped}")
    if no_results:
        print(f"  No results ({len(no_results)}): {', '.join(no_results)}")
    if not args.do_import and total_kept:
        print(f"\n  Re-run with --import to write contacts to DB")
    print()


if __name__ == "__main__":
    main()
