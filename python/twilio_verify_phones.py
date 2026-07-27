#!/usr/bin/env python3
"""
Verify phone numbers via Twilio Lookup API (CNAM + active check).
Cost: $0.01 per lookup.

Usage:
  python twilio_verify_phones.py              # verify all contacts with unverified phones
  python twilio_verify_phones.py --ids 7 42   # verify specific contact IDs
  python twilio_verify_phones.py --dry-run    # show what would be verified, no API calls

Stores per contact:
  phone_verified (bool)       - True if active, False if invalid/dead
  phone_registered_name (str) - CNAM registered name from carrier
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import requests
from requests.auth import HTTPBasicAuth

ACCOUNT_SID = None  # set via --account-sid or TWILIO_ACCOUNT_SID env var
AUTH_TOKEN  = None  # set via --auth-token  or TWILIO_AUTH_TOKEN  env var

RAILS_ROOT = Path(__file__).parent.parent


def rails(code: str) -> str:
    r = subprocess.run(["bin/rails", "runner", code],
                       capture_output=True, text=True, cwd=RAILS_ROOT)
    if r.returncode != 0:
        print(f"Rails error: {r.stderr[:500]}", file=sys.stderr)
        sys.exit(1)
    return r.stdout.strip()


def e164(phone: str) -> str:
    """Normalize to E.164: strip non-digits, add +1 if 10 digits (US)."""
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10:
        digits = "1" + digits
    return f"+{digits}"


def lookup(phone_e164: str, account_sid: str, auth_token: str) -> dict:
    """Call Twilio Lookup v2 with CallerName package."""
    url = f"https://lookups.twilio.com/v2/PhoneNumbers/{phone_e164}"
    r = requests.get(url, params={"Fields": "caller_name"},
                     auth=HTTPBasicAuth(account_sid, auth_token))
    return r.json()


def load_contacts(ids: list[int] = None) -> list[dict]:
    if ids:
        id_list = json.dumps(ids)
        filter_clause = f".where(id: {id_list})"
    else:
        filter_clause = ".where(phone_verified: nil)"

    code = f"""
contacts = Contact.where.not(phone: [nil, '']){filter_clause}
contacts.each do |c|
  puts [c.id, c.full_name, c.phone].join('||')
end
"""
    rows = []
    for line in rails(code).splitlines():
        parts = line.split("||")
        if len(parts) < 3:
            continue
        cid, name, phone = parts[0], parts[1], parts[2]
        rows.append({"contact_id": int(cid), "name": name.strip(), "phone": phone.strip()})
    return rows


def save_result(contact_id: int, verified: bool, registered_name: str):
    name_val = json.dumps(registered_name) if registered_name else "nil"
    rails(f'Contact.find({contact_id}).update!(phone_verified: {str(verified).lower()}, phone_registered_name: {name_val})')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-sid", default=None)
    parser.add_argument("--auth-token", default=None)
    parser.add_argument("--ids", nargs="+", type=int, default=None,
                        help="Specific contact IDs to verify")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show contacts that would be verified, no API calls")
    args = parser.parse_args()

    import os
    account_sid = args.account_sid or os.environ.get("TWILIO_ACCOUNT_SID")
    auth_token  = args.auth_token  or os.environ.get("TWILIO_AUTH_TOKEN")

    if not args.dry_run and not (account_sid and auth_token):
        print("Error: provide --account-sid and --auth-token, or set TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN env vars",
              file=sys.stderr)
        sys.exit(1)

    contacts = load_contacts(ids=args.ids)
    print(f"Contacts to verify: {len(contacts)}  (~${len(contacts) * 0.01:.2f} at $0.01/lookup)")

    if args.dry_run:
        for c in contacts:
            print(f"  [{c['contact_id']}] {c['name']}: {c['phone']}")
        return

    active = 0
    inactive = 0
    name_mismatch = 0

    for c in contacts:
        try:
            normalized = e164(c["phone"])
        except Exception:
            print(f"  ? [{c['contact_id']}] {c['name']}: can't normalize {c['phone']!r}")
            continue

        result = lookup(normalized, account_sid, auth_token)

        # valid=False means number not found in carrier DB (likely dead)
        valid = result.get("valid", False)
        caller = result.get("caller_name") or {}
        registered_name = (caller.get("caller_name") or "").strip().title() or None
        caller_type = caller.get("caller_type", "")

        save_result(c["contact_id"], valid, registered_name)

        if valid:
            active += 1
            name_info = f" → '{registered_name}' ({caller_type})" if registered_name else " → no CNAM"
            # Flag if registered name looks different from our contact name
            our_name = c["name"].lower()
            reg_lower = (registered_name or "").lower()
            mismatch = registered_name and not any(
                part in reg_lower for part in our_name.split() if len(part) > 2
            )
            flag = " ⚠ name mismatch" if mismatch else ""
            if mismatch:
                name_mismatch += 1
            print(f"  ✓ [{c['contact_id']}] {c['name']}{name_info}{flag}")
        else:
            inactive += 1
            print(f"  ✗ [{c['contact_id']}] {c['name']}: {c['phone']} — INVALID/DEAD")

        time.sleep(0.1)  # gentle rate limiting

    print(f"\n=== Summary ===")
    print(f"  Verified:      {len(contacts)}")
    print(f"  Active:        {active}")
    print(f"  Dead/invalid:  {inactive}")
    print(f"  Name mismatches: {name_mismatch}")
    print(f"  Cost: ~${len(contacts) * 0.01:.2f}")


if __name__ == "__main__":
    main()
