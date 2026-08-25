import time
import logging
import json
import re
from urllib.parse import quote_plus
from job_pulse.models import JobPost, SearchQuery, ScrapeResult, WorkMode
from job_pulse.scrapers.base import BaseScraper

logger = logging.getLogger("job_pulse.scraper.indeed")


class IndeedScraper(BaseScraper):
    """Scraper for Indeed jobs."""

    def __init__(self, client=None):
        super().__init__(client)
        self.portal_name = "indeed"
        self.base_url = "https://in.indeed.com/jobs"

    def search(self, query: SearchQuery) -> ScrapeResult:
        start_time = time.time()
        jobs: list[JobPost] = []
        error_msg = None
        limit = min(query.limit, 100)
        start_offset = 0

        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Referer": "https://in.indeed.com/",
        }

        while len(jobs) < limit:
            params = {
                "q": query.keywords,
                "l": query.location or "India",
                "start": start_offset,
            }
            if query.remote_only:
                params["sc"] = "0kf:attr(DS3S6);"  # Indeed Remote filter

            soup = self.client.get_soup(self.base_url, params=params, headers=headers)
            if not soup:
                if not jobs:
                    error_msg = "Indeed search request failed or was challenged."
                break

            # Try parsing embedded JSON-LD or script data first
            ld_jobs = self._extract_json_ld(soup, query)
            if ld_jobs:
                jobs.extend(ld_jobs)
                if len(jobs) >= limit:
                    break

            cards = soup.find_all("div", class_=lambda c: c and "job_seen_beacon" in c) or soup.find_all("div", class_="cardOutline") or soup.find_all("div", attrs={"data-jk": True})
            if not cards:
                break

            page_jobs = 0
            for card in cards:
                try:
                    title_elem = card.find("h2", class_=lambda c: c and "jobTitle" in c) or card.find("h2")
                    comp_elem = card.find(attrs={"data-testid": "company-name"}) or card.find(class_=lambda c: c and "companyName" in c)
                    loc_elem = card.find(attrs={"data-testid": "text-location"}) or card.find(class_=lambda c: c and "companyLocation" in c)
                    salary_elem = card.find(class_=lambda c: c and "salary-snippet-container" in c) or card.find(attrs={"data-testid": "attribute_snippets_test_id"})
                    
                    if not title_elem:
                        continue

                    title = title_elem.get_text(strip=True)
                    company = comp_elem.get_text(strip=True) if comp_elem else "Company"
                    location = loc_elem.get_text(strip=True) if loc_elem else "Not Specified"

                    # JK attribute for Direct Job URL
                    jk = card.get("data-jk") or (card.find("a", attrs={"data-jk": True}) or {}).get("data-jk")
                    link_elem = title_elem.find("a") or card.find("a")
                    if jk:
                        job_url = f"https://in.indeed.com/viewjob?jk={jk}"
                    elif link_elem and link_elem.get("href"):
                        href = link_elem["href"]
                        job_url = f"https://in.indeed.com{href}" if href.startswith("/") else href
                    else:
                        job_url = self.base_url

                    sal_text = salary_elem.get_text(strip=True) if salary_elem else None
                    sal_min, sal_max, cur, _ = self.parse_salary(sal_text or "")

                    work_mode = self.detect_work_mode(f"{title} {location}")
                    if query.remote_only and work_mode != WorkMode.REMOTE and "remote" not in location.lower():
                        continue

                    job = JobPost(
                        title=title,
                        company=company,
                        location=location,
                        work_mode=work_mode,
                        salary_min=sal_min,
                        salary_max=sal_max,
                        salary_currency=cur,
                        salary_text=sal_text,
                        url=job_url,
                        source_portal="Indeed",
                    )
                    jobs.append(job)
                    page_jobs += 1

                    if len(jobs) >= limit:
                        break
                except Exception as e:
                    logger.debug(f"Error parsing Indeed card: {e}")
                    continue

            if page_jobs == 0:
                break

            start_offset += 10
            time.sleep(1.2)

        elapsed = time.time() - start_time
        return ScrapeResult(
            portal="Indeed",
            success=len(jobs) > 0 or error_msg is None,
            total_found=len(jobs),
            jobs=jobs[:limit],
            error_message=error_msg,
            execution_time_seconds=round(elapsed, 2),
        )

    def _extract_json_ld(self, soup, query: SearchQuery) -> list[JobPost]:
        """Extract jobs from Schema.org JSON-LD scripts if present."""
        jobs: list[JobPost] = []
        scripts = soup.find_all("script", type="application/ld+json")
        for s in scripts:
            try:
                data = json.loads(s.string or "")
                if isinstance(data, dict) and data.get("@type") == "JobPosting":
                    data = [data]
                elif isinstance(data, dict) and "@graph" in data:
                    data = data["@graph"]

                if isinstance(data, list):
                    for item in data:
                        if item.get("@type") == "JobPosting":
                            title = item.get("title", "")
                            comp = item.get("hiringOrganization", {}).get("name", "Company")
                            loc = item.get("jobLocation", {}).get("address", {}).get("addressLocality", "Not Specified")
                            url = item.get("url", "")
                            if title and url:
                                jobs.append(
                                    JobPost(
                                        title=title,
                                        company=comp,
                                        location=loc,
                                        work_mode=self.detect_work_mode(f"{title} {loc}"),
                                        url=url,
                                        source_portal="Indeed",
                                        posted_date=item.get("datePosted"),
                                    )
                                )
            except Exception:
                continue
        return jobs
