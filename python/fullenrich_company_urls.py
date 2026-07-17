#!/usr/bin/env python3
"""
Find company websites using FullEnrich Company Search API.

For companies in the DB with no website, normalizes their name
and searches FullEnrich to find their domain. Tries multiple name
variants (strip legal suffixes, expand abbreviations) before giving up.

Usage:
  python fullenrich_company_urls.py --sample 5    # dry-run 5 companies
  python fullenrich_company_urls.py --limit 50    # search 50 companies
  python fullenrich_company_urls.py --import       # also write to DB
"""

import argparse
import re
import subprocess
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

import requests

# Throttle to stay under FullEnrich rate limit (~15 req/min)
_CALL_DELAY = 4.0  # seconds between API calls

MIN_SIMILARITY = 0.75  # below this, treat match as a false positive

API_KEY  = "54e1b540-1c6e-494f-a689-d914c8bde1a9"
BASE_URL = "https://app.fullenrich.com/api/v2"
HEADERS  = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

RAILS_ROOT = Path(__file__).parent.parent

# Trailing legal-suffix pattern — strip these before searching.
# Multiple passes to handle "Something, Inc., LLC" etc.
_SUFFIX_RE = re.compile(
    r",?\s+(LLC|L\.L\.C\.|Inc\.?|Incorporated|Ltd\.?|Limited|Corp\.?|"
    r"Corporation|LP|L\.P\.|LLP|L\.L\.P\.|Co\.?|Company|PLC)\s*[,.]?\s*$",
    re.IGNORECASE,
)

# Abbreviations that trip up company-name search engines
_ABBR = [
    (re.compile(r"\bSvcs\b", re.I), "Services"),
    (re.compile(r"\bSvc\b", re.I),  "Service"),
    (re.compile(r"\bIntl\b", re.I), "International"),
    (re.compile(r"\bMgmt\b", re.I), "Management"),
    (re.compile(r"\bMfg\b", re.I),  "Manufacturing"),
    (re.compile(r"\bGrp\b", re.I),  "Group"),
    (re.compile(r"\bOps\b", re.I),  "Operations"),
    (re.compile(r"\bAssoc\b", re.I),"Associates"),
    (re.compile(r"\bDept\b", re.I), "Department"),
    (re.compile(r"\bAdmin\b", re.I),"Administration"),
]


def _strip_suffixes(name: str) -> str:
    """Strip trailing legal suffixes (up to 3 passes for compound suffixes)."""
    for _ in range(3):
        stripped = _SUFFIX_RE.sub("", name).strip().rstrip(",").strip()
        if stripped == name:
            break
        name = stripped
    return name


def normalize_name(name: str) -> str:
    """Return the trade-name form: no legal suffixes, no location parentheticals."""
    # Remove location or modifier in parens: "Acme Cargo (JFK)" → "Acme Cargo"
    name = re.sub(r"\s*\([^)]*\)", "", name).strip()
    # Strip legal suffixes
    name = _strip_suffixes(name)
    # Expand abbreviations
    for pat, repl in _ABBR:
        name = pat.sub(repl, name).strip()
    return " ".join(name.split())


def name_variants(canonical: str) -> list[str]:
    """
    Return name candidates to try, most-specific first.
    Stops as soon as FullEnrich returns a domain.
    """
    norm = normalize_name(canonical)
    candidates = []

    # 1. Normalized name (no suffixes, expanded abbrevs) — usually best
    if norm.lower() != canonical.lower():
        candidates.append(norm)

    # 2. Raw canonical (for companies where legal name IS the trade name)
    candidates.append(canonical)

    # 3. First 3 words of normalized name (for names with 5+ words)
    words = norm.split()
    if len(words) >= 5:
        candidates.append(" ".join(words[:3]))

    # Deduplicate, preserve order
    seen: set[str] = set()
    unique: list[str] = []
    for v in candidates:
        if v.lower() not in seen and v.strip():
            seen.add(v.lower())
            unique.append(v)
    return unique


def _name_sim(a: str, b: str) -> float:
    """Case-insensitive normalized string similarity [0..1]."""
    def norm(s: str) -> str:
        s = _strip_suffixes(s.lower())
        return re.sub(r"[^a-z0-9 ]", " ", s).strip()
    return SequenceMatcher(None, norm(a), norm(b)).ratio()


