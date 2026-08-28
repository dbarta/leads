#!/usr/bin/env python3
"""
Find, enrich, and verify contacts at SFO-linked companies.

Single-pass pipeline:
  1. FullEnrich people search → find CA-based managers at SFO companies
  2. FullEnrich bulk enrich   → get email + phone for each person found
  3. Twilio CNAM verify       → validate phone is active
  4. Import to DB             → only contacts with a verified phone

Usage:
  python fullenrich_find_sfo_contacts.py              # dry run (no DB writes)
  python fullenrich_find_sfo_contacts.py --import     # run full pipeline + write verified contacts
  python fullenrich_find_sfo_contacts.py --airport-id 1671

Requires env vars for Twilio:
  TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from extractors.title_filter import should_keep_contact  # noqa: E402

RAILS_ROOT = Path(__file__).parent.parent

FE_API_KEY  = "54e1b540-1c6e-494f-a689-d914c8bde1a9"
FE_BASE_URL = "https://app.fullenrich.com/api/v2"
FE_HEADERS  = {"Authorization": f"Bearer {FE_API_KEY}", "Content-Type": "application/json"}

TWILIO_SID   = os.environ.get("TWILIO_ACCOUNT_SID")
TWILIO_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")

TARGET_SENIORITY = ["Owner", "Founder", "C-level", "VP", "Director", "Manager"]
TARGET_TITLES = [
    "President", "CEO", "Chief Executive",
    "Owner", "Founder",
    "General Manager", "Managing Director",
    "Station Manager", "Station Director",
    "Airport Manager", "Airport Director",
    "Ground Operations Manager", "Ground Operations Director",
    "Cargo Manager", "Cargo Director",
    "Ramp Manager", "Ramp Director",
    "VP Operations", "Vice President Operations",
    "Director of Operations", "Operations Director",
    "Regional Manager", "Regional Director",
    "Country Manager", "District Manager",
    "CFO", "Chief Financial",
]

CA_TERMS = ["california", "san francisco", "san mateo", "burlingame",
            "millbrae", "san bruno", "south san francisco", "brisbane",
            "daly city", "san jose", "oakland", "bay area"]
CA_ABBREV_RE = re.compile(r"\bca\b")

PARENT_DOMAIN_THRESHOLD = 500


# ── Utilities ──────────────────────────────────────────────────────────────

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


def strip_domain(url: str) -> str:
    u = (url or "").lower().strip()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    return u.split("/")[0]


def fe_credits() -> float:
    r = requests.get(f"{FE_BASE_URL}/account/credits", headers=FE_HEADERS)
    r.raise_for_status()
    return r.json().get("balance", 0)


# ── Step 1: FullEnrich people search ───────────────────────────────────────

def get_airport_id_by_iata(iata: str) -> int:
    out = rails(f"a = Airport.find_by(iata_code: '{iata.upper()}'); puts a ? a.id : 'NOT_FOUND'")
    out = out.strip()
    if out == "NOT_FOUND":
        raise SystemExit(f"Airport with IATA code '{iata}' not found in DB")
    return int(out)


def get_airport_companies(airport_id: int) -> list[dict]:
    out = rails(f"""
AirportCompanyRelationship
  .where(airport_id: {airport_id}, active: true)
  .joins(:company)
  .where.not(companies: {{website: [nil, '']}})
  .where(companies: {{is_airline: false}})
  .distinct
  .each do |r|
    c = r.company
    puts [c.id, c.canonical_name, c.website].join('||')
  end
