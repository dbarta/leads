#!/usr/bin/env python3
from __future__ import annotations

"""
Airport service-provider crawler.

Usage:
  python airport_crawler.py ATL [options]
  python airport_crawler.py ATL DFW DEN [options]
  python airport_crawler.py --all [options]

Options:
  --max-pages N      Max pages per airport (default: 80)
  --max-depth N      Max link depth from seed (default: 5)
  --min-score N      Min link score to follow (default: 20)
  --output DIR       Output directory (default: python/output)
  --logs DIR         Log directory (default: python/logs)
  --dry-run          Score links and report but don't fetch pages
  --seeds FILE       Seeds JSON file (default: python/crawl_seeds.json)
  --delay SECS       Delay between requests in seconds (default: 1.0)
  --playwright       Use Playwright (headless Chromium) for JS-heavy pages (default: on if installed)
  --no-playwright    Disable Playwright even if installed
"""

import argparse
import csv
import json
import sys
import time
import re
from datetime import datetime, timezone
from pathlib import Path
from collections import deque
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup
from hashlib import md5

# Optional Playwright support for JS-heavy / SPA sites
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from extractors.link_scorer import score_url, score_page_content, score_reasons
from extractors.pdf_extractor import extract_companies as extract_pdf
from extractors.html_extractor import extract_companies as extract_html, is_js_heavy

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT = 15
MAX_PDF_SIZE = 20 * 1024 * 1024  # 20 MB


# ── Session setup ─────────────────────────────────────────────────────────────

def make_session(delay: float) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return s


# ── robots.txt ────────────────────────────────────────────────────────────────

_robots_cache: dict[str, RobotFileParser | None] = {}

def can_fetch(url: str) -> bool:
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    if base not in _robots_cache:
        robots_url = f"{base}/robots.txt"
        rp = None
        try:
            resp = requests.get(
                robots_url, timeout=8,
                headers={"User-Agent": USER_AGENT},
                allow_redirects=True,
            )
            ct = resp.headers.get("content-type", "")
            # If the server returns HTML instead of plain text (e.g. Cloudflare challenge,
            # login wall, or custom 404 page), treat as no restrictions.
            if resp.status_code == 200 and "text/plain" in ct:
                rp = RobotFileParser()
                rp.set_url(robots_url)
                rp.parse(resp.text.splitlines())
        except Exception:
            pass  # unreachable — treat as allow-all
        _robots_cache[base] = rp
    rp = _robots_cache[base]
    return rp is None or rp.can_fetch(USER_AGENT, url)


# ── URL normalisation ─────────────────────────────────────────────────────────

def normalize_url(url: str) -> str:
    p = urlparse(url)
    # Drop fragments and some tracking params
    cleaned = urlunparse((p.scheme, p.netloc, p.path.rstrip("/") or "/", "", p.query, ""))
    return cleaned.lower()


def same_domain(url: str, base: str) -> bool:
    return urlparse(url).netloc == urlparse(base).netloc


def is_document_url(url: str) -> bool:
    ext = Path(urlparse(url).path).suffix.lower()
    return ext in {".pdf", ".xlsx", ".xls", ".csv", ".docx", ".doc"}


# ── Core fetch ────────────────────────────────────────────────────────────────

