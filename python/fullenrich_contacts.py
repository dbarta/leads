#!/usr/bin/env python3
"""
Enrich contacts via FullEnrich waterfall API (20+ providers).

Sends contacts in batches of up to 100; polls for results; writes back to DB.
Lookup method:
  - Contacts with linkedin_url  → use linkedin_url (+ name+domain as fallback)
  - Contacts with company domain → use first_name + last_name + domain

Usage:
  python fullenrich_contacts.py --sample 5              # test 5, no DB writes
  python fullenrich_contacts.py --sample 5 --source sam_gov  # test 5 SAM contacts only
  python fullenrich_contacts.py                         # full run, writes to DB
  python fullenrich_contacts.py --limit 50              # cap at N contacts
  python fullenrich_contacts.py --source pdl            # filter by source
"""

import argparse
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
    """https://www.example.com/path → example.com"""
    if not url:
        return ""
    u = url.lower().strip()
    u = re.sub(r"^https?://", "", u)
    u = re.sub(r"^www\.", "", u)
    u = u.split("/")[0]
    return u


def load_contacts(limit: int = None, source: str = None, skip_disqualified: bool = False) -> list[dict]:
    """Pull enrichable contacts from DB (no email AND no phone)."""
    source_filter = f'.where(source: {json.dumps(source)})' if source else ''
    qual_filter   = ".joins(:company).where.not(companies: {qualification_status: 'No'})" if skip_disqualified else ''
    # Order Yes → Review → other → No so most valuable contacts are enriched first
    order_clause  = "CASE companies.qualification_status WHEN 'Yes' THEN 1 WHEN 'Review' THEN 2 ELSE 3 END, contacts.id"
    code = f"""
contacts = Contact.includes(:company)
  .where(email: [nil, ''])
  .where(phone: [nil, '']){source_filter}{qual_filter}
  .joins(:company)
  .order(Arel.sql("{order_clause}"))

contacts.each do |c|
  website = c.company&.website.to_s
  puts [c.id, c.first_name.to_s, c.last_name.to_s, c.linkedin_url.to_s,
        website, c.source.to_s, c.company&.canonical_name.to_s].join('||')
end
"""
    output = rails(code)
    rows = []
    for line in output.splitlines():
        parts = line.split("||")
        if len(parts) < 7:
            continue
        cid, first, last, li_url, website, src, company_name = parts[:7]
        domain = strip_domain(website)

        has_li          = bool(li_url.strip())
        has_name_domain = bool(first.strip() and last.strip() and domain)

        if not (has_li or has_name_domain):
            continue

        rows.append({
            "contact_id":   int(cid),
            "first_name":   first.strip().title(),
            "last_name":    last.strip().title(),
            "linkedin_url": li_url.strip(),
            "domain":       domain,
            "source":       src.strip(),
            "company_name": company_name.strip(),
        })

    if limit:
        rows = rows[:limit]
    return rows