""")
    companies, seen = [], set()
    for line in out.splitlines():
        parts = line.split("||", 2)
        if len(parts) == 3:
            domain = strip_domain(parts[2])
            if domain and domain not in seen:
                seen.add(domain)
                companies.append({"id": int(parts[0]), "name": parts[1], "domain": domain})
    return companies


def search_people(domain: str) -> tuple[list[dict], float, int]:
    payload = {
        "limit": 15,
        "current_company_domains": [{"value": domain, "exact_match": True}],
        "current_position_seniority_level": [
            {"value": s, "exact_match": True} for s in TARGET_SENIORITY
        ],
        "current_position_titles": [
            {"value": t, "exact_match": False} for t in TARGET_TITLES
        ],
    }
    r = requests.post(f"{FE_BASE_URL}/people/search", headers=FE_HEADERS, json=payload)
    if not r.ok:
        print(f"    FE search error {r.status_code}: {r.text[:200]}")
        return [], 0.0, 0
    data = r.json()
    return data.get("people", []), data.get("metadata", {}).get("credits", 0), data.get("metadata", {}).get("total", 0)


def format_person(p: dict, company_id: int, company_name: str, domain: str) -> dict:
    emp = p.get("employment", {}).get("current", {})
    li  = p.get("social_profiles", {}).get("professional_network", {})
    loc = p.get("location", {})
    city, region = (loc.get("city") or ""), (loc.get("region") or "")
    return {
        "company_id":   company_id,
        "company_name": company_name,
        "domain":       domain,
        "full_name":    p.get("full_name", ""),
        "first_name":   p.get("first_name", ""),
        "last_name":    p.get("last_name", ""),
        "title":        emp.get("title", ""),
        "linkedin_url": li.get("url", ""),
        "city":         city,
        "region":       region,
        "location_str": f"{city}, {region}".strip(", "),
    }


def is_california(p: dict) -> bool:
    loc = f"{p['city']} {p['region']}".lower()
    if not loc.strip():
        return True
    if any(term in loc for term in CA_TERMS):
        return True
    return bool(CA_ABBREV_RE.search(loc))


def collect_candidates(airport_id: int) -> list[dict]:
    companies = get_airport_companies(airport_id)
    print(f"  {len(companies)} companies with a domain")

    candidates = []
    for c in companies:
        print(f"  {c['name']}  ({c['domain']})")
        people, credits_used, total_in_db = search_people(c["domain"])
        time.sleep(0.3)

        if not people:
            print(f"    → no results  [{credits_used} credits]")
            continue
        if total_in_db > PARENT_DOMAIN_THRESHOLD:
            print(f"    ⚠ {total_in_db} total in DB — large parent domain")

        formatted   = [format_person(p, c["id"], c["name"], c["domain"]) for p in people]
        title_kept  = [p for p in formatted if should_keep_contact(p["title"])]
        ca_people   = [p for p in title_kept if is_california(p)]
        non_ca      = [p for p in title_kept if not is_california(p)]

        if non_ca:
            print(f"    ↷ non-CA skipped ({len(non_ca)}): "
                  + ", ".join(f"{p['full_name']} ({p['location_str']})" for p in non_ca[:3]))
        if ca_people:
            print(f"    → {len(ca_people)} CA candidates  [{credits_used} credits]")
            for p in ca_people:
                loc = f" [{p['location_str']}]" if p["location_str"] else " [location unknown]"
                print(f"       {p['full_name']:<30} {p['title']:<40}{loc}")
        else:
            print(f"    → 0 CA candidates after filters  [{credits_used} credits]")

        candidates.extend(ca_people)
    return candidates


# ── Step 2: FullEnrich bulk enrich ─────────────────────────────────────────

def build_enrich_item(p: dict) -> dict:
    item = {
        "enrich_fields": ["contact.work_emails", "contact.personal_emails", "contact.phones"],
        "custom": {"idx": p["_idx"]},
    }
    if p["linkedin_url"]:
        item["linkedin_url"] = p["linkedin_url"]
        if p["first_name"] and p["last_name"] and p["domain"]:
            item["first_name"] = p["first_name"]
            item["last_name"]  = p["last_name"]
            item["domain"]     = p["domain"]
    elif p["first_name"] and p["last_name"] and p["domain"]:
        item["first_name"] = p["first_name"]
        item["last_name"]  = p["last_name"]
        item["domain"]     = p["domain"]
    return item


def submit_batch(candidates: list[dict]) -> str:
    payload = {
        "name": f"sfo-contacts-{int(time.time())}",
        "data": [build_enrich_item(p) for p in candidates],
    }
    r = requests.post(f"{FE_BASE_URL}/contact/enrich/bulk", headers=FE_HEADERS, json=payload)
    if not r.ok:
        print(f"Enrich submit error {r.status_code}: {r.text}", file=sys.stderr)
        sys.exit(1)
    return r.json()["enrichment_id"]


def poll_results(enrichment_id: str, timeout: int = 600) -> list[dict]:
    print(f"  Polling enrichment {enrichment_id} ...", end="", flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(f"{FE_BASE_URL}/contact/enrich/bulk/{enrichment_id}", headers=FE_HEADERS)
        r.raise_for_status()
        data = r.json()
        if data.get("status") == "FINISHED":
            print(" done.")
            return data.get("data", [])
        if data.get("status") in ("CANCELED", "CREDITS_INSUFFICIENT"):
            print(f" failed: {data['status']}")
            return []
        print(".", end="", flush=True)
        time.sleep(10)
    print(" timed out.")
    return []


def extract_best(rec: dict) -> dict:
    ci = rec.get("contact_info") or {}
    we = ci.get("most_probable_work_email") or {}
    pe = ci.get("most_probable_personal_email") or {}
    ph = ci.get("most_probable_phone") or {}
    out = {"email": "", "email_status": "", "phone": ""}
    if we.get("email"):
        out["email"]        = we["email"]
        out["email_status"] = we.get("status", "")
    elif pe.get("email"):
        out["email"]        = pe["email"]
        out["email_status"] = pe.get("status", "")
    if ph.get("number"):
        out["phone"] = ph["number"]
    return out


# ── Step 3: Twilio verify ──────────────────────────────────────────────────

def twilio_verify(phone: str) -> dict:
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10:
        digits = "1" + digits
    e164 = f"+{digits}"
    r = requests.get(
        f"https://lookups.twilio.com/v2/PhoneNumbers/{e164}",
        params={"Fields": "caller_name"},
        auth=HTTPBasicAuth(TWILIO_SID, TWILIO_TOKEN),
    )
    data = r.json()
    caller = data.get("caller_name") or {}
    name = (caller.get("caller_name") or "").strip().title() or None
    return {"valid": data.get("valid", False), "registered_name": name}


# ── Step 4: Write to DB ────────────────────────────────────────────────────

def write_contact(p: dict, email: str, phone: str, phone_verified: bool, registered_name: str, run_id: int = 2):
    full  = json.dumps(p["full_name"])
    first = json.dumps(p["first_name"])
    last  = json.dumps(p["last_name"])
    title = json.dumps(p["title"])
    li    = json.dumps(p["linkedin_url"])
    em    = json.dumps(email)
    ph    = json.dumps(phone)
    reg   = json.dumps(registered_name or "")
    pv    = "true" if phone_verified else "false"
    lookup = f"linkedin_url: {li}" if p["linkedin_url"] else f"full_name: {full}"
    rails(f"""
