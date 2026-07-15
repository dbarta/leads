#!/usr/bin/env python3
"""
Company enrichment pipeline.

Sources (in priority order):
  1. SAM.gov Entity API — NAICS codes, employee count, CAGE code, registration status
     Requires: SAM_GOV_API_KEY env var (free from https://open.gsa.gov/apis/entity-api/)
  2. NAICS inference from service categories (no API needed)
  3. State contractor license lookup:
       CA CSLB  — construction contractors at LAX, SFO, SAN
       CA BSIS  — security guard companies at LAX, SFO, SAN
       WA L&I   — contractors at SEA
       IL IDFPR — contractors at ORD, MDW

Usage:
  python enrich_companies.py                          # all companies
  python enrich_companies.py --ids 1 5 42             # specific company IDs
  python enrich_companies.py --airport LAX SEA        # companies at specific airports
  python enrich_companies.py --sam-only               # skip state license lookups
  python enrich_companies.py --skip-sam               # skip SAM.gov (NAICS inference only)

Output:
  python/output/enrichment_YYYYMMDD_HHMMSS.csv

Import result:
  bin/rails companies:import_enrichment[<output_file>]
"""

from __future__ import annotations
import argparse
import csv
from difflib import SequenceMatcher
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

SCRIPT_DIR = Path(__file__).parent
INPUT_CSV = SCRIPT_DIR / "companies_for_enrichment.csv"
OUTPUT_DIR = SCRIPT_DIR / "output"
CHECKPOINT_FILE = OUTPUT_DIR / "checkpoint.jsonl"

SAM_GOV_API_KEY = os.environ.get("SAM_GOV_API_KEY", "")
SAM_BASE = "https://api.sam.gov/entity-information/v3/entities"

APOLLO_API_KEY = os.environ.get("APOLLO_API_KEY", "")
APOLLO_ORG_SEARCH = "https://api.apollo.io/v1/organizations/search"

BBB_SEARCH = "https://www.bbb.org/search"

OPENCORP_API_TOKEN = os.environ.get("OPENCORPORATES_API_TOKEN", "")
OPENCORP_SEARCH = "https://api.opencorporates.com/v0.4/companies/search"

FMCSA_SAFER = "https://safer.fmcsa.dot.gov/query.asp"

PDL_API_KEY = os.environ.get("PDL_API_KEY", "")
PDL_COMPANY_ENRICH = "https://api.peopledatalabs.com/v5/company/enrich"

# NAICS prefixes that indicate FMCSA relevance (ground transport, cargo, ramp)
FMCSA_NAICS_PREFIXES = ("485", "488", "492", "493")

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
REQUEST_TIMEOUT = 15

# ---------------------------------------------------------------------------
# NAICS inference map: service category keywords → NAICS codes
# Based on NAICS 2022 / SBA size standards
# ---------------------------------------------------------------------------
NAICS_INFERENCE_MAP = [
    # Security
    (r"security\b", ["561612"]),  # Security Guards and Patrol Services
    # Aircraft maintenance / repair
    (r"aircraft.?(maintenance|repair|line.?maint|overhaul|mro)", ["488190"]),  # Other Support Activities for Air Transportation
    (r"aeronautical.?maintenance", ["488190"]),
    (r"avionics", ["488190"]),
    # Ground handling / ramp
    (r"ramp\b|cargo.?handling|baggage|ground.?handling|ground.?service", ["488190"]),
    (r"into.?plane.?fuel|fueling\b", ["447190"]),  # Other Gasoline Stations (into-plane fueling)
    # Cargo / freight
    (r"cargo\b|freight\b", ["488510"]),  # Freight Transportation Arrangement
    (r"cargo.?screen", ["488190"]),
    # Cabin cleaning / janitorial
    (r"cabin.?clean|janitorial|custodial|cleaning.?service|housekeeping", ["561720"]),  # Janitorial Services
    (r"snow.?remov", ["561790"]),  # Other Services to Buildings and Dwellings
    # Passenger services / wheelchair / terminal
    (r"wheelchair|passenger.?serv|in.?terminal.?handl|terminal\b", ["488190"]),
    (r"passenger.?ramp", ["488190"]),
    # Ground transportation / shuttle / taxi / TNC
    (r"ground.?transport|shuttle|taxi|limousine|limo\b|charter.?bus|van\b", ["485999"]),  # All Other Transit and Ground Passenger Transportation
    (r"airfield.?transport", ["485999"]),
    # Food & beverage
    (r"food.?service|catering|aircraft.?food|inflight.?food|in.?flight", ["722310"]),  # Food Service Contractors
    (r"restaurant|café|cafe\b|coffee|bar\b|grill\b|bistro|lounge.?serv|dining", ["722515"]),  # Snack and Nonalcoholic Beverage Bars
    (r"fast.?food|quick.?serv", ["722513"]),  # Limited-Service Restaurants
    # Retail
    (r"retail\b|gift.?shop|duty.?free|newsstand|bookstore|souvenir", ["453998"]),  # All Other Miscellaneous Store Retailers
    # Currency exchange
    (r"currency|foreign.?exchange|money.?exchange|bureau.?de.?change", ["523130"]),  # Currency Exchange
    # Car rental
    (r"car.?rental|auto.?rental|vehicle.?rental|rent.?a.?car", ["532111"]),  # Passenger Car Rental
    # Parking
    (r"parking\b", ["812930"]),  # Parking Lots and Garages
    # Personnel / staffing
    (r"staffing|personnel|temporary.?help|temp\b.+staff|labor.?supply", ["561320"]),  # Temporary Help Services
    # Waste / environmental
    (r"waste|garbage|refuse|recyclable|environmental\b", ["562998"]),  # All Other Miscellaneous Waste Management
    # Ground equipment maintenance
    (r"ground.?service.?equipment|gse.?maint|equipment.?maint", ["811310"]),  # Commercial Machinery and Equipment (except Automotive and Electronic) Repair and Maintenance
    # IT / tech
    (r"information.?technology|software|it\b.+service|tech.?support", ["541512"]),  # Computer Systems Design Services
    # Construction / tenant improvement
    (r"construction|tenant.?improvement|tenant.?alteration|renovation", ["236220"]),  # Commercial and Institutional Building Construction
    # Consulting
    (r"consulting|advisory|management.?service", ["541611"]),  # Administrative Management Consulting Services
    # Hotels / hospitality
    (r"hotel|motel|hospitality\b", ["721110"]),  # Hotels (except Casino Hotels) and Motels
]


def infer_naics_from_categories(service_cats: str) -> list[str]:
    """Return NAICS codes inferred from service category text."""
    if not service_cats:
        return []
    codes: list[str] = []
    seen: set[str] = set()
    text = service_cats.lower()
    for pattern, naics_list in NAICS_INFERENCE_MAP:
        if re.search(pattern, text, re.I):
            for code in naics_list:
                if code not in seen:
                    seen.add(code)
                    codes.append(code)
    return codes


