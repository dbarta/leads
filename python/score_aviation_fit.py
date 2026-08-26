#!/usr/bin/env python3
"""
Score 561720 (Janitorial) companies for aviation relevance.

A 561720 company is aviation-relevant if it cleans aircraft cabins, galleys,
or provides ground support cleaning at airports. General office/building
janitors should be excluded.

Scoring signals (0-100):
  Name keywords       0-40   "aviation", "flight", "airline", "cabin", "ramp", etc.
  Domain keywords     0-20   domain contains "avia", "aero", "flight", "air", etc.
  Website content     0-40   homepage/about page mentions aircraft/aviation keywords
  Sourced from airport  +20  bonus if found via airport's own vendor list

Verdict:
  80-100  → aviation      (confident yes — keep)
  50-79   → likely        (probably aviation — keep, worth a manual glance)
  25-49   → review        (unclear — manual review recommended)
  0-24    → skip          (likely not aviation — exclude from pipeline)

Usage:
  python score_aviation_fit.py                    # all 561720 companies in DB
  python score_aviation_fit.py --ids 241 304      # specific company IDs
  python score_aviation_fit.py --no-fetch         # name/domain only, no web requests
  python score_aviation_fit.py --update-db        # set qualification_status=No for skips
  python score_aviation_fit.py --csv FILE         # score companies from a CSV (pre-import)
"""

from __future__ import annotations
import argparse
import csv
import re
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

RAILS_ROOT = Path(__file__).parent.parent
REQUEST_TIMEOUT = 10
DELAY = 0.5  # seconds between web requests

# ── Aviation keyword sets ─────────────────────────────────────────────────────

# Name/domain keywords — strong aviation signals
NAME_STRONG = [
    r"\baviation\b", r"\baircraft\b", r"\bairline\b", r"\baerospace\b",
    r"\bflight\b", r"\bairport\b", r"\bcabin\b", r"\bgalley\b",
    r"\bramp\b", r"\bjet\b", r"\baero\b", r"\bair\s+serv", r"\bairserv\b",
    r"\bground\s+serv", r"\bground\s+support", r"\binflight\b", r"\bin-flight\b",
]
# Name keywords — medium signals (could be non-aviation)
NAME_MEDIUM = [
    r"\bair\b", r"\bfbo\b", r"\bhangar\b", r"\btarmac\b", r"\bterminal\b",
]

# Content keywords — found in website body text
CONTENT_STRONG = [
    "aircraft", "airline", "aviation", "cabin cleaning", "galley", "lavatory",
    "inflight", "in-flight", "ramp", "air carrier", "commercial aviation",
    "seat cleaning", "aircraft interior", "charter flight", "aircraft cabin",
    "aircraft detailing", "aircraft services",
]
CONTENT_MEDIUM = [
    "airport", "terminal", "flight crew", "tarmac", "hangar", "ground handling",
    "fbo", "aerospace", "jet", "airside",
]

# Hard non-aviation signals — if found in content, penalize
CONTENT_NEGATIVE = [
    "office cleaning", "office building", "commercial cleaning",
    "residential", "carpet cleaning", "window cleaning", "floor care",
    "school", "hospital", "hotel", "restaurant", "retail",
    "janitorial service", "maid service", "house cleaning",
]


# ── Scoring ───────────────────────────────────────────────────────────────────

def score_name(name: str) -> tuple[int, list[str]]:
    text = name.lower()
    matched = []
    score = 0
    for pattern in NAME_STRONG:
        if re.search(pattern, text):
            score += 40
            label = pattern.replace("\\b", "").replace("\\", "").replace("(", "").replace(")", "")
            matched.append(f"name:{label}")
            break
    if score == 0:
        for pattern in NAME_MEDIUM:
            if re.search(pattern, text):
                score += 15
                label = pattern.replace("\\b", "").replace("\\", "").replace("(", "").replace(")", "")
                matched.append(f"name:{label}")
                break
    return min(score, 40), matched


def score_domain(website: str) -> tuple[int, list[str]]:
    if not website:
        return 0, []
    domain = urlparse(website if "://" in website else f"https://{website}").netloc.lower()
    domain = domain.replace("www.", "")
    matched = []
    score = 0
    aviation_domain_patterns = [
        "avia", "aero", "flight", "airline", "aircraft", "cabin", "ramp",
        "airserv", "airway", "jetway", "groundserv", "inflight",
    ]
    for pat in aviation_domain_patterns:
        if pat in domain:
            score = 20
            matched.append(f"domain:{pat}")
            break
    return score, matched


