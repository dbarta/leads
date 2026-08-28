#!/usr/bin/env python3
"""
Discover aviation service providers at airports by scraping airport websites.

For each airport:
  1. Tries known pages (from config) that have published vendor/FBO lists
  2. Falls back to standard URL patterns on the airport's site
  3. Extracts company names via Claude API (if ANTHROPIC_API_KEY set) or heuristics
  4. Matches against existing DB companies
  5. Reports new vs already known; --import writes to DB

If ANTHROPIC_API_KEY is set, uses claude-haiku-4-5 for accurate extraction.
Otherwise falls back to regex/keyword heuristics (less accurate but free).

Usage:
  python discover_airport_companies.py --airport OAK SJC SMF FAT SAN SNA BUR ONT
  python discover_airport_companies.py --airport OAK --import
  python discover_airport_companies.py --airport SMF --dry-run
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
from bs4 import BeautifulSoup

RAILS_ROOT = Path(__file__).parent.parent
TIMEOUT = 15
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

# ── Airport config ────────────────────────────────────────────────────────────
# Maps IATA → {site, pages:[confirmed working URLs with vendor/FBO lists]}
# Pages discovered via manual research 2026-08-27.
AIRPORT_CONFIG = {
    "OAK": {
        "site": "https://www.iflyoak.com",
        "pages": [
            "https://www.iflyoak.com/visit/education/general-aviation/fixed-base-operators/",
            "https://www.iflyoak.com/visit/education/general-aviation/aircraft-maintenance-training/",
        ],
    },
    "SJC": {
        "site": "https://www.flysanjose.com",
        "pages": [
            "https://www.flysanjose.com/business/sjc-general-aviation/fbo",
        ],
    },
    "SMF": {
        "site": "https://flysmf.gov",
        "pages": [
            "https://flysmf.gov/about/pilot-information",  # Complete Aviation Support Services list
        ],
    },
    "FAT": {
        "site": "https://www.flyfresno.com",  # DNS dead as of 2026-08-27
        "pages": [],
        # Signature + Atlantic + Menzies covered by KNOWN_PROVIDERS
    },
    "SAN": {
        "site": "https://www.san.org",
        "pages": [
            "https://www.san.org/general-aviation-and-charter-services",
        ],
        "companies": [
            # Alliance Ground International (formerly ATS) — confirmed via Google 2026-08-27
            {"name": "Alliance Ground International", "website": "https://www.alliancegroundintl.com/",
             "phone": "314-739-1900"},
        ],
    },
    "SNA": {
        "site": "https://www.ocair.com",
        "pages": [
            "https://www.ocair.com/business/general-aviation/services",  # Full list with contacts
        ],
    },
    "BUR": {
        "site": "https://www.hollywoodburbankairport.com",
        "pages": [],
        "companies": [
            # Hollywood Burbank Jet Center — local FBO, confirmed via Google 2026-08-27
            {"name": "Hollywood Burbank Jet Center", "website": "https://hollywoodburbankjetcenter.com/",
             "phone": None},
        ],
    },
    "ONT": {
        "site": "https://www.flyontario.com",
        "pages": [],  # Cloudflare blocks scraping
        "companies": [
            # Guardian Jet Center — confirmed via Google 2026-08-27
            {"name": "Guardian Jet Center", "website": "https://www.guardianjetcenter.com/",
             "phone": "(909) 605-6366"},
        ],
    },
    "LAX": {
        "site": "https://www.lawa.org",
        "pages": [
            "https://www.lawa.org/en/lawa-business/areas-of-business/approved-ground-handlers",
        ],
    },
    "SFO": {
        "site": "https://www.flysfo.com",
        "pages": [
            "https://www.flysfo.com/business/aviation-services",
        ],
    },
    "JFK": {
        "site": "https://www.panynj.gov",
        "pages": [
            "https://www.panynj.gov/airports/en/jfk.html",
        ],
    },
    "ORD": {
        "site": "https://www.flychicago.com",
        "pages": [
            "https://www.flychicago.com/business/CDA/Pages/default.aspx",
        ],
    },
    "MDW": {
        "site": "https://www.flychicago.com",
        "pages": [],
    },
}

# Major aviation service providers with per-airport location pages.
# URL templates use {iata} placeholder. Checked automatically when airport site yields nothing.
KNOWN_PROVIDERS = [
    ("Signature Flight Support",        "https://www.signatureaviation.com/locations/{iata}"),
    ("Atlantic Aviation",               "https://www.atlanticaviation.com/Locations/{iata}"),
    ("Menzies Aviation",                "https://www.menziesaviation.com/en/locations/americas/usa/{iata}/"),
    ("Worldwide Flight Services",       "https://www.wfs.aero/find-a-location/{iata}/"),
    ("Swissport",                       "https://www.swissport.com/en/stations/{iata}"),
    ("Dnata",                           "https://www.dnata.com/en/operations/locations/{iata}"),
    ("PrimeFlight Aviation Services",   "https://www.primeflight.com/airports/{iata}/"),
    ("Jet Aviation",                    "https://www.jetaviation.com/locations/{iata}"),
    ("Clay Lacy Aviation",              "https://www.claylacy.com/locations/{iata}/"),
    ("KaiserAir",                       "https://www.kaiserair.com/locations/{iata}/"),
]

# Standard URL path patterns to probe for any airport (no confirmed page)
STANDARD_PATTERNS = [
    "/general-aviation",
    "/general-aviation/services",
    "/general-aviation/fixed-base-operators",
    "/business/general-aviation/services",
    "/business/general-aviation",
    "/about/pilot-information",
    "/about/general-aviation",
    "/airport-experience/general-aviation",
    "/visit/education/general-aviation/fixed-base-operators/",
    "/sjc-general-aviation/fbo",
]

# Regexes for heuristic extraction
PHONE_RE = re.compile(r"\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}")
ADDRESS_RE = re.compile(
    r"^\d{2,6}\s+\w+.{0,60}(Avenue|Ave|Boulevard|Blvd|Road|Rd|Drive|Dr|Street|St|Way|Circle|Lane|Pkwy)\b",
    re.I,
)
COMPANY_SUFFIXES = re.compile(
    r"\b(Inc\.?|LLC\.?|Ltd\.?|Corp\.?|Co\.?|L\.P\.?|Group|Center|International|"
    r"Worldwide|Global|Services|Aviation|Airways|Aero|Jet|Flight|Air|Support|"
    r"Handling|Maintenance|Cargo|Catering|Chefs?)\b"
)
AVIATION_KEYWORDS = re.compile(
    r"\b(aviation|ground.handl|ramp|fueling|fuel|fbo|fixed.base|maintenance|"
    r"repair|cargo|jet|flight|catering|sky.chef|cleaning|detailing|handling)\b",
    re.I,
)
# Lines that are definitely not company names
NOT_COMPANY_RE = re.compile(
    r"^(home|about|contact|search|terms|privacy|copyright|©|select|skip|"
    r"back\s*to|read\s*more|learn\s*more|click|submit|facebook|twitter|"
    r"instagram|linkedin|youtube|email|website|address|phone|fax|hours|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"open|closed|available|24[\s\-]hour|pilot|information|navigation|"
    r"noise|abatement|radio|frequenc|tower|control|atis|clearance|"
    r"arrivals?|departures?|parking|terminal|gate|concourse)\b",
    re.I,
)

# ── Utilities ─────────────────────────────────────────────────────────────────

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


def normalize(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"\b(inc|llc|ltd|corp|co|lp|plc|dba|the)\b\.?", "", name)
    name = re.sub(r"[^a-z0-9 ]", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def fetch(url: str):
    """Fetch a URL, return cleaned text or None on failure."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if not r.ok:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        # Remove nav, footer, scripts, styles
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.decompose()
        return soup.get_text(separator="\n")
    except Exception:
        return None


