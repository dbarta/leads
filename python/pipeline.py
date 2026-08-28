#!/usr/bin/env python3
"""
Full pipeline orchestrator for airport lead generation.

Stages (per airport, in order):
  1  discover    — scrape airport website, import new companies to DB
  2  fullenrich  — FullEnrich people search + bulk enrich + Twilio verify + import contacts
  3  contacts    — MeetLeo + PDL contact search → CSV → auto-import to DB
  4  sam         — SAM.gov .dat match → CSV → auto-import (global, runs once at end)
  5  enrich      — company NAICS/CAGE enrichment → CSV → auto-import

Before stage 1: refreshes companies_for_enrichment.csv from DB (rake companies:export_for_enrichment).
After  stage 1: refreshes again so stages 3/5 see newly imported companies.

Usage:
  python pipeline.py --airport SFO --dry-run
  python pipeline.py --airport OAK SJC SMF --run-id 2
  python pipeline.py --airport OAK --stages 1,2
  python pipeline.py --airport SFO --stages 4        # SAM only
"""

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PYTHON_DIR  = Path(__file__).parent
RAILS_ROOT  = PYTHON_DIR.parent
LOG_DIR     = PYTHON_DIR / "logs"

STAGE_NAMES = {
    1: "discover",
    2: "fullenrich",
    3: "contacts",
    4: "sam",
    5: "enrich",
}

# ── Logging ─────────────────────────────────────────────────────────────────

class Tee:
    """Writes to both a file and a stream simultaneously."""
    def __init__(self, path: Path, stream=sys.stdout):
        self._f = open(path, "a", buffering=1)
        self._s = stream

    def write(self, text: str):
        self._f.write(text)
        self._s.write(text)

    def flush(self):
        self._f.flush()
        self._s.flush()

    def close(self):
        self._f.close()


def banner(tee: Tee, text: str, char: str = "═"):
    width = 70
    line = char * width
    tee.write(f"\n{line}\n  {text}\n{line}\n")


_rails_creds_cache: dict | None = None

def _inject_rails_credentials(env: dict) -> None:
    """Load API credentials from Rails encrypted credentials file and inject into env."""
    global _rails_creds_cache
    if _rails_creds_cache is None:
        try:
            import subprocess as _sp, yaml as _yaml
            result = _sp.run(
                ["bin/rails", "credentials:show", "--environment", "production"],
                capture_output=True, text=True, cwd=RAILS_ROOT,
            )
            _rails_creds_cache = _yaml.safe_load(result.stdout) or {}
        except Exception:
            _rails_creds_cache = {}

    c = _rails_creds_cache
    mapping = {
        "TWILIO_ACCOUNT_SID":  c.get("twilio", {}).get("account_sid"),
        "TWILIO_AUTH_TOKEN":   c.get("twilio", {}).get("auth_token"),
        "MEETLEO_EMAIL":       c.get("meetleo", {}).get("email"),
        "MEETLEO_PASSWORD":    c.get("meetleo", {}).get("password"),
        "PDL_API_KEY":         c.get("pdl", {}).get("api_key"),
        "FULLENRICH_API_KEY":  c.get("fullenrich", {}).get("api_key"),
        "APOLLO_API_KEY":      c.get("apollo", {}).get("api_key"),
        "SAM_GOV_API_KEY":     c.get("sam_gov", {}).get("api_key"),
    }
    for k, v in mapping.items():
        if v:
            env.setdefault(k, str(v))


def run_stage(tee: Tee, label: str, cmd: list[str], dry_run: bool = False) -> bool:
    """Run a subprocess, tee-ing output. Returns True on success."""
    tee.write(f"\n▶ {label}\n")
    tee.write(f"  $ {' '.join(str(c) for c in cmd)}\n\n")
    tee.flush()

    t0 = time.monotonic()
    env = os.environ.copy()
    _inject_rails_credentials(env)
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=RAILS_ROOT,
        env=env,
    )
    for line in proc.stdout:
        tee.write(line)
        tee.flush()
    proc.wait()
    elapsed = time.monotonic() - t0
    ok = proc.returncode == 0
    status = "OK" if ok else f"FAILED (exit {proc.returncode})"
    tee.write(f"\n  → {label}: {status} in {elapsed:.1f}s\n")
    tee.flush()
    return ok


