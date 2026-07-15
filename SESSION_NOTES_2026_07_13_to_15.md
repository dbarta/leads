# Session Notes: July 13–15, 2026

## Goals

1. Enrich the airport service company database with employee counts, NAICS codes, CAGE codes, and phone numbers so we can identify prime GL insurance prospects.
2. Find CFO/finance decision-maker contacts at those companies — email and phone — using MeetLeo (primary), Apollo, and People Data Labs (PDL).
3. Add a CSV export button to the Companies index view, plus Phone and Top Contact columns.
4. Deploy everything to Heroku.

---

## What Was Accomplished

### Database Growth
- Started: ~312 companies (LAX, SFO, ORD/MDW/JFK)
- Added 10 new airports: ATL, DFW, LAS, CLT, PHX, MCO, IAH, MIA, MSP, DTW via `airport_crawler.py`
- Final count: **407 companies** (after deleting 3 junk records)
- MCO, IAH, MIA, MSP returned 0 companies — no usable data from crawlers for those airports

### Enrichment Pipeline (`python/enrich_companies.py`)
The enrichment script hits multiple data sources per company:
- **SAM.gov Entity API** — CAGE code, NAICS, registration status, employee count
- **NAICS inference** — from service categories and company name (fallback)
- **People Data Labs (PDL)** — LinkedIn-based employee count + size range + NAICS
- **FMCSA SAFER** — DOT number, driver count, power units (ground transport only)
- **OpenCorporates** — dissolution/inactive status check
- **BBB** — existence confirmation and business category
- **Website scraping** — employee count extraction from about/careers pages

Food-only companies (all service categories are food/catering) are excluded from enrichment exports (`export_for_enrichment` rake task).

#### SAM.gov Results: 0 CAGE Codes
Despite multiple runs consuming the daily API quota, the `legalBusinessName` exact-match search returned 0 results for all 400+ companies. The airport-sourced company names don't match SAM's legal name format exactly (e.g., "ACCUFLEET INTERNATIONAL INC" vs "AccuFleet International Inc"). The `_sam_search()` function in `enrich_companies.py` needs to be updated to use a partial/wildcard search (`q` param or fuzzy matching) before the next run.

SAM quota resets: **July 16, 2026 00:00 UTC (July 15, 5 PM PDT)**.

#### PDL Results: 79 Companies with Employee Counts
PDL provided LinkedIn-member-based employee counts for 79 companies. These are typically 5–10× lower than actual headcount (e.g., Swissport: 60,000 reported by PDL, but actually 70,000 globally). Still useful for rough filtering.

After importing enrichment: **254 companies have NAICS codes** (64%), **108 have numeric employee data**.

### Contact Discovery (`python/find_contacts.py`)

#### MeetLeo Integration (Written from Scratch)
- Two-step flow: free search → async enrichment job (credits charged only when email found)
- Parallel batch processing: up to 20 jobs submitted simultaneously, polled in parallel
- Name shortening: strips legal/industry suffixes iteratively (`llc`, `inc`, `international`, `aviation`, `services`, `svcs`, `security`, etc.) to get a distinctive keyword for `prospectName` filter
- Domain-first search: tries `websiteUrl` first, falls back to shortened name
- Name similarity threshold: 0.70 minimum to avoid matching wrong companies
- Account: jonathan@jeffersonfinancialins.com / env var `MEETLEO_PASSWORD`
- Credits available: ~9,000 (charges only on email found)

**Key bugs fixed during development:**
1. `companyName` filter returns 422 — correct key is `prospectName`
2. Full legal name in `prospectName` matches on generic words ("INTERNATIONAL INC") — fixed by stripping suffixes
3. `websiteUrl` returns 0 results for most companies — fixed by falling back to name search
4. "PrimeFlight Aviation Svcs" matched "CHOICE AVIATION SERVICES" at 0.70 similarity — fixed by adding `svcs`, `svc` to suffix regex

**MeetLeo run results:**
- Ran on 20 companies with `employee_min` 100–7500 (PDL data)
- Found contacts for 1 company: Viasat, Inc. (VP-CTO Craig Miller, Chairman/CEO Mark Dankberg)
- Low hit rate because PDL undercounts employees — most target-sized companies show <100 in PDL data
- 28 large companies (Swissport, Menzies, ABM, etc.) excluded by 7500 cap
- **Recommendation:** Run MeetLeo on large companies (Swissport, Menzies, ABM, Unifi, etc.) separately — remove or raise the `--max-employees` cap

#### PDL Contacts (Earlier Run)
PDL returned executive contacts for 3 companies:
- **Black Knight Patrol, Inc.** — CEO Manuel Jimenez, Deputy CEO Ed Salaz, **CFO Rosie Jackson**, Director of Finance Jesus Olivarez (LinkedIn only, no email)
- **Air Fayre CA Inc** — CEO Allison Budd, SVP Kenneth Jamison, multiple General Managers (LinkedIn only)
- **Calop Aeroground Services** — SVP Salim Rashad (LinkedIn only)