def fetch_browser(url: str):
    """Fetch a URL using a headless Chromium browser (handles JS-rendered sites)."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=HEADERS["User-Agent"])
            page.goto(url, timeout=20000, wait_until="networkidle")
            text = page.inner_text("body")
            browser.close()
            return text if text.strip() else None
    except Exception:
        return None


def fetch_with_fallback(url: str):
    """Try HTTP first, then Playwright. Returns (text, method)."""
    text = fetch(url)
    if text:
        return text, "http"
    text = fetch_browser(url)
    if text:
        return text, "browser"
    return None, "failed"


def fetch_known_providers(iata: str) -> list[dict]:
    """Check each major provider's per-airport location page. Returns confirmed companies."""
    found = []
    for name, tpl in KNOWN_PROVIDERS:
        url = tpl.format(iata=iata.upper())
        try:
            r = requests.get(url, headers=HEADERS, timeout=8)
            if r.status_code != 200 or len(r.text) < 500:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            text = soup.get_text()
            if iata.upper() not in text.upper() and iata.lower() not in r.url.lower():
                continue
            phone_m = PHONE_RE.search(text)
            phone = phone_m.group(0) if phone_m else None
            found.append({"name": name, "phone": phone, "website": url, "_source_url": url})
        except Exception:
            continue
    return found


