#!/usr/bin/env python3
"""
Parse FAA NASR APT fixed-width data and output JSON to stdout.

Usage:
  python3 parse_nasr.py                          # download latest NASR subscription
  python3 parse_nasr.py /path/to/APT_BASE.csv   # use local CSV
  python3 parse_nasr.py /path/to/nasr.zip        # use local NASR zip

FAA NASR subscription: https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/
"""

import sys
import csv
import json
import os
import re
import urllib.request
import zipfile
import io
import tempfile
from datetime import datetime, date

# US states + territories accepted
VALID_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN","IA",
    "KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT","VT",
    "VA","WA","WV","WI","WY",
    # Territories
    "AS","GU","MP","PR","VI","MH","FM","PW",
}

# FAA NASR APT.txt fixed-width field positions (0-based byte offsets, lengths)
# Record layout from FAA NFDC APT data dictionary
APT_FIELDS = {
    # Record type is always "APT" at 0-3
    "site_number":     (3,  11),  # DLID - site number
    "state":           (48,  2),  # State abbreviation
    "faa_code":        (27,  4),  # FAA location identifier (DLID)
    "name":            (133, 42), # Official airport name
    "city":            (93,  40), # Associated city
    "county":          (143, 21), # County
    "facility_type":   (14,  13), # Facility type
    "ownership_type":  (173,  2), # Ownership type
    "owner_name":      (175, 42), # Owner name
    "airport_status":  (780,  2), # Airport status code
    "icao_code":       (1204, 7), # ICAO identifier
    "latitude_dms":    (523, 15), # Latitude DMS
    "latitude_dec":    (538, 12), # Latitude decimal
    "longitude_dms":   (550, 15), # Longitude DMS
    "longitude_dec":   (565, 12), # Longitude decimal
    "iata_code":       (1210, 3), # IATA identifier (not in all versions)
}


def clean(s):
    return s.strip() if s else ""


def parse_decimal_coord(s):
    s = clean(s)
    if not s:
        return None
    # May be formatted as decimal or with trailing S/W for negative
    neg = s.endswith(("S", "W"))
    digits = re.sub(r"[NSEW]", "", s).strip()
    try:
        val = float(digits)
        return -val if neg else val
    except ValueError:
        return None


def parse_apt_line(line):
    """Parse one APT-type line from APT.txt fixed-width format."""
    if len(line) < 50:
        return None

    def field(offset, length):
        return clean(line[offset:offset + length])

    state = field(48, 2)
    if state not in VALID_STATES:
        return None

    faa_code = field(27, 4)
    if not faa_code:
        return None

    lat = parse_decimal_coord(field(538, 12))
    lon = parse_decimal_coord(field(565, 12))

    # ICAO at offset 1204 only exists if line is long enough
    icao = field(1204, 7) if len(line) > 1210 else ""

    return {
        "faa_code":       faa_code,
        "name":           field(133, 42),
        "city":           field(93,  40),
        "county":         field(143, 21),
        "state":          state,
        "facility_type":  field(14,  13),
        "ownership_type": field(173,  2),
        "owner_name":     field(175, 42),
        "airport_status": field(780,  2),
        "icao_code":      icao,
        "iata_code":      "",
        "latitude":       lat,
        "longitude":      lon,
        "source_url":     "https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/",
    }


def parse_apt_txt(file_obj):
    airports = []
    encoding = "latin-1"  # NASR files use latin-1
    for raw_line in file_obj:
        if isinstance(raw_line, bytes):
            line = raw_line.decode(encoding)
        else:
            line = raw_line
        line = line.rstrip("\n").rstrip("\r")
        if not line.startswith("APT"):
            continue
        record = parse_apt_line(line)
        if record:
            airports.append(record)
    return airports