c = Contact.find_or_initialize_by(company_id: {p['company_id']}, {lookup})
c.assign_attributes(
  full_name:              {full},
  first_name:             {first},
  last_name:              {last},
  title:                  {title},
  linkedin_url:           {li},
  email:                  {em},
  phone:                  {ph},
  phone_verified:         {pv},
  phone_registered_name:  {reg},
  source:                 'fullenrich_sfo',
  run_id:                 {run_id},
)
c.save!
company = Company.find({p['company_id']})
company.update!(run_id: {run_id}) if company.run_id.nil?
""")


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    id_group = parser.add_mutually_exclusive_group()
    id_group.add_argument("--airport", metavar="IATA", help="Airport IATA code (e.g. OAK)")
    id_group.add_argument("--airport-id", type=int, default=None,
                          help="Airport DB id (default: SFO=1671)")
    parser.add_argument("--run-id", type=int, default=2, help="Run ID to tag contacts (default: 2)")
    parser.add_argument("--import", dest="do_import", action="store_true",
                        help="Write verified contacts to DB")
    args = parser.parse_args()

    if args.airport:
        airport_id = get_airport_id_by_iata(args.airport)
        print(f"Airport {args.airport.upper()} → DB id {airport_id}")
    else:
        airport_id = args.airport_id if args.airport_id is not None else 1671

    twilio_ok = bool(TWILIO_SID and TWILIO_TOKEN)
    print(f"Twilio: {'enabled ($0.01/phone)' if twilio_ok else 'NOT SET — phones will not be verified'}")
    if not twilio_ok:
        print("  Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN to enable verification.")

    credits_before = fe_credits()
    print(f"FullEnrich credits: {credits_before}\n")

    # Step 1: search
    print("── Step 1: FullEnrich people search ──")
    candidates = collect_candidates(airport_id)
    if not candidates:
        print("\nNo candidates found.")
        return

    # Tag each with an index for matching enrich results back
    for i, p in enumerate(candidates):
        p["_idx"] = str(i)

    # Skip candidates already in DB with a phone
    all_names = " | ".join(p["full_name"] for p in candidates)
    existing_with_phone = set()
    for p in candidates:
        parts = p["full_name"].split()
        if len(parts) >= 2:
            result = rails(f"""