def _google_search(query: str, max_results: int = 10) -> list[dict]:
    """Search Google via headless Playwright. Returns list of {href, title, body}."""
    try:
        from playwright.sync_api import sync_playwright
        from urllib.parse import quote_plus
    except ImportError:
        return []

    results = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=HEADERS["User-Agent"])
            page.goto(
                f"https://www.google.com/search?q={quote_plus(query)}&hl=en&gl=us&num={max_results}",
                wait_until="domcontentloaded",
                timeout=20000,
            )
            # Extract result blocks: each has an <h3> title and a parent <a> with the URL
            items = page.query_selector_all("div.g, div[data-hveid]")
            for item in items[:max_results]:
                try:
                    a_el = item.query_selector("a[href]")
                    h3_el = item.query_selector("h3")
                    snippet_el = item.query_selector("[data-sncf], .VwiC3b, [style*='-webkit-line-clamp']")
                    if not a_el:
                        continue
                    href = a_el.get_attribute("href") or ""
                    if not href.startswith("http") or "google" in href:
                        continue
                    results.append({
                        "href": href,
                        "title": h3_el.inner_text() if h3_el else "",
                        "body": snippet_el.inner_text() if snippet_el else "",
                    })
                except Exception:
                    continue
            browser.close()
    except Exception as e:
        print(f"    Playwright Google search error: {e}")

    return results


# Domains we skip when scanning search results for independent company pages
_AGGREGATOR_RE = re.compile(
    r"flightaware|wikipedia|flightbridge|businessairnews|universalweather|"
    r"tripadvisor|yelp|airnav|l33jets|lfs\.aero|thejetfinder|nvoii",
    re.I,
)


