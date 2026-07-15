#!/usr/bin/env python3
from __future__ import annotations

"""
Search DuckDuckGo for ACDBE/DBE plan PDFs for each airport and extract company names.

Usage:
  python search_acdbe.py BOS MCO EWR      # specific airports
  python search_acdbe.py --all            # all airports in seeds
  python search_acdbe.py BOS --playwright --max-results 10 --delay 3

How it works:
  For each airport, runs site: queries against the airport domain to find ACDBE/DBE
  program pages and PDFs. HTML pages are fetched one level deep to find embedded PDF
  links. PDFs are downloaded and company names extracted.

  With --playwright: JS/SPA pages are rendered with Chromium, and Cloudflare-protected
  PDFs are downloaded through the browser after visiting the source page for cookie priming.
"""

import argparse
import json
import os
import re
import sys
import tempfile
import time
import io
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests
from bs4 import BeautifulSoup

try:
    from ddgs import DDGS
except ImportError:
    from duckduckgo_search import DDGS  # type: ignore[no-redef]

try:
    from playwright.sync_api import sync_playwright as _sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from extractors.pdf_extractor import extract_companies as extract_pdf
from airport_crawler import USER_AGENT, write_companies_csv

REQUEST_TIMEOUT = 20
MAX_PDF_SIZE = 25 * 1024 * 1024
PLAYWRIGHT_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

# Search query templates — {name} = airport full name, {faa} = FAA code, {domain} = site domain
# DDG ignores filetype:pdf; we search broadly and filter PDF URLs ourselves.
QUERY_TEMPLATES = [
    "site:{domain} ACDBE",
    "site:{domain} DBE \"disadvantaged business\"",
    "site:{domain} \"service provider\" concession program",
    "\"{name}\" airport ACDBE certified companies",
]


def search_airport(faa_code: str, seed: dict, max_results: int, delay: float) -> tuple[list[str], list[str]]:
    """
    Run DDG queries and return (pdf_urls, html_urls) deduplicated lists.
    PDFs found directly; HTML pages are crawled one level for embedded PDF links.
    """
    name = seed["name"]
    domain = urlparse(seed["homepage"]).netloc.lstrip("www.")

    pdf_urls: list[str] = []
    html_urls: list[str] = []
    seen: set[str] = set()

    with DDGS() as ddgs:
        for template in QUERY_TEMPLATES:
            query = template.format(name=name, faa=faa_code, domain=domain)
            print(f"  DDG: {query}")
            try:
                results = list(ddgs.text(query, max_results=max_results))
                for r in results:
                    url = r.get("href", "")
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    if ".pdf" in url.lower():
                        pdf_urls.append(url)
                        print(f"    PDF: {url[-80:]}")
                    else:
                        html_urls.append(url)
            except Exception as e:
                print(f"    DDG error: {e}")
            time.sleep(delay)

    return pdf_urls, html_urls


def fetch_pdf_requests(url: str, session: requests.Session) -> bytes | None:
    """Download a PDF with requests. Returns bytes or None on failure."""
    try:
        head = session.head(url, timeout=10, allow_redirects=True)
        size = int(head.headers.get("content-length", 0) or 0)
        if size > MAX_PDF_SIZE:
            print(f"    Skipping — too large ({size // 1024 // 1024} MB)")
            return None

        resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True, stream=False)
        if resp.status_code >= 400:
            print(f"    HTTP {resp.status_code}")
            return None
        ct = resp.headers.get("content-type", "")
        if "pdf" not in ct and ".pdf" not in url.lower():
            return None
        if "html" in ct.lower() and len(resp.content) < 50000:
            # Probably a bot-challenge page (e.g. Cloudflare)
            return None
        return resp.content
    except Exception as e:
        print(f"    Fetch error: {e}")
        return None


def fetch_pdf_playwright(pw_ctx, referer_url: str, pdf_url: str) -> bytes | None:
    """
    Download a Cloudflare-protected PDF via Playwright.
    Primes session cookies by first loading referer_url, then navigates to pdf_url.
    """
    page = pw_ctx.new_page()
    try:
        page.goto(referer_url, wait_until="networkidle", timeout=30000)
        with page.expect_download(timeout=30000) as dl:
            page.evaluate(f"window.location.href = {repr(pdf_url)}")
        download = dl.value
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        download.save_as(tmp.name)
        tmp.close()
        pdf_bytes = open(tmp.name, "rb").read()
        os.unlink(tmp.name)
        return pdf_bytes
    except Exception as e:
        print(f"    Playwright error: {e}")
        return None
    finally:
        page.close()


