import time
import logging
import urllib.parse
from bs4 import BeautifulSoup
from job_pulse.models import JobPost, SearchQuery, ScrapeResult, WorkMode
from job_pulse.scrapers.base import BaseScraper

logger = logging.getLogger("job_pulse.scraper.internshala")


class InternshalaScraper(BaseScraper):
    """Scraper for Internshala jobs and internships."""

    def __init__(self, client=None):
        super().__init__(client)
        self.portal_name = "internshala"

    def search(self, query: SearchQuery) -> ScrapeResult:
        start_time = time.time()
        jobs: list[JobPost] = []
        error_msg = None
        limit = min(query.limit, 100)

        search_term = (query.keywords or query.company_name or "").strip()
        clean_kw = search_term.replace(" ", "-").lower() if search_term else ""
        
        # Select base path: internships or jobs
        is_internship = query.internship_only or query.experience_level == "internship"
        base_section = "internships" if is_internship else "jobs"
        
        url = f"https://internshala.com/{base_section}/{clean_kw}-{base_section}/" if clean_kw else f"https://internshala.com/{base_section}/"
        if query.location and query.location.lower() not in ["india", "all", ""]:
            loc_slug = query.location.replace(" ", "-").lower()
            url = f"https://internshala.com/{base_section}/{clean_kw}-{base_section}-in-{loc_slug}/" if clean_kw else f"https://internshala.com/{base_section}/{base_section}-in-{loc_slug}/"

        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Referer": "https://internshala.com/",
        }

        soup = self.client.get_soup(url, headers=headers)
        if not soup:
            # Fallback to general jobs
            soup = self.client.get_soup(f"https://internshala.com/{base_section}/", headers=headers)

        if soup:
            cards = soup.find_all("div", class_=lambda c: c and "individual_internship" in c)
            for card in cards:
                try:
                    title_elem = card.find("a", class_="job-title-href") or card.find("h2") or card.find("h3")
                    comp_elem = card.find(class_="company_name") or card.find(class_="company_and_premium") or card.find(class_="company")
                    loc_elem = card.find(class_="location_link") or card.find(id="location_names")
                    sal_elem = card.find(class_="salary") or card.find(class_="stipend") or card.find(class_="desktop")
                    status_elem = card.find(class_="status-success") or card.find(class_="posted_by_container")

                    if not title_elem:
                        continue

                    title = title_elem.get_text(strip=True)
                    company = comp_elem.get_text(strip=True) if comp_elem else "Company"
                    # Clean company name
                    if "Actively hiring" in company:
                        company = company.replace("Actively hiring", "").strip()

                    if query.company_name:
                        from job_pulse.radar.scanner import CompanyRadarScanner
                        if not CompanyRadarScanner.is_company_match(company, query.company_name):
                            continue

                    location = loc_elem.get_text(strip=True) if loc_elem else "India"
                    raw_href = title_elem.get("href", "")
                    job_url = urllib.parse.urljoin("https://internshala.com", raw_href) if raw_href else url

                    sal_text = sal_elem.get_text(strip=True) if sal_elem else None
                    sal_min, sal_max, cur, _ = self.parse_salary(sal_text or "")

                    posted_date = status_elem.get_text(strip=True) if status_elem else "Recently Posted"

                    work_mode = self.detect_work_mode(f"{title} {location}")
                    if query.remote_only and work_mode != WorkMode.REMOTE and "remote" not in location.lower() and "work from home" not in location.lower():
                        continue

                    job = JobPost(
                        title=title,
                        company=company,
                        location=location,
                        work_mode=work_mode,
                        is_internship=is_internship or "intern" in title.lower(),
                        salary_min=sal_min,
                        salary_max=sal_max,
                        salary_currency=cur,
                        salary_text=sal_text,
                        url=job_url,
                        source_portal="Internshala",
                        posted_date=posted_date,
                    )
                    jobs.append(job)

                    if len(jobs) >= limit:
                        break
                except Exception as e:
                    logger.debug(f"Error parsing Internshala card: {e}")
                    continue

        elapsed = time.time() - start_time
        return ScrapeResult(
            portal="Internshala",
            success=len(jobs) > 0 or error_msg is None,
            total_found=len(jobs),
            jobs=jobs[:limit],
            error_message=error_msg,
            execution_time_seconds=round(elapsed, 2),
        )