def parse_apt_csv(file_obj):
    """Parse the APT_BASE.csv format that FAA also publishes."""
    airports = []
    if isinstance(file_obj.read(0), bytes):
        import codecs
        reader = csv.DictReader(codecs.getreader("utf-8-sig")(file_obj))
    else:
        reader = csv.DictReader(file_obj)

    for row in reader:
        # Field names vary slightly by version; try common variants
        state = (row.get("STATE_CODE") or row.get("STATE-CODE") or row.get("STATE") or "").strip()
        if state not in VALID_STATES:
            continue
        faa_code = (row.get("LOCATION_ID") or row.get("LOC_ID") or row.get("FAA_ID") or "").strip()
        if not faa_code:
            continue

        def get(*keys):
            for k in keys:
                v = row.get(k, "")
                if v:
                    return v.strip()
            return ""

        try:
            lat = float(get("LAT_DECIMAL", "LATITUDE", "LAT")) or None
        except (ValueError, TypeError):
            lat = None
        try:
            lon = float(get("LONG_DECIMAL", "LONGITUDE", "LON")) or None
        except (ValueError, TypeError):
            lon = None

        airports.append({
            "faa_code":       faa_code,
            "name":           get("AIRPORT_NAME", "NAME", "FACILITY_NAME"),
            "city":           get("CITY", "ASSOC_CITY"),
            "county":         get("COUNTY", "COUNTY_NAME"),
            "state":          state,
            "facility_type":  get("FACILITY_TYPE", "TYPE_CODE", "SITE_TYPE_CODE"),
            "ownership_type": get("OWNERSHIP_TYPE", "OWNERSHIP", "OWNER_TYPE"),
            "owner_name":     get("OWNER_NAME", "OWNER"),
            "airport_status": get("STATUS_CODE", "AIRPORT_STATUS", "STATUS"),
            "icao_code":      get("ICAO_ID", "ICAO_CODE", "INTL_ID"),
            "iata_code":      get("IATA_CODE", "IATA_ID", ""),
            "latitude":       lat,
            "longitude":      lon,
            "source_url":     "https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/",
        })

    return airports


def find_nasr_zip_url():
    """Find the current NASR subscription ZIP URL from the FAA index page."""
    index_url = "https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/"
    try:
        with urllib.request.urlopen(index_url, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
        # Find the most recent zip link
        matches = re.findall(r'href="([^"]*NASR_Subscription[^"]*\.zip)"', html, re.IGNORECASE)
        if not matches:
            # Try alternate pattern
            matches = re.findall(r'href="(/[^"]*\d{4}-\d{2}-\d{2}[^"]*\.zip)"', html)
        if matches:
            url = matches[0]
            if url.startswith("/"):
                url = "https://www.faa.gov" + url
            return url
    except Exception as e:
        print(f"Warning: could not fetch NASR index: {e}", file=sys.stderr)
    # Fallback: construct URL for today's cycle
    today = date.today()
    return f"https://www.faa.gov/air_traffic/flight_info/aeronav/aero_data/NASR_Subscription/{today.strftime('%Y-%m-%d')}/APT_CSV.zip"


def download_and_parse(url):
    print(f"Downloading NASR data from {url} ...", file=sys.stderr)
    req = urllib.request.Request(url, headers={"User-Agent": "FAA-Airport-Importer/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()

    airports = []
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        print(f"ZIP contents: {names}", file=sys.stderr)

        # Prefer CSV
        csv_files = [n for n in names if n.upper().endswith(".CSV") and "APT" in n.upper()]
        apt_files = [n for n in names if n.upper() == "APT.TXT" or n.upper().endswith("/APT.TXT")]

        if csv_files:
            with zf.open(csv_files[0]) as f:
                print(f"Parsing {csv_files[0]} (CSV) ...", file=sys.stderr)
                airports = parse_apt_csv(f)
        elif apt_files:
            with zf.open(apt_files[0]) as f:
                print(f"Parsing {apt_files[0]} (fixed-width) ...", file=sys.stderr)
                airports = parse_apt_txt(f)
        else:
            # Try any txt file that might be the apt data
            txt_files = [n for n in names if n.upper().endswith(".TXT")]
            for fn in txt_files:
                with zf.open(fn) as f:
                    data_bytes = f.read()
                if b"\nAPT" in data_bytes or data_bytes[:3] == b"APT":
                    print(f"Parsing {fn} (fixed-width) ...", file=sys.stderr)
                    airports = parse_apt_txt(io.BytesIO(data_bytes))
                    break

    return airports


def load_local_file(path):
    ext = os.path.splitext(path)[1].lower()
    if ext == ".zip":
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            csv_files = [n for n in names if n.upper().endswith(".CSV") and "APT" in n.upper()]
            apt_files = [n for n in names if "APT" in n.upper() and n.upper().endswith(".TXT")]
            if csv_files:
                with zf.open(csv_files[0]) as f:
                    return parse_apt_csv(f)
            elif apt_files:
                with zf.open(apt_files[0]) as f:
                    return parse_apt_txt(f)
    elif ext == ".csv":
        with open(path, "rb") as f:
            return parse_apt_csv(f)
    else:
        # Assume fixed-width APT.txt
        with open(path, "rb") as f:
            return parse_apt_txt(f)
    return []


def main():
    if len(sys.argv) > 1:
        path = sys.argv[1]
        print(f"Loading local file: {path}", file=sys.stderr)
        airports = load_local_file(path)
    else:
        url = find_nasr_zip_url()
        airports = download_and_parse(url)

    print(f"Parsed {len(airports)} U.S. airport records", file=sys.stderr)
    print(json.dumps(airports, ensure_ascii=False))


if __name__ == "__main__":
    main()
