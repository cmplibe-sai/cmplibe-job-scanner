import time
import logging
from urllib.parse import quote_plus
from job_pulse.models import JobPost, SearchQuery, ScrapeResult, WorkMode
from job_pulse.scrapers.base import BaseScraper

logger = logging.getLogger("job_pulse.scraper.linkedin")


class LinkedInScraper(BaseScraper):
    """Scraper for public LinkedIn Job Postings via Guest API."""

    def __init__(self, client=None):
        super().__init__(client)
        self.portal_name = "linkedin"
        self.base_url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"

    def search(self, query: SearchQuery) -> ScrapeResult:
        start_time = time.time()
        jobs: list[JobPost] = []
        error_msg = None
        limit = min(query.limit, 100)
        start_offset = 0

        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://www.linkedin.com/jobs",
        }

        search_term = f"{query.keywords or ''} {query.company_name or ''}".strip() or (query.keywords or query.company_name or "")

        while len(jobs) < limit:
            params = {
                "keywords": search_term,
                "location": query.location or "India",
                "start": start_offset,
            }
            if query.remote_only:
                params["f_WT"] = "2"  # LinkedIn code for Remote

            resp = self.client.get(self.base_url, params=params, headers=headers)
            if not resp or resp.status_code != 200 or not resp.text.strip():
                if not jobs:
                    error_msg = f"LinkedIn returned HTTP {resp.status_code if resp else 'None'}"
                break

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "lxml")
            cards = soup.find_all("li")
            if not cards:
                cards = soup.find_all("div", class_=lambda c: c and "base-card" in c)

            if not cards:
                break

            page_jobs_count = 0
            for card in cards:
                try:
                    title_elem = card.find(class_=lambda c: c and "base-search-card__title" in c) or card.find("h3")
                    company_elem = card.find(class_=lambda c: c and "base-search-card__subtitle" in c) or card.find("h4")
                    location_elem = card.find(class_=lambda c: c and "job-search-card__location" in c)
                    link_elem = card.find("a", class_=lambda c: c and "base-card__full-link" in c) or card.find("a")
                    time_elem = card.find("time")

                    if not title_elem or not link_elem:
                        continue

                    title = title_elem.get_text(strip=True)
                    company = company_elem.get_text(strip=True) if company_elem else "Unknown Company"

                    if query.company_name:
                        from job_pulse.radar.scanner import CompanyRadarScanner
                        if not CompanyRadarScanner.is_company_match(company, query.company_name):
                            continue

                    location = location_elem.get_text(strip=True) if location_elem else "Not Specified"
                    job_url = link_elem.get("href", "").split("?")[0]
                    posted_date = time_elem.get("datetime") or time_elem.get_text(strip=True) if time_elem else None

                    work_mode = self.detect_work_mode(f"{title} {location}")
                    if query.remote_only and work_mode != WorkMode.REMOTE and "remote" not in location.lower():
                        continue

                    job = JobPost(
                        title=title,
                        company=company,
                        location=location,
                        work_mode=work_mode,
                        url=job_url,
                        source_portal="LinkedIn",
                        posted_date=posted_date,
                    )
                    jobs.append(job)
                    page_jobs_count += 1

                    if len(jobs) >= limit:
                        break
                except Exception as e:
                    logger.debug(f"Error parsing LinkedIn card: {e}")
                    continue

            if page_jobs_count == 0:
                break

            start_offset += 25
            time.sleep(1.0)

        elapsed = time.time() - start_time
        return ScrapeResult(
            portal="LinkedIn",
            success=len(jobs) > 0 or error_msg is None,
            total_found=len(jobs),
            jobs=jobs,
            error_message=error_msg,
            execution_time_seconds=round(elapsed, 2),
        )