**Total contacts in DB: 13** (2 with email, 0 with direct phone)

### Phone Numbers
- Scraped 56 company phones from websites via `scrape_phones.py`
- 13 additional HQ phones from MeetLeo
- **Total: 63 companies with phone numbers**

### Rails UI Changes

#### Companies Index (`app/views/companies/index.html.erb`)
- **Export CSV button** — exports filtered view (respects all active filter params) as downloadable CSV
- **Phone column** — shows company main phone with `tel:` link
- **Top Contact column** — shows best GL contact per company (GL title priority: owner/president/CEO > CFO/controller/finance director > risk manager/director of risk)
- GL contact selection implemented in `CompaniesController#top_contacts_for` with `GL_TITLE_PRIORITY` constant

#### Contacts Index (NEW — `app/views/contacts/index.html.erb`)
New top-level view at `/contacts` showing all found contacts with:
- Name, Title, Contact Info (email with mailto, phone with tel:, LinkedIn link)
- Company (linked to company show page), company phone
- Airports (FAA code badges, each linked to airport show)
- Qualification badge
- Source badge (MEETLEO, APOLLO, PDL)
- Filter bar: search (name/title/email), qualification status, source, has-email/has-phone checkboxes
- Sort by name, title, source
- Export CSV button (respects filters)

#### Routes
```ruby
resources :contacts, only: [:index] do
  collection { get :export }
end
```

#### Nav
Added "Contacts" link between "Companies" and "Activity Log" in left nav.

---

## What Still Needs Work

### Priority 1: Fix SAM.gov Search
The `_sam_search()` function in `enrich_companies.py` uses exact `legalBusinessName` matching.
Replace with partial/wildcard search:
```python
params = {
    "api_key": SAM_GOV_API_KEY,
    "q": name,   # wildcard/partial search
    "includeSections": "entityRegistration,coreData,assertions",
    "registrationStatus": "A",
}
```
Or try UEI-based lookup if we can get UEI numbers from another source.

Run after: **July 15, 5 PM PDT** (quota reset).

### Priority 2: More MeetLeo Coverage
Only 20 companies matched the 100–7500 employee filter. Large airport service companies (Swissport, Menzies, ABM, Unifi, Total Airport Services, G2 Secure, ACTS Aviation) were excluded because PDL employee counts represent global headcount.

Suggested next run:
```bash
# Target the large companies directly
MEETLEO_PASSWORD='...' python find_contacts.py --no-apollo --no-pdl --all \
  --ids 235 238 239 295 304 ... # Swissport, Menzies, ABM, etc.
```
Or filter by known-large companies differently (not by employee count).

### Priority 3: Manual Research for 4 Airports
MCO (Orlando), IAH (Houston), MIA (Miami), MSP (Minneapolis) returned 0 companies from automated crawlers. Need manual research or different data sources.

### Priority 4: OpenCorporates Rate Limit
Free tier is 100 requests/day. Get an API token from opencorporates.com for full coverage.

---

## Key Deployment Info

- **App:** https://odeca-leads-eded03cc87a4.herokuapp.com
- **Deploy script:** `./deploy_to_heroku.sh` (DB sync) or `./deploy_to_heroku.sh --code` (code + DB)
- **Heroku app name:** `odeca-leads`
- **Local DB:** `jumpstart_development`
- **Python virtualenv:** `.venv` in `python/` directory

## Key Environment Variables

```
SAM_GOV_API_KEY=SAM-f39c16ee-86eb-4cc0-9202-f700bb1548da
MEETLEO_EMAIL=jonathan@jeffersonfinancialins.com
MEETLEO_PASSWORD=...  # see memory file
APOLLO_API_KEY=...    # see memory file
PDL_API_KEY=...       # see memory file
```

## Useful Commands

```bash
# Export companies for enrichment (skips food-only)
bin/rails companies:export_for_enrichment

# Import enrichment CSV
bin/rails companies:import_enrichment[python/output/enrichment_YYYYMMDD_HHMMSS.csv]

# Import contacts
bin/rails contacts:import[python/output/contacts_YYYYMMDD_HHMMSS.csv]

# Import HQ phones
bin/rails companies:import_phones[python/output/hq_phones_YYYYMMDD_HHMMSS.csv]

# Run MeetLeo (100-7500 employees)
MEETLEO_PASSWORD='...' python -u python/find_contacts.py --no-apollo --no-pdl --all \
  --min-employees 100 --max-employees 7500 2>&1 | tee python/output/meetleo_run.log

# Deploy to Heroku
./deploy_to_heroku.sh --code   # code + DB
./deploy_to_heroku.sh          # DB only
```