def fetch(session: requests.Session, url: str, log: list, delay: float) -> dict | None:
    """Fetch a URL; return a result dict or None on failure. Appends to log."""
    t0 = time.time()
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "url": url,
        "status": None,
        "content_type": None,
        "size_bytes": None,
        "elapsed_ms": None,
        "error": None,
    }

    if not can_fetch(url):
        entry["error"] = "blocked_by_robots_txt"
        log.append(entry)
        return None

    try:
        # HEAD first for large resources (skip huge non-relevant files)
        head = session.head(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        content_type = head.headers.get("content-type", "").lower()
        content_length = int(head.headers.get("content-length", 0) or 0)

        if content_length > MAX_PDF_SIZE and "pdf" in content_type:
            entry["error"] = f"pdf_too_large:{content_length}"
            entry["status"] = head.status_code
            log.append(entry)
            return None

        time.sleep(delay)
        resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        elapsed = int((time.time() - t0) * 1000)

        entry.update({
            "status": resp.status_code,
            "content_type": resp.headers.get("content-type", ""),
            "size_bytes": len(resp.content),
            "elapsed_ms": elapsed,
            "final_url": resp.url,
        })

        if resp.status_code >= 400:
            entry["error"] = f"http_{resp.status_code}"
            log.append(entry)
            return None

        log.append(entry)
        return {"url": resp.url, "content_type": entry["content_type"], "content": resp.content}

    except Exception as e:
        entry["error"] = str(e)
        entry["elapsed_ms"] = int((time.time() - t0) * 1000)
        log.append(entry)
        return None


# ── Playwright fetch ──────────────────────────────────────────────────────────

def fetch_with_playwright(pw_ctx, url: str, log: list, delay: float) -> dict | None:
    """Fetch a URL using Playwright (renders JavaScript). Same return format as fetch()."""
    if pw_ctx is None:
        return None

    t0 = time.time()
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "url": url,
        "status": None,
        "content_type": "text/html; charset=utf-8",
        "size_bytes": None,
        "elapsed_ms": None,
        "error": None,
        "via": "playwright",
    }

    if not can_fetch(url):
        entry["error"] = "blocked_by_robots_txt"
        log.append(entry)
        return None

    try:
        time.sleep(delay)
        page = pw_ctx.new_page()
        try:
            resp = page.goto(url, wait_until="networkidle", timeout=30000)
            status = resp.status if resp else 0
            html = page.content()
            final_url = page.url
        finally:
            page.close()

        content = html.encode("utf-8")
        entry.update({
            "status": status,
            "size_bytes": len(content),
            "elapsed_ms": int((time.time() - t0) * 1000),
            "final_url": final_url,
        })

        if status >= 400:
            entry["error"] = f"http_{status}"
            log.append(entry)
            return None

        log.append(entry)
        return {"url": final_url, "content_type": "text/html; charset=utf-8", "content": content}

    except Exception as e:
        entry["error"] = f"playwright:{e}"
        entry["elapsed_ms"] = int((time.time() - t0) * 1000)
        log.append(entry)
        return None


# ── Link extraction ───────────────────────────────────────────────────────────

