#!/usr/bin/env python3
"""
Find contacts at companies using FullEnrich's People Search API.

Searches for executives/GMs at companies that have no contacts yet,
returns names + LinkedIn URLs. Does NOT cost enrich credits — just search credits.

Usage:
  python fullenrich_search.py --limit 5     # search 5 companies, print results
  python fullenrich_search.py --limit 20    # search 20 companies
  python fullenrich_search.py --import      # also write found contacts to DB
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from extractors.title_filter import should_keep_contact  # noqa: E402

API_KEY  = "54e1b540-1c6e-494f-a689-d914c8bde1a9"
BASE_URL = "https://app.fullenrich.com/api/v2"
HEADERS  = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

RAILS_ROOT = Path(__file__).parent.parent

# Seniority levels we care about (FullEnrich enum values)
TARGET_SENIORITY = ["Owner", "Founder", "C-level", "VP", "Director", "Manager"]

# Title keywords as a fallback / secondary filter
TARGET_TITLES = [
    "President", "CEO", "Chief Executive",
    "Owner", "Founder",
    "General Manager", "Managing Director",
    "VP Operations", "Vice President Operations",
    "Director of Operations", "Operations Director",
    "CFO", "Chief Financial",
]


def rails(code: str) -> str:
    result = subprocess.run(
        ["bin/rails", "runner", code],
        capture_output=True, text=True, cwd=RAILS_ROOT
    )
    if result.returncode != 0:
        print(f"Rails error: {result.stderr[:500]}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def get_credits() -> int:
    r = requests.get(f"{BASE_URL}/account/credits", headers=HEADERS)
    r.raise_for_status()
    return r.json().get("balance", 0)


def strip_domain(url: str) -> str:
    if not url:
        return ""
    u = url.lower().strip()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.split("/")[0]


def load_companies(limit: int) -> list[dict]:
    """Companies with no contacts that have a website."""
    code = f"""
companies = Company
  .left_joins(:contacts)
  .where(contacts: {{id: nil}})
  .where.not(website: [nil, ''])
  .where(is_airline: false)
  .order(:canonical_name)
  .limit({limit})

companies.each do |c|
  puts [c.id, c.canonical_name, c.website].join('||')
end
"""
    rows = []
    for line in rails(code).splitlines():
        parts = line.split("||")
        if len(parts) < 3:
            continue
        cid, name, website = parts[0], parts[1], parts[2]
        domain = strip_domain(website)
        if domain:
            rows.append({"id": int(cid), "name": name, "domain": domain})
    return rows


PARENT_DOMAIN_THRESHOLD = 500  # if total > this, domain likely belongs to a large parent

def search_people(domain: str) -> tuple[list[dict], float, int]:
    """Search FullEnrich for executives at a given domain. Returns (people, credits_used, total)."""
    payload = {
        "limit": 10,
        "current_company_domains": [{"value": domain, "exact_match": True}],
        "current_position_seniority_level": [
            {"value": s, "exact_match": True} for s in TARGET_SENIORITY
        ],
        "current_position_titles": [
            {"value": t, "exact_match": False} for t in TARGET_TITLES
        ],
    }
    r = requests.post(f"{BASE_URL}/people/search", headers=HEADERS, json=payload)
    if not r.ok:
        print(f"    Search error {r.status_code}: {r.text[:200]}")
        return [], 0.0, 0
    data    = r.json()
    people  = data.get("people", [])
    credits = data.get("metadata", {}).get("credits", 0)
    total   = data.get("metadata", {}).get("total", 0)
    return people, credits, total


def format_person(p: dict) -> dict:
    emp = p.get("employment", {}).get("current", {})
    li  = p.get("social_profiles", {}).get("professional_network", {})
    return {
        "full_name":    p.get("full_name", ""),
        "first_name":   p.get("first_name", ""),
        "last_name":    p.get("last_name", ""),
        "title":        emp.get("title", ""),
        "seniority":    emp.get("seniority", ""),
        "linkedin_url": li.get("url", ""),
        "location":     f"{p.get('location', {}).get('city', '')} {p.get('location', {}).get('region', '')}".strip(),
    }


def write_contacts(company_id: int, people: list[dict]):
    """Write search results to DB as contacts (source=fullenrich_search, no email/phone yet)."""
    for p in people:
        if not p["full_name"]:
            continue
        full  = json.dumps(p["full_name"])
        first = json.dumps(p["first_name"])
        last  = json.dumps(p["last_name"])
        title = json.dumps(p["title"])
        li    = json.dumps(p["linkedin_url"])
        # Use full_name as dedup key when linkedin_url is blank
        lookup_key = f"linkedin_url: {li}" if p["linkedin_url"] else f"full_name: {full}"
        rails(f"""
c = Contact.find_or_initialize_by(company_id: {company_id}, {lookup_key})
c.assign_attributes(
  full_name:    {full},
  first_name:   {first},
  last_name:    {last},
  title:        {title},
  linkedin_url: {li},
  source:       'fullenrich_search',
)
c.save!
""")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5,
                        help="Number of companies to search (default: 5)")
    parser.add_argument("--import", dest="do_import", action="store_true",
                        help="Write found contacts to DB")
    args = parser.parse_args()

    credits_before = get_credits()
    print(f"Credits available: {credits_before}")

    companies = load_companies(args.limit)
    print(f"Searching {len(companies)} companies with no contacts\n")

    total_found   = 0
    total_credits = 0.0

    for c in companies:
        print(f"  {c['name']} ({c['domain']})")
        people, credits_used, total_in_db = search_people(c["domain"])
        total_credits += credits_used

        if not people:
            print(f"    → no results  [{credits_used} credits, {total_in_db} total in DB]")
            continue

        if total_in_db > PARENT_DOMAIN_THRESHOLD:
            print(f"    ⚠ {total_in_db} total — likely a parent company domain, skipping")
            continue

        formatted = [format_person(p) for p in people]

        # Title filter — exclude janitors, ramp agents, etc.
        kept = [p for p in formatted if should_keep_contact(p.get("title", ""))]
        skipped = [p for p in formatted if not should_keep_contact(p.get("title", ""))]
        if skipped:
            print(f"    ✂ title filter excluded: {', '.join(p['full_name'] + ' (' + p['title'] + ')' for p in skipped)}")
        formatted = kept

        total_found += len(formatted)
        print(f"    → {len(formatted)} kept (of {total_in_db} total)  [{credits_used} credits]")

        for p in formatted:
            loc = f"  [{p['location']}]" if p["location"] else ""
            print(f"       {p['full_name']:<30} {p['title']:<40}{loc}")

        if args.do_import:
            write_contacts(c["id"], formatted)
            print(f"    → written to DB")

    credits_after = get_credits()
    spent = credits_before - credits_after
    print(f"\n=== Summary ===")
    print(f"  Companies searched: {len(companies)}")
    print(f"  People found:       {total_found}")
    print(f"  Credits used:       {spent}  (remaining: {credits_after})")
    if not args.do_import and total_found:
        print(f"  Re-run with --import to write contacts to DB")


if __name__ == "__main__":
    main()