def discover_via_search(iata: str, airport_name: str, site: str) -> list[dict]:
    """
    Search DuckDuckGo for aviation service providers at this airport.
    Finds: known provider location pages, airport's own service pages,
    and local/independent FBO websites.
    """
    query = f"{iata} airport FBO ground handler aviation services"
    print(f"  Google: {query!r}")

    results = _google_search(query, max_results=10)
    if not results:
        print("    Google search returned no results")
        return []

    print(f"  {len(results)} results")

    found = []
    seen_names = set()
    airport_domain = site.split("//")[-1].split("/")[0] if site else ""
    airport_pages_found = []

    # Map provider domain → (name, template)
    provider_by_domain = {}
    for name, tpl in KNOWN_PROVIDERS:
        domain = tpl.split("//")[1].split("/")[0]
        provider_by_domain[domain] = (name, tpl)

    for result in results:
        url = result.get("href", "")
        title = result.get("title", "")
        body = result.get("body", "")

        # 1. Known provider location page?
        matched = None
        for domain, (pname, tpl) in provider_by_domain.items():
            if domain in url:
                matched = (pname, url)
                break

        if matched:
            pname, provider_url = matched
            key = normalize(pname)
            if key not in seen_names:
                try:
                    r = requests.get(provider_url, headers=HEADERS, timeout=8)
                    if r.status_code == 200 and len(r.text) > 500:
                        text = BeautifulSoup(r.text, "html.parser").get_text()
                        if iata.upper() in text.upper():
                            seen_names.add(key)
                            phone_m = PHONE_RE.search(text)
                            found.append({
                                "name": pname,
                                "phone": phone_m.group(0) if phone_m else None,
                                "website": provider_url,
                                "_source_url": provider_url,
                            })
                            print(f"    ✓ {pname} (confirmed at {iata})")
                except Exception:
                    pass
            continue

        # 2. Airport's own page — collect for HTTP fetch
        if airport_domain and airport_domain in url:
            airport_pages_found.append(url)
            continue

        # 3. Independent local company website?
        if _AGGREGATOR_RE.search(url):
            continue
        company_name = title.split("|")[0].split(" - ")[0].strip()
        company_name = re.sub(
            r"\s+(fbo|handler|services?|aviation|group)\s*$", "",
            company_name, flags=re.I
        ).strip()
        key = normalize(company_name)
        if (key and key not in seen_names and is_company_name_candidate(company_name)
                and (iata.upper() in (title + body).upper()
                     or airport_name.split()[0].lower() in (title + body).lower())):
            seen_names.add(key)
            phone_m = PHONE_RE.search(body)
            found.append({
                "name": company_name,
                "phone": phone_m.group(0) if phone_m else None,
                "website": url,
                "_source_url": url,
            })
            print(f"    ✓ {company_name} (local FBO from search)")

    # Fetch airport's own pages found in search (HTTP only — no slow Playwright)
    for page_url in airport_pages_found:
        print(f"  Fetching airport page: {page_url} ...", end=" ", flush=True)
        text = fetch(page_url)
        if text:
            companies = extract_companies(text, airport_name, False)
            if companies:
                print(f"{len(companies)} companies found [http]")
                for c in companies:
                    k = normalize(c["name"])
                    if k and k not in seen_names:
                        seen_names.add(k)
                        c["_source_url"] = page_url
                        found.append(c)
            else:
                print("no companies found [http]")
        else:
            print("failed/404")

    return found


def fetch_airnav_fbos(iata: str) -> list[dict]:
    """Parse FBO and ground-support company listings from airnav.com."""
    url = f"https://www.airnav.com/airport/K{iata.upper()}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception:
        return []

    # Find the FBO section by header text
    fbo_header = None
    for tag in soup.find_all(["h3", "th"]):
        if "FBO" in tag.get_text() and "Fuel" in tag.get_text():
            fbo_header = tag
            break
    if not fbo_header:
        return []

    # Walk rows of the following table
    table = fbo_header.find_next("table")
    if not table:
        return []

    companies = []
    for row in table.find_all("tr", recursive=False):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 3:
            continue
        # Business name cell: look for img alt or link text
        name_cell = cells[0] if len(cells) >= 1 else None
        if not name_cell:
            continue
        name = None
        img = name_cell.find("img")
        if img and img.get("alt"):
            name = img["alt"].strip()
        if not name:
            a = name_cell.find("a")
            if a:
                name = a.get_text(strip=True)
        if not name or len(name) < 3:
            continue

        # Contact cell: extract phone
        phone = None
        contact_cell = cells[2] if len(cells) > 2 else None
        if contact_cell:
            contact_text = contact_cell.get_text(" ", strip=True)
            m = PHONE_RE.search(contact_text)
            if m:
                phone = m.group(0)
            # Website
            website = None
            for a in contact_cell.find_all("a", href=True):
                href = a["href"]
                if href.startswith("http") and "airnav" not in href and "mailto" not in href:
                    website = href
                    break

        companies.append({"name": name, "phone": phone, "website": website,
                          "_source_url": url})
    return companies