def rails_task(tee: Tee, task: str) -> bool:
    return run_stage(tee, f"rake {task}", ["bin/rails", task])


def refresh_csv(tee: Tee) -> bool:
    return rails_task(tee, "companies:export_for_enrichment")


# ── Stage runners ────────────────────────────────────────────────────────────

def stage1_discover(tee: Tee, airports: list[str], run_id: int, dry_run: bool) -> bool:
    cmd = [
        sys.executable, str(PYTHON_DIR / "discover_airport_companies.py"),
        "--airport", *airports,
        "--run-id", str(run_id),
    ]
    if not dry_run:
        cmd.append("--import")
    else:
        cmd.append("--dry-run")
    return run_stage(tee, "Company discovery", cmd, dry_run)


def stage2_fullenrich(tee: Tee, airports: list[str], run_id: int, dry_run: bool) -> bool:
    all_ok = True
    for iata in airports:
        cmd = [
            sys.executable, str(PYTHON_DIR / "fullenrich_find_sfo_contacts.py"),
            "--airport", iata,
            "--run-id", str(run_id),
        ]
        if not dry_run:
            cmd.append("--import")
        ok = run_stage(tee, f"FullEnrich contacts [{iata}]", cmd, dry_run)
        if not ok:
            all_ok = False
    return all_ok


