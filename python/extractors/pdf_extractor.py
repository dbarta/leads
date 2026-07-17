from __future__ import annotations

"""
Extract company names from PDF documents using pdfplumber.
Tries table extraction first (structured rosters); falls back to text pattern matching.
"""

import re
import io
import pdfplumber

# Legal entity suffixes — high-precision; used for list/text extraction where context is weak.
# Uses only abbreviated forms (llc, inc, ltd, corp, lp, llp) to avoid matching
# plain English words like "limited" or "incorporated" in legal prose.
LEGAL_ENTITY_SUFFIXES = re.compile(
    r"\b(llc|l\.l\.c\.|inc\.?|ltd\.?|corp\.?|lp|l\.p\.|llp)\b",
    re.IGNORECASE,
)

# Broader suffixes (include aviation/industry words) — used only for table cells where
# column header already tells us the cell should be a company name.
# Avoids long-form words ("limited", "incorporated", "corporation") that appear in legal prose.
COMPANY_SUFFIXES = re.compile(
    r"\b(llc|l\.l\.c\.|inc\.?|ltd\.?|corp\.?|lp|l\.p\.|llp|co\.|company|group|"
    r"services|solutions|systems|enterprises|"
    r"aviation|air|ground|cargo|handling|security|catering|fueling|logistics)\b",
    re.IGNORECASE,
)

# Patterns that indicate a cell is NOT a company name
NOT_A_COMPANY = re.compile(
    r"^\s*$|^page\s*\d|^date|^phone|^email|^address|^service\s+type|^category|"
    r"^status|^contact|^certification|^\d{3}[-.\s]\d{3}|@|"
    # Form field labels (blank form templates)
    r"^(name|title|signature|operator|company\s*(name|phone)|us\s*dot|print\s*name|"
    r"authorized\s*by|attention|attn)\s*[:;]?\s*$|"
    # Rate/group categories (tariffs, not companies)
    r"^group\s+[a-z0-9]\b|^category\s+[a-z0-9]\b|"
    # Address fragments and location strings
    r"^\d+\s+\w+\s+(blvd|ave|st|rd|ln|dr|way|floor|suite|ste)\b|"
    # Legal boilerplate starts
    r"^whereas\b|^herein|^hereto\b|^therefor|^pursuant|"
    r"^the\s+(port|city|county|authority|contractor|operator)\b|"
    # DBA rows are alias lines, not company names
    r"^dba\b|^d/b/a\b|"
    # Concourse/terminal labels
    r"^concourse\s+[a-z0-9]\b|^terminal\s+[a-z0-9]\b|"
    r"^(domestic|international)\s+(baggage|terminal|arrivals|departures)\b|"
    # ACDBE/procurement form field labels
    r"^acdbe\b|^annual\s+(gross|subcontractor)|^solicitation\s+(name|number)\b|"
    r"^(bidder|proposer)\s+(address|annual|name)\b|^contract\s+n[oº°]\b|"
    r"^(project|contract)\s+(name|number)\b|^precent\s+acdbe\b|"
    # Financial institutions / banks (not airport service providers)
    r"\bbank\b.*\b(fort|irving|chase|amegy|regions)\b|\bsba[\-\s]small\s+business\b|"
    r"^(dfw\s+)?wbc\s+(lift\s+)?fund\b|^(ascension|covenant)\s+(business\s+)?capital\b|"
    # Level/floor indicators
    r"^\w+\s+level\s*$|^fis\s+level\b",
    re.IGNORECASE,
)

# Service category keywords — used to detect which column contains services
SERVICE_KEYWORDS = re.compile(
    r"ground\s*handl|ramp|cargo|fuel|catering|cabin\s*clean|security|wheelchair|"
    r"maintenance|deic|snow\s*remov|janitorial|passenger\s*assist|baggage|"
    r"lounge|transport|shuttle|lavatory|potable",
    re.IGNORECASE,
)


def extract_companies(pdf_bytes: bytes, source_url: str) -> dict:
    """
    Extract company names and service categories from a PDF.

    Returns:
        {
          "method": "table" | "text",
          "page_count": int,
          "tables_found": int,
          "companies": [
              {"name": str, "services": [str], "page": int, "row_index": int}
          ],
          "warnings": [str],
        }
    """
    result = {
        "method": None,
        "page_count": 0,
        "tables_found": 0,
        "companies": [],
        "warnings": [],
    }

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            result["page_count"] = len(pdf.pages)
            all_tables = []

            for page_num, page in enumerate(pdf.pages, start=1):
                tables = page.extract_tables()
                if tables:
                    result["tables_found"] += len(tables)
                    for table in tables:
                        all_tables.append((page_num, table))

            if all_tables:
                result["method"] = "table"
                companies = _extract_from_tables(all_tables)
                result["companies"] = companies
            else:
                # Fall back to text scanning
                result["method"] = "text"
                text = "\n".join(
                    page.extract_text() or "" for page in pdf.pages
                )
                result["companies"] = _extract_from_text(text)
                if not result["companies"]:
                    result["warnings"].append("no_tables_and_no_text_matches")

    except Exception as e:
        result["warnings"].append(f"extraction_error:{e}")

    return result