# ── Company extraction ────────────────────────────────────────────────────────

def extract_with_claude(text: str, airport_name: str) -> list[dict]:
    """Use Claude API to extract aviation service companies from page text."""
    try:
        import anthropic
        client = anthropic.Anthropic()
        prompt = (
            f"Extract aviation ground service companies from this airport website text for {airport_name}.\n\n"
            "Include companies that provide any of:\n"
            "- Ground handling / ramp services\n"
            "- FBO (Fixed Base Operator) services  \n"
            "- Aircraft fueling\n"
            "- Aircraft cleaning or detailing\n"
            "- Aircraft maintenance and MRO\n"
            "- Cargo handling\n"
            "- In-flight catering\n\n"
            "EXCLUDE: airlines, airport authority entities, retail/dining concessions, "
            "car rentals, taxi/shuttle dispatchers, training schools.\n\n"
            'Return ONLY a JSON array like: [{"name": "Company Name", "website": "url or null", '
            '"phone": "phone or null", "address": "address or null", '
            '"type": "FBO|ground_handler|fueling|cleaning|maintenance|catering|cargo"}]\n'
            "Return [] if nothing found.\n\n"
            f"Text:\n{text[:6000]}"
        )
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = msg.content[0].text.strip()
        # Pull JSON array out of the response
        m = re.search(r"\[.*\]", raw, re.S)
        if m:
            return json.loads(m.group(0))
        return []
    except Exception as e:
        print(f"    Claude API error: {e}; falling back to heuristics")
        return extract_heuristic(text)


def is_company_name_candidate(line: str) -> bool:
    """Return True if a line could plausibly be a company name."""
    if len(line) < 3 or len(line) > 75:
        return False
    if re.match(r"^[\d\s()+.\-]+$", line):  # pure digits/phone
        return False
    if ADDRESS_RE.match(line):              # starts with street number
        return False
    if NOT_COMPANY_RE.match(line):          # navigation/boilerplate
        return False
    if "@" in line or "://" in line:       # email or URL
        return False
    if line.upper() == line and len(line) > 10:  # ALL CAPS paragraph
        return False
    # Exclude educational institutions and training programs
    if re.search(r"\b(college|university|school|academy)\b", line, re.I):
        return False
    if re.search(r"\btraining\s*$", line, re.I):  # ends with "Training"
        return False
    # Must have a company suffix OR aviation keyword
    return bool(COMPANY_SUFFIXES.search(line) or AVIATION_KEYWORDS.search(line))


def extract_heuristic(text: str) -> list[dict]:
    """
    Anchor on phone numbers, then scan backwards for company name candidates.
    This avoids picking up addresses and section headings.
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    found = []
    seen = set()

    iata_suffix_re = re.compile(r"\s*[–\-]\s*[A-Z]{3}(\s*-\s*\w+)?\s*$")  # strip "– OAK" etc.

    for i, line in enumerate(lines):
        if not PHONE_RE.search(line):
            continue
        phone = PHONE_RE.search(line).group(0)

        # Look up to 6 lines back for the company name
        for j in range(i - 1, max(-1, i - 7), -1):
            candidate = lines[j]
            if ADDRESS_RE.match(candidate):
                continue  # skip address lines, keep looking back
            if is_company_name_candidate(candidate):
                clean_name = iata_suffix_re.sub("", candidate).strip()
                key = normalize(clean_name)
                if key and key not in seen and len(key) > 3:
                    seen.add(key)
                    # Try to grab website from nearby lines
                    website = None
                    for neighbor in lines[j + 1: i + 2]:
                        if "http" in neighbor.lower() or ".com" in neighbor.lower():
                            website = neighbor.strip()
                            break
                    found.append({
                        "name": clean_name,
                        "phone": phone,
                        "website": website,
                        "address": None,
                        "type": "unknown",
                    })
                break  # found a name for this phone — stop looking back

    return found


def extract_companies(text: str, airport_name: str, use_claude: bool) -> list[dict]:
    if use_claude:
        return extract_with_claude(text, airport_name)
    return extract_heuristic(text)


# ── DB helpers ────────────────────────────────────────────────────────────────

def get_airport_info(iata: str) -> dict:
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
    out = rails("Company.all.each { |c| puts [c.id, c.canonical_name].join('||') }")
    result = {}
    for line in out.splitlines():
        parts = line.split("||", 1)
        if len(parts) == 2:
            result[normalize(parts[1])] = int(parts[0])
    return result


def get_linked_company_ids(airport_id: int) -> set[int]:
    out = rails(f"""
