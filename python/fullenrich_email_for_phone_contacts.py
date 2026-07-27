#!/usr/bin/env python3
"""
One-off: enrich email addresses for contacts that already have a phone but no email.
Email enrichment costs 0 credits regardless of outcome.
"""
import json, re, subprocess, sys, time
from pathlib import Path
import requests

API_KEY  = "54e1b540-1c6e-494f-a689-d914c8bde1a9"
BASE_URL = "https://app.fullenrich.com/api/v2"
HEADERS  = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
RAILS_ROOT = Path(__file__).parent.parent


def rails(code):
    r = subprocess.run(["bin/rails", "runner", code],
                       capture_output=True, text=True, cwd=RAILS_ROOT)
    if r.returncode != 0:
        print(f"Rails error: {r.stderr[:500]}", file=sys.stderr)
        sys.exit(1)
    return r.stdout.strip()


def strip_domain(url):
    if not url: return ""
    u = re.sub(r"^https?://", "", url.lower().strip())
    u = re.sub(r"^www\.", "", u)
    return u.split("/")[0]


def load_contacts():
    code = """
contacts = Contact.where.not(phone: [nil, '']).where(email: [nil, '']).includes(:company)
contacts.each do |c|
  puts [c.id, c.first_name.to_s, c.last_name.to_s,
        c.linkedin_url.to_s, c.company&.website.to_s,
        c.company&.canonical_name.to_s].join('||')
end
"""
    rows = []
    for line in rails(code).splitlines():
        parts = line.split("||")
        if len(parts) < 6: continue
        cid, first, last, li_url, website, company = parts[:6]
        domain = strip_domain(website)
        if not (li_url.strip() or (first.strip() and last.strip() and domain)):
            continue
        rows.append({"contact_id": int(cid), "first_name": first.strip().title(),
                     "last_name": last.strip().title(), "linkedin_url": li_url.strip(),
                     "domain": domain, "company_name": company.strip()})
    return rows


def build_item(c):
    item = {"enrich_fields": ["contact.work_emails", "contact.personal_emails"],
            "custom": {"contact_id": str(c["contact_id"])}}
    if c["linkedin_url"]:
        item["linkedin_url"] = c["linkedin_url"]
        if c["first_name"] and c["last_name"] and c["domain"]:
            item.update(first_name=c["first_name"], last_name=c["last_name"], domain=c["domain"])
    else:
        item.update(first_name=c["first_name"], last_name=c["last_name"], domain=c["domain"])
    return item


def submit_batch(contacts, name):
    r = requests.post(f"{BASE_URL}/contact/enrich/bulk", headers=HEADERS,
                      json={"name": name, "data": [build_item(c) for c in contacts]})
    if not r.ok:
        print(f"Submit error {r.status_code}: {r.text}", file=sys.stderr); sys.exit(1)
    return r.json()["enrichment_id"]


def poll(eid, timeout=900):
    print(f"  Polling {eid} ...", end="", flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(f"{BASE_URL}/contact/enrich/bulk/{eid}", headers=HEADERS)
        d = r.json(); status = d.get("status")
        if status == "FINISHED": print(" done."); return d
        if status in ("CANCELED", "CREDITS_INSUFFICIENT", "UNKNOWN"):
            print(f" {status}"); return d
        print(".", end="", flush=True); time.sleep(10)
    print(" timed out")
    return requests.get(f"{BASE_URL}/contact/enrich/bulk/{eid}",
                        headers=HEADERS, params={"forceResults": "true"}).json()


def main():
    print("Loading contacts with phone but no email ...")
    contacts = load_contacts()
    print(f"  {len(contacts)} contacts to enrich for email (0 credits cost)")

    if not contacts:
        print("Nothing to enrich."); return

    print(f"\nSubmitting batch of {len(contacts)} ...")
    eid = submit_batch(contacts, "leads-email-for-phone-contacts")
    result = poll(eid)

    records = result.get("data", [])
    print(f"  Status: {result.get('status')} | Records: {len(records)}")

    found = 0
    for rec in records:
        cid = int((rec.get("custom") or {}).get("contact_id", 0))
        if not cid: continue
        ci = rec.get("contact_info") or {}
        we = (ci.get("most_probable_work_email") or {})
        pe = (ci.get("most_probable_personal_email") or {})
        email = we.get("email") or pe.get("email") or ""
        name = (rec.get("input") or {}).get("full_name", f"[{cid}]")
        company = next((c["company_name"] for c in contacts if c["contact_id"] == cid), "")
        if email:
            found += 1
            print(f"  ✓ [{cid}] {name} @ {company}: {email}")
            rails(f'Contact.find({cid}).update!(email: {json.dumps(email)})')
        else:
            print(f"  · [{cid}] {name}: not found")

    print(f"\n=== Summary ===")
    print(f"  Submitted: {len(contacts)}  |  Emails found: {found}  |  Credits used: 0")


if __name__ == "__main__":
    main()
