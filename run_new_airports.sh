#!/bin/bash
# Pipeline: crawl 10 new airports → import → enrich → import enrichment
# Run from /Users/dbarta/leads/leads

set -e
LEADS_DIR="/Users/dbarta/leads/leads"
cd "$LEADS_DIR"

LOG=/tmp/new_airports_pipeline.log
exec > >(tee -a "$LOG") 2>&1

echo ""
echo "========================================="
echo "New airports pipeline — $(date)"
echo "========================================="

# ── Step 1: ACDBE search (DuckDuckGo → PDFs) for all 10 airports ────────────
echo ""
echo "--- Step 1: search_acdbe.py for ATL DFW LAS CLT PHX MCO IAH MIA MSP DTW ---"
python -u python/search_acdbe.py ATL DFW LAS CLT PHX MCO IAH MIA MSP DTW \
    --delay 2.5 2>&1 | tee /tmp/acdbe_search.log &
ACDBE_PID=$!

# ── Step 2: Direct crawler for 6 airports not yet crawled ───────────────────
echo ""
echo "--- Step 2: airport_crawler.py for LAS PHX MCO IAH MIA MSP ---"
python -u python/airport_crawler.py LAS PHX MCO IAH MIA MSP \
    2>&1 | tee /tmp/crawl_new.log &
CRAWLER_PID=$!

echo "Crawlers running (ACDBE PID=$ACDBE_PID, Crawler PID=$CRAWLER_PID) — waiting..."
wait $ACDBE_PID
echo "search_acdbe.py finished at $(date)"
wait $CRAWLER_PID
echo "airport_crawler.py finished at $(date)"

# ── Step 3: Import all new airport CSVs ────────────────────────────────────
echo ""
echo "--- Step 3: Importing all new airport CSVs ---"
AIRPORTS="ATL DFW LAS CLT PHX MCO IAH MIA MSP DTW"
for FAA in $AIRPORTS; do
    for f in python/output/${FAA}_*_companies.csv; do
        if [ -f "$f" ]; then
            COUNT=$(tail -n +2 "$f" | wc -l | tr -d ' ')
            echo "Importing $f ($COUNT rows)..."
            bin/rails "companies:import_csv[$f]"
        fi
    done
done

echo ""
echo "--- Database state after import ---"
bin/rails runner "
Airport.joins(:companies).group('airports.faa_code, airports.name') \
  .select('airports.faa_code, airports.name, count(distinct companies.id) as co_count') \
  .order('co_count desc') \
  .each { |a| puts \"  #{a.faa_code}: #{a.co_count}\" }
puts \"Total: #{Company.count} companies\"
"

# ── Step 4: Export for enrichment ──────────────────────────────────────────
echo ""
echo "--- Step 4: Exporting for enrichment ---"
bin/rails companies:export_for_enrichment

# ── Step 5: Run enrichment (Apollo+BBB+OpenCorp+FMCSA; SAM skipped — quota) ─
echo ""
echo "--- Step 5: Running enrichment (skip SAM, resume from checkpoint) ---"
APOLLO_API_KEY=hwc04Ivj4QleZ3ooZl0Wqw \
    python -u python/enrich_companies.py \
        --skip-sam --sam-only --no-website \
        2>&1 | tee /tmp/enrich_new_airports.log

# ── Step 6: Import enrichment results ──────────────────────────────────────
echo ""
echo "--- Step 6: Importing enrichment results ---"
LATEST=$(ls -t python/output/enrichment_*.csv | head -1)
echo "Importing $LATEST..."
bin/rails "companies:import_enrichment[$LATEST]"

# ── Step 7: Final summary ───────────────────────────────────────────────────
echo ""
echo "--- Final summary ---"
bin/rails runner "
total   = Company.count
w_emp   = Company.where.not(employee_min: nil).count
w_naics = Company.where.not(naics_codes: [nil, '']).count
w_web   = Company.where.not(website: [nil, '']).count
puts \"Total companies: #{total}\"
puts \"With numeric employees: #{w_emp} (#{(w_emp*100.0/total).round}%)\"
puts \"With NAICS codes:  #{w_naics} (#{(w_naics*100.0/total).round}%)\"
puts \"With website:      #{w_web}  (#{(w_web*100.0/total).round}%)\"
puts ''
puts 'By airport:'
Airport.joins(:companies).group('airports.faa_code') \
  .select('airports.faa_code, count(distinct companies.id) as co_count') \
  .order('co_count desc') \
  .each { |a| puts \"  #{a.faa_code}: #{a.co_count}\" }
"

echo ""
echo "========================================="
echo "Pipeline complete — $(date)"
echo "========================================="
