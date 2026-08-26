#!/usr/bin/env python3
"""
Diagnostic: search + enrich for Airport Terminal Management Inc,
printing full request/response JSON at each step for MeetLeo support.
"""
import json, os, time
import requests

AUTH_URL   = "https://users.meetleo.com/auth/token"
SEARCH_URL = "https://api.meetleo.com/v1/prospects/search"
ENRICH_URL = "https://api.meetleo.com/v1/prospects/enrich"
JOBS_URL   = "https://api.meetleo.com/v1/jobs"

EMAIL    = os.environ.get("MEETLEO_EMAIL", "jonathan@jeffersonfinancialins.com")
PASSWORD = os.environ.get("MEETLEO_PASSWORD", "")

# ATM Inc data from our database
COMPANY_NAME  = "Airport Terminal Management Inc"
AIRPORT_STATE = "CA"   # LAX → CA
NAICS_CODES   = ["561612", "488190", "488510", "485999"]

SIMILARITY_THRESHOLD = 0.70

session = requests.Session()

def separator(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

def name_similarity(a, b):
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()

# ── Auth ──────────────────────────────────────────────────────────────────────
separator("1. AUTHENTICATE")
r = session.post(AUTH_URL, json={"email": EMAIL, "password": PASSWORD}, timeout=15)
r.raise_for_status()
token = r.json()["accessToken"]
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
print("OK — token obtained")

# ── Search ────────────────────────────────────────────────────────────────────
separator("2. SEARCH")
search_filters = [
    {"prospectName": COMPANY_NAME},
    {"state": [AIRPORT_STATE]},
    {"naicsList": NAICS_CODES},
]
search_body = {"filters": search_filters, "page": 1, "limit": 10}

print("REQUEST BODY:")
print(json.dumps(search_body, indent=2))
print()

r = session.post(SEARCH_URL, headers=headers, json=search_body, timeout=15)
print(f"HTTP {r.status_code}")
print("RESPONSE BODY:")
print(json.dumps(r.json(), indent=2))

if r.status_code != 200:
    print("Search failed — stopping.")
    raise SystemExit(1)

prospects = r.json().get("data", {}).get("prospects", [])
print(f"\n→ {len(prospects)} prospects returned")

if not prospects:
    print("0 results — nothing to enrich. Sharing this with MeetLeo support.")
    raise SystemExit(0)

# Pick best name match
best, best_sim = prospects[0], 0.0
for p in prospects:
    s = name_similarity(COMPANY_NAME, p.get("standardCompanyName", ""))
    print(f"  sim={s:.2f}  {p.get('standardCompanyName')}  state={p.get('state')}")
    if s > best_sim:
        best, best_sim = p, s

print(f"\n→ Best match: {best.get('standardCompanyName')!r}  sim={best_sim:.2f}")
if best_sim < SIMILARITY_THRESHOLD:
    print(f"  Below threshold ({SIMILARITY_THRESHOLD}) — no reliable match found.")
    raise SystemExit(0)

# ── Enrich (same filters 1:1) ─────────────────────────────────────────────────
separator("3. ENRICH (same filters as search, 1:1)")
enrich_body = {"filters": search_filters, "maxProspects": 1}

print("REQUEST BODY:")
print(json.dumps(enrich_body, indent=2))
print()

r = session.post(ENRICH_URL, headers=headers, json=enrich_body, timeout=15)
print(f"HTTP {r.status_code}")
print("RESPONSE BODY:")
print(json.dumps(r.json(), indent=2))

if r.status_code != 202:
    print("Enrich submit failed — stopping.")
    raise SystemExit(1)

task_id = r.json()["data"]["taskId"]
poll_url = r.json()["data"].get("pollUrl", f"/v1/jobs/{task_id}")
print(f"\n→ taskId={task_id}  pollUrl={poll_url}")

# ── Poll ──────────────────────────────────────────────────────────────────────
separator("4. POLL JOB")
for i in range(36):
    time.sleep(10)
    r = session.get(f"{JOBS_URL}/{task_id}", headers=headers, timeout=15)
    data = r.json().get("data", {})
    status = data.get("status")
    print(f"  poll {i+1}: status={status!r}")
    if status in ("completed", "failed", "no_email"):
        print("\nFULL JOB RESULT:")
        print(json.dumps(r.json(), indent=2))
        break

print("\nDone.")