def extract_pdf_links_from_html(url: str, session: requests.Session, base_domain: str, pw_ctx=None) -> list[str]:
    """
    Fetch an HTML page and extract PDF links from it.
    If pw_ctx is provided, tries Playwright for JS-rendered pages when requests yields no PDFs.
    """
    pdf_links = _extract_pdf_links_requests(url, session, base_domain)
    if not pdf_links and pw_ctx is not None:
        pdf_links = _extract_pdf_links_playwright(url, pw_ctx, base_domain)
    return pdf_links


def _extract_pdf_links_requests(url: str, session: requests.Session, base_domain: str) -> list[str]:
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if resp.status_code >= 400:
            return []
        ct = resp.headers.get("content-type", "")
        if "html" not in ct.lower() and "text" not in ct.lower():
            return []
        if len(resp.content) < 5000:
            # Probably a bot challenge
            return []
        return _parse_pdf_links(resp.text, url, base_domain)
    except Exception:
        return []


def _extract_pdf_links_playwright(url: str, pw_ctx, base_domain: str) -> list[str]:
    page = pw_ctx.new_page()
    try:
        page.goto(url, wait_until="networkidle", timeout=30000)
        html = page.content()
        return _parse_pdf_links(html, url, base_domain)
    except Exception:
        return []
    finally:
        page.close()