AirportCompanyRelationship.where(airport_id: {airport_id}).pluck(:company_id).each {{|id| puts id}}
""")
    return {int(x) for x in out.splitlines() if x.strip().isdigit()}


def import_company(name: str, website, phone,
                   airport_id: int, source_url: str, run_id: int):
    name_j = json.dumps(name)
    web_j  = json.dumps(website or "")
    out = rails(f"""
c = Company.find_or_initialize_by(canonical_name: {name_j})
if c.new_record?
  c.assign_attributes(
    website:              {web_j},
    run_id:               {run_id},
    is_airline:           false,
    qualification_status: 'Yes',
  )
  c.save!
  puts c.id
else
  puts "exists"
end
AirportCompanyRelationship.find_or_create_by!(airport_id: {airport_id}, company_id: c.id) do |r|
  r.active = true
  r.source_url = {json.dumps(source_url)}
  r.evidence_notes = 'Found via discover_airport_companies.py web scrape'
end
""")
    if out.strip() == "exists":
        return None
    try:
        return int(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


# ── Airport processing ────────────────────────────────────────────────────────

def discover_for_airport(iata: str, existing_companies: dict[str, int],
                          do_import: bool, run_id: int, use_claude: bool) -> dict:
    iata = iata.upper()
    print(f"\n{'='*60}")
    print(f"  {iata}")
    print(f"{'='*60}")

    info = get_airport_info(iata)
    if not info:
        print(f"  Airport {iata} not found in DB")
        return {}

    print(f"  {info['name']}  ({info['city']}, {info['state']})")
    airport_id = info["id"]
    linked_ids = get_linked_company_ids(airport_id)

    cfg = AIRPORT_CONFIG.get(iata, {})
    site = cfg.get("site", "")
    confirmed_pages = cfg.get("pages", [])

    all_companies: list[dict] = []
    pages_with_results: list[str] = []
    seen_keys: set[str] = set()

    def add_companies(companies, source_url=None):
        for c in companies:
            key = normalize(c["name"])
            if key and key not in seen_keys:
                seen_keys.add(key)
                if source_url:
                    c["_source_url"] = source_url
                all_companies.append(c)

    # Step 1: Pre-loaded companies from config (researched manually via Google)
    pre_loaded = cfg.get("companies", [])
    if pre_loaded:
        print(f"  Using {len(pre_loaded)} pre-loaded companies from config")
        add_companies(pre_loaded)

    # Step 2: Try confirmed pages from config (pages known to list vendors)
    for url in confirmed_pages:
        print(f"  Fetching {url} ...", end=" ", flush=True)
        text, method = fetch_with_fallback(url)
        if not text:
            print("failed/404")
            continue
        companies = extract_companies(text, info["name"], use_claude)
        if not companies:
            print(f"no companies found [{method}]")
            continue
        print(f"{len(companies)} companies found [{method}]")
        pages_with_results.append(url)
        add_companies(companies, url)

    # Step 3: Known providers (Signature, Atlantic, Menzies, WFS, etc.) — check per-airport pages
    if not all_companies or True:  # always augment with known providers
        provider_companies = fetch_known_providers(iata)
        if provider_companies:
            print(f"  Known providers: {len(provider_companies)} confirmed at {iata}")
            add_companies(provider_companies)

    # Step 4: airnav.com as supplemental source
    if not all_companies:
        print(f"\n  Trying airnav.com ...")
        airnav_companies = fetch_airnav_fbos(iata)
        if airnav_companies:
            print(f"  airnav.com: {len(airnav_companies)} companies found")
            add_companies(airnav_companies)

    if not all_companies:
        print(f"  No companies found for {iata} via any source.")
        return {"found": 0, "new": 0, "existing": 0}

    # Split into new vs existing
    new_companies = []
    known_companies = []
    for c in all_companies:
        key = normalize(c["name"])
        if key in existing_companies:
            cid = existing_companies[key]
            known_companies.append((c, cid))
        else:
            new_companies.append(c)

    print(f"\n  ALREADY IN DB ({len(known_companies)}):")
    for c, cid in known_companies:
        already_linked = cid in linked_ids
        tag = "✓ linked" if already_linked else "✓ db (not yet linked to airport)"
        print(f"    {tag}  {c['name']}  (id={cid})")

    print(f"\n  NEW ({len(new_companies)}):")
    for c in new_companies:
        phone = f"  📞 {c['phone']}" if c.get("phone") else ""
        site_str = f"  🌐 {c['website']}" if c.get("website") else ""
        print(f"    + {c['name']}{phone}{site_str}")

    if do_import:
        print(f"\n  Importing {len(new_companies)} new + linking {len(known_companies)} existing...")
        imported = 0
        for c in new_companies:
            result = import_company(
                c["name"], c.get("website"), c.get("phone"),
                airport_id, c.get("_source_url", "discover_airport_companies"),
                run_id
            )
            if result is not None:
                imported += 1
                existing_companies[normalize(c["name"])] = result
                print(f"    ✓ Imported: {c['name']} (id={result})")
            else:
                print(f"    ~ Already existed: {c['name']}")

        # Link already-known companies to this airport
        for c, cid in known_companies:
            if cid not in linked_ids:
                rails(f"""