# Name-based NAICS inference for companies without service categories
NAME_NAICS_MAP = [
    # Airlines
    (r"\bairlines?\b|\bairways?\b|\bair\s+lines?\b", ["481111"]),
    # Airport operations / concessions
    (r"airport\s+(field\s+services?|services?|ops)\b|airworks|conrac\b", ["488190"]),
    # Food & beverage
    (r"food(s)?\b|cafe|café|coffee|baking|pastry|empanada|pizza|bistro|kitchen|dining|restaurant|caterin|caffe|tea\b|lounge\b|pub\b|brew|harvest|snooze|playground\s+eat|breakfast|chocolate", ["722515"]),
    (r"food\s+service|food\s+distribution|catering", ["722310"]),
    # Retail / marketplace
    (r"marketplace|market\s?place|retail\b|bookstore|essential|newsstand|duty[\s-]free", ["453998"]),
    # Security
    (r"security\b|guard\b|patrol\b|protect\b", ["561612"]),
    (r"\bCLEAR\b", ["561612"]),  # CLEAR biometric security
    # Fueling
    (r"fuel(ing)?\s+(co|company|services?)\b|into[\s-]plane\b", ["447190"]),
    (r"\bSFO\s+fuel\b", ["447190"]),
    # Ground transportation
    (r"transport(ation)?\b|shuttle\b|limousine\b|limo\b|\bcoach\b", ["485999"]),
    (r"groome\s+transport", ["485999"]),
    # Cargo / freight
    (r"cargo\b|freight\b|air\s+cargo", ["488510"]),
    # Aircraft maintenance
    (r"deic(e|ing)\b|anti[\s-]ic|aviat(ion)?\s+maintenance|aircraft\s+(maintenance|repair|services?)\b", ["488190"]),
    (r"airframe|avionics\b|mro\b", ["488190"]),
    # Janitorial / cleaning
    (r"janitorial|cleaning|custodial|environmental\s+services?\b", ["561720"]),
    # Staffing
    (r"staffing\b|workforce\b|personnel\b|temp(orary)?\s+(services?|help)\b", ["561320"]),
    # Ground service equipment
    (r"gse\b|ground[\s-]service\s+equipment", ["811310"]),
    # Hotels
    (r"hotel\b|hilton\b|hyatt\b|marriott\b|doubletree\b|harborside\b|hlt\b|lho\b", ["721110"]),
    # Engineering / consulting
    (r"engineer(ing)?\b|architect(ural)?\b|keville\b", ["541330"]),
    # IT / tech
    (r"software\b|\bIT\b|technology|tech\b|data\s+services?\b|surewx\b", ["541512"]),
    # Currency / financial services
    (r"currency\b|foreign\s+exchange\b|lenlyn\b|ice\s+currency\b|travelex\b", ["523130"]),
    # Waste / recycling
    (r"waste\b|recycl\b|garbage\b|disposal\b", ["562998"]),
    # Parking
    (r"\bparking\b", ["812930"]),
    # Law / legal — only if "law firm/office" or "legal services/group" explicitly
    (r"\blaw\s+(firm|office|group)\b|\blegal\s+(services?|group|assoc)", ["541110"]),
    # Communications / media
    (r"communication(s)?\b|media\b|travel\s+content\b", ["541613"]),
    # Construction
    (r"construction\b|builder\b|contracting\b", ["236220"]),
    # Enterprises (general — only if no other match)
    # (Not included — too broad)
]


def infer_naics_from_name(company_name: str) -> list[str]:
    """Return NAICS codes inferred from company name. Used when no service categories available."""
    if not company_name:
        return []
    codes: list[str] = []
    seen: set[str] = set()
    text = company_name.lower()
    for pattern, naics_list in NAME_NAICS_MAP:
        if re.search(pattern, text, re.I):
            for code in naics_list:
                if code not in seen:
                    seen.add(code)
                    codes.append(code)
    return codes


