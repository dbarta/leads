#!/usr/bin/env python3
"""
Contact finder for GL insurance cold calling.

Searches MeetLeo, Apollo.io, and People Data Labs for decision-maker contacts
at airport service companies. MeetLeo is the primary source (email + title for
CFO/finance/owner tier). Apollo and PDL add phones and cross-validation.

Target titles (GL insurance decision makers):
  Small (<50 emp):  Owner, President, CEO, General Manager
  Mid (50-500):     CFO, Controller, Finance Director, VP Finance
  Large (500+):     Risk Manager, Director of Risk, CRO

Usage:
  python find_contacts.py                    # all qualified companies
  python find_contacts.py --all              # include No/Uncertain companies too
  python find_contacts.py --ids 1 5 42       # specific company IDs
  python find_contacts.py --airport LAX SFO  # companies at specific airports
  python find_contacts.py --no-meetleo       # skip MeetLeo
  python find_contacts.py --no-apollo        # skip Apollo
  python find_contacts.py --no-pdl           # skip PDL
  python find_contacts.py --fresh            # ignore checkpoint, reprocess all

Output:
  python/output/contacts_YYYYMMDD_HHMMSS.csv       (contacts)
  python/output/hq_phones_YYYYMMDD_HHMMSS.csv      (company HQ phones from MeetLeo)

Import:
  bin/rails contacts:import[<contacts_file>]
  bin/rails companies:import_phones[<hq_phones_file>]
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

import requests

SCRIPT_DIR = Path(__file__).parent
INPUT_CSV = SCRIPT_DIR / "companies_for_enrichment.csv"
OUTPUT_DIR = SCRIPT_DIR / "output"
CHECKPOINT_FILE = OUTPUT_DIR / "contacts_checkpoint.jsonl"
MEETLEO_CHECKPOINT_FILE = OUTPUT_DIR / "meetleo_checkpoint.jsonl"

APOLLO_API_KEY = os.environ.get("APOLLO_API_KEY", "")
APOLLO_PEOPLE_SEARCH = "https://api.apollo.io/v1/people/search"

PDL_API_KEY = os.environ.get("PDL_API_KEY", "")
PDL_PERSON_SEARCH = "https://api.peopledatalabs.com/v5/person/search"

MEETLEO_EMAIL    = os.environ.get("MEETLEO_EMAIL", "jonathan@jeffersonfinancialins.com")
MEETLEO_PASSWORD = os.environ.get("MEETLEO_PASSWORD", "")
MEETLEO_AUTH_URL    = "https://users.meetleo.com/auth/token"
MEETLEO_SEARCH_URL  = "https://api.meetleo.com/v1/prospects/search"
MEETLEO_ENRICH_URL  = "https://api.meetleo.com/v1/prospects/enrich"
MEETLEO_JOBS_URL    = "https://api.meetleo.com/v1/jobs"

MEETLEO_BATCH_SIZE  = 20   # jobs submitted in parallel
MEETLEO_POLL_INTERVAL = 10  # seconds between polls
MEETLEO_MAX_POLLS   = 36   # 6 minutes max per batch
MEETLEO_NAME_THRESHOLD = 0.70  # min similarity to accept a name match

# Airport FAA code → US state abbreviation
AIRPORT_STATE = {
    "LAX": "CA", "SFO": "CA", "SJC": "CA", "SAN": "CA", "OAK": "CA",
    "BUR": "CA", "LGB": "CA", "ONT": "CA", "SNA": "CA", "SMF": "CA",
    "ORD": "IL", "MDW": "IL",
    "JFK": "NY", "LGA": "NY", "EWR": "NJ",
    "DFW": "TX", "DAL": "TX", "HOU": "TX", "IAH": "TX", "AUS": "TX",
    "MIA": "FL", "MCO": "FL", "TPA": "FL", "FLL": "FL",
    "SEA": "WA", "DEN": "CO", "ATL": "GA", "PHX": "AZ", "MSP": "MN",
    "BWI": "MD", "DCA": "VA", "IAD": "VA", "CLT": "NC", "PHL": "PA",
    "BOS": "MA", "DTW": "MI", "SLC": "UT", "PDX": "OR",
}

REQUEST_TIMEOUT = 15

# Titles most relevant for GL insurance purchasing decisions, in priority order
GL_TITLES = [
    # Ownership / top leadership (for small companies these are the buyers)
    "owner", "co-owner", "president", "co-president",
    "ceo", "chief executive officer",
    "founder", "co-founder",
    "principal", "managing member", "managing partner",
    "managing director", "general manager",
    # Finance (for mid-size)
    "cfo", "chief financial officer",
    "controller", "comptroller",
    "finance director", "director of finance",
    "vp finance", "vp of finance",
    "vice president finance", "vice president of finance",
    # Risk / Insurance (for large companies)
    "risk manager", "director of risk", "director of risk management",
    "chief risk officer", "cro",
    "vp risk", "vp of risk",
    "insurance manager", "director of insurance",
]

# Shorter list for Apollo title filters (API performs better with fewer titles)
APOLLO_TITLE_GROUPS = [
    ["owner", "president", "ceo", "chief executive officer", "founder", "principal",
     "managing member", "managing partner", "general manager"],
    ["cfo", "chief financial officer", "controller", "finance director",
     "director of finance", "vp finance"],
    ["risk manager", "director of risk", "chief risk officer", "insurance manager"],
]

TITLE_PRIORITY = {t.lower(): i for i, t in enumerate(GL_TITLES)}


def title_priority(title: str) -> int:
    t = (title or "").lower()
    for i, gl in enumerate(GL_TITLES):
        if gl in t:
            return i
    return 999


def name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def states_for_airports(airport_codes_str: str) -> list[str]:
    """Return unique state codes derived from a semicolon-separated airport code string."""
    states = []
    for code in re.split(r"[;,\s]+", airport_codes_str or ""):
        code = code.strip().upper()
        if code in AIRPORT_STATE and AIRPORT_STATE[code] not in states:
            states.append(AIRPORT_STATE[code])
    return states


def domain_from_url(url: str) -> str:
    url = url.strip()
    url = re.sub(r"^https?://", "", url)
    url = url.split("/")[0].split("?")[0]
    return url.lower()


_LEGAL_SUFFIX_RE = re.compile(
    r"\b(llc|inc|corp|ltd|co|lp|llp|plc|incorporated|limited|company"
    r"|international|group|services|solutions|usa|us|america|americas"
    r"|holdings|enterprises|associates|partners|management"
    r"|aviation|airlines|airline|air|airways"
    r"|security|patrol|guard|protection"
    r"|transportation|transport|logistics|cargo|freight"
    r"|industries|industry|industrial"
    r"|support|systems|system|technologies|technology"
    r"|ground|handling|airport|flight|global"
    r"|worldwide|nationwide|national"
    r"|svcs|svc|dept)\b[.,]?\s*$",
    re.IGNORECASE,
)

def meetleo_search_name(canonical_name: str) -> str:
    """
    Shorten a company name to its distinctive keyword(s) for MeetLeo's prospectName filter.
    MeetLeo does keyword matching, not full-name fuzzy matching, so 'Accufleet' finds
    'ACCUFLEET INTERNATIONAL INC' but 'ACCUFLEET INTERNATIONAL INC' does not.
    Strip trailing legal suffixes iteratively until the name stabilises or gets too short.
    """
    name = canonical_name.strip().rstrip(".,")
    for _ in range(4):
        shortened = _LEGAL_SUFFIX_RE.sub("", name).strip().rstrip(".,")
        if shortened == name or len(shortened) < 4:
            break
        name = shortened
    return name


# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------

def load_checkpoint() -> dict[int, list]:
    """Returns {company_id: [contact_dicts]} from checkpoint file."""
    result: dict[int, list] = {}
    if not CHECKPOINT_FILE.exists():
        return result
    with open(CHECKPOINT_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                result[rec["company_id"]] = rec["contacts"]
            except Exception:
                pass
    return result


def save_checkpoint(company_id: int, contacts: list) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(CHECKPOINT_FILE, "a") as f:
        f.write(json.dumps({"company_id": company_id, "contacts": contacts}) + "\n")


def load_meetleo_checkpoint() -> dict[int, dict]:
    """Returns {company_id: {contacts, hq_phone}} from MeetLeo checkpoint."""
    result: dict[int, dict] = {}
    if not MEETLEO_CHECKPOINT_FILE.exists():
        return result
    with open(MEETLEO_CHECKPOINT_FILE) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                result[rec["company_id"]] = rec
            except Exception:
                pass
    return result


def save_meetleo_checkpoint(company_id: int, contacts: list, hq_phone: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(MEETLEO_CHECKPOINT_FILE, "a") as f:
        f.write(json.dumps({
            "company_id": company_id,
            "contacts": contacts,
            "hq_phone": hq_phone,
        }) + "\n")


# ---------------------------------------------------------------------------
# MeetLeo — token management
# ---------------------------------------------------------------------------

_meetleo_token: str = ""
_meetleo_token_expires: float = 0.0


def meetleo_get_token(session: requests.Session) -> str:
    global _meetleo_token, _meetleo_token_expires
    if _meetleo_token and time.time() < _meetleo_token_expires - 60:
        return _meetleo_token
    if not MEETLEO_PASSWORD:
        return ""
    try:
        r = session.post(MEETLEO_AUTH_URL,
                         json={"email": MEETLEO_EMAIL, "password": MEETLEO_PASSWORD},
                         timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            print(f"  MeetLeo auth failed: {r.status_code} {r.text[:200]}")
            return ""
        data = r.json()
        _meetleo_token = data.get("accessToken", "")
        expires_in = data.get("expiresIn", 21600)
        _meetleo_token_expires = time.time() + expires_in
        return _meetleo_token
    except Exception as e:
        print(f"  MeetLeo auth error: {e}")
        return ""


def meetleo_headers(session: requests.Session) -> dict:
    token = meetleo_get_token(session)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# ---------------------------------------------------------------------------
# MeetLeo — prospect search (free) + enrich (credits)
# ---------------------------------------------------------------------------

def meetleo_build_filter(row: dict) -> dict:
    """
    Build the filter object for a company.
    - With website: use websiteUrl (exact domain) — most precise.
    - Without website: use shortened prospectName only (no state filter — companies are
      registered in their HQ state, which often differs from the airport's state).
    MeetLeo's prospectName is a keyword match, so we strip legal suffixes to get
    the distinctive keyword (e.g. 'Accufleet' not 'Accufleet International Inc').
    """
    website = (row.get("website") or "").strip()
    if website:
        return {"websiteUrl": domain_from_url(website)}
    return {"prospectName": meetleo_search_name(row["canonical_name"])}


def _meetleo_search(filt: dict, session: requests.Session) -> list[dict]:
    """Execute one MeetLeo search, return prospect list."""
    body = {"filters": [filt], "limit": 5, "page": 1}
    try:
        r = session.post(MEETLEO_SEARCH_URL, headers=meetleo_headers(session),
                         json=body, timeout=REQUEST_TIMEOUT)
        if r.status_code == 429:
            time.sleep(15)
            r = session.post(MEETLEO_SEARCH_URL, headers=meetleo_headers(session),
                             json=body, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            return r.json().get("data", {}).get("prospects", [])
    except Exception as e:
        print(f"    MeetLeo search error: {e}")
    return []


def meetleo_search_one(row: dict, session: requests.Session) -> tuple[int | None, str, str]:
    """
    Search MeetLeo for the company (free, no credits).
    Tries websiteUrl first; falls back to shortened prospectName if domain not indexed.
    Returns (prospectId, standardCompanyName, hqPhone) or (None, "", "").
    """
    our_name = row["canonical_name"]
    website = (row.get("website") or "").strip()
    prospects = []
    used_domain = False

    # 1. Try domain match first (most precise)
    if website:
        domain = domain_from_url(website)
        prospects = _meetleo_search({"websiteUrl": domain}, session)
        if prospects:
            used_domain = True

    # 2. Fall back to name match
    if not prospects:
        short = meetleo_search_name(our_name)
        prospects = _meetleo_search({"prospectName": short}, session)

    if not prospects:
        return None, "", ""

    # Pick the best name match among results
    best, best_sim = prospects[0], 0.0
    for p in prospects:
        s = name_similarity(our_name, p.get("standardCompanyName", ""))
        if s > best_sim:
            best, best_sim = p, s

    # Domain matches bypass the threshold (domain is authoritative); name matches need 0.70+
    if not used_domain and best_sim < MEETLEO_NAME_THRESHOLD:
        return None, "", ""

    hq = (best.get("hqPhone") or "").strip()
    return best["prospectId"], best.get("standardCompanyName", ""), hq


def meetleo_submit_enrich(filt: dict, session: requests.Session) -> str | None:
    """Submit an async enrich job. Returns taskId or None."""
    body = {"filters": [filt], "maxProspects": 1}
    try:
        r = session.post(MEETLEO_ENRICH_URL, headers=meetleo_headers(session),
                         json=body, timeout=REQUEST_TIMEOUT)
        if r.status_code == 202:
            return r.json()["data"]["taskId"]
        if r.status_code == 402:
            print("  MeetLeo: insufficient credits — disabling MeetLeo")
            return "__NO_CREDITS__"
        if r.status_code == 429:
            time.sleep(15)
            r = session.post(MEETLEO_ENRICH_URL, headers=meetleo_headers(session),
                             json=body, timeout=REQUEST_TIMEOUT)
            if r.status_code == 202:
                return r.json()["data"]["taskId"]
        return None
    except Exception as e:
        print(f"    MeetLeo enrich submit error: {e}")
        return None


def meetleo_poll_job(task_id: str, session: requests.Session) -> list[dict] | None:
    """
    Poll one job. Returns list of enriched prospect dicts when complete,
    [] on no_email/failed, None if still pending/processing.
    """
    try:
        r = session.get(f"{MEETLEO_JOBS_URL}/{task_id}",
                        headers=meetleo_headers(session), timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json().get("data", {})
        status = data.get("status")
        if status == "completed":
            return data.get("prospects", [])
        if status == "failed":
            return []
        return None  # still pending/processing
    except Exception:
        return None


def _format_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    if len(digits) == 11 and digits[0] == "1":
        return f"({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
    return raw.strip()


def parse_meetleo_contacts(prospects: list[dict], our_name: str) -> list[dict]:
    """
    From a completed enrich job's prospect list, extract the top GL-relevant contacts.
    Returns at most 2 contacts (best-priority title first).
    """
    contacts = []
    for prospect in prospects:
        if prospect.get("enrichmentStatus") != "enriched":
            continue
        # Verify name still matches (enrich can sometimes drift)
        ml_name = prospect.get("standardCompanyName") or prospect.get("prospectName") or ""
        if ml_name and name_similarity(our_name, ml_name) < MEETLEO_NAME_THRESHOLD:
            continue
        for c in (prospect.get("contacts") or []):
            if c.get("enrichmentStatus") not in ("enriched", None):
                continue
            first = (c.get("firstName") or "").strip()
            last  = (c.get("lastName") or "").strip()
            full  = f"{first} {last}".strip()
            if not full:
                continue
            email = (c.get("email") or "").strip()
            phone = _format_phone(c.get("phone") or "")
            title = (c.get("jobTitle") or "").strip()
            contacts.append({
                "full_name":    full,
                "first_name":   first,
                "last_name":    last,
                "title":        title,
                "email":        email,
                "phone":        phone,
                "linkedin_url": "",
                "source":       "meetleo",
                "_priority":    title_priority(title),
            })

    # Sort by GL title priority, keep top 2
    contacts.sort(key=lambda c: c["_priority"])
    for c in contacts:
        c.pop("_priority", None)
    return contacts[:2]


# ---------------------------------------------------------------------------
# MeetLeo — batch runner
# ---------------------------------------------------------------------------

def run_meetleo_batch(rows: list[dict], session: requests.Session,
                      ml_checkpoint: dict[int, dict]) -> dict[int, dict]:
    """
    Process a batch of companies through MeetLeo search + enrich.
    Returns {company_id: {contacts, hq_phone}} for newly processed companies.
    """
    results: dict[int, dict] = {}

    # Step 1: Free search to get prospectId + hqPhone
    pending_enrich: list[tuple[dict, dict, str]] = []  # (row, enrich_filter, hq_phone)
    for row in rows:
        cid = int(row["id"])
        prospect_id, ml_name, hq_phone = meetleo_search_one(row, session)
        if not prospect_id:
            save_meetleo_checkpoint(cid, [], hq_phone)
            results[cid] = {"contacts": [], "hq_phone": hq_phone}
            continue
        # Build enrich filter: prefer domain for precision, else use the same name search
        website = (row.get("website") or "").strip()
        enrich_filt = ({"websiteUrl": domain_from_url(website)} if website
                       else {"prospectName": meetleo_search_name(row["canonical_name"])})
        pending_enrich.append((row, enrich_filt, hq_phone))
        time.sleep(0.3)

    if not pending_enrich:
        return results

    # Step 2: Submit enrich jobs
    jobs: list[tuple[dict, str, str]] = []  # (row, task_id, hq_phone)
    for row, filt, hq_phone in pending_enrich:
        task_id = meetleo_submit_enrich(filt, session)
        if task_id == "__NO_CREDITS__":
            return results  # abort remaining
        if task_id:
            jobs.append((row, task_id, hq_phone))
        else:
            cid = int(row["id"])
            save_meetleo_checkpoint(cid, [], hq_phone)
            results[cid] = {"contacts": [], "hq_phone": hq_phone}
        time.sleep(0.5)

    if not jobs:
        return results

    # Step 3: Poll all jobs until complete or timeout
    print(f"    Polling {len(jobs)} MeetLeo enrich jobs", end="", flush=True)
    remaining = list(jobs)
    for poll_n in range(MEETLEO_MAX_POLLS):
        time.sleep(MEETLEO_POLL_INTERVAL)
        still_running = []
        for row, task_id, hq_phone in remaining:
            prospects = meetleo_poll_job(task_id, session)
            if prospects is None:
                still_running.append((row, task_id, hq_phone))
                continue
            cid = int(row["id"])
            contacts = parse_meetleo_contacts(prospects, row["canonical_name"])
            save_meetleo_checkpoint(cid, contacts, hq_phone)
            results[cid] = {"contacts": contacts, "hq_phone": hq_phone}
        remaining = still_running
        print(".", end="", flush=True)
        if not remaining:
            break
    print()

    # Anything still pending after timeout → save empty
    for row, task_id, hq_phone in remaining:
        cid = int(row["id"])
        print(f"    MeetLeo job timed out for {row['canonical_name']}")
        save_meetleo_checkpoint(cid, [], hq_phone)
        results[cid] = {"contacts": [], "hq_phone": hq_phone}

    return results


# ---------------------------------------------------------------------------
# Apollo people search
# ---------------------------------------------------------------------------

def search_apollo(company_name: str, website: str, session: requests.Session) -> list[dict]:
    """Search Apollo for GL insurance decision makers at a company."""
    if not APOLLO_API_KEY:
        return []

    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": APOLLO_API_KEY,
    }

    all_people: list[dict] = []

    for title_group in APOLLO_TITLE_GROUPS:
        body: dict = {
            "person_titles": title_group,
            "page": 1,
            "per_page": 5,
        }
        # Search by domain first (more precise), fall back to name
        if website:
            domain = re.sub(r"^https?://", "", website).strip("/").split("/")[0]
            body["q_organization_domains"] = [domain]
        else:
            body["q_organization_name"] = company_name

        try:
            r = session.post(APOLLO_PEOPLE_SEARCH, json=body, headers=headers,
                             timeout=REQUEST_TIMEOUT)
            if r.status_code == 429:
                print("    Apollo: rate limited — waiting 15s")
                time.sleep(15)
                r = session.post(APOLLO_PEOPLE_SEARCH, json=body, headers=headers,
                                 timeout=REQUEST_TIMEOUT)
            if r.status_code == 401:
                print("    Apollo: invalid API key")
                return []
            if r.status_code != 200:
                continue
            people = r.json().get("people", [])
            all_people.extend(people)
        except Exception as e:
            print(f"    Apollo error: {e}")

        # Short pause between requests to avoid rate limits
        time.sleep(0.5)

    return all_people


def parse_apollo_contacts(people: list[dict], company_name: str) -> list[dict]:
    """Convert Apollo API people records to our contact format."""
    contacts = []
    seen_names: set[str] = set()

    for p in people:
        name = (p.get("name") or "").strip()
        if not name or name.lower() in seen_names:
            continue
        seen_names.add(name.lower())

        # Extract best phone number (prefer direct, then mobile)
        phone = ""
        for ph in (p.get("phone_numbers") or []):
            raw = (ph.get("raw_number") or "").strip()
            if raw:
                if ph.get("type") in ("direct_phone",):
                    phone = raw
                    break
                elif not phone:
                    phone = raw

        # Apollo often returns email as sanitized string or null on free tier
        email = (p.get("email") or "").strip()
        if email and p.get("email_status") not in ("verified", "likely"):
            email = ""  # Don't store low-confidence emails

        contacts.append({
            "full_name":    name,
            "first_name":   (p.get("first_name") or "").strip(),
            "last_name":    (p.get("last_name") or "").strip(),
            "title":        (p.get("title") or "").strip(),
            "email":        email,
            "phone":        phone,
            "linkedin_url": (p.get("linkedin_url") or "").strip(),
            "source":       "apollo",
        })

    return contacts


# ---------------------------------------------------------------------------
# PDL person search
# ---------------------------------------------------------------------------

def search_pdl(company_name: str, website: str, session: requests.Session,
               args: argparse.Namespace) -> list[dict]:
    """Search PDL for GL insurance decision makers at a company (SQL API)."""
    if not PDL_API_KEY:
        return []

    # PDL SQL API — more reliable than ES DSL for our use case
    # Use domain if available (more precise), else company name
    if website:
        domain = re.sub(r"^https?://", "", website).strip("/").split("/")[0]
        where = f"job_company_website = '{domain}'"
    else:
        # Escape single quotes
        safe_name = company_name.replace("'", "''")
        where = f"job_company_name = '{safe_name}'"

    title_clauses = " OR ".join([
        "job_title LIKE '%owner%'",
        "job_title LIKE '%president%'",
        "job_title LIKE '%chief executive%'",
        "job_title LIKE '% ceo%'",
        "job_title LIKE 'ceo%'",
        "job_title LIKE '%founder%'",
        "job_title LIKE '%general manager%'",
        "job_title LIKE '%managing member%'",
        "job_title LIKE '%chief financial%'",
        "job_title LIKE '% cfo%'",
        "job_title LIKE 'cfo%'",
        "job_title LIKE '%controller%'",
        "job_title LIKE '%finance director%'",
        "job_title LIKE '%director of finance%'",
        "job_title LIKE '%risk manager%'",
        "job_title LIKE '%director of risk%'",
    ])

    sql = (
        f"SELECT full_name, first_name, last_name, job_title, "
        f"work_email, mobile_phone, linkedin_url "
        f"FROM person "
        f"WHERE ({where}) AND ({title_clauses})"
    )

    params = {
        "api_key": PDL_API_KEY,
        "sql": sql,
        "size": "10",
        "titlecase": "true",
    }

    def _do_request():
        return session.get(PDL_PERSON_SEARCH, params=params, timeout=REQUEST_TIMEOUT)

    try:
        r = _do_request()
        if r.status_code == 402:
            print("    PDL: quota exhausted — skipping PDL for remaining companies")
            args.no_pdl = True
            return []
        if r.status_code == 429:
            print("    PDL: rate limited — waiting 15s")
            time.sleep(15)
            r = _do_request()
        if r.status_code == 404:
            return []  # No records found — not an error
        if r.status_code != 200:
            return []
        return r.json().get("data", [])
    except Exception as e:
        print(f"    PDL error: {e}")
        return []


def _pdl_str(value) -> str:
    """PDL free tier masks real values as boolean True — treat those as empty."""
    if isinstance(value, str):
        return value.strip()
    return ""


def parse_pdl_contacts(people: list[dict]) -> list[dict]:
    """Convert PDL API person records to our contact format."""
    contacts = []
    seen_names: set[str] = set()

    for p in people:
        name = _pdl_str(p.get("full_name"))
        if not name or name.lower() in seen_names:
            continue
        seen_names.add(name.lower())

        linkedin = _pdl_str(p.get("linkedin_url"))
        if linkedin and not linkedin.startswith("http"):
            linkedin = "https://" + linkedin

        contacts.append({
            "full_name":    name,
            "first_name":   _pdl_str(p.get("first_name")),
            "last_name":    _pdl_str(p.get("last_name")),
            "title":        _pdl_str(p.get("job_title")),
            "email":        _pdl_str(p.get("work_email")),
            "phone":        _pdl_str(p.get("mobile_phone")),
            "linkedin_url": linkedin,
            "source":       "pdl",
        })

    return contacts


# ---------------------------------------------------------------------------
# Merge contacts from multiple sources
# ---------------------------------------------------------------------------

def _merge_into(base: list[dict], additions: list[dict], threshold: float = 0.85) -> list[dict]:
    """Merge additions into base list, deduplicating by name similarity."""
    merged = list(base)
    for add in additions:
        add_name = add["full_name"].lower()
        match_idx = None
        for i, existing in enumerate(merged):
            if name_similarity(add_name, existing["full_name"]) >= threshold:
                match_idx = i
                break
        if match_idx is not None:
            b = merged[match_idx]
            sources = {b["source"], add["source"]} - {""}
            b["source"] = "both" if len(sources) > 1 else b["source"]
            if not b["phone"] and add.get("phone"):
                b["phone"] = add["phone"]
            if not b["email"] and add.get("email"):
                b["email"] = add["email"]
            if not b["linkedin_url"] and add.get("linkedin_url"):
                b["linkedin_url"] = add["linkedin_url"]
            if not b["title"] and add.get("title"):
                b["title"] = add["title"]
        else:
            merged.append(add)
    merged.sort(key=lambda c: title_priority(c.get("title", "")))
    return merged


def merge_contacts(apollo: list[dict], pdl: list[dict]) -> list[dict]:
    return _merge_into(apollo, pdl)


# ---------------------------------------------------------------------------
# Per-company processing (Apollo + PDL only)
# ---------------------------------------------------------------------------

def find_contacts_for_company(row: dict, session: requests.Session,
                               args: argparse.Namespace) -> list[dict]:
    company_id   = int(row["id"])
    company_name = row["canonical_name"]
    website      = row.get("website", "") or ""

    apollo_people = []
    pdl_people    = []

    if not args.no_apollo and APOLLO_API_KEY:
        apollo_people = search_apollo(company_name, website, session)

    if not args.no_pdl and PDL_API_KEY and not getattr(args, "no_pdl", False):
        pdl_people = search_pdl(company_name, website, session, args)

    apollo_contacts = parse_apollo_contacts(apollo_people, company_name)
    pdl_contacts    = parse_pdl_contacts(pdl_people)
    contacts        = merge_contacts(apollo_contacts, pdl_contacts)

    for c in contacts:
        c["company_id"]   = company_id
        c["company_name"] = company_name

    return contacts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Find GL insurance decision-maker contacts")
    parser.add_argument("--ids",     nargs="*", type=int, help="Specific company IDs")
    parser.add_argument("--airport", nargs="*", help="Filter by airport FAA code")
    parser.add_argument("--all",     action="store_true",
                        help="Include all companies (default: Yes/Review qualified only)")
    parser.add_argument("--min-employees", type=int, default=None,
                        help="Only companies with employee_min >= this value")
    parser.add_argument("--max-employees", type=int, default=None,
                        help="Only companies with employee_max <= this value (or employee_min if max unknown)")
    parser.add_argument("--no-meetleo", action="store_true", help="Skip MeetLeo")
    parser.add_argument("--no-apollo",  action="store_true", help="Skip Apollo")
    parser.add_argument("--no-pdl",     action="store_true", help="Skip PDL")
    parser.add_argument("--fresh",      action="store_true",
                        help="Ignore all checkpoints and reprocess everything")
    parser.add_argument("--input",  default=str(INPUT_CSV))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    use_meetleo = not args.no_meetleo and bool(MEETLEO_PASSWORD)
    use_apollo  = not args.no_apollo  and bool(APOLLO_API_KEY)
    use_pdl     = not args.no_pdl     and bool(PDL_API_KEY)

    if not use_meetleo and not use_apollo and not use_pdl:
        print("ERROR: no data source available — set MEETLEO_PASSWORD, APOLLO_API_KEY, or PDL_API_KEY")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file      = args.output or str(OUTPUT_DIR / f"contacts_{timestamp}.csv")
    hq_phone_file = str(OUTPUT_DIR / f"hq_phones_{timestamp}.csv")

    # Load input companies
    with open(args.input) as f:
        rows = list(csv.DictReader(f))

    # Apply filters
    if args.ids:
        rows = [r for r in rows if int(r["id"]) in args.ids]
    if args.airport:
        codes = {c.upper() for c in args.airport}
        rows = [r for r in rows if any(c in (r.get("airport_codes") or "") for c in codes)]
    if not args.all:
        rows = [r for r in rows
                if (r.get("qualification_status") or "").strip() in ("Yes", "Review")]
    if args.min_employees is not None:
        def _emp_min(r):
            v = r.get("employee_min") or r.get("employee_max") or ""
            try: return int(v)
            except: return 0
        rows = [r for r in rows if _emp_min(r) >= args.min_employees]
    if args.max_employees is not None:
        def _emp_max(r):
            v = r.get("employee_max") or r.get("employee_min") or ""
            try: return int(v)
            except: return 999999
        rows = [r for r in rows if _emp_max(r) <= args.max_employees]

    print(f"Companies: {len(rows)} total")
    print(f"  MeetLeo: {'ON' if use_meetleo else 'OFF' + ('' if args.no_meetleo else ' (no password)')}")
    print(f"  Apollo:  {'ON' if use_apollo  else 'OFF' + ('' if args.no_apollo  else ' (no API key)')}")
    print(f"  PDL:     {'ON' if use_pdl     else 'OFF' + ('' if args.no_pdl     else ' (no API key)')}")
    print()

    session = requests.Session()

    # ------------------------------------------------------------------
    # Phase 1: MeetLeo (batch parallel — submit all jobs, poll together)
    # ------------------------------------------------------------------
    ml_checkpoint: dict[int, dict] = {}
    if use_meetleo:
        if args.fresh and MEETLEO_CHECKPOINT_FILE.exists():
            MEETLEO_CHECKPOINT_FILE.unlink()
        ml_checkpoint = load_meetleo_checkpoint()
        ml_pending = [r for r in rows if int(r["id"]) not in ml_checkpoint]
        print(f"MeetLeo: {len(ml_checkpoint)} in checkpoint, {len(ml_pending)} to process")

        # Verify token works before starting
        token = meetleo_get_token(session)
        if not token:
            print("  MeetLeo: could not obtain token — skipping")
            use_meetleo = False
        else:
            ml_found = ml_enriched = 0
            for batch_start in range(0, len(ml_pending), MEETLEO_BATCH_SIZE):
                batch = ml_pending[batch_start: batch_start + MEETLEO_BATCH_SIZE]
                batch_end = min(batch_start + MEETLEO_BATCH_SIZE, len(ml_pending))
                print(f"  Batch {batch_start + 1}–{batch_end} / {len(ml_pending)}")
                batch_results = run_meetleo_batch(batch, session, ml_checkpoint)
                for cid, res in batch_results.items():
                    ml_checkpoint[cid] = res
                    if res["contacts"] or res["hq_phone"]:
                        ml_found += 1
                    if res["contacts"]:
                        ml_enriched += 1
                        for c in res["contacts"]:
                            print(f"    {batch[0]['canonical_name'] if len(batch)==1 else ''} "
                                  f"{c['title'] or '(no title)'}: {c['full_name']} "
                                  f"{'✉ ' + c['email'] if c['email'] else ''}")
            print(f"  MeetLeo done: {ml_found} companies found, {ml_enriched} with contacts\n")

    # Write HQ phones CSV (companies where MeetLeo returned an hqPhone)
    hq_rows = [
        {"id": cid, "phone": rec["hq_phone"]}
        for cid, rec in ml_checkpoint.items()
        if rec.get("hq_phone")
    ]
    if hq_rows:
        with open(hq_phone_file, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["id", "phone"])
            writer.writeheader()
            writer.writerows(hq_rows)
        print(f"HQ phones: {len(hq_rows)} companies → {hq_phone_file}")

    # ------------------------------------------------------------------
    # Phase 2: Apollo + PDL (sequential per company)
    # ------------------------------------------------------------------
    checkpoint = {} if args.fresh else load_checkpoint()
    if args.fresh and CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()
        checkpoint = {}

    pending = [r for r in rows if int(r["id"]) not in checkpoint]
    print(f"\nApollo/PDL: {len(checkpoint)} in checkpoint, {len(pending)} to process")

    all_contacts: list[dict] = []
    apollo_hits = pdl_hits = both_hits = ml_hits = 0

    for i, row in enumerate(pending, 1):
        company_id   = int(row["id"])
        company_name = row["canonical_name"]
        print(f"[{i}/{len(pending)}] {company_name}")

        ap_pdl_contacts = [] if (not use_apollo and not use_pdl) else \
            find_contacts_for_company(row, session, args)
        save_checkpoint(company_id, ap_pdl_contacts)
        checkpoint[company_id] = ap_pdl_contacts

        for c in ap_pdl_contacts:
            src = c.get("source", "")
            if src == "both":   both_hits  += 1
            elif src == "apollo": apollo_hits += 1
            elif src == "pdl":    pdl_hits    += 1

        if not ap_pdl_contacts:
            print("  (no contacts from Apollo/PDL)")
        time.sleep(0.3)

    # ------------------------------------------------------------------
    # Merge all sources and write final CSV
    # ------------------------------------------------------------------
    for row in rows:
        cid  = int(row["id"])
        name = row["canonical_name"]

        ml_contacts  = [dict(c, company_id=cid, company_name=name)
                        for c in (ml_checkpoint.get(cid) or {}).get("contacts", [])]
        ap_pdl       = [dict(c, company_id=cid, company_name=name)
                        for c in checkpoint.get(cid, [])]

        merged = _merge_into(ml_contacts, ap_pdl)
        for c in merged:
            if c.get("source") == "meetleo":
                ml_hits += 1
        all_contacts.extend(merged)

    fieldnames = ["company_id", "company_name", "full_name", "first_name", "last_name",
                  "title", "email", "phone", "linkedin_url", "source", "notes"]

    with open(out_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_contacts)

    with_phone = sum(1 for c in all_contacts if c.get("phone"))
    with_email = sum(1 for c in all_contacts if c.get("email"))

    print(f"\nWrote {len(all_contacts)} contacts ({len(rows)} companies) to {out_file}")
    print(f"  With phone: {with_phone} | With email: {with_email}")
    print(f"  Sources: MeetLeo={ml_hits}, Apollo={apollo_hits}, PDL={pdl_hits}, Both={both_hits}")

    rails = Path(__file__).parent.parent
    print(f"\nImport contacts:")
    print(f"  cd {rails} && bin/rails contacts:import[{out_file}]")
    if hq_rows:
        print(f"\nImport HQ phones:")
        print(f"  cd {rails} && bin/rails companies:import_phones[{hq_phone_file}]")
    print(f"\nExport cold-call list:")
    print(f"  bin/rails contacts:export_with_phone")


if __name__ == "__main__":
    main()