AirportCompanyRelationship.find_or_create_by!(airport_id: {airport_id}, company_id: {cid}) do |r|
  r.active = true
  r.source_url = {json.dumps(c.get('_source_url', 'discover_airport_companies'))}
  r.evidence_notes = 'Found via discover_airport_companies.py web scrape'
end
""")
                print(f"    ✓ Linked existing: {c['name']} (id={cid})")

    return {
        "found": len(all_companies),
        "new": len(new_companies),
        "existing": len(known_companies),
        "pages": pages_with_results,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--airport", nargs="+", required=True,
                        help="Airport IATA code(s) e.g. OAK SJC SMF")
    parser.add_argument("--import", dest="do_import", action="store_true",
                        help="Write discovered companies to DB")
    parser.add_argument("--run-id", type=int, default=2,
                        help="Run ID to tag new companies (default: 2)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and extract, but don't import (same as no --import)")
    args = parser.parse_args()

    use_claude = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if use_claude:
        print(f"ℹ️  ANTHROPIC_API_KEY found — using Claude for extraction")
    else:
        print(f"ℹ️  No ANTHROPIC_API_KEY — using heuristic extraction")
        print(f"    (Set ANTHROPIC_API_KEY env var for better accuracy)")

    print(f"\nLoading existing companies from DB...")
    existing = get_existing_companies()
    print(f"  {len(existing)} companies already in DB")

    totals = {"found": 0, "new": 0, "existing": 0}
    for iata in args.airport:
        result = discover_for_airport(
            iata, existing,
            do_import=args.do_import and not args.dry_run,
            run_id=args.run_id,
            use_claude=use_claude,
        )
        for k in ["found", "new", "existing"]:
            totals[k] += result.get(k, 0)
        time.sleep(1)  # be polite between airports

    print(f"\n{'='*60}")
    print(f"SUMMARY across {len(args.airport)} airport(s):")
    print(f"  Companies found:    {totals['found']}")
    print(f"  Already in DB:      {totals['existing']}")
    print(f"  New companies:      {totals['new']}")
    if not args.do_import and totals["new"]:
        print(f"\n  Re-run with --import to write to DB")
    print()


if __name__ == "__main__":
    main()