# ---------------------------------------------------------------------------
# SAM.gov Entity API
# ---------------------------------------------------------------------------
def _sam_search(name: str, session: requests.Session) -> dict | None:
    """Search SAM.gov for a legal business name. Returns first matching entity or None."""
    if not SAM_GOV_API_KEY:
        return None
    params = {
        "api_key": SAM_GOV_API_KEY,
        "legalBusinessName": name,
        "includeSections": "entityRegistration,coreData,assertions",
        "registrationStatus": "A",  # Active
    }
    try:
        r = session.get(SAM_BASE, params=params, timeout=REQUEST_TIMEOUT)
        if r.status_code == 429:
            print("    SAM.gov rate limit — waiting 10s")
            time.sleep(10)
            r = session.get(SAM_BASE, params=params, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json()
        entities = data.get("entityData", [])
        if not entities:
            return None
        return entities[0]
    except Exception as e:
        print(f"    SAM.gov error: {e}")
        return None


def _sam_search_inactive(name: str, session: requests.Session) -> dict | None:
    """Try SAM.gov search including inactive/expired registrations."""
    if not SAM_GOV_API_KEY:
        return None
    params = {
        "api_key": SAM_GOV_API_KEY,
        "legalBusinessName": name,
        "includeSections": "entityRegistration,coreData,assertions",
        "registrationStatus": "E",  # Expired
    }
    try:
        r = session.get(SAM_BASE, params=params, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json()
        entities = data.get("entityData", [])
        return entities[0] if entities else None
    except Exception:
        return None


def parse_sam_entity(entity: dict) -> dict:
    """Extract useful fields from a SAM.gov entity record."""
    result = {}
    try:
        reg = entity.get("entityRegistration", {})
        core = entity.get("coreData", {})
        assertions = entity.get("assertions", {})

        result["sam_cage_code"] = reg.get("cageCode", "")
        result["sam_uei"] = reg.get("ueiSAM", "")
        result["sam_registration_status"] = reg.get("registrationStatus", "")

        # NAICS codes — primary + extras
        naics_list = []
        primary = core.get("naicsCode", {}) or {}
        if primary.get("naicsCode"):
            naics_list.append(str(primary["naicsCode"]))
        for entry in assertions.get("goodsAndServices", {}).get("naicsCodeList", []) or []:
            code = str(entry.get("naicsCode", ""))
            if code and code not in naics_list:
                naics_list.append(code)
        result["naics_codes_sam"] = naics_list

        # Employee count
        general = core.get("generalInformation", {}) or {}
        employees = general.get("numberOfEmployees") or general.get("entityStructureDesc")
        result["employee_count_sam"] = employees

        # Business type
        result["entity_type"] = general.get("entityTypeDesc", "")

        # Physical address
        addr = core.get("physicalAddress", {}) or {}
        result["state"] = addr.get("stateOrProvinceCode", "")
        result["zip"] = addr.get("zipCode", "")

        # Size category
        size_facts = assertions.get("sizeMetrics", {}) or {}
        result["is_small_business"] = size_facts.get("sbaBusinessTypeList") or ""

    except Exception as e:
        print(f"    parse_sam_entity error: {e}")
    return result


# ---------------------------------------------------------------------------
# Name-matching helpers (used by BBB and Apollo)
# ---------------------------------------------------------------------------

def _normalize_for_match(name: str) -> str:
    """Strip legal suffixes, replace hyphens/slashes with spaces, remove other punctuation."""
    name = re.sub(r',?\s+(llc|l\.l\.c\.|inc\.?|incorporated|ltd\.?|limited|lp|llp|corp\.?|co\.?)\s*\.?\s*$', '', name, flags=re.I)
    name = re.sub(r'[-/]', ' ', name)        # hyphen/slash → space (e.g. "ACTS-Aviation" → "ACTS Aviation")
    name = re.sub(r'[^a-z0-9\s]', '', name.lower())
    return ' '.join(name.split())


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize_for_match(a), _normalize_for_match(b)).ratio()


def _best_org_similarity(query: str, org_name: str) -> float:
    """Match query against org name AND any DBA in parentheses, return best score."""
    dba_m = re.search(r'\(([^)]+)\)', org_name)
    if dba_m:
        base = org_name[:dba_m.start()].strip()
        dba  = dba_m.group(1).strip()
        return max(_name_similarity(query, base), _name_similarity(query, dba))
    return _name_similarity(query, org_name)


# ---------------------------------------------------------------------------
# BBB — existence check + business category (search results only; profile
# pages are Cloudflare-protected so we don't fetch them)
# ---------------------------------------------------------------------------

def check_bbb(name: str, session: requests.Session) -> dict:
    """
    Search BBB and confirm company existence + category via JSON-LD from search results page.
    Returns dict with found/bbb_name/bbb_category/bbb_state or empty dict on miss/error.
    """
    try:
        r = session.get(BBB_SEARCH, params={"find_text": name, "find_country": "USA"},
                        timeout=15)
        if r.status_code != 200:
            return {}

        # JSON-LD on the search page has business name + address
        m = re.search(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
                      r.text, re.S)
        if not m:
            return {}
        ld = json.loads(m.group(1))
        items = ld.get("mainEntity", {}).get("itemListElement", [])
        if not items:
            return {}

        businesses = [it.get("item", {}) for it in items]

        # Find best name match
        best, best_score = None, 0.0
        for biz in businesses:
            raw = re.sub(r'<[^>]+>', '', biz.get("name", ""))
            score = _best_org_similarity(name, raw)
            if score > best_score:
                best_score, best = score, biz

        if best_score < 0.5 or not best:
            return {}

        raw_name = re.sub(r'<[^>]+>', '', best.get("name", ""))
        addr = best.get("address", {})

        # Business category is embedded in the HTML cards but not JSON-LD —
        # extract from the rendered card text after stripping the company name
        category = ""
        soup = BeautifulSoup(r.text, "html.parser")
        cards = soup.find_all(['article', 'div'],
                              class_=lambda c: c and 'result' in str(c).lower())
        if cards:
            card_text = cards[0].get_text(" ", strip=True)
            norm = _normalize_for_match(raw_name)
            after = re.sub(re.escape(norm), '', card_text.lower(), count=1).strip()
            cat_m = re.match(r'^([A-Z][A-Za-z\s&/]+?)(?:Service Area|BBB Rating|\d|\(|$)', card_text)
            if cat_m:
                category = cat_m.group(1).strip()

        return {
            "found": True,
            "bbb_name": raw_name,
            "bbb_similarity": round(best_score, 2),
            "bbb_category": category,
            "bbb_city": addr.get("addressLocality", ""),
            "bbb_state": addr.get("addressRegion", ""),
        }
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Apollo.io — employee count + website
# ---------------------------------------------------------------------------

def _apollo_search(query: str, session: requests.Session) -> list:
    """POST to Apollo organizations/search, return organizations list."""
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": APOLLO_API_KEY,
    }
    try:
        r = session.post(APOLLO_ORG_SEARCH, json={"q_organization_name": query, "per_page": 5},
                         headers=headers, timeout=15)
        if r.status_code == 429:
            print("    Apollo rate limit — waiting 10s")
            time.sleep(10)
            r = session.post(APOLLO_ORG_SEARCH, json={"q_organization_name": query, "per_page": 5},
                             headers=headers, timeout=15)
        if r.status_code != 200:
            return []
        return r.json().get("organizations", [])
    except Exception:
        return []


def check_apollo(name: str, session: requests.Session) -> dict:
    """
    Search Apollo.io organizations for employee count and website.
    Tries the full name first, then falls back to normalized/shortened names.
    Requires APOLLO_API_KEY env var (free account at apollo.io).
    """
    if not APOLLO_API_KEY:
        return {}

    # Build list of search queries to try in order
    normalized = _normalize_for_match(name)
    words = normalized.split()
    queries = [name]
    if normalized != name.lower():
        queries.append(normalized)           # suffix-stripped version
    if len(words) > 2:
        queries.append(" ".join(words[:3]))  # first 3 meaningful words

    # Deduplicate while preserving order
    seen, unique_queries = set(), []
    for q in queries:
        if q.lower() not in seen:
            seen.add(q.lower())
            unique_queries.append(q)

    US_COUNTRIES = {"united states", "us", "usa", ""}

    all_candidates: list[tuple[float, dict]] = []  # (score, org)
    for query in unique_queries:
        orgs = _apollo_search(query, session)
        for org in orgs:
            score = _best_org_similarity(name, org.get("name", ""))
            if score >= 0.6:
                all_candidates.append((score, org))
        if any(s >= 0.85 for s, _ in all_candidates):
            break
        time.sleep(0.3)

    if not all_candidates:
        return {}

    # Prefer US-based companies; only fall back to orgs with no country set
    # (never use an org explicitly identified as a foreign country)
    us_candidates = [(s, o) for s, o in all_candidates
                     if (o.get("country") or "").lower() in US_COUNTRIES]
    unknown_country = [(s, o) for s, o in all_candidates
                       if not (o.get("country") or "").strip()]
    pool = us_candidates or unknown_country
    if not pool:
        return {}
    best_score, best = max(pool, key=lambda x: x[0])

    if best_score < 0.6:
        return {}

    emp = best.get("estimated_num_employees")
    website = (best.get("website_url") or "").strip().rstrip("/")

    return {
        "found": True,
        "apollo_name": best.get("name", ""),
        "apollo_similarity": round(best_score, 2),
        "employee_count": emp,
        "website": website,
        "industry": best.get("industry", ""),
    }


