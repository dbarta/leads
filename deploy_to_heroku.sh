#!/usr/bin/env bash
# Push the local database to Heroku and restart the app.
# Run this after any local enrichment/import work to sync Heroku.
#
# Usage:
#   ./deploy_to_heroku.sh           # push DB + restart
#   ./deploy_to_heroku.sh --code    # also git push (deploy code changes)

set -euo pipefail

APP="odeca-leads"
LOCAL_DB="jumpstart_development"

# ── helpers ──────────────────────────────────────────────────────────────────
info()  { echo "▶  $*"; }
ok()    { echo "✓  $*"; }
die()   { echo "✗  $*" >&2; exit 1; }

# ── preflight ────────────────────────────────────────────────────────────────
command -v heroku &>/dev/null || die "heroku CLI not found"
heroku whoami &>/dev/null      || die "not logged in to Heroku (run: heroku login)"

# ── optional: push code first ─────────────────────────────────────────────
if [[ "${1:-}" == "--code" ]]; then
  info "Pushing code to Heroku..."
  git push heroku main
  ok "Code deployed"
fi

# ── reset + push database ────────────────────────────────────────────────────
info "Resetting Heroku Postgres (retrying up to 3x on 504)..."
for attempt in 1 2 3; do
  if heroku pg:reset DATABASE_URL --app "$APP" --confirm "$APP" 2>&1; then
    break
  fi
  [[ $attempt -eq 3 ]] && die "pg:reset failed after 3 attempts"
  info "  Attempt $attempt failed, retrying in 15s..."
  sleep 15
done
ok "Database reset"

info "Pushing $LOCAL_DB → Heroku..."
# Use pg17 tools to match local server version; avoids "server version mismatch" error
PATH="/opt/homebrew/opt/postgresql@17/bin:$PATH" heroku pg:push "$LOCAL_DB" DATABASE_URL --app "$APP" || true
ok "Database pushed"

# ── fix environment stamp ────────────────────────────────────────────────────
info "Stamping database as production..."
heroku run --no-tty --app "$APP" "rails db:environment:set RAILS_ENV=production" 2>&1 | grep -v "^Running\|^$" || true
ok "Environment stamped"

# ── create secondary schema tables (cache / queue / cable) ───────────────────
info "Loading cache/queue/cable schemas..."
heroku run --no-tty --app "$APP" \
  "DISABLE_DATABASE_ENVIRONMENT_CHECK=1 rails db:schema:load:cache && \
   DISABLE_DATABASE_ENVIRONMENT_CHECK=1 rails db:schema:load:queue && \
   DISABLE_DATABASE_ENVIRONMENT_CHECK=1 rails db:schema:load:cable" \
  2>&1 | grep -v "^Running\|^$" || true
ok "Secondary schemas loaded"

# ── restart ──────────────────────────────────────────────────────────────────
info "Restarting dynos..."
heroku restart --app "$APP"

# ── verify ───────────────────────────────────────────────────────────────────
info "Verifying record counts..."
heroku run --no-tty --app "$APP" \
  "rails runner 'puts \"Companies: #{Company.count} | Airports: #{Airport.count} | Contacts: #{Contact.count}\"'" \
  2>&1 | grep -E "Companies:|Error"

echo ""
ok "Done → https://$(heroku domains --app $APP 2>/dev/null | grep herokuapp | head -1 || echo "${APP}.herokuapp.com")"
