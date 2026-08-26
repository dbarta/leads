#!/usr/bin/env python3
"""
One-off test: search MeetLeo for a company by exact name, then enrich using
the prospectId from search (instead of re-using the name filter).
"""
import json, os, time
import requests

AUTH_URL    = "https://users.meetleo.com/auth/token"
SEARCH_URL  = "https://api.meetleo.com/v1/prospects/search"
ENRICH_URL  = "https://api.meetleo.com/v1/prospects/enrich"
JOBS_URL    = "https://api.meetleo.com/v1/jobs"

EMAIL    = os.environ.get("MEETLEO_EMAIL", "jonathan@jeffersonfinancialins.com")
PASSWORD = os.environ.get("MEETLEO_PASSWORD", "")
COMPANY  = "Airport Terminal Management Inc"

session = requests.Session()

# ── 1. Auth ───────────────────────────────────────────────────────────────────
r = session.post(AUTH_URL, json={"email": EMAIL, "password": PASSWORD}, timeout=15)
r.raise_for_status()
token = r.json()["accessToken"]
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
print(f"Authenticated OK\n")

# ── 2. Search ─────────────────────────────────────────────────────────────────
r = session.post(SEARCH_URL, headers=headers,
                 json={"filters": [{"prospectName": COMPANY}], "page": 1, "limit": 5},
                 timeout=15)
r.raise_for_status()
prospects = r.json().get("data", {}).get("prospects", [])
print(f"Search results ({len(prospects)}):")
for p in prospects:
    print(f"  prospectId={p.get('prospectId')}  name={p.get('standardCompanyName')!r}  "
          f"state={p.get('state')!r}  hqPhone={p.get('hqPhone')!r}")
print()

if not prospects:
    print("No results — stopping.")
    raise SystemExit(1)

# Pick first result and note its prospectId
chosen = prospects[0]
prospect_id = chosen["prospectId"]
print(f"Using prospectId={prospect_id}  name={chosen.get('standardCompanyName')!r}\n")

# ── 3. Enrich using prospectId ────────────────────────────────────────────────
print(f"Submitting enrich with filter {{'prospectId': {prospect_id}}} ...")
r = session.post(ENRICH_URL, headers=headers,
                 json={"filters": [{"prospectId": prospect_id}], "maxProspects": 1},
                 timeout=15)
print(f"  HTTP {r.status_code}")
print(f"  Body: {r.text[:500]}\n")

if r.status_code != 202:
    print("Enrich submit failed — stopping.")
    raise SystemExit(1)

task_id = r.json()["data"]["taskId"]
print(f"taskId={task_id}")

# ── 4. Poll until done ────────────────────────────────────────────────────────
for i in range(36):
    time.sleep(10)
    r = session.get(f"{JOBS_URL}/{task_id}", headers=headers, timeout=15)
    if r.status_code != 200:
        print(f"  poll {i+1}: HTTP {r.status_code}")
        continue
    data = r.json().get("data", {})
    status = data.get("status")
    print(f"  poll {i+1}: status={status!r}", end="")
    if status in ("completed", "failed"):
        print()
        print("\nFull job response:")
        print(json.dumps(data, indent=2))
        break
    print("  (waiting...)")