def stage3_contacts(tee: Tee, airports: list[str], run_id: int, dry_run: bool) -> bool:
    cmd = [
        sys.executable, str(PYTHON_DIR / "find_contacts.py"),
        "--airport", *airports,
    ]
    ok = run_stage(tee, "MeetLeo/PDL contact search", cmd, dry_run)
    if not ok or dry_run:
        return ok
    # Auto-import: find the freshest contacts CSV written
    output_dir = PYTHON_DIR / "output"
    csvs = sorted(output_dir.glob("contacts_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if csvs:
        contacts_csv = csvs[0]
        tee.write(f"\n  Importing {contacts_csv.name} …\n")
        ok2 = run_stage(tee, "contacts:import", [
            "bin/rails", f"contacts:import[{contacts_csv}]"
        ])
        # Also import HQ phones if present
        phone_csvs = sorted(output_dir.glob("hq_phones_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
        if phone_csvs:
            phone_csv = phone_csvs[0]
            run_stage(tee, "companies:import_phones", [
                "bin/rails", f"companies:import_phones[{phone_csv}]"
            ])
        return ok2
    return ok


def stage4_sam(tee: Tee, dry_run: bool) -> bool:
    cmd = [sys.executable, str(PYTHON_DIR / "parse_sam_data.py")]
    ok = run_stage(tee, "SAM.gov match", cmd, dry_run)
    if not ok or dry_run:
        return ok
    output_dir = PYTHON_DIR / "output"
    sam_csvs = sorted(output_dir.glob("sam_enrichment*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if sam_csvs:
        sam_csv = sam_csvs[0]
        run_stage(tee, "companies:import_sam", ["bin/rails", f"companies:import_sam[{sam_csv}]"])
    sam_contact_csvs = sorted(output_dir.glob("sam_contacts*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if sam_contact_csvs:
        sc_csv = sam_contact_csvs[0]
        run_stage(tee, "contacts:import (SAM)", ["bin/rails", f"contacts:import[{sc_csv}]"])
    return ok


def stage5_enrich(tee: Tee, airports: list[str], dry_run: bool) -> bool:
    cmd = [
        sys.executable, str(PYTHON_DIR / "enrich_companies.py"),
        "--airport", *airports,
    ]
    ok = run_stage(tee, "Company enrichment", cmd, dry_run)
    if not ok or dry_run:
        return ok
    output_dir = PYTHON_DIR / "output"
    enrich_csvs = sorted(output_dir.glob("enrichment_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    if enrich_csvs:
        e_csv = enrich_csvs[0]
        run_stage(tee, "companies:import_enrichment", ["bin/rails", f"companies:import_enrichment[{e_csv}]"])
    return ok


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Airport leads pipeline orchestrator")
    parser.add_argument("--airport", nargs="+", required=True, metavar="IATA",
                        help="One or more airport IATA codes (e.g. SFO OAK)")
    parser.add_argument("--run-id", type=int, default=2,
                        help="Run ID to tag new records (default: 2)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and extract but do not write to DB or spend API credits")
    parser.add_argument("--stages", default="1,2,3,4,5",
                        help="Comma-separated stage numbers to run (default: 1,2,3,4,5)")
    args = parser.parse_args()

    airports = [a.upper() for a in args.airport]
    stages   = {int(s.strip()) for s in args.stages.split(",")}

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    iata_str = "_".join(airports)
    log_path = LOG_DIR / f"pipeline_{ts}_{iata_str}.log"

    tee = Tee(log_path)

    banner(tee, f"Airport Pipeline  |  airports: {', '.join(airports)}  |  {'DRY RUN' if args.dry_run else f'run_id={args.run_id}'}")
    tee.write(f"Log: {log_path}\n")
    tee.write(f"Stages: {sorted(stages)}\n")

    results = {}
    t_total = time.monotonic()

    # Refresh CSV before stage 1 so stages 3/5 start from a known-good baseline
    if stages & {1, 3, 5}:
        banner(tee, "Pre-flight: refresh companies_for_enrichment.csv", char="─")
        refresh_csv(tee)

    # ── Stage 1: Company discovery ──────────────────────────────────────────
    if 1 in stages:
        banner(tee, "Stage 1: Company Discovery")
        ok = stage1_discover(tee, airports, args.run_id, args.dry_run)
        results[1] = ok
        if ok and not args.dry_run and stages & {3, 5}:
            tee.write("\n  Refreshing companies CSV after import …\n")
            refresh_csv(tee)

    # ── Stage 2: FullEnrich contact discovery ───────────────────────────────
    if 2 in stages:
        banner(tee, "Stage 2: FullEnrich Contact Discovery")
        results[2] = stage2_fullenrich(tee, airports, args.run_id, args.dry_run)

    # ── Stage 3: MeetLeo/PDL contact search ────────────────────────────────
    if 3 in stages:
        banner(tee, "Stage 3: MeetLeo/PDL Contact Search")
        results[3] = stage3_contacts(tee, airports, args.run_id, args.dry_run)

    # ── Stage 4: SAM.gov enrichment (global) ───────────────────────────────
    if 4 in stages:
        banner(tee, "Stage 4: SAM.gov Enrichment (global)")
        results[4] = stage4_sam(tee, args.dry_run)

    # ── Stage 5: Company enrichment ─────────────────────────────────────────
    if 5 in stages:
        banner(tee, "Stage 5: Company Enrichment (NAICS/CAGE)")
        results[5] = stage5_enrich(tee, airports, args.dry_run)

    # ── Summary ─────────────────────────────────────────────────────────────
    elapsed = time.monotonic() - t_total
    banner(tee, f"Pipeline Complete  |  total time: {elapsed:.0f}s")
    for s in sorted(results):
        icon = "✓" if results[s] else "✗"
        tee.write(f"  {icon}  Stage {s}: {STAGE_NAMES[s]}\n")
    any_failed = any(not v for v in results.values())
    tee.write(f"\nLog saved to: {log_path}\n")
    tee.close()

    sys.exit(1 if any_failed else 0)


if __name__ == "__main__":
    main()