# ---------------------------------------------------------------------------
# State contractor license lookups
# ---------------------------------------------------------------------------

def check_ca_cslb(company_name: str, session: requests.Session) -> dict | None:
    """
    Search California CSLB (Contractors State License Board).
    Returns license info dict or None.
    """
    url = "https://www.cslb.ca.gov/OnlineServices/CheckLicenseII/CheckLicense.aspx"
    try:
        r = session.get(url, timeout=REQUEST_TIMEOUT)
        soup = BeautifulSoup(r.text, "html.parser")
        # Get viewstate for ASP.NET form
        vs = soup.find("input", {"id": "__VIEWSTATE"})
        vsg = soup.find("input", {"id": "__VIEWSTATEGENERATOR"})
        ev = soup.find("input", {"id": "__EVENTVALIDATION"})
        if not vs:
            return None

        data = {
            "__VIEWSTATE": vs["value"] if vs else "",
            "__VIEWSTATEGENERATOR": vsg["value"] if vsg else "",
            "__EVENTVALIDATION": ev["value"] if ev else "",
            "ctl00$ContentPlaceHolder1$txtBusinessName": company_name,
            "ctl00$ContentPlaceHolder1$btnSearch": "Search",
            "ctl00$ContentPlaceHolder1$DropDownList1": "ALL",
        }
        r2 = session.post(url, data=data, timeout=REQUEST_TIMEOUT)
        soup2 = BeautifulSoup(r2.text, "html.parser")

        # Check for results table
        results = soup2.find("table", {"id": "ctl00_ContentPlaceHolder1_gvLicensees"})
        if not results:
            return None

        rows = results.find_all("tr")[1:]  # skip header
        if not rows:
            return None

        licenses = []
        for row in rows[:3]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) >= 4:
                licenses.append({
                    "license_number": cells[0],
                    "status": cells[1],
                    "name": cells[2],
                    "type": cells[3] if len(cells) > 3 else "",
                })
        return {"source": "CA CSLB", "licenses": licenses} if licenses else None
    except Exception as e:
        print(f"    CA CSLB error: {e}")
        return None


def check_ca_bsis(company_name: str, session: requests.Session) -> dict | None:
    """
    Search California BSIS (Bureau of Security and Investigative Services).
    Relevant for security guard companies (561612).
    """
    search_url = "https://www2.dca.ca.gov/pls/wllpub/wllqryna$lcev2.startup?p_qte_code=PPO&p_qte_pgm_code=8008"
    try:
        r = session.get(search_url, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")

        # Find search form
        form = soup.find("form")
        if not form:
            return None

        action = urljoin(search_url, form.get("action", ""))
        inputs = {i.get("name"): i.get("value", "") for i in form.find_all("input") if i.get("name")}
        inputs["busnam"] = company_name
        inputs.pop("clear", None)

        r2 = session.post(action, data=inputs, timeout=REQUEST_TIMEOUT)
        soup2 = BeautifulSoup(r2.text, "html.parser")

        # Parse results
        table = soup2.find("table")
        if not table:
            return None
        rows = table.find_all("tr")[1:]
        licenses = []
        for row in rows[:3]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) >= 2:
                licenses.append({"license_number": cells[0], "name": cells[1], "status": cells[2] if len(cells) > 2 else ""})
        return {"source": "CA BSIS", "licenses": licenses} if licenses else None
    except Exception as e:
        print(f"    CA BSIS error: {e}")
        return None


def check_wa_lni(company_name: str, session: requests.Session) -> dict | None:
    """Washington State L&I contractor verification."""
    url = f"https://secure.lni.wa.gov/verify/Results.aspx?UBI=&Name={quote_plus(company_name)}&LicenseType=CC&County=0&City=&Start=1"
    try:
        r = session.get(url, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, "html.parser")
        results_div = soup.find("div", {"id": "results"}) or soup.find("table", {"class": "license-results"})
        if not results_div:
            return None
        rows = results_div.find_all("tr") if results_div.name == "table" else results_div.find_all("tr")
        licenses = []
        for row in rows[:3]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if cells and len(cells) >= 2:
                licenses.append({"name": cells[0], "status": cells[1] if len(cells) > 1 else ""})
        return {"source": "WA L&I", "licenses": licenses} if licenses else None
    except Exception as e:
        print(f"    WA L&I error: {e}")
        return None


# ---------------------------------------------------------------------------
# Website employee scraping (last resort)
# ---------------------------------------------------------------------------
EMPLOYEE_PATTERNS = [
    re.compile(r"(\d[\d,]+)\+?\s+employees?", re.I),
    re.compile(r"team\s+of\s+(\d[\d,]+)", re.I),
    re.compile(r"(\d[\d,]+)\+?\s+staff\b", re.I),
    re.compile(r"over\s+(\d[\d,]+)\s+people", re.I),
    re.compile(r"workforce\s+of\s+(\d[\d,]+)", re.I),
    re.compile(r"(\d[\d,]+)\s+professionals\b", re.I),
]

def scrape_employee_count(website: str, session: requests.Session) -> tuple[int | None, str]:
    """Try to extract employee count from company website about/team page."""
    if not website:
        return None, ""
    base = website.rstrip("/")
    pages_to_try = [base, base + "/about", base + "/about-us", base + "/company", base + "/team"]
    for url in pages_to_try[:3]:
        try:
            r = session.get(url, timeout=10, allow_redirects=True)
            if r.status_code >= 400:
                continue
            ct = r.headers.get("content-type", "")
            if "html" not in ct.lower():
                continue
            text = BeautifulSoup(r.text, "html.parser").get_text(" ", strip=True)
            for pat in EMPLOYEE_PATTERNS:
                m = pat.search(text)
                if m:
                    count_str = m.group(1).replace(",", "")
                    try:
                        return int(count_str), url
                    except ValueError:
                        pass
        except Exception:
            pass
    return None, ""


# ---------------------------------------------------------------------------
# OpenCorporates — entity registration status
# ---------------------------------------------------------------------------

def check_opencorporates(name: str, session: requests.Session) -> dict:
    """
    Search OpenCorporates for entity registration status.
    Free tier: ~100 req/day without token; set OPENCORPORATES_API_TOKEN for more.
    Returns dict with oc_status/oc_jurisdiction/oc_company_number or {} on miss.
    """
    params: dict = {"q": name, "jurisdiction_code": "us"}
    if OPENCORP_API_TOKEN:
        params["api_token"] = OPENCORP_API_TOKEN
    try:
        r = session.get(OPENCORP_SEARCH, params=params, timeout=15)
        if r.status_code == 403:
            print("    OpenCorporates: rate limited (free tier exhausted for today)")
            return {"oc_rate_limited": True}
        if r.status_code != 200:
            return {}
        data = r.json()
        companies = data.get("results", {}).get("companies", [])
        if not companies:
            return {}

        best_score, best = 0.0, None
        for wrapper in companies[:5]:
            c = wrapper.get("company", {})
            score = _best_org_similarity(name, c.get("name", ""))
            if score > best_score:
                best_score, best = score, c

        if best_score < 0.65 or not best:
            return {}

        return {
            "oc_name": best.get("name", ""),
            "oc_status": best.get("current_status", ""),
            "oc_jurisdiction": (best.get("jurisdiction_code") or "").replace("us_", "").upper(),
            "oc_company_number": best.get("company_number", ""),
            "oc_incorporation_date": best.get("incorporation_date", ""),
            "oc_similarity": round(best_score, 2),
        }
    except Exception as e:
        print(f"    OpenCorporates error: {e}")
        return {}


