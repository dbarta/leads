from __future__ import annotations

"""
Score URLs and page content for relevance to airport service-provider discovery.
Returns a score 0-100; higher = more likely to contain provider lists.
"""

import re
from urllib.parse import urlparse

# URL/link-text patterns — checked against both the href and the anchor text
HIGH = [
    r"service.?provider", r"certified.?provider", r"vendor.?list", r"vendor.?direct",
    r"approved.?vendor", r"ground.?handler", r"ground.?handl", r"\bfbo\b",
    r"tenant.?list", r"tenant.?direct", r"contractor.?list", r"permit.?holder",
    r"\bdbe\b", r"\bacdbe\b", r"roster", r"ramp.?agent", r"cargo.?handler",
    r"fueling.?provider", r"cabin.?clean", r"de.?ic", r"catering.?provider",
    r"wheelchair.?provider", r"ground.?support", r"\bgsm\b", r"handler.?list",
    r"certified.?company", r"active.?provider", r"licensed.?vendor",
]

MEDIUM = [
    r"procurement", r"contract.?award", r"business.?develop", r"aviation.?service",
    r"ground.?transport", r"air.?cargo", r"concession", r"doing.?business",
    r"vendor", r"contractor", r"tenant", r"permit", r"license", r"operator",
    r"business.?opportun", r"rfp", r"rfq", r"solicitation", r"award",
]

# These strongly suggest the page won't have provider lists — deprioritize
SKIP = [
    r"news|press.?release|media", r"career|job.?posting|employment",
    r"food|dining|restaurant|bar\b", r"retail|shopping|shop\b",
    r"parking|garage|valet", r"terminal.?map|airport.?map|wayfind",
    r"flight.?status|departure|arrival", r"passenger|traveler",
    r"hotel|accommodation|stay", r"wifi|internet|connect",
    r"lost.?found|baggage.?claim", r"accessibility|ada\b",
    r"social|instagram|facebook|twitter|linkedin",
    r"privacy|cookie|terms.?of.?use|legal\b",
    r"sitemap", r"search\b",
]

# PDF URL/anchor patterns that indicate low-value documents (forms, maps, procedures)
SKIP_PDF = [
    r"tariff|fee.?schedule|rate.?card|rate.?sheet",
    r"operating.?agreement|agreement.?packet|agreement.?form",
    r"charter.?agreement",
    r"instruction|how.?to\b",
    r"(?:airport|terminal).?map|wayfind|parking.?map|bike.?map|rail.?map",
    r"brochure|booklet",
    r"key.?request|compactor|training\b",
    # Marketing/meeting documents — not vendor lists
    r"presentation|info.?session|attendee|redevelop",
    r"concession.?101|concession.?handbook|concession.?design|concession.?employee",
    r"design.?criteria|design.?manual|tenant.?improvement|construction",
    r"supplier.?guide|procurement.?manual|procurement.?ethics|procurement.?policy",
    r"purchase.?order|tax.?exempt|ethics.?guide",
    # Legal/compliance boilerplate
    r"civil.?rights|ada.?cert|non.?discrim",
]

# File extensions that are always relevant (downloadable documents)
DOCUMENT_EXTENSIONS = {".pdf", ".xlsx", ".xls", ".csv", ".docx", ".doc"}


def score_url(url: str, anchor_text: str = "") -> int:
    """Return 0-100 relevance score for a URL + its anchor text."""
    text = f"{url} {anchor_text}".lower()
    parsed = urlparse(url)
    path = parsed.path.lower()
    ext = "." + path.rsplit(".", 1)[-1] if "." in path.split("/")[-1] else ""

    # Documents are always worth fetching
    if ext in DOCUMENT_EXTENSIONS:
        return _document_score(ext, text)

    # Hard skip
    for pattern in SKIP:
        if re.search(pattern, text):
            return 0

    score = 0
    for pattern in HIGH:
        if re.search(pattern, text):
            score += 40
            break
    for pattern in MEDIUM:
        if re.search(pattern, text):
            score += 20
            break

    # Boost for deeper paths (more specific pages)
    depth = len([p for p in path.split("/") if p])
    if depth >= 2:
        score += 5

    return min(score, 90)


def _document_score(ext: str, text: str) -> int:
    if ext == ".pdf":
        # Skip low-value PDF types (forms, rate tariffs, maps, procedural docs)
        for pattern in SKIP_PDF:
            if re.search(pattern, text):
                return 10
        # PDFs with provider-related names score highest
        for pattern in HIGH:
            if re.search(pattern, text):
                return 95
        for pattern in MEDIUM:
            if re.search(pattern, text):
                return 75
        return 50  # generic PDFs — fetch but at lower priority
    return 60  # other document types


def score_page_content(url: str, text: str, title: str = "") -> int:
    """Score a fetched HTML page by its content."""
    combined = f"{url} {title} {text[:3000]}".lower()
    score = 0
    for pattern in HIGH:
        if re.search(pattern, combined):
            score += 35
    for pattern in MEDIUM:
        if re.search(pattern, combined):
            score += 15
    return min(score, 100)


def score_reasons(url: str, anchor_text: str = "") -> list[str]:
    """Return human-readable reasons for the score (for instrumentation)."""
    text = f"{url} {anchor_text}".lower()
    reasons = []
    for pattern in HIGH:
        if re.search(pattern, text):
            reasons.append(f"HIGH:{pattern}")
    for pattern in MEDIUM:
        if re.search(pattern, text):
            reasons.append(f"MEDIUM:{pattern}")
    for pattern in SKIP:
        if re.search(pattern, text):
            reasons.append(f"SKIP:{pattern}")
    return reasons
