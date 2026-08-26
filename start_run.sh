#!/usr/bin/env bash
# start_run.sh — Prepare a new data collection run.
#
# Usage:
#   ./start_run.sh "Run 2 — DFW / DEN / SEA / ATL"
#
# What it does:
#   1. Dumps local DB to backups/before_runN_YYYYMMDD.dump
#   2. Triggers a Heroku manual backup
#   3. Creates the Run record in local DB (status: in_progress)
#   4. Prints the new run ID and next steps
#
# Restore local DB if run goes wrong:
#   pg_restore --clean -d leads_development backups/<file>.dump
#
# Restore Heroku DB:
#   heroku pg:backups:restore <backup_id> DATABASE_URL --app odeca-leads

set -e

RUN_NAME="${1:-}"
if [[ -z "$RUN_NAME" ]]; then
  echo "Usage: ./start_run.sh \"Run 2 — DFW / DEN / SEA / ATL\""
  exit 1
fi

DATE=$(date +%Y%m%d)
DUMP_FILE="backups/before_$(echo "$RUN_NAME" | sed 's/[^a-zA-Z0-9]/_/g' | tr '[:upper:]' '[:lower:]' | sed 's/__*/_/g' | sed 's/^_//;s/_$//').dump"

echo ""
echo "=========================================="
echo "  Starting: $RUN_NAME"
echo "=========================================="
echo ""

# Step 1: Local DB snapshot
echo "→ [1/3] Creating local DB snapshot..."
PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH" \
  pg_dump -Fc leads_development -f "$DUMP_FILE"
echo "  Saved: $DUMP_FILE"
echo ""

# Step 2: Heroku backup
echo "→ [2/3] Triggering Heroku backup..."
heroku pg:backups:capture --app odeca-leads
echo ""

# Step 3: Create Run record
echo "→ [3/3] Creating Run record in DB..."
RUN_ID=$(bin/rails runner "
run = Run.create!(
  name: '${RUN_NAME}',
  started_at: Time.current
)
puts run.id
" 2>&1 | grep -v VIPS | grep -v 'libheif\|x265\|dlopen\|Referenced\|Reason\|tried\|Volumes\|Cellar' | tail -1)

echo "  Run ID: $RUN_ID"
echo ""
echo "=========================================="
echo "  Ready. Run ID = $RUN_ID"
echo ""
echo "  Next steps:"
echo "  1. Crawl airport websites:"
echo "       python python/airport_crawler.py DFW DEN SEA ATL"
echo ""
echo "  2. Import companies (tag with run_id=$RUN_ID):"
echo "       bin/rails companies:import_csv[file,run_id=$RUN_ID]"
echo ""
echo "  3. Score 561720 companies for aviation fit:"
echo "       python python/score_aviation_fit.py"
echo ""
echo "  4. Find contacts:"
echo "       python python/find_contacts.py"
echo ""
echo "  5. Enrich phone + email:"
echo "       TWILIO_ACCOUNT_SID=... TWILIO_AUTH_TOKEN=... python python/fullenrich_contacts.py"
echo ""
echo "  If something goes wrong, restore local DB with:"
echo "    pg_restore --clean -d leads_development $DUMP_FILE"
echo "=========================================="