# ---------------------------------------------------------------------------
# FMCSA SAFER — motor carrier fleet / driver data for transport companies
# ---------------------------------------------------------------------------

def check_fmcsa(name: str, session: requests.Session) -> dict:
    """
    Scrape FMCSA SAFER for DOT number, fleet size, driver count, and operating status.
    Most useful for ground transport, cargo, ramp handling companies.
    No API key required.
    """
    params = {
        "searchtype": "ANY",
        "query_type": "queryCarrierSnapshot",
        "query_param": "CARRIER_NAME",
        "query_string": name,
    }
    try:
        r = session.get(FMCSA_SAFER, params=params, timeout=15)
        if r.status_code != 200:
            return {}
        soup = BeautifulSoup(r.text, "html.parser")

        # SAFER returns either a snapshot directly or a search results list.
        # Detect snapshot by presence of "DOT#:" label in a table.
        data: dict = {}
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            for row in rows:
                cells = row.find_all(["td", "th"])
                if len(cells) < 2:
                    continue
                key = cells[0].get_text(strip=True).lower().rstrip(":")
                val = cells[1].get_text(strip=True)
                if not val:
                    continue
                if "entity name" in key:
                    data["fmcsa_name"] = val
                elif key == "dot#" or key == "dot #":
                    data["fmcsa_dot"] = val
                elif "power units" in key:
                    try:
                        data["fmcsa_power_units"] = int(val.replace(",", ""))
                    except ValueError:
                        pass
                elif key == "drivers":
                    try:
                        data["fmcsa_drivers"] = int(val.replace(",", ""))
                    except ValueError:
                        pass
                elif "operating status" in key:
                    data["fmcsa_status"] = val

        if not data.get("fmcsa_name"):
            # May be a search results page — check for a results table and pick
            # the first row that matches by name
            links = soup.find_all("a", href=re.compile(r"query_type=queryCarrierSnapshot"))
            for link in links[:5]:
                link_name = link.get_text(strip=True)
                if _best_org_similarity(name, link_name) >= 0.7:
                    detail_url = "https://safer.fmcsa.dot.gov/" + link["href"].lstrip("/")
                    r2 = session.get(detail_url, timeout=15)
                    if r2.status_code == 200:
                        return check_fmcsa_parse(name, r2.text)
            return {}

        similarity = _best_org_similarity(name, data.get("fmcsa_name", ""))
        if similarity < 0.6:
            return {}
        data["fmcsa_similarity"] = round(similarity, 2)
        return data
    except Exception as e:
        print(f"    FMCSA error: {e}")
        return {}


def check_fmcsa_parse(name: str, html: str) -> dict:
    """Parse a SAFER carrier snapshot HTML page."""
    soup = BeautifulSoup(html, "html.parser")
    data: dict = {}
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue
            key = cells[0].get_text(strip=True).lower().rstrip(":")
            val = cells[1].get_text(strip=True)
            if not val:
                continue
            if "entity name" in key:
                data["fmcsa_name"] = val
            elif key in ("dot#", "dot #"):
                data["fmcsa_dot"] = val
            elif "power units" in key:
                try:
                    data["fmcsa_power_units"] = int(val.replace(",", ""))
                except ValueError:
                    pass
            elif key == "drivers":
                try:
                    data["fmcsa_drivers"] = int(val.replace(",", ""))
                except ValueError:
                    pass
            elif "operating status" in key:
                data["fmcsa_status"] = val
    if not data.get("fmcsa_name"):
        return {}
    similarity = _best_org_similarity(name, data.get("fmcsa_name", ""))
    if similarity < 0.6:
        return {}
    data["fmcsa_similarity"] = round(similarity, 2)
    return data


# ---------------------------------------------------------------------------
# People Data Labs — company enrichment (employee count, size, NAICS, website)
# ---------------------------------------------------------------------------

# PDL size-range → approximate midpoint for numeric storage when exact count unavailable
PDL_SIZE_MIDPOINTS = {
    "1-10": 5, "11-50": 30, "51-200": 125, "201-500": 350,
    "501-1000": 750, "1001-5000": 3000, "5001-10000": 7500,
    "10001-50000": 30000, "50001-200000": 125000, "200001+": 200001,
}


def check_pdl(name: str, website: str, session: requests.Session) -> dict:
    """
    Enrich company via People Data Labs company enrichment API.
    Tries by name first; if company has a website, also tries by domain for a
    higher-confidence match. Free tier: 100 lookups/month.
    Requires PDL_API_KEY env var (register free at peopledatalabs.com).
    """
    if not PDL_API_KEY:
        return {}

    headers = {"X-Api-Key": PDL_API_KEY, "Content-Type": "application/json"}

    def _call(params: dict) -> dict:
        try:
            r = session.get(PDL_COMPANY_ENRICH, params=params, headers=headers, timeout=15)
            if r.status_code == 402:
                print("    PDL: quota exhausted (free tier)")
                return {"pdl_quota_exhausted": True}
            if r.status_code == 404:
                return {}  # no match
            if r.status_code == 429:
                print("    PDL: rate limited — waiting 10s")
                time.sleep(10)
                r = session.get(PDL_COMPANY_ENRICH, params=params, headers=headers, timeout=15)
            if r.status_code != 200:
                return {}
            return r.json()
        except Exception as e:
            print(f"    PDL error: {e}")
            return {}

    data: dict = {}

    # Try by domain first (most accurate) if we have a website
    if website:
        domain = urlparse(website).netloc.lstrip("www.") or website.lstrip("www.")
        if domain:
            data = _call({"website": domain})

    # Fall back to name search
    if not data or data.get("pdl_quota_exhausted"):
        if data.get("pdl_quota_exhausted"):
            return data
        data = _call({"name": name})

    if not data or data.get("pdl_quota_exhausted"):
        return data or {}

    # Validate name match
    pdl_name = data.get("display_name") or data.get("name") or ""
    similarity = _best_org_similarity(name, pdl_name) if pdl_name else 0.0
    if similarity < 0.55:  # PDL often returns canonical names that differ slightly
        return {}

    result: dict = {
        "pdl_name": pdl_name,
        "pdl_similarity": round(similarity, 2),
        "pdl_size": data.get("size", ""),           # "51-200" etc.
        "pdl_employee_count": data.get("employee_count"),  # exact int or None
        "pdl_industry": data.get("industry", ""),
        "pdl_naics": "",
        "pdl_website": (data.get("website") or "").strip().rstrip("/"),
        "pdl_founded": str(data.get("founded") or ""),
        "pdl_type": data.get("type", ""),           # "private", "public", etc.
    }

    # NAICS codes — PDL returns a list of dicts with "naics_code" key
    naics_list = data.get("naics_codes") or []
    if isinstance(naics_list, list):
        result["pdl_naics"] = ", ".join(
            str(n.get("naics_code", n) if isinstance(n, dict) else n)
            for n in naics_list[:4] if n
        )

    return result


