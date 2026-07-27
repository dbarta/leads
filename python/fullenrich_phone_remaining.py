#!/usr/bin/env python3
"""
One-off script: phone enrichment for the remaining 60 contacts.
Queries contacts missing phone, not in already-tried list, meeting criteria.
Submits phone-only to FullEnrich and saves results to DB.
"""

import json
import re
import subprocess
import sys
import time
from pathlib import Path

import requests

API_KEY  = "54e1b540-1c6e-494f-a689-d914c8bde1a9"
BASE_URL = "https://app.fullenrich.com/api/v2"
HEADERS  = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

RAILS_ROOT = Path(__file__).parent.parent

ALREADY_TRIED = [
    7, 9, 10, 141, 142, 158, 159, 161, 162, 165,
    143, 144, 145, 146, 167, 168, 169, 170, 171, 172, 173, 174, 175, 176, 178, 179, 180, 181,
    183, 184, 185, 186, 187, 188, 189, 190, 191, 192, 197, 198, 231, 232, 233, 234, 235,
    246, 247, 248, 259, 260, 263, 264, 285, 286, 287, 288, 289, 290, 291, 292,
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
    u = u.split("/")[0]
    return u


def load_contacts() -> list[dict]:
    already_ids = json.dumps(ALREADY_TRIED)
    code = f"""
contacts = Contact.joins(:company)
  .where.not(companies: {{ qualification_status: 'No' }})
  .where.not(companies: {{ is_airline: true }})
  .where('companies.canonical_name NOT ILIKE ?', '%bank%')
  .where('(companies.naics_codes NOT ILIKE ? OR companies.naics_codes IS NULL)', '522%')
  .where(Arel.sql('COALESCE(companies.employee_max, companies.employee_min) BETWEEN 1 AND 10000'))
  .where(phone: [nil, ''])
  .where.not(id: {already_ids})
  .includes(:company)
  .order(Arel.sql("CASE companies.qualification_status WHEN 'Yes' THEN 1 WHEN 'Review' THEN 2 ELSE 3 END, contacts.id"))

contacts.each do |c|
  puts [c.id, c.first_name.to_s, c.last_name.to_s, c.linkedin_url.to_s,
        c.company&.website.to_s, c.company&.canonical_name.to_s].join('||')
end
"""
    output = rails(code)
    rows = []
    for line in output.splitlines():
        parts = line.split("||")
        if len(parts) < 6:
            continue
        cid, first, last, li_url, website, company_name = parts[:6]
        domain = strip_domain(website)

        has_li          = bool(li_url.strip())
        has_name_domain = bool(first.strip() and last.strip() and domain)

        if not (has_li or has_name_domain):
            print(f"  Skipping [{cid}] {first} {last} @ {company_name} — no LinkedIn or domain", file=sys.stderr)
            continue

        rows.append({
            "contact_id":   int(cid),
            "first_name":   first.strip().title(),
            "last_name":    last.strip().title(),
            "linkedin_url": li_url.strip(),
            "domain":       domain,
            "company_name": company_name.strip(),
        })
    return rows


def build_request_item(c: dict) -> dict:
    item = {
        "enrich_fields": ["contact.phones", "contact.work_emails", "contact.personal_emails"],
        "custom": {"contact_id": str(c["contact_id"])},
    }
    if c["linkedin_url"]:
        item["linkedin_url"] = c["linkedin_url"]
        if c["first_name"] and c["last_name"] and c["domain"]:
            item["first_name"] = c["first_name"]
            item["last_name"]  = c["last_name"]
            item["domain"]     = c["domain"]
    else:
        item["first_name"] = c["first_name"]
        item["last_name"]  = c["last_name"]
        item["domain"]     = c["domain"]
    return item


def submit_batch(contacts: list[dict], batch_name: str) -> str:
    payload = {
        "name": batch_name,
        "data": [build_request_item(c) for c in contacts],
    }
    r = requests.post(f"{BASE_URL}/contact/enrich/bulk", headers=HEADERS, json=payload)
    if not r.ok:
        print(f"Submit error {r.status_code}: {r.text}", file=sys.stderr)
        sys.exit(1)
    return r.json()["enrichment_id"]


def poll_results(enrichment_id: str, timeout: int = 900) -> dict:
    print(f"  Polling {enrichment_id} ...", end="", flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(f"{BASE_URL}/contact/enrich/bulk/{enrichment_id}", headers=HEADERS)
        # Don't raise on 402 — response body still has data
        data = r.json()
        status = data.get("status")
        if status == "FINISHED":
            print(" done.")
            return data
        if status in ("CANCELED", "CREDITS_INSUFFICIENT", "UNKNOWN"):
            print(f" {status} — reading partial results.")
            return data
        print(".", end="", flush=True)
        time.sleep(10)
    print(" timed out — fetching with forceResults.")
    r = requests.get(f"{BASE_URL}/contact/enrich/bulk/{enrichment_id}",
                     headers=HEADERS, params={"forceResults": "true"})
    return r.json()


def write_phone(contact_id: int, phone: str):
    rails(f'Contact.find({contact_id}).update!(phone: {json.dumps(phone)})')


def main():
    credits_before = get_credits()
    print(f"Credits available: {credits_before}")

    print("Loading contacts ...")
    contacts = load_contacts()
    print(f"  {len(contacts)} contacts to enrich "
          f"({sum(1 for c in contacts if c['linkedin_url'])} LinkedIn, "
          f"{sum(1 for c in contacts if not c['linkedin_url'])} name+domain)")

    if not contacts:
        print("Nothing to enrich.")
        return

    # Single batch (60 contacts, well under 100 limit)
    print(f"\nSubmitting batch of {len(contacts)} contacts ...")
    enrichment_id = submit_batch(contacts, "leads-phones-remaining")
    result = poll_results(enrichment_id)

    status  = result.get("status")
    records = result.get("data", [])
    credits_used = result.get("cost", {}).get("credits", "?")
    print(f"  Status: {status} | Credits used: {credits_used} | Records: {len(records)}")

    # Build lookup by contact_id for ordering
    id_to_contact = {c["contact_id"]: c for c in contacts}

    found = 0
    not_found = 0
    for rec in records:
        contact_id = int((rec.get("custom") or {}).get("contact_id", 0))
        if not contact_id:
            continue
        inp  = rec.get("input") or {}
        name = inp.get("full_name") or f"{inp.get('first_name','')} {inp.get('last_name','')}".strip()
        ci    = (rec.get("contact_info") or {})
        ph    = (ci.get("most_probable_phone") or {})
        we    = (ci.get("most_probable_work_email") or {})
        pe    = (ci.get("most_probable_personal_email") or {})
        phone = ph.get("number", "")
        email = we.get("email") or pe.get("email") or ""

        if phone or email:
            found += 1
            company = id_to_contact.get(contact_id, {}).get("company_name", "")
            print(f"  ✓ [{contact_id}] {name} @ {company}: phone={phone or '—'}  email={email or '—'}")
            if phone:
                write_phone(contact_id, phone)
            if email:
                rails(f'Contact.find({contact_id}).update!(email: {json.dumps(email)})')
        else:
            not_found += 1
            print(f"  · [{contact_id}] {name}: not found")

    credits_after = get_credits()
    print(f"\n=== Summary ===")
    print(f"  Submitted:    {len(contacts)}")
    print(f"  Found:        {found}")
    print(f"  Not found:    {not_found}")
    print(f"  Credits used: {credits_before - credits_after}  (remaining: {credits_after})")


if __name__ == "__main__":
    main()
