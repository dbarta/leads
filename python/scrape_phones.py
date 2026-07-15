#!/usr/bin/env python3
"""
Scrape business phone numbers from company websites.

For each company that has a website, visits the homepage and common
contact pages (/, /contact, /about, /contact-us) and extracts the
first US phone number found.

Usage:
  python scrape_phones.py                  # all companies with websites
  python scrape_phones.py --ids 216 222    # specific companies
  python scrape_phones.py --fresh          # ignore checkpoint

Output:
  python/output/phones_YYYYMMDD_HHMMSS.csv

Import:
  bin/rails companies:import_phones[<output_file>]
"""

from __future__ import annotations
import argparse
import csv
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

SCRIPT_DIR = Path(__file__).parent
INPUT_CSV  = SCRIPT_DIR / "companies_for_enrichment.csv"
OUTPUT_DIR = SCRIPT_DIR / "output"
CHECKPOINT = OUTPUT_DIR / "phones_checkpoint.jsonl"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36")
TIMEOUT = 10

# US phone number patterns — matches (555) 867-5309, 555-867-5309, +1 555 867 5309, etc.
PHONE_RE = re.compile(
    r"""(?<!\d)          # not preceded by digit
        (?:\+1[\s.\-]?)? # optional country code
        \(?(\d{3})\)?    # area code
        [\s.\-]          # separator
        (\d{3})          # exchange
        [\s.\-]          # separator
        (\d{4})          # subscriber
        (?!\d)           # not followed by digit
    """,
    re.VERBOSE,
)

# Pages to check in order — stop as soon as a phone is found
CONTACT_PATHS = ["", "/contact", "/contact-us", "/about", "/about-us",
                 "/contact.html", "/about.html", "/contactus"]


def load_checkpoint() -> dict[int, str]:
    result: dict[int, str] = {}
    if not CHECKPOINT.exists():
        return result
    with open(CHECKPOINT) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                result[rec["id"]] = rec["phone"]
            except Exception:
                pass
    return result


def save_checkpoint(company_id: int, phone: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINT, "a") as f:
        f.write(json.dumps({"id": company_id, "phone": phone}) + "\n")


def normalize_url(raw: str) -> str:
    raw = raw.strip()
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    return raw.rstrip("/")


def extract_phone(html: str) -> str:
    """Return the first US phone number found in the HTML, or ''."""
    # Prefer phone: href links (most reliable)
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("tel:"):
            digits = re.sub(r"\D", "", href.replace("tel:", ""))
            if len(digits) == 10:
                return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
            if len(digits) == 11 and digits[0] == "1":
                return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"

    # Fall back to regex scan of visible text
    text = soup.get_text(" ")
    matches = PHONE_RE.findall(text)
    if matches:
        area, exch, sub = matches[0]
        return f"({area}) {exch}-{sub}"

    return ""


def scrape_company(company_id: int, name: str, website: str,
                   session: requests.Session) -> str:
    base = normalize_url(website)
    parsed = urlparse(base)
    if not parsed.netloc:
        return ""

    for path in CONTACT_PATHS:
        url = base + path
        try:
            r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code != 200:
                continue
            phone = extract_phone(r.text)
            if phone:
                return phone
        except Exception:
            pass
        time.sleep(0.3)

    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape business phones from company websites")
    parser.add_argument("--ids",   nargs="*", type=int)
    parser.add_argument("--fresh", action="store_true")
    parser.add_argument("--input", default=str(INPUT_CSV))
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = OUTPUT_DIR / f"phones_{timestamp}.csv"

    with open(args.input) as f:
        rows = [r for r in csv.DictReader(f) if r.get("website", "").strip()]

    if args.ids:
        rows = [r for r in rows if int(r["id"]) in args.ids]

    checkpoint = {} if args.fresh else load_checkpoint()
    pending    = [r for r in rows if int(r["id"]) not in checkpoint]

    print(f"Companies with websites: {len(rows)} total, "
          f"{len(checkpoint)} cached, {len(pending)} to scrape")

    session = requests.Session()
    session.headers["User-Agent"] = UA

    found = 0
    for i, row in enumerate(pending, 1):
        cid     = int(row["id"])
        name    = row["canonical_name"]
        website = row["website"]
        print(f"[{i}/{len(pending)}] {name}  ({website})", end="  ", flush=True)

        phone = scrape_company(cid, name, website, session)
        save_checkpoint(cid, phone)
        checkpoint[cid] = phone

        if phone:
            print(f"☎ {phone}")
            found += 1
        else:
            print("—")

    # Write CSV of all results (cached + newly scraped)
    with open(out_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "canonical_name", "phone"])
        for row in rows:
            cid = int(row["id"])
            writer.writerow([cid, row["canonical_name"], checkpoint.get(cid, "")])

    with_phone = sum(1 for v in checkpoint.values() if v)
    print(f"\nFound phones: {found} new  |  {with_phone} total")
    print(f"Output: {out_file}")
    print(f"\nImport: bin/rails companies:import_phones[{out_file}]")


if __name__ == "__main__":
    main()