c = Contact.where("full_name ILIKE ?", "%{parts[0]}%{parts[-1]}%").where.not(phone: [nil, '']).first
puts c ? "yes" : "no"
""")
            if result.strip() == "yes":
                existing_with_phone.add(p["full_name"])

    if existing_with_phone:
        print(f"\n  Skipping {len(existing_with_phone)} already in DB with phone: "
              + ", ".join(existing_with_phone))

    enrichable = [
        p for p in candidates
        if p["full_name"] not in existing_with_phone
        and (p["linkedin_url"] or (p["first_name"] and p["last_name"]))
    ]
    print(f"\nTotal CA candidates: {len(candidates)}  ({len(enrichable)} to enrich, {len(existing_with_phone)} skipped — already have phone)")

    if not enrichable:
        print("Nothing to enrich.")
        return

    # Step 2: bulk enrich
    print("\n── Step 2: FullEnrich bulk enrich ──")
    print(f"  Submitting {len(enrichable)} contacts ...")
    enrichment_id = submit_batch(enrichable)
    records = poll_results(enrichment_id)

    # Map results back by idx
    idx_map = {p["_idx"]: p for p in enrichable}
    enriched = {}  # idx → {email, phone}
    for rec in records:
        idx = str((rec.get("custom") or {}).get("idx", ""))
        enriched[idx] = extract_best(rec)

    # Step 3: Twilio verify + decide
    print("\n── Step 3: Twilio verification ──")
    verified_contacts = []
    for p in enrichable:
        best = enriched.get(p["_idx"], {})
        phone = best.get("phone", "")
        email = best.get("email", "")
        name  = p["full_name"]

        if not phone:
            print(f"  · {name:<35} no phone found (email={email or '—'})")
            continue

        if not twilio_ok:
            print(f"  ? {name:<35} phone={phone}  (Twilio not configured — skipping)")
            continue

        result = twilio_verify(phone)
        tag = "✓" if result["valid"] else "✗"
        print(f"  {tag} {name:<35} phone={phone}  valid={result['valid']}  name={result['registered_name'] or '—'}")

        if result["valid"]:
            verified_contacts.append({
                **p,
                "email":            email,
                "phone":            phone,
                "phone_verified":   True,
                "registered_name":  result["registered_name"],
            })

    # Summary
    credits_after = fe_credits()
    print(f"\n── Summary ──")
    print(f"  Candidates found:    {len(candidates)}")
    print(f"  Enriched:            {len(enrichable)}")
    print(f"  With phone:          {sum(1 for p in enrichable if enriched.get(p['_idx'], {}).get('phone'))}")
    print(f"  Phone verified (✓):  {len(verified_contacts)}")
    print(f"  FullEnrich credits used: {credits_before - credits_after:.2f}  (remaining: {credits_after:.2f})")

    if not verified_contacts:
        print("\nNo contacts with verified phones — nothing to import.")
        return

    print(f"\nContacts to import ({len(verified_contacts)}):")
    for p in verified_contacts:
        print(f"  {p['full_name']:<35} {p['title']:<35} {p['company_name']}")

    # Step 4: import
    if args.do_import:
        print(f"\n── Step 4: Writing {len(verified_contacts)} contacts to DB ──")
        for p in verified_contacts:
            write_contact(p, p["email"], p["phone"], p["phone_verified"], p["registered_name"], run_id=args.run_id)
            print(f"  ✓ {p['full_name']} ({p['company_name']})")
        print("Done.")
    else:
        print(f"\n  Re-run with --import to write {len(verified_contacts)} verified contacts to DB")


if __name__ == "__main__":
    main()