def _normalize_cell(text: str) -> str:
    """Normalize a PDF table cell: collapse internal newlines and strip list bullets."""
    text = re.sub(r"\s*\n\s*", " ", text).strip()
    # Strip leading list bullets like "a) ", "1. ", "• ", "- "
    text = re.sub(r"^([a-z]\)|[0-9]+\.|\*|•|-)\s+", "", text, flags=re.I)
    return text


def _extract_from_tables(all_tables: list) -> list:
    companies = []

    for page_num, table in all_tables:
        if not table or len(table) < 2:
            continue

        header = [str(c or "").strip().lower() for c in table[0]]
        name_col = _find_name_column(header)
        service_col = _find_service_column(header)

        for row_idx, row in enumerate(table[1:], start=1):
            if not row:
                continue
            # If we identified a name column, use it; otherwise score every cell
            if name_col is not None and name_col < len(row):
                cell = _normalize_cell(str(row[name_col] or ""))
                if _looks_like_company(cell):
                    services = []
                    if service_col is not None and service_col < len(row):
                        services = _parse_services(str(row[service_col] or ""))
                    companies.append({
                        "name": cell,
                        "services": services,
                        "page": page_num,
                        "row_index": row_idx,
                    })
            else:
                # No identified name column — require a legal entity suffix to avoid
                # pulling form labels, legal prose, and address fragments from blank templates
                for col_idx, cell in enumerate(row):
                    cell = _normalize_cell(str(cell or ""))
                    if LEGAL_ENTITY_SUFFIXES.search(cell) and _looks_like_company(cell):
                        companies.append({
                            "name": cell,
                            "services": [],
                            "page": page_num,
                            "row_index": row_idx,
                        })
                        break  # take first company-like cell per row

    return companies


def _extract_from_text(text: str) -> list:
    """Last resort: scan lines for company-name patterns.
    Stricter than table mode — requires a legal entity suffix and short length
    to avoid pulling in legal boilerplate, form labels, and nav text."""
    companies = []
    seen = set()
    for line in text.splitlines():
        line = line.strip()
        # Skip blank, very long (legal sentences), or very short lines
        if not line or len(line) > 80 or len(line) < 4:
            continue
        # Must have a legal entity suffix (not just title-case) to avoid contract prose
        if LEGAL_ENTITY_SUFFIXES.search(line) and not NOT_A_COMPANY.match(line) and line not in seen:
            seen.add(line)
            companies.append({"name": line, "services": [], "page": None, "row_index": None})
    return companies


def _find_name_column(header: list) -> int | None:
    name_hints = ["company", "name", "vendor", "provider", "contractor", "operator", "tenant"]
    for i, h in enumerate(header):
        for hint in name_hints:
            if hint in h:
                return i
    return None


def _find_service_column(header: list) -> int | None:
    service_hints = ["service", "category", "type", "description", "activity", "operation"]
    for i, h in enumerate(header):
        for hint in service_hints:
            if hint in h:
                return i
    return None


def _looks_like_company(text: str) -> bool:
    if not text or "@" in text or len(text) < 3 or len(text) > 120:
        return False
    if NOT_A_COMPANY.match(text):
        return False
    words = text.split()
    # Company names rarely exceed 9 words; longer strings are usually legal sentences
    if len(words) > 9:
        return False
    if COMPANY_SUFFIXES.search(text):
        # Extra guard: word "company/group/services" mid-sentence doesn't count alone
        # unless it appears at or near the end of the name
        if re.search(r"^(this|the|an?|such|each|all|any|said|above)\b", text, re.I):
            return False
        return True
    # Multi-word title-cased phrase (likely a company name even without suffix)
    if len(words) >= 2 and sum(1 for w in words if w and w[0].isupper()) >= len(words) * 0.6:
        return True
    return False


def _parse_services(text: str) -> list:
    if not text:
        return []
    # Split on common delimiters
    parts = re.split(r"[;,/\n]", text)
    return [p.strip() for p in parts if p.strip() and len(p.strip()) > 2]
