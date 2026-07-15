#!/usr/bin/env python3
"""Convert an existing enrichment CSV into a checkpoint JSONL so the next
enrich_companies.py run skips already-processed companies."""
import csv, json, sys
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "output"
CHECKPOINT = OUTPUT_DIR / "checkpoint.jsonl"

# Use the most recent enrichment CSV
if len(sys.argv) > 1:
    src = Path(sys.argv[1])
else:
    csvs = sorted(OUTPUT_DIR.glob("enrichment_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not csvs:
        print("No enrichment CSV found"); sys.exit(1)
    src = csvs[0]

print(f"Building checkpoint from {src}")
rows = list(csv.DictReader(open(src)))
with open(CHECKPOINT, "w") as f:
    for row in rows:
        f.write(json.dumps(row) + "\n")
print(f"Wrote {len(rows)} entries to {CHECKPOINT}")