def extract_links(html_bytes: bytes, base_url: str) -> list[tuple[str, str, int, list]]:
    """Return [(absolute_url, anchor_text, score, reasons)] sorted by score desc."""
    soup = BeautifulSoup(html_bytes, "lxml")
    links = []
    seen = set()
    for tag in soup.find_all("a", href=True):
        href = tag["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        abs_url = urljoin(base_url, href)
        norm = normalize_url(abs_url)
        if norm in seen:
            continue
        seen.add(norm)
        anchor = tag.get_text(strip=True)[:120]
        s = score_url(abs_url, anchor)
        reasons = score_reasons(abs_url, anchor)
        links.append((abs_url, anchor, s, reasons))
    links.sort(key=lambda x: x[2], reverse=True)
    return links


# ── Output helpers ────────────────────────────────────────────────────────────

def write_companies_csv(companies: list, faa_code: str, output_dir: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = output_dir / f"{faa_code}_{ts}_companies.csv"
    fieldnames = [
        "Legal company name", "DBA", "Airport(s) serviced",
        "Airport service categories", "Website",
        "Ultimate parent company", "Estimated consolidated employees",
        "Employee source", "Airline?", "Under 5,000?", "Qualified lead?",
        "Notes", "Verified date", "Official roster source(s)",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for c in companies:
            name = c.get("name", "").strip().rstrip(",.;:")
            writer.writerow({
                "Legal company name": name,
                "DBA": "",
                "Airport(s) serviced": faa_code,
                "Airport service categories": "; ".join(c.get("services", [])),
                "Website": "",
                "Ultimate parent company": "",
                "Estimated consolidated employees": "",
                "Employee source": "",
                "Airline?": "No",
                "Under 5,000?": "Uncertain",
                "Qualified lead?": "Review",
                "Notes": f"Crawled from {c.get('source_url', '')}",
                "Verified date": datetime.now().strftime("%Y-%m-%d"),
                "Official roster source(s)": c.get("source_url", ""),
            })
    return path


def write_crawl_log(log_data: dict, faa_code: str, logs_dir: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = logs_dir / f"{faa_code}_{ts}_crawl.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(log_data, f, indent=2, default=str)
    return path


def print_summary(summary: dict) -> None:
    print(f"\n{'='*60}")
    print(f"Crawl summary: {summary['faa_code']}")
    print(f"  Pages fetched:     {summary['pages_fetched']}")
    print(f"  Pages skipped:     {summary['pages_skipped']} (score too low or already visited)")
    print(f"  Errors:            {summary['errors']}")
    print(f"  PDFs found:        {summary['pdfs_found']}")
    print(f"  JS-heavy pages:    {summary['js_heavy_pages']} (may need Playwright)")
    if summary.get("spa_detected"):
        print(f"  *** SPA detected: site requires JavaScript rendering {'(Playwright active)' if summary.get('js_heavy_pages', 0) > 0 and summary.get('companies_found', 0) > 0 else '(Playwright used)'} ***")
    print(f"  Companies found:   {summary['companies_found']}")
    print(f"  Elapsed:           {summary['elapsed_secs']:.1f}s")
    if summary.get("top_scoring_pages"):
        print(f"\n  Top pages by extraction yield:")
        for p in summary["top_scoring_pages"][:5]:
            print(f"    [{p['companies']} co.] {p['url']}")
    if summary.get("js_heavy_urls"):
        print(f"\n  JS-heavy pages (add to Playwright list if important):")
        for u in summary["js_heavy_urls"][:5]:
            print(f"    {u}")
    if summary.get("high_score_not_fetched"):
        print(f"\n  High-score links NOT fetched (hit page limit):")
        for u in summary["high_score_not_fetched"][:5]:
            print(f"    {u}")
    print(f"{'='*60}\n")


# ── Main crawl logic ──────────────────────────────────────────────────────────

def crawl_airport(
    faa_code: str,
    seed: dict,
    session: requests.Session,
    max_pages: int,
    max_depth: int,
    min_score: int,
    delay: float,
    dry_run: bool,
    pw_ctx=None,
) -> tuple[list, dict]:
    """Crawl one airport. Returns (companies, summary_dict)."""
    homepage = seed["homepage"]

    # Build initial queue from homepage + candidate seed paths
    initial_urls = [homepage] + [
        homepage.rstrip("/") + path
        for path in seed.get("seed_paths", [])
    ]

    queue: deque[tuple[str, int, int]] = deque()  # (url, depth, score)
    for url in initial_urls:
        queue.append((url, 0, 80))

    visited: set[str] = set()
    fetch_log: list[dict] = []
    page_results: list[dict] = []
    all_companies: list[dict] = []

    summary = {
        "faa_code": faa_code,
        "homepage": homepage,
        "pages_fetched": 0,
        "pages_skipped": 0,
        "errors": 0,
        "pdfs_found": 0,
        "js_heavy_pages": 0,
        "js_heavy_urls": [],
        "spa_detected": False,
        "companies_found": 0,
        "top_scoring_pages": [],
        "high_score_not_fetched": [],
        "elapsed_secs": 0,
    }

    t_start = time.time()
    # Track content hashes to detect JS SPA (same shell returned for every path)
    _seed_hashes: list[str] = []
    # Switched to Playwright after SPA detection
    _use_playwright: bool = False

    while queue:
        url, depth, link_score = queue.popleft()
        norm = normalize_url(url)

        if norm in visited:
            continue
        if depth > max_depth:
            summary["pages_skipped"] += 1
            continue
        if summary["pages_fetched"] >= max_pages:
            if link_score >= 50:
                summary["high_score_not_fetched"].append(url)
            summary["pages_skipped"] += 1
            continue
        if not same_domain(url, homepage) and not is_document_url(url):
            summary["pages_skipped"] += 1
            continue

        visited.add(norm)

        if dry_run:
            reasons = score_reasons(url)
            print(f"  [score={link_score}] {url}  {reasons[:2]}")
            summary["pages_fetched"] += 1
            continue

        via = "playwright" if _use_playwright else "requests"
        print(f"  [{summary['pages_fetched']+1}/{max_pages}] d={depth} s={link_score:2d} [{via}] {url}")
        if _use_playwright:
            result = fetch_with_playwright(pw_ctx, url, fetch_log, delay)
        else:
            result = fetch(session, url, fetch_log, delay)

        if result is None:
            summary["errors"] += 1
            continue

        summary["pages_fetched"] += 1
        ct = result["content_type"]
        content = result["content"]
        page_url = result["url"]

        # SPA detection: if the first 3 seed-depth pages all return identical content,
        # the site renders everything via JavaScript.
        if depth == 0 and "html" in ct and not _use_playwright:
            _seed_hashes.append(md5(content).hexdigest())
            if len(_seed_hashes) >= 3 and len(set(_seed_hashes)) == 1:
                summary["spa_detected"] = True
                summary["js_heavy_pages"] += 1
                summary["js_heavy_urls"].append(homepage)
                if pw_ctx is not None:
                    _use_playwright = True
                    print(f"  *** SPA detected — switching to Playwright mode ***")
                    # Re-fetch the current URL so we get actual rendered content
                    result2 = fetch_with_playwright(pw_ctx, url, fetch_log, delay)
                    if result2:
                        content = result2["content"]
                        ct = result2["content_type"]
                        page_url = result2["url"]
                else:
                    print(f"  *** SPA detected — Playwright not available; skipping site ***")
                    break

        page_entry = {
            "url": page_url,
            "depth": depth,
            "link_score": link_score,
            "content_type": ct,
            "companies": 0,
            "extraction_method": None,
            "warnings": [],
        }

        if "pdf" in ct or page_url.lower().endswith(".pdf"):
            summary["pdfs_found"] += 1
            pdf_result = extract_pdf(content, page_url)
            page_entry["extraction_method"] = f"pdf:{pdf_result['method']}"
            page_entry["tables_found"] = pdf_result["tables_found"]
            page_entry["warnings"] = pdf_result["warnings"]
            for c in pdf_result["companies"]:
                c["source_url"] = page_url
                all_companies.append(c)
            page_entry["companies"] = len(pdf_result["companies"])
            print(f"    → PDF: {pdf_result['page_count']} pages, "
                  f"{pdf_result['tables_found']} tables, "
                  f"{len(pdf_result['companies'])} companies")

        elif "html" in ct or "text" in ct:
            try:
                html_text = content.decode("utf-8", errors="replace")
            except Exception:
                html_text = ""

            # If JS-heavy, try playwright upgrade before giving up
            if is_js_heavy(html_text) and not _use_playwright and pw_ctx is not None:
                print(f"    → JS-heavy — retrying with Playwright")
                result2 = fetch_with_playwright(pw_ctx, url, fetch_log, delay)
                if result2:
                    content = result2["content"]
                    html_text = content.decode("utf-8", errors="replace")
                    page_url = result2["url"]
                    page_entry["url"] = page_url

            # If still JS-heavy (no playwright or playwright failed), log and skip extraction
            if is_js_heavy(html_text) and not _use_playwright:
                summary["js_heavy_pages"] += 1
                summary["js_heavy_urls"].append(page_url)
                page_entry["warnings"].append("js_heavy")
                via_msg = "retry failed" if pw_ctx else "Playwright not available"
                print(f"    → JS-heavy ({via_msg})")
            else:
                # Score page content
                soup = BeautifulSoup(html_text, "lxml")
                title = soup.title.string.strip() if soup.title else ""
                page_score = score_page_content(page_url, html_text, title)
                page_entry["page_content_score"] = page_score

                html_result = extract_html(html_text, page_url)
                page_entry["extraction_method"] = f"html:{html_result['method']}"
                page_entry["warnings"] = html_result.get("warnings", [])

                for c in html_result["companies"]:
                    c["source_url"] = page_url
                    all_companies.append(c)
                page_entry["companies"] = len(html_result["companies"])
                if html_result["companies"]:
                    print(f"    → HTML: {len(html_result['companies'])} companies "
                          f"via {html_result['method']}")

                # Enqueue new links
                if depth < max_depth:
                    links = extract_links(content, page_url)
                    enqueued = 0
                    for link_url, anchor, s, reasons in links:
                        if s >= min_score and normalize_url(link_url) not in visited:
                            queue.append((link_url, depth + 1, s))
                            enqueued += 1
                    if enqueued:
                        print(f"    → enqueued {enqueued} links (top score: {links[0][2] if links else 0})")

        page_results.append(page_entry)

    # Deduplicate companies by name
    seen_names: set[str] = set()
    deduped: list[dict] = []
    for c in all_companies:
        key = c["name"].lower().strip()
        if key not in seen_names and len(key) > 2:
            seen_names.add(key)
            deduped.append(c)

    summary["companies_found"] = len(deduped)
    summary["elapsed_secs"] = time.time() - t_start
    summary["top_scoring_pages"] = sorted(
        [p for p in page_results if p["companies"] > 0],
        key=lambda p: p["companies"],
        reverse=True,
    )

    log_data = {
        "faa_code": faa_code,
        "crawl_start": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "page_results": page_results,
        "fetch_log": fetch_log,
    }

    return deduped, log_data, summary


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Crawl airport websites for service providers")
    parser.add_argument("airports", nargs="*", help="FAA codes to crawl (e.g. ATL DFW)")
    parser.add_argument("--all", action="store_true", help="Crawl all airports in seeds file")
    parser.add_argument("--max-pages", type=int, default=80)
    parser.add_argument("--max-depth", type=int, default=5)
    parser.add_argument("--min-score", type=int, default=20)
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between requests")
    parser.add_argument("--output", type=Path, default=SCRIPT_DIR / "output")
    parser.add_argument("--logs", type=Path, default=SCRIPT_DIR / "logs")
    parser.add_argument("--seeds", type=Path, default=SCRIPT_DIR / "crawl_seeds.json")
    parser.add_argument("--dry-run", action="store_true", help="Score links only, don't fetch")
    pw_group = parser.add_mutually_exclusive_group()
    pw_group.add_argument("--playwright", dest="playwright", action="store_true", default=None,
                          help="Use Playwright for JS-heavy/SPA sites (default: on if installed)")
    pw_group.add_argument("--no-playwright", dest="playwright", action="store_false",
                          help="Disable Playwright even if installed")
    args = parser.parse_args()

    # Playwright defaults to on if installed
    want_playwright = args.playwright if args.playwright is not None else PLAYWRIGHT_AVAILABLE

    args.output.mkdir(exist_ok=True)
    args.logs.mkdir(exist_ok=True)

    seeds = json.loads(args.seeds.read_text())
    seeds = {k: v for k, v in seeds.items() if not k.startswith("_")}

    if args.all:
        targets = list(seeds.keys())
    elif args.airports:
        targets = [a.upper() for a in args.airports]
    else:
        parser.print_help()
        sys.exit(1)

    session = make_session(args.delay)
    all_output_files = []

    if want_playwright and PLAYWRIGHT_AVAILABLE:
        print(f"Playwright enabled — JS-heavy and SPA sites will be rendered with Chromium")
        pw_manager = sync_playwright().start()
        pw_browser = pw_manager.chromium.launch(headless=True)
    elif want_playwright and not PLAYWRIGHT_AVAILABLE:
        print(f"WARNING: --playwright requested but playwright is not installed. Run: pip install playwright && playwright install chromium")
        pw_manager = pw_browser = None
    else:
        pw_manager = pw_browser = None

    try:
        for faa_code in targets:
            if faa_code not in seeds:
                print(f"WARNING: No seed data for {faa_code} — skipping")
                continue

            seed = seeds[faa_code]
            print(f"\n{'─'*60}")
            print(f"Crawling {faa_code} — {seed['name']}")
            print(f"  Homepage:  {seed['homepage']}")
            print(f"  Max pages: {args.max_pages}  Max depth: {args.max_depth}")
            print(f"{'─'*60}")

            # Create a fresh browser context per airport (clean cookies/state)
            pw_ctx = pw_browser.new_context(
                user_agent=USER_AGENT,
                java_script_enabled=True,
            ) if pw_browser else None

            try:
                companies, log_data, summary = crawl_airport(
                    faa_code=faa_code,
                    seed=seed,
                    session=session,
                    max_pages=args.max_pages,
                    max_depth=args.max_depth,
                    min_score=args.min_score,
                    delay=args.delay,
                    dry_run=args.dry_run,
                    pw_ctx=pw_ctx,
                )
            finally:
                if pw_ctx:
                    pw_ctx.close()

            print_summary(summary)

            if not args.dry_run:
                log_path = write_crawl_log(log_data, faa_code, args.logs)
                print(f"  Log: {log_path}")

                if companies:
                    csv_path = write_companies_csv(companies, faa_code, args.output)
                    print(f"  Companies CSV: {csv_path}  ({len(companies)} companies)")
                    all_output_files.append(str(csv_path))
                else:
                    print(f"  No companies extracted — check log for details")

    finally:
        if pw_browser:
            pw_browser.close()
        if pw_manager:
            pw_manager.stop()

    if all_output_files:
        print(f"\nOutput files:")
        for f in all_output_files:
            print(f"  {f}")
        print(f"\nTo import: bin/rails companies:import_csv[<file>]")


if __name__ == "__main__":
    main()