def _parse_pdf_links(html: str, page_url: str, base_domain: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    pdf_links = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        abs_url = urljoin(page_url, href)
        parsed = urlparse(abs_url)
        netloc = parsed.netloc
        # Accept: same domain, subdomains of same domain, or known CDN hosts for airport assets
        cdn_domains = ("ctfassets.net", "cloudfront.net", "amazonaws.com", "akamaized.net",
                       "edgesuite.net", "azurefd.net", "blob.core.windows.net")
        if base_domain not in netloc and not any(c in netloc for c in cdn_domains):
            continue
        if ".pdf" in abs_url.lower() and abs_url not in seen:
            seen.add(abs_url)
            pdf_links.append(abs_url)
            print(f"    PDF link: {abs_url[-80:]}")
    return pdf_links


def _is_low_value_pdf(url: str) -> bool:
    skip = re.compile(
        # Standard exclusions
        r"tariff|fee.?schedule|rate.?card|operating.?agreement|agreement.?form|"
        r"instruction|airport.?map|terminal.?map|brochure|training\b|"
        r"civil.?rights|ada.?cert|application.?checklist|checklist|"
        r"joint.?venture|outreach|info.?session|presentation|"
        # Construction / technical documents
        r"construction|tenant.?alteration|tenant.?improvement|design.?guide|"
        r"design.?standard|design.?criteria|BIM|VDC|CAD|GIS|roadmap|toolkit|"
        r"escalator|pedestrian|sustainability|floodproof|crane|radio.?request|"
        r"escort.?request|work.?order|closeout|permit.?application|trench.?permit|"
        r"wayfind|sign.?standard|toilet.?room|planner.?system|primavera|pmweb|"
        r"last.?planner|blank\b|"
        # Certification process / form templates (not company directories)
        r"starter.?package|next.?step.?guide|good.?faith|acronyms|personal.?narrative|"
        r"net.?worth.?statement|personal.?net.?worth|certification.?forms|"
        r"sample.?documents|follow.?up.?request|letter.?to.?dbe|letter.?to.?acdbe|"
        r"reevaluation.?info|reevaluation.?presentation|reevaluation.?webinar|"
        r"info.?session.?pn|webinar.?slides|info.?session.?slides|"
        r"performance.?standards.?manual|cx.?performance|standards.?manual|"
        r"procurement.?process.?websites|airport.?rules.?regs|rules.?and.?regs|"
        r"regulation\b",
        re.IGNORECASE,
    )
    return bool(skip.search(url))


def main():
    parser = argparse.ArgumentParser(description="Search DDG for airport ACDBE plans and extract companies")
    parser.add_argument("airports", nargs="*", help="FAA codes (e.g. BOS MCO EWR)")
    parser.add_argument("--all", action="store_true", help="Process all airports in seeds file")
    parser.add_argument("--playwright", action=argparse.BooleanOptionalAction, default=PLAYWRIGHT_AVAILABLE,
                        help="Use Playwright for JS pages and protected PDFs (default: on if installed)")
    parser.add_argument("--max-results", type=int, default=8, help="Max DDG results per query (default: 8)")
    parser.add_argument("--delay", type=float, default=2.0, help="Seconds between DDG queries (default: 2.0)")
    parser.add_argument("--output", type=Path, default=SCRIPT_DIR / "output")
    parser.add_argument("--seeds", type=Path, default=SCRIPT_DIR / "crawl_seeds.json")
    args = parser.parse_args()

    args.output.mkdir(exist_ok=True)

    seeds = json.loads(args.seeds.read_text())
    seeds = {k: v for k, v in seeds.items() if not k.startswith("_")}

    if args.all:
        targets = list(seeds.keys())
    elif args.airports:
        targets = [a.upper() for a in args.airports]
    else:
        parser.print_help()
        sys.exit(1)

    use_playwright = args.playwright and PLAYWRIGHT_AVAILABLE
    if args.playwright and not PLAYWRIGHT_AVAILABLE:
        print("WARNING: --playwright requested but playwright not installed")

    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/pdf,text/html,*/*",
    })

    pw_instance = None
    pw_browser = None

    if use_playwright:
        print("Playwright enabled — will render JS pages and download protected PDFs")
        pw_instance = _sync_playwright().start()
        pw_browser = pw_instance.chromium.launch(headless=True)

    try:
        all_output_files = []

        for faa_code in targets:
            if faa_code not in seeds:
                print(f"WARNING: No seed data for {faa_code} — skipping")
                continue

            seed = seeds[faa_code]
            domain = urlparse(seed["homepage"]).netloc.lstrip("www.")
            print(f"\n{'─'*60}")
            print(f"Searching {faa_code} — {seed['name']}")
            print(f"{'─'*60}")

            pw_ctx = None
            if use_playwright:
                pw_ctx = pw_browser.new_context(
                    user_agent=PLAYWRIGHT_UA,
                    accept_downloads=True,
                )

            direct_pdfs, html_pages = search_airport(faa_code, seed, args.max_results, args.delay)

            # Crawl relevant HTML pages for embedded PDF links
            # Only visit pages specifically about ACDBE/DBE/diversity — not general business pages
            extra_pdfs: list[str] = []
            acdbe_pages = [u for u in html_pages if re.search(r"acdbe|dbe|diversity|compliance|concession", u, re.I)]
            if acdbe_pages:
                print(f"\n  Crawling {len(acdbe_pages)} relevant HTML pages for PDF links...")
                seen_pdf_urls: set[str] = set(direct_pdfs)
                for html_url in acdbe_pages[:6]:
                    print(f"  → {html_url[-70:]}")
                    for pdf_url in extract_pdf_links_from_html(html_url, session, domain, pw_ctx):
                        if pdf_url not in seen_pdf_urls:
                            seen_pdf_urls.add(pdf_url)
                            extra_pdfs.append(pdf_url)
                    time.sleep(1)

            all_pdf_urls = [u for u in (direct_pdfs + extra_pdfs) if not _is_low_value_pdf(u)]

            if not all_pdf_urls:
                print(f"  No PDFs found")
                if pw_ctx:
                    pw_ctx.close()
                continue

            print(f"\n  Fetching {len(all_pdf_urls)} PDFs...")
            all_companies: list[dict] = []

            for url in all_pdf_urls:
                print(f"  ↓ {url[-70:]}")
                # Try requests first; fall back to Playwright for protected PDFs
                pdf_bytes = fetch_pdf_requests(url, session)
                if not pdf_bytes and pw_ctx:
                    # Find the best referer: the HTML page we found this PDF on, or the first acdbe page
                    referer = (acdbe_pages[0] if acdbe_pages else seed["homepage"])
                    print(f"    → retrying with Playwright (referer: {referer[-50:]})")
                    pdf_bytes = fetch_pdf_playwright(pw_ctx, referer, url)

                if not pdf_bytes:
                    continue

                result = extract_pdf(pdf_bytes, url)
                n = len(result["companies"])
                print(f"    → {result['page_count']}pp, {result['tables_found']} tables, {n} companies")

                if result["warnings"]:
                    print(f"    warnings: {result['warnings']}")

                for c in result["companies"]:
                    c["source_url"] = url
                    all_companies.append(c)

            if pw_ctx:
                pw_ctx.close()

            # Deduplicate
            seen_names: set[str] = set()
            deduped: list[dict] = []
            for c in all_companies:
                key = c["name"].lower().strip()
                if key not in seen_names and len(key) > 2:
                    seen_names.add(key)
                    deduped.append(c)

            print(f"\n  Total unique companies: {len(deduped)}")

            if deduped:
                csv_path = write_companies_csv(deduped, faa_code, args.output)
                print(f"  CSV: {csv_path}")
                all_output_files.append(str(csv_path))
            else:
                print(f"  No companies extracted")

            time.sleep(args.delay)

        if all_output_files:
            print(f"\nOutput files:")
            for f in all_output_files:
                print(f"  {f}")
            print(f"\nTo import: cd /Users/dbarta/leads/leads && bin/rails companies:import_csv[<file>]")

    finally:
        if pw_browser:
            pw_browser.close()
        if pw_instance:
            pw_instance.stop()


if __name__ == "__main__":
    main()