def build_request_item(c: dict) -> dict:
    item = {
        "enrich_fields": ["contact.work_emails", "contact.personal_emails", "contact.phones"],
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


def poll_results(enrichment_id: str, timeout: int = 600) -> dict:
    print(f"  Polling {enrichment_id} ...", end="", flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(f"{BASE_URL}/contact/enrich/bulk/{enrichment_id}", headers=HEADERS)
        r.raise_for_status()
        data = r.json()
        status = data.get("status")
        if status == "FINISHED":
            print(" done.")
            return data
        if status in ("CANCELED", "CREDITS_INSUFFICIENT", "UNKNOWN"):
            print(f" failed: {status}")
            return data
        print(".", end="", flush=True)
        time.sleep(10)
    print(" timed out — fetching partial results.")
    r = requests.get(f"{BASE_URL}/contact/enrich/bulk/{enrichment_id}",
                     headers=HEADERS, params={"forceResults": "true"})
    r.raise_for_status()
    return r.json()


def extract_best(rec: dict) -> dict:
    """Pull best email + phone from a contact_info block."""
    out = {"email": "", "email_status": "", "phone": "", "found": False}
    ci = rec.get("contact_info") or {}

    we = ci.get("most_probable_work_email") or {}
    pe = ci.get("most_probable_personal_email") or {}
    ph = ci.get("most_probable_phone") or {}

    if we.get("email"):
        out["email"]        = we["email"]
        out["email_status"] = we.get("status", "")
        out["found"] = True
    elif pe.get("email"):
        out["email"]        = pe["email"]
        out["email_status"] = pe.get("status", "")
        out["found"] = True

    if ph.get("number"):
        out["phone"] = ph["number"]
        out["found"] = True

    return out


def write_back(contact_id: int, email: str, phone: str):
    updates = []
    if email:
        updates.append(f"email: {json.dumps(email)}")
    if phone:
        updates.append(f"phone: {json.dumps(phone)}")
    if not updates:
        return
    rails(f'Contact.find({contact_id}).update!({", ".join(updates)})')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=0,
                        help="Test N contacts without writing to DB")
    parser.add_argument("--limit", type=int, default=0,
                        help="Cap total contacts processed (full run)")
    parser.add_argument("--source", default=None,
                        help="Filter by source: sam_gov | pdl | meetleo")
    parser.add_argument("--skip-disqualified", dest="skip_disqualified", action="store_true",
                        help="Skip contacts at companies with qualification_status=No (airlines etc)")
    args = parser.parse_args()

    dry_run = args.sample > 0
    limit   = args.sample if dry_run else (args.limit or None)

    credits_before = get_credits()
    print(f"Credits available: {credits_before}")

    source_label = f" (source={args.source})" if args.source else ""
    print(f"Loading contacts from DB{source_label} ...")
    contacts = load_contacts(limit=limit, source=args.source, skip_disqualified=args.skip_disqualified)
    print(f"  {len(contacts)} enrichable contacts "
          f"({sum(1 for c in contacts if c['linkedin_url'])} with LinkedIn, "
          f"{sum(1 for c in contacts if not c['linkedin_url'])} name+domain only)")

    if not contacts:
        print("Nothing to enrich.")
        return

    if dry_run:
        print(f"\n--- DRY RUN: {len(contacts)} contacts (no DB writes) ---\n")

    batch_size      = 100
    total_found     = 0
    total_processed = 0

    for i in range(0, len(contacts), batch_size):
        batch     = contacts[i:i + batch_size]
        batch_num = i // batch_size + 1
        print(f"\nBatch {batch_num}: {len(batch)} contacts → submitting ...")

        enrichment_id = submit_batch(batch, f"leads-batch-{batch_num}")
        result        = poll_results(enrichment_id)

        credits_used = result.get("cost", {}).get("credits", "?")
        records      = result.get("data", [])
        print(f"  Status: {result.get('status')} | Credits used: {credits_used} | Records: {len(records)}")

        found_in_batch = 0
        for rec in records:
            contact_id = int((rec.get("custom") or {}).get("contact_id", 0))
            inp        = rec.get("input") or {}
            name       = inp.get("full_name") or f"{inp.get('first_name','')} {inp.get('last_name','')}".strip()
            best       = extract_best(rec)

            if best["found"]:
                found_in_batch += 1
                tag = f"({best['email_status']})" if best["email_status"] else ""
                print(f"  ✓ [{contact_id}] {name}: "
                      f"email={best['email'] or '—'}{tag}  phone={best['phone'] or '—'}")
                if not dry_run and contact_id:
                    write_back(contact_id, best["email"], best["phone"])
            else:
                print(f"  · [{contact_id}] {name}: not found")

        total_found     += found_in_batch
        total_processed += len(batch)
        print(f"  Found: {found_in_batch}/{len(batch)} in this batch")

    credits_after = get_credits()
    print(f"\n=== Summary ===")
    print(f"  Processed:    {total_processed}")
    print(f"  Found:        {total_found}")
    print(f"  Credits used: {credits_before - credits_after}  (remaining: {credits_after})")
    if dry_run:
        print("  (Dry run — no DB writes)")


if __name__ == "__main__":
    main()