def fetch_text(url: str) -> str:
    """Fetch a URL and return cleaned body text. Returns '' on failure."""
    try:
        if "://" not in url:
            url = f"https://{url}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, headers=headers,
                            allow_redirects=True)
        if resp.status_code >= 400:
            return ""
        soup = BeautifulSoup(resp.content, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return " ".join(soup.get_text(" ", strip=True).lower().split())
    except Exception:
        return ""


def score_content(website: str) -> tuple[int, list[str]]:
    """Fetch homepage + /about, score content for aviation keywords."""
    if not website:
        return 0, ["no_website"]

    base = website if "://" in website else f"https://{website}"
    base = base.rstrip("/")

    texts = []
    for path in ["", "/about", "/about-us", "/services"]:
        time.sleep(DELAY)
        text = fetch_text(base + path)
        if text:
            texts.append(text)

    if not texts:
        return 0, ["fetch_failed"]

    combined = " ".join(texts)
    matched = []
    score = 0

    for kw in CONTENT_STRONG:
        if kw in combined:
            score += 15
            matched.append(f"content:{kw}")
            if score >= 40:
                break

    if score < 40:
        for kw in CONTENT_MEDIUM:
            if kw in combined:
                score += 8
                matched.append(f"content:{kw}")
                if score >= 40:
                    break

    # Penalize non-aviation content (only if no strong positive signals)
    if score < 20:
        for kw in CONTENT_NEGATIVE:
            if kw in combined:
                score = max(0, score - 10)
                matched.append(f"negative:{kw}")
                break

    return min(score, 40), matched


def verdict(score: int) -> str:
    if score >= 80:
        return "aviation"
    if score >= 50:
        return "likely"
    if score >= 25:
        return "review"
    return "skip"


def verdict_color(v: str) -> str:
    return {"aviation": "✅", "likely": "🟡", "review": "⚠️ ", "skip": "❌"}.get(v, "?")


# ── DB helpers ────────────────────────────────────────────────────────────────

def rails(code: str) -> str:
    result = subprocess.run(
        ["bin/rails", "runner", code],
        capture_output=True, text=True, cwd=RAILS_ROOT
    )
    real_errors = [l for l in result.stderr.splitlines()
                   if l.strip() and "VIPS" not in l and "libheif" not in l
                   and "x265" not in l and "dlopen" not in l]
    if result.returncode != 0 and real_errors:
        print(f"Rails error: {chr(10).join(real_errors[:5])}", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def load_db_companies(ids: list[int] | None) -> list[dict]:
    if ids:
        id_list = ", ".join(str(i) for i in ids)
        filter_clause = f".where(id: [{id_list}])"
    else:
        filter_clause = ".where('naics_codes ILIKE ?', '%561720%')"

    code = f"""
companies = Company{filter_clause}.order(:canonical_name)
companies.each do |c|
  airport_codes = c.airports.map(&:faa_code).sort.join(',')
  puts [c.id, c.canonical_name, c.website.to_s, airport_codes].join("\\t")
end
"""
    out = rails(code)
    results = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            results.append({
                "id": int(parts[0]),
                "name": parts[1],
                "website": parts[2],
                "airports": parts[3] if len(parts) > 3 else "",
            })
    return results


def load_csv_companies(path: Path) -> list[dict]:
    results = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            naics = row.get("naics_codes", "") or row.get("NAICS", "") or ""
            if "561720" not in naics:
                continue
            results.append({
                "id": None,
                "name": row.get("Legal company name", row.get("canonical_name", "")),
                "website": row.get("Website", row.get("website", "")),
                "airports": row.get("Airport(s) serviced", ""),
                "source": "csv",
            })
    return results


def update_db(company_id: int, new_status: str):
    rails(f'Company.find({company_id}).update!(qualification_status: "{new_status}")')


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Score 561720 companies for aviation relevance")
    parser.add_argument("--ids", nargs="+", type=int, help="Specific company IDs to score")
    parser.add_argument("--no-fetch", action="store_true", help="Skip web fetching (name/domain only)")
    parser.add_argument("--update-db", action="store_true",
                        help="Set qualification_status=No for 'skip' verdicts")
    parser.add_argument("--csv", type=Path, help="Score companies from a CSV file (pre-import)")
    args = parser.parse_args()

    if args.csv:
        companies = load_csv_companies(args.csv)
        print(f"Loaded {len(companies)} 561720 companies from {args.csv}")
    else:
        companies = load_db_companies(args.ids)
        print(f"Loaded {len(companies)} 561720 companies from DB")

    if not companies:
        print("No companies found.")
        return

    results = []
    for c in companies:
        name_score, name_matched = score_name(c["name"])
        domain_score, domain_matched = score_domain(c["website"])

        if args.no_fetch:
            content_score, content_matched = 0, ["fetch_skipped"]
        else:
            content_score, content_matched = score_content(c["website"])

        # Bonus: sourced from airport's official vendor list
        airport_bonus = 20 if c["airports"] else 0

        total = min(100, name_score + domain_score + content_score + airport_bonus)
        v = verdict(total)
        matched = name_matched + domain_matched + content_matched

        results.append({**c, "score": total, "verdict": v, "signals": matched})

        icon = verdict_color(v)
        print(f"{icon} [{total:3d}] {c['name'][:45]:<45}  {c['website'][:35]:<35}  {', '.join(matched[:3])}")

    # Summary
    counts = {v: sum(1 for r in results if r["verdict"] == v)
              for v in ["aviation", "likely", "review", "skip"]}
    print(f"\n{'='*70}")
    print(f"  ✅ aviation: {counts['aviation']}   🟡 likely: {counts['likely']}   "
          f"⚠️  review: {counts['review']}   ❌ skip: {counts['skip']}")
    print(f"{'='*70}")

    skips = [r for r in results if r["verdict"] == "skip"]
    if skips:
        print(f"\nSuggested SKIP (likely not aviation):")
        for r in skips:
            print(f"  [{r['id']}] {r['name']}  —  {r['website'] or 'no website'}")

    if args.update_db and not args.csv:
        print(f"\nUpdating DB: setting qualification_status=No for {len(skips)} skip companies...")
        for r in skips:
            if r["id"]:
                update_db(r["id"], "No")
                print(f"  Set No: [{r['id']}] {r['name']}")
        print("Done.")


if __name__ == "__main__":
    main()
