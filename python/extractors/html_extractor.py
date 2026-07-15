from __future__ import annotations

"""
Extract company names from HTML pages.
Targets <table>, <ul>/<ol> lists, and definition lists that look like provider directories.
"""

import re
from bs4 import BeautifulSoup
from .pdf_extractor import _looks_like_company, _parse_services, SERVICE_KEYWORDS, COMPANY_SUFFIXES, LEGAL_ENTITY_SUFFIXES


def extract_companies(html: str, url: str) -> dict:
    """
    Extract company names from an HTML page.

    Returns:
        {
          "method": "table" | "list" | "none",
          "tables_found": int,
          "lists_found": int,
          "companies": [{"name": str, "services": [str], "source": str}],
          "warnings": [str],
          "js_heavy": bool,   # True if page appears to be a JS-rendered SPA
        }
    """
    result = {
        "method": "none",
        "tables_found": 0,
        "lists_found": 0,
        "companies": [],
        "warnings": [],
        "js_heavy": False,
    }

    soup = BeautifulSoup(html, "lxml")

    # Detect JS-heavy pages (very little visible text, lots of script tags)
    scripts = soup.find_all("script")
    body_text = soup.get_text(separator=" ", strip=True)
    if len(body_text) < 500 and len(scripts) > 5:
        result["js_heavy"] = True
        result["warnings"].append("js_heavy_page_may_need_playwright")
        return result

    companies = []

    # Try tables first
    table_companies = _extract_from_tables(soup)
    if table_companies:
        result["method"] = "table"
        result["tables_found"] = len(soup.find_all("table"))
        companies.extend(table_companies)

    # Try lists (ul/ol) — often used for vendor directories
    list_companies = _extract_from_lists(soup)
    if list_companies:
        if result["method"] == "none":
            result["method"] = "list"
        result["lists_found"] = len(soup.find_all(["ul", "ol"]))
        companies.extend(list_companies)

    # Deduplicate by normalized name
    seen = set()
    deduped = []
    for c in companies:
        key = c["name"].lower().strip()
        if key not in seen:
            seen.add(key)
            deduped.append(c)

    result["companies"] = deduped
    if not deduped:
        result["warnings"].append("no_companies_extracted")

    return result


def _extract_from_tables(soup: BeautifulSoup) -> list:
    companies = []
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        # Find header row
        header_cells = rows[0].find_all(["th", "td"])
        header = [c.get_text(strip=True).lower() for c in header_cells]

        name_col = _find_col(header, ["company", "name", "vendor", "provider", "contractor", "operator", "tenant"])
        service_col = _find_col(header, ["service", "category", "type", "description", "activity"])

        # Skip tables that clearly aren't vendor lists (e.g. flight schedules)
        if not _table_looks_relevant(header, rows):
            continue

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            if name_col is not None and name_col < len(cells):
                name = cells[name_col].get_text(strip=True)
                if _looks_like_company(name):
                    services = []
                    if service_col is not None and service_col < len(cells):
                        services = _parse_services(cells[service_col].get_text(strip=True))
                    companies.append({"name": name, "services": services, "source": "table"})
            else:
                for cell in cells:
                    text = cell.get_text(strip=True)
                    if _looks_like_company(text):
                        companies.append({"name": text, "services": [], "source": "table"})
                        break
    return companies


def _extract_from_lists(soup: BeautifulSoup) -> list:
    companies = []
    # Never pull from structural/navigation elements
    nav_contexts = soup.find_all(["nav", "header", "footer"])
    nav_elements = set()
    for ctx in nav_contexts:
        for el in ctx.find_all(["ul", "ol"]):
            nav_elements.add(id(el))
    # Also skip any list with nav-like CSS classes
    nav_class_pat = re.compile(r"nav|menu|header|footer|breadcrumb|sidebar", re.I)

    for ul in soup.find_all(["ul", "ol"]):
        if id(ul) in nav_elements:
            continue
        classes = " ".join(ul.get("class", []))
        if nav_class_pat.search(classes):
            continue

        items = ul.find_all("li", recursive=False)
        if len(items) < 3:
            continue
        candidates = [li.get_text(strip=True) for li in items]
        # Require a legal entity suffix (LLC, Inc, Corp, etc.) — broad COMPANY_SUFFIXES
        # like "air", "cargo", "security" match airport nav categories and cause false positives
        matches = [c for c in candidates if _looks_like_company(c) and LEGAL_ENTITY_SUFFIXES.search(c)]
        if len(matches) >= 2:
            for name in matches:
                companies.append({"name": name, "services": [], "source": "list"})
    return companies


def _find_col(header: list, hints: list) -> int | None:
    for i, h in enumerate(header):
        for hint in hints:
            if hint in h:
                return i
    return None


def _table_looks_relevant(header: list, rows: list) -> bool:
    header_text = " ".join(header)
    # Positive signal: header contains company/vendor/provider keywords
    if re.search(r"company|vendor|provider|contractor|operator|tenant|name", header_text):
        return True
    # Negative signal: looks like a flight table or price list
    if re.search(r"flight|departure|arrival|gate|terminal|price|cost|\$|fare", header_text):
        return False
    # Check if the first data row has any company-looking cells
    if len(rows) > 1:
        first_row_text = " ".join(c.get_text(strip=True) for c in rows[1].find_all(["td", "th"]))
        if SERVICE_KEYWORDS.search(first_row_text):
            return True
    return False


def is_js_heavy(html: str) -> bool:
    """Quick check before full parse — used to decide if Playwright is needed."""
    soup = BeautifulSoup(html, "lxml")
    body_text = soup.get_text(separator=" ", strip=True)
    scripts = soup.find_all("script")
    return len(body_text) < 500 and len(scripts) > 5