# ---------------------------------------------------------------------------
# Checkpoint helpers — resume interrupted runs without repeating API calls
# ---------------------------------------------------------------------------

def load_checkpoint() -> dict[int, dict]:
    """Load previously completed company results from checkpoint file. Returns {id: result}."""
    cache: dict[int, dict] = {}
    if not CHECKPOINT_FILE.exists():
        return cache
    with open(CHECKPOINT_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                cid = int(rec.get("id", 0))
                if cid:
                    cache[cid] = rec
            except (json.JSONDecodeError, ValueError, KeyError):
                pass
    return cache


def save_checkpoint(enriched: dict) -> None:
    """Append one completed company result to the checkpoint file."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    with open(CHECKPOINT_FILE, "a") as f:
        f.write(json.dumps(enriched) + "\n")


# ---------------------------------------------------------------------------
# Main enrichment loop
# ---------------------------------------------------------------------------

def enrich_company(row: dict, session: requests.Session, args) -> dict:
    """Enrich one company row. Returns dict of enrichment fields to update."""
    company_id = row["id"]
    name = row["canonical_name"]
    website = row["website"] or ""
    service_cats = row["service_categories"] or ""
    airports = (row["airport_codes"] or "").split("; ")
    has_employee_data = bool(row.get("employee_min"))
    has_naics = bool(row.get("naics_codes"))

    enrichment = {
        "id": company_id,
        "naics_codes": row.get("naics_codes") or "",
        "sam_cage_code": row.get("sam_cage_code") or "",
        "sam_registration_status": "",
        "employee_min": row.get("employee_min") or "",
        "employee_max": row.get("employee_max") or "",
        "employee_estimate_text": "",
        "employee_evidence": "",
        "license_info": "",
        "notes": "",
    }

    # --- Phase 1: SAM.gov ---
    sam_data = {}
    if not args.skip_sam and SAM_GOV_API_KEY:
        print(f"  SAM: {name[:50]}")
        entity = _sam_search(name, session)
        if not entity:
            entity = _sam_search_inactive(name, session)
        if entity:
            sam_data = parse_sam_entity(entity)
            enrichment["sam_cage_code"] = sam_data.get("sam_cage_code", "")
            enrichment["sam_registration_status"] = sam_data.get("sam_registration_status", "")
            if sam_data.get("naics_codes_sam"):
                enrichment["naics_codes"] = ", ".join(sam_data["naics_codes_sam"])
            emp = sam_data.get("employee_count_sam")
            if emp and not has_employee_data:
                enrichment["employee_estimate_text"] = str(emp)
                enrichment["employee_evidence"] = "SAM.gov entity record"
        time.sleep(0.5)  # SAM.gov rate limit: be gentle

    # --- Phase 2: NAICS inference from service categories, then company name ---
    if not enrichment["naics_codes"]:
        inferred = infer_naics_from_categories(service_cats) if service_cats else []
        if not inferred:
            inferred = infer_naics_from_name(name)
        if inferred:
            enrichment["naics_codes"] = ", ".join(inferred)
            source = "service categories" if service_cats else "company name"
            print(f"  NAICS inferred ({source}): {enrichment['naics_codes']} ({name[:40]})")

    # --- Phase 3: Website employee scraping ---
    if not args.no_website and not has_employee_data and not enrichment["employee_estimate_text"] and website:
        count, source_url = scrape_employee_count(website, session)
        if count:
            enrichment["employee_estimate_text"] = str(count)
            enrichment["employee_evidence"] = source_url
            print(f"  Website employees: {count} ({name[:40]})")

    # --- Phase 4: State contractor license lookup ---
    if not args.sam_only:
        ca_airports = {"LAX", "SFO", "SAN"}
        wa_airports = {"SEA"}
        il_airports = {"ORD", "MDW"}
        my_airports = set(airports)

        license_results = []
        if my_airports & ca_airports:
            # Check CSLB for construction-type companies
            naics = enrichment["naics_codes"]
            is_construction = any(c.startswith("236") or c.startswith("237") or c.startswith("238") for c in naics.split(", ") if c)
            is_security = any(c == "561612" for c in naics.split(", ") if c)

            if is_construction:
                print(f"  CA CSLB: {name[:40]}")
                result = check_ca_cslb(name, session)
                if result:
                    license_results.append(result)
                time.sleep(1)

            if is_security:
                print(f"  CA BSIS: {name[:40]}")
                result = check_ca_bsis(name, session)
                if result:
                    license_results.append(result)
                time.sleep(1)

        if my_airports & wa_airports:
            naics = enrichment["naics_codes"]
            is_construction_wa = any(c.startswith("236") or c.startswith("237") or c.startswith("238") for c in naics.split(", ") if c)
            if is_construction_wa:
                print(f"  WA L&I: {name[:40]}")
                result = check_wa_lni(name, session)
                if result:
                    license_results.append(result)
                time.sleep(1)

        if license_results:
            enrichment["license_info"] = json.dumps(license_results)

    # --- Phase 5: BBB existence & category verification ---
    bbb_data = {}
    if not args.no_bbb:
        bbb_data = check_bbb(name, session)
        if bbb_data.get("found"):
            print(f"  BBB: {bbb_data['bbb_name']} ({bbb_data.get('bbb_category','')}) "
                  f"[{bbb_data['bbb_similarity']:.0%} match]")
        time.sleep(1.5)

    # --- Phase 6: Apollo.io employee count + website ---
    apollo_data = {}
    if not args.no_apollo and APOLLO_API_KEY:
        apollo_data = check_apollo(name, session)
        if apollo_data.get("found"):
            emp_str = f"{apollo_data['employee_count']:,}" if apollo_data.get("employee_count") else "—"
            print(f"  Apollo: {apollo_data['apollo_name']} — {emp_str} employees "
                  f"[{apollo_data['apollo_similarity']:.0%} match]")
        time.sleep(0.5)

    # --- Cross-verify: populate employee data and website ---
    bbb_confirmed = bbb_data.get("found", False)
    apollo_emp = apollo_data.get("employee_count")
    apollo_website = apollo_data.get("website", "")

    # Fill website if company has none and Apollo/BBB found one
    enrichment["website"] = ""
    if not website and apollo_website:
        enrichment["website"] = apollo_website
        print(f"  Website (Apollo): {apollo_website}")

    # Employee data: prefer SAM.gov already set, otherwise Apollo
    if apollo_emp and not has_employee_data and not enrichment.get("employee_estimate_text"):
        confidence = "high" if bbb_confirmed else "medium"
        source = "Apollo.io (BBB confirmed)" if bbb_confirmed else "Apollo.io"
        apollo_name = apollo_data.get("apollo_name", "")
        enrichment["employee_estimate_text"] = f"{apollo_emp:,}"
        enrichment["employee_evidence"] = (
            f"{source}: {apollo_emp:,} employees"
            + (f" (matched: {apollo_name})" if apollo_name != name else "")
        )
        enrichment["employee_min"] = apollo_emp
        enrichment["employee_max"] = apollo_emp
        print(f"  Employees [{confidence}]: {apollo_emp:,}")
    elif apollo_emp and enrichment.get("employee_estimate_text") and \
            enrichment["employee_estimate_text"] not in ("", "Unknown"):
        # Cross-check: annotate existing evidence with Apollo's number
        enrichment["employee_evidence"] = (
            (enrichment.get("employee_evidence") or "") +
            f" | Apollo cross-check: {apollo_emp:,}"
        ).lstrip(" | ")
        print(f"  Apollo cross-check: {apollo_emp:,} employees")

    enrichment["bbb_confirmed"] = "yes" if bbb_confirmed else ""
    enrichment["bbb_category"] = bbb_data.get("bbb_category", "")
    enrichment["apollo_employee_count"] = str(apollo_emp) if apollo_emp else ""

    # --- Phase 7: OpenCorporates — entity registration status ---
    oc_data: dict = {}
    if not args.no_opencorp:
        oc_data = check_opencorporates(name, session)
        if oc_data.get("oc_rate_limited"):
            args.no_opencorp = True  # stop trying for rest of run
        elif oc_data.get("oc_status"):
            print(f"  OpenCorp: {oc_data['oc_name']} [{oc_data['oc_status']}] "
                  f"{oc_data.get('oc_jurisdiction','')} [{oc_data['oc_similarity']:.0%}]")
            if oc_data.get("oc_status", "").lower() in ("dissolved", "inactive", "revoked"):
                enrichment["notes"] = (
                    (enrichment.get("notes") or "") +
                    f"\nOpenCorporates: {oc_data['oc_status']} in {oc_data.get('oc_jurisdiction','')}"
                ).lstrip()
        time.sleep(0.5)

    enrichment["opencorp_status"] = oc_data.get("oc_status", "")
    enrichment["opencorp_jurisdiction"] = oc_data.get("oc_jurisdiction", "")

    # --- Phase 8: FMCSA SAFER — fleet/driver data for transport companies ---
    fmcsa_data: dict = {}
    naics_str = enrichment.get("naics_codes", "")
    is_transport = any(naics_str.startswith(p) for p in FMCSA_NAICS_PREFIXES
                       if naics_str) or any(
                           c.strip()[:3] in ("485", "488", "492", "493")
                           for c in naics_str.split(",") if c.strip())
    if not args.no_fmcsa and is_transport:
        fmcsa_data = check_fmcsa(name, session)
        if fmcsa_data.get("fmcsa_drivers") or fmcsa_data.get("fmcsa_power_units"):
            drivers = fmcsa_data.get("fmcsa_drivers", 0)
            units = fmcsa_data.get("fmcsa_power_units", 0)
            print(f"  FMCSA: {fmcsa_data.get('fmcsa_name','')} — "
                  f"{drivers} drivers / {units} power units [{fmcsa_data.get('fmcsa_similarity',0):.0%}]")
            if drivers and not has_employee_data and not enrichment.get("employee_estimate_text"):
                enrichment["employee_estimate_text"] = str(drivers)
                enrichment["employee_evidence"] = (
                    f"FMCSA SAFER: {drivers} drivers"
                    + (f" / {units} power units" if units else "")
                    + (f" (DOT #{fmcsa_data['fmcsa_dot']})" if fmcsa_data.get("fmcsa_dot") else "")
                )
                enrichment["employee_min"] = drivers
                enrichment["employee_max"] = drivers
                print(f"  Employees [FMCSA]: {drivers}")
        time.sleep(0.5)

    enrichment["fmcsa_dot"] = fmcsa_data.get("fmcsa_dot", "")
    enrichment["fmcsa_power_units"] = str(fmcsa_data.get("fmcsa_power_units", ""))
    enrichment["fmcsa_drivers"] = str(fmcsa_data.get("fmcsa_drivers", ""))

    # --- Phase 9: People Data Labs — employee count + NAICS + website ---
    pdl_data: dict = {}
    if not args.no_pdl and PDL_API_KEY:
        pdl_data = check_pdl(name, website or enrichment.get("website", ""), session)
        if pdl_data.get("pdl_quota_exhausted"):
            args.no_pdl = True  # stop trying for rest of run
        elif pdl_data.get("pdl_name"):
            emp_exact = pdl_data.get("pdl_employee_count")
            emp_range = pdl_data.get("pdl_size", "")
            print(f"  PDL: {pdl_data['pdl_name']} — "
                  f"{emp_exact or emp_range or '—'} employees "
                  f"[{pdl_data['pdl_similarity']:.0%}]")

            # Fill website if missing
            if not website and not enrichment.get("website") and pdl_data.get("pdl_website"):
                enrichment["website"] = pdl_data["pdl_website"]
                print(f"  Website (PDL): {pdl_data['pdl_website']}")

            # Fill NAICS if missing and PDL has it
            if not enrichment.get("naics_codes") and pdl_data.get("pdl_naics"):
                enrichment["naics_codes"] = pdl_data["pdl_naics"]
                print(f"  NAICS (PDL): {pdl_data['pdl_naics']}")

            # Employee count — prefer exact; fall back to midpoint of size range
            if not has_employee_data and not enrichment.get("employee_estimate_text"):
                if emp_exact and emp_exact > 0:
                    confidence = "high" if emp_exact > 50 else "medium"
                    enrichment["employee_min"] = emp_exact
                    enrichment["employee_max"] = emp_exact
                    enrichment["employee_estimate_text"] = str(emp_exact)
                    enrichment["employee_evidence"] = (
                        f"People Data Labs: {emp_exact:,} employees"
                        + (f" (matched: {pdl_data['pdl_name']})" if pdl_data["pdl_name"] != name else "")
                    )
                    print(f"  Employees [{confidence}]: {emp_exact:,}")
                elif emp_range:
                    midpoint = PDL_SIZE_MIDPOINTS.get(emp_range)
                    enrichment["employee_estimate_text"] = emp_range
                    enrichment["employee_evidence"] = f"People Data Labs: {emp_range} employees (size range)"
                    if midpoint:
                        enrichment["employee_min"] = midpoint
                        enrichment["employee_max"] = midpoint
                    print(f"  Employees [PDL range]: {emp_range}")
            elif emp_exact:
                # Cross-check existing data
                enrichment["employee_evidence"] = (
                    (enrichment.get("employee_evidence") or "")
                    + f" | PDL cross-check: {emp_exact:,}"
                ).lstrip(" | ")
        time.sleep(0.3)

    enrichment["pdl_employee_count"] = str(pdl_data.get("pdl_employee_count") or "")
    enrichment["pdl_size"] = pdl_data.get("pdl_size", "")
    enrichment["pdl_naics"] = pdl_data.get("pdl_naics", "")

    return enrichment


def main():
    parser = argparse.ArgumentParser(description="Enrich company data from SAM.gov, NAICS inference, and state license lookups")
    parser.add_argument("--ids", nargs="*", type=int, help="Specific company IDs to enrich")
    parser.add_argument("--airport", nargs="*", help="Filter by airport FAA code")
    parser.add_argument("--skip-sam", action="store_true", help="Skip SAM.gov lookup")
    parser.add_argument("--sam-only", action="store_true", help="Skip state license lookups")
    parser.add_argument("--no-website", action="store_true", help="Skip website employee scraping")
    parser.add_argument("--no-bbb", action="store_true", help="Skip BBB lookup")
    parser.add_argument("--no-apollo", action="store_true", help="Skip Apollo.io lookup")
    parser.add_argument("--no-opencorp", action="store_true", help="Skip OpenCorporates lookup")
    parser.add_argument("--no-fmcsa", action="store_true", help="Skip FMCSA SAFER lookup")
    parser.add_argument("--no-pdl", action="store_true", help="Skip People Data Labs lookup")
    parser.add_argument("--input", type=Path, default=INPUT_CSV)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--fresh", action="store_true",
                        help="Ignore existing checkpoint and start over (default: resume)")
    args = parser.parse_args()

    if not SAM_GOV_API_KEY and not args.skip_sam:
        print("NOTE: SAM_GOV_API_KEY not set. SAM.gov lookup disabled.")
        print("  Get a free key at: https://open.gsa.gov/apis/entity-api/")
        print()
    if not APOLLO_API_KEY and not args.no_apollo:
        print("NOTE: APOLLO_API_KEY not set. Apollo.io lookup disabled.")
        print("  Get a free key at: https://app.apollo.io/#/settings/integrations/api")
        print()

    # Load companies
    with open(args.input, newline="") as f:
        rows = list(csv.DictReader(f))

    # Filter
    if args.ids:
        rows = [r for r in rows if int(r["id"]) in args.ids]
    if args.airport:
        airport_set = {a.upper() for a in args.airport}
        rows = [r for r in rows if any(a in (r.get("airport_codes", "") or "") for a in airport_set)]

    # Checkpoint — load prior results unless --fresh requested
    checkpoint: dict[int, dict] = {}
    if not args.fresh and CHECKPOINT_FILE.exists():
        checkpoint = load_checkpoint()
        if checkpoint:
            print(f"Resuming from checkpoint: {len(checkpoint)} companies already done "
                  f"({CHECKPOINT_FILE})")
            print("  Use --fresh to ignore checkpoint and start over.")
    elif args.fresh and CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
        print("Checkpoint cleared — starting fresh.")

    # Skip companies already in checkpoint
    pending = [r for r in rows if int(r["id"]) not in checkpoint]
    skipped = len(rows) - len(pending)
    if skipped:
        print(f"Skipping {skipped} already-processed companies.")

    print(f"Enriching {len(pending)} companies...")

    # Output
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = args.output or (OUTPUT_DIR / f"enrichment_{ts}.csv")
    OUTPUT_DIR.mkdir(exist_ok=True)

    fieldnames = ["id", "naics_codes", "sam_cage_code", "sam_registration_status",
                  "employee_min", "employee_max", "employee_estimate_text", "employee_evidence",
                  "license_info", "notes",
                  "website", "bbb_confirmed", "bbb_category", "apollo_employee_count",
                  "opencorp_status", "opencorp_jurisdiction",
                  "fmcsa_dot", "fmcsa_power_units", "fmcsa_drivers",
                  "pdl_employee_count", "pdl_size", "pdl_naics"]

    session = requests.Session()
    session.headers["User-Agent"] = UA

    new_results = []
    for i, row in enumerate(pending, 1):
        print(f"\n[{i}/{len(pending)}] {row['canonical_name'][:60]}")
        try:
            enriched = enrich_company(row, session, args)
            new_results.append(enriched)
            save_checkpoint(enriched)
        except Exception as e:
            print(f"  ERROR: {e}")
            err_rec = {"id": row["id"], "notes": f"error: {e}"}
            new_results.append(err_rec)
            save_checkpoint(err_rec)

    # Merge checkpoint + new results, preserving original row order
    result_by_id = {**checkpoint, **{int(r["id"]): r for r in new_results}}
    results = [result_by_id[int(r["id"])] for r in rows if int(r["id"]) in result_by_id]

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    print(f"\nWrote {len(results)} rows to {out_path}")
    if CHECKPOINT_FILE.exists():
        print(f"Checkpoint at {CHECKPOINT_FILE} (delete it to start fresh next time, or use --fresh)")
    print(f"Import: cd /Users/dbarta/leads/leads && bin/rails companies:import_enrichment[{out_path}]")

    # Summary
    with_naics  = sum(1 for r in results if r.get("naics_codes"))
    with_sam    = sum(1 for r in results if r.get("sam_cage_code"))
    with_emp    = sum(1 for r in results if r.get("employee_estimate_text"))
    with_bbb    = sum(1 for r in results if r.get("bbb_confirmed") == "yes")
    with_apollo = sum(1 for r in results if r.get("apollo_employee_count"))
    with_web    = sum(1 for r in results if r.get("website"))
    with_oc     = sum(1 for r in results if r.get("opencorp_status"))
    with_fmcsa  = sum(1 for r in results if r.get("fmcsa_dot"))
    with_pdl    = sum(1 for r in results if r.get("pdl_employee_count") or r.get("pdl_size"))
    print(f"\nSummary: {with_naics} NAICS | {with_sam} SAM | {with_emp} employee estimates "
          f"| {with_bbb} BBB confirmed | {with_apollo} Apollo | {with_pdl} PDL "
          f"| {with_web} websites | {with_oc} OpenCorp | {with_fmcsa} FMCSA")


if __name__ == "__main__":
    main()