def search_company(name: str) -> tuple[str, str, float, int]:
    """
    Call FullEnrich company search for a given name.
    Returns (domain, matched_name, similarity, headcount) or ("", "", 0.0, 0).
    """
    payload = {
        "limit": 5,
        "names": [{"value": name, "exact_match": False}],
    }
    time.sleep(_CALL_DELAY)
    r = requests.post(f"{BASE_URL}/company/search", headers=HEADERS,
                      json=payload, timeout=15)
    if r.status_code == 429:
        print("    Rate limited — waiting 65s")
        time.sleep(65)
        r = requests.post(f"{BASE_URL}/company/search", headers=HEADERS,
                          json=payload, timeout=15)
    if not r.ok:
        print(f"    API error {r.status_code}: {r.text[:200]}")
        return "", "", 0.0, 0

    data = r.json()
    companies = data.get("companies") or []
    if not companies:
        return "", "", 0.0, 0

    # Two-character country TLD suffixes that indicate non-US domains.
    # Generic TLDs (.com, .net, .org, .io, .co) are allowed even with no country.
    _FOREIGN_TLDS = re.compile(
        r"\.(br|au|fi|uk|ca|de|fr|nl|se|es|it|pt|mx|co\.id|co\.uk|com\.au|"
        r"com\.br|co\.za|co\.nz|co\.jp|org\.au|net\.au)$", re.I
    )

    def country(c: dict) -> str:
        return (c.get("locations") or {}).get("headquarters", {}).get("country_code", "") or ""

    def is_us_or_unknown(c: dict) -> bool:
        cc = country(c)
        if cc in ("US", "USA"):
            return True
        if cc == "":
            domain = (c.get("domain") or "")
            return not _FOREIGN_TLDS.search(domain)
        return False

    # Only consider US-based or country-unknown-with-generic-TLD companies.
    # Airport service companies are US businesses — non-US matches are false positives.
    us_cos = [c for c in companies[:5] if is_us_or_unknown(c)]

    best_domain = best_matched = ""
    best_sim = 0.0
    best_headcount = 0

    for c in us_cos:
        domain = (c.get("domain") or "").strip()
        matched = c.get("name", "")
        sim = _name_sim(name, matched)
        headcount = c.get("headcount") or 0
        if domain and sim > best_sim:
            best_sim = sim
            best_domain = domain
            best_matched = matched
            best_headcount = headcount

    if best_domain and best_sim >= MIN_SIMILARITY:
        return best_domain, best_matched, best_sim, best_headcount

    # No domain passed threshold — return what we found for diagnostic output
    first = companies[0]
    sim = _name_sim(name, first.get("name", ""))
    return "", first.get("name", ""), sim, 0


def rails(code: str) -> str:
    result = subprocess.run(
        ["bin/rails", "runner", code],
        capture_output=True, text=True, cwd=RAILS_ROOT
    )
    if result.returncode != 0:
        print(f"Rails error: {result.stderr[:500]}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def load_companies(limit: int, offset: int = 0) -> list[dict]:
    """Companies with no website, excluding airlines and concessions."""
    code = f"""
companies = Company
  .where(website: [nil, ''])
  .where(is_airline: false)
  .where(is_concession: false)
  .order(:canonical_name)
  .offset({offset})
  .limit({limit})

companies.each do |c|
  puts [c.id, c.canonical_name].join('||')
end
"""
    rows: list[dict] = []
    for line in rails(code).splitlines():
        parts = line.split("||")
        if len(parts) < 2:
            continue
        rows.append({"id": int(parts[0]), "name": parts[1]})
    return rows


def write_website(company_id: int, url: str):
    url_safe = url.replace("'", "\\'")
    rails(f"Company.find({company_id}).update!(website: '{url_safe}')")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int,
                        help="Dry-run on N companies (no DB writes)")
    parser.add_argument("--limit", type=int, default=20,
                        help="Max companies to search (default: 20)")
    parser.add_argument("--offset", type=int, default=0,
                        help="Skip first N companies (default: 0)")
    parser.add_argument("--import", dest="do_import", action="store_true",
                        help="Write found URLs to DB")
    args = parser.parse_args()

    limit = args.sample if args.sample else args.limit
    dry_run = bool(args.sample)

    companies = load_companies(limit, offset=args.offset)
    print(f"Searching {len(companies)} companies with no website\n")

    found: list[dict] = []
    not_found: list[dict] = []

    for c in companies:
        name = c["name"]
        variants = name_variants(name)

        domain = matched = used_variant = ""
        sim = 0.0
        headcount = 0
        for variant in variants:
            domain, matched, sim, headcount = search_company(variant)
            if domain:
                used_variant = variant
                break

        if domain:
            url = f"https://{domain}" if not domain.startswith("http") else domain
            found.append({**c, "url": url, "domain": domain,
                          "matched": matched, "sim": sim, "variant": used_variant,
                          "headcount": headcount})
            note = f" [via '{used_variant}']" if used_variant != name else ""
            emp_note = f"  ({headcount:,} employees)" if headcount else ""
            print(f"  {name[:50]}{note}")
            print(f"    → {url}  (matched: '{matched}', {sim:.0%}){emp_note}")
            if args.do_import and not dry_run:
                write_website(c["id"], url)
                print(f"    → written to DB")
        else:
            not_found.append(c)
            tried = " / ".join(f"'{v}'" for v in variants[:2])
            no_domain_note = f"  [closest: '{matched}' {sim:.0%}]" if matched else ""
            print(f"  {name[:50]}: not found{no_domain_note}  [tried: {tried}]")

    print(f"\n=== Summary ===")
    print(f"  Found:     {len(found)} / {len(companies)}")
    print(f"  Not found: {len(not_found)}")
    if found and not args.do_import and not dry_run:
        print(f"\n  Re-run with --import to write to DB")
    if dry_run and found:
        print(f"\n  --sample mode: no DB writes. Use --limit {len(companies)} --import to persist.")
    if not_found:
        print(f"\nNot found:")
        for c in not_found:
            print(f"  - {c['name']}")


if __name__ == "__main__":
    main()
