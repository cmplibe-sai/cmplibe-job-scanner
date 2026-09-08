import re
import base64
import hashlib
import logging
import urllib.parse
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from job_pulse.config import (
    STORY_SHEET_ID,
    STORY_SHEET_NAME,
    STORY_MAIN_COMPANY_COL,
    STORY_COMPETITORS_COL,
)
from job_pulse.models import CompanyTarget, StoryIngestionLog
from job_pulse.storage.base import JobRepository
from job_pulse.radar.story_ingestion import extract_companies_from_story_row

logger = logging.getLogger("job_pulse.radar.story_worker")

# Domains that turn up in "<company> official website" searches but are never the
# company's own site - skip these when picking a homepage candidate.
_AGGREGATOR_DOMAINS = (
    "linkedin.com", "facebook.com", "twitter.com", "x.com", "instagram.com",
    "youtube.com", "wikipedia.org", "crunchbase.com", "bloomberg.com",
    "economictimes.indiatimes.com", "moneycontrol.com", "livemint.com",
    "zaubacorp.com", "tofler.in", "indiamart.com", "justdial.com",
    "glassdoor.com", "glassdoor.co.in", "indeed.com", "naukri.com",
    "google.com", "bing.com", "yourstory.com", "inc42.com", "entrackr.com",
    "reddit.com", "quora.com", "medium.com",
)


def compute_row_hash(sheet_name: str, row: List[str]) -> str:
    """
    Stable identity for a sheet row, independent of its position (safe against rows
    being sorted/inserted). Any edit to the row's content produces a new hash, so an
    edited-and-republished story is treated as new rather than silently skipped.
    """
    raw = sheet_name + "|" + "|".join(row)
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def discover_company_homepage(company_name: str, client, max_results: int = 5) -> Optional[str]:
    """
    Resolve a company name to its official homepage via a Bing search, reusing the
    same search + redirect-unwrapping approach as LinkedInPostsScraper. Best-effort:
    returns None if nothing plausible turns up, which callers must treat as a normal
    (not exceptional) outcome - plenty of freshly-funded companies won't resolve cleanly.
    """
    if not company_name:
        return None

    query = f'"{company_name}" official website India'
    headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://www.bing.com/",
    }

    resp = client.get(f"https://www.bing.com/search?q={urllib.parse.quote_plus(query)}", headers=headers)
    if not resp or resp.status_code != 200:
        return None

    soup = BeautifulSoup(resp.text, "lxml")
    results = soup.find_all("li", class_="b_algo")[:max_results]

    for res in results:
        h2 = res.find("h2")
        link = h2.find("a") if h2 else None
        if not link:
            continue
        href = link.get("href", "")

        real_url = href
        if "u=a1" in href:
            m = re.search(r"u=a1([a-zA-Z0-9_\-]+)", href)
            if m:
                try:
                    padded = m.group(1) + "=" * (-len(m.group(1)) % 4)
                    real_url = base64.b64decode(padded).decode("utf-8", errors="ignore")
                except Exception:
                    continue

        if not real_url or not real_url.startswith("http"):
            continue
        netloc = urllib.parse.urlparse(real_url).netloc.lower()
        if any(dom in netloc for dom in _AGGREGATOR_DOMAINS):
            continue

        return real_url

    return None


def _register_new_target(company_name: str, career_scraper, source_row_id: str) -> CompanyTarget:
    """Build a CompanyTarget for a newly-discovered company, resolving a career URL
    when a homepage can be found. career_url is left empty (not an error) when
    discovery fails - the radar still scans LinkedIn/portal channels for the company."""
    from job_pulse.scrapers.career_pages import _is_safe_url

    career_url = ""
    homepage = discover_company_homepage(company_name, career_scraper.client)
    if homepage and _is_safe_url(homepage):
        resolved = career_scraper._resolve_career_url(homepage)
        career_url = resolved or ""

    return CompanyTarget(
        company_name=company_name,
        career_url=career_url,
        channels=["ats", "linkedin", "internshala", "unstop", "shine", "social_posts"],
        is_active=True,
        source="story_ingestion",
        source_row_id=source_row_id,
    )


def sync_companies_from_stories(
    repo: JobRepository,
    sheets_config: Dict[str, Any],
    sheet_id: str = STORY_SHEET_ID,
    sheet_name: str = STORY_SHEET_NAME,
    main_company_col: int = STORY_MAIN_COMPANY_COL,
    competitors_col: int = STORY_COMPETITORS_COL,
    max_rows_per_run: int = 50,
) -> Dict[str, Any]:
    """
    Read new rows from the story sheet, extract main company + competitors, register
    any that aren't already watched targets, and log each row processed so re-running
    this (e.g. on the next scheduled cycle) only picks up genuinely new/edited rows.

    Registration is capped at max_rows_per_run *rows* (not targets) per call - a large
    backlog on the first-ever run is deliberately spread across multiple scheduled
    cycles rather than firing a burst of homepage-discovery searches + career-page
    fetches all at once. Newly registered targets are picked up by the *next* normal
    radar scan cycle (not scanned synchronously here) - see RadarBackgroundScheduler.
    """
    from job_pulse.pipeline.sheets_sync import GoogleSheetsManager
    from job_pulse.radar.scanner import CompanyRadarScanner
    from job_pulse.scrapers.career_pages import CareerPageScraper

    stats: Dict[str, Any] = {
        "rows_scanned": 0,
        "rows_processed": 0,
        "rows_skipped": 0,
        "targets_created": 0,
        "errors": [],
    }

    try:
        rows = GoogleSheetsManager.read_worksheet_rows(sheets_config, sheet_id, sheet_name)
    except Exception as e:
        logger.error(f"Failed to read story sheet '{sheet_name}': {e}")
        stats["errors"].append(str(e))
        return stats

    if len(rows) <= 1:
        return stats

    existing_targets = repo.get_company_targets(active_only=False)
    existing_names = [t["company_name"] for t in existing_targets]

    career_scraper = CareerPageScraper()
    processed_this_run = 0

    for row in rows[1:]:
        if processed_this_run >= max_rows_per_run:
            break

        stats["rows_scanned"] += 1
        row_hash = compute_row_hash(sheet_name, row)
        if repo.is_story_row_processed(row_hash):
            continue

        processed_this_run += 1
        main_company, competitors = extract_companies_from_story_row(row, main_company_col, competitors_col)

        if not main_company:
            repo.log_story_ingestion(StoryIngestionLog(
                sheet_row_hash=row_hash,
                main_company="",
                status="skipped",
                error_message="No usable company name in this row.",
            ))
            stats["rows_skipped"] += 1
            continue

        log = StoryIngestionLog(
            sheet_row_hash=row_hash,
            main_company=main_company,
            competitors=competitors,
            status="processed",
        )

        try:
            for candidate_name in [main_company] + competitors:
                if any(CompanyRadarScanner.is_company_match(candidate_name, existing) for existing in existing_names):
                    continue  # already a watched target under some name variant

                target = _register_new_target(candidate_name, career_scraper, source_row_id=log.id)
                repo.save_company_target(target)
                log.targets_created.append(target.id)
                existing_names.append(candidate_name)  # avoid re-registering within this same run
                stats["targets_created"] += 1
        except Exception as e:
            logger.error(f"Error registering targets for story row (main_company='{main_company}'): {e}")
            log.status = "error"
            log.error_message = str(e)
            stats["errors"].append(f"{main_company}: {e}")

        repo.log_story_ingestion(log)
        stats["rows_processed"] += 1

    return stats
