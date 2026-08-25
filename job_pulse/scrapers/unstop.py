import time
import logging
import urllib.parse
from job_pulse.models import JobPost, SearchQuery, ScrapeResult, WorkMode, clean_location_string
from job_pulse.scrapers.base import BaseScraper

logger = logging.getLogger("job_pulse.scraper.unstop")


class UnstopScraper(BaseScraper):
    """Scraper for Unstop (formerly Dare2Compete) jobs and internships."""

    def __init__(self, client=None):
        super().__init__(client)
        self.portal_name = "unstop"
        self.api_url = "https://unstop.com/api/public/opportunity/search-result"

    def search(self, query: SearchQuery) -> ScrapeResult:
        start_time = time.time()
        jobs: list[JobPost] = []
        error_msg = None
        limit = min(query.limit, 100)

        is_internship = query.internship_only or query.experience_level == "internship"
        opp_type = "internships" if is_internship else "jobs"

        params = {
            "opportunity": opp_type,
            "per_page": min(limit, 50),
            "oppstatus": "open",
        }
        search_term = (query.keywords or query.company_name or "").strip()
        if search_term:
            params["searchTerm"] = search_term

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://unstop.com/jobs",
        }

        resp = self.client.get(self.api_url, params=params, headers=headers)
        if resp and resp.status_code == 200:
            try:
                data = resp.json().get("data", {})
                results = data.get("data", []) or data.get("results", [])
                for item in results:
                    title = item.get("title", "").strip()
                    org_info = item.get("organisation", {})
                    company = org_info.get("name") if isinstance(org_info, dict) else str(org_info) or "Unstop Partner"

                    if query.company_name:
                        from job_pulse.radar.scanner import CompanyRadarScanner
                        if not CompanyRadarScanner.is_company_match(company, query.company_name):
                            continue

                    locs = item.get("locations", [])
                    if locs:
                        location = clean_location_string(locs)
                    else:
                        location = clean_location_string(item.get("location") or "India")

                    public_url = item.get("public_url", "")
                    job_url = f"https://unstop.com/{public_url}" if public_url else "https://unstop.com/jobs"

                    posted_date = item.get("created_at") or item.get("start_date") or "Recently Posted"

                    work_mode = self.detect_work_mode(f"{title} {location}")
                    if query.remote_only and work_mode != WorkMode.REMOTE and "remote" not in location.lower():
                        continue

                    # Filter by location if specified
                    if query.location and query.location.lower() not in ["india", "all", ""]:
                        if query.location.lower() not in location.lower():
                            continue

                    job = JobPost(
                        title=title,
                        company=company,
                        location=location,
                        work_mode=work_mode,
                        is_internship=is_internship or "intern" in title.lower(),
                        url=job_url,
                        source_portal="Unstop",
                        posted_date=str(posted_date) if posted_date else "Recently Posted",
                    )
                    jobs.append(job)

                    if len(jobs) >= limit:
                        break
            except Exception as e:
                logger.error(f"Error parsing Unstop API: {e}")
                error_msg = str(e)
        else:
            error_msg = f"Unstop returned HTTP {resp.status_code if resp else 'None'}"

        elapsed = time.time() - start_time
        return ScrapeResult(
            portal="Unstop",
            success=len(jobs) > 0 or error_msg is None,
            total_found=len(jobs),
            jobs=jobs[:limit],
            error_message=error_msg,
            execution_time_seconds=round(elapsed, 2),
        )
