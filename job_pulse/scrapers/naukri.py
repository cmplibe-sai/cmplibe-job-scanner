import time
import logging
import json
from job_pulse.models import JobPost, SearchQuery, ScrapeResult, WorkMode
from job_pulse.scrapers.base import BaseScraper

logger = logging.getLogger("job_pulse.scraper.naukri")


class NaukriScraper(BaseScraper):
    """Scraper for Naukri.com using public API endpoints with fallback parsing."""

    def __init__(self, client=None):
        super().__init__(client)
        self.portal_name = "naukri"
        self.api_url = "https://www.naukri.com/jobapi/v3/search"

    def search(self, query: SearchQuery) -> ScrapeResult:
        start_time = time.time()
        jobs: list[JobPost] = []
        error_msg = None
        limit = min(query.limit, 100)
        page = 1

        headers = {
            "appid": "109",
            "systemid": "Naukri",
            "clientid": "d3wh4s14",
            "gid": "LOCATION,INDUSTRY,EDUCATION,FAREA_ROLE",
            "Accept": "application/json",
            "Referer": "https://www.naukri.com/",
        }

        while len(jobs) < limit:
            params = {
                "noOfResults": min(20, limit - len(jobs)),
                "keyword": query.keywords,
                "location": query.location or "",
                "pageNo": page,
                "searchType": "adv",
            }
            if query.remote_only:
                params["wfhType"] = "2"  # WFH filter in Naukri

            resp = self.client.get(self.api_url, params=params, headers=headers)
            if not resp or resp.status_code != 200:
                # If API fails, try HTML search fallback
                if not jobs:
                    jobs = self._scrape_html_fallback(query)
                    if not jobs and resp:
                        error_msg = f"Naukri returned HTTP {resp.status_code}"
                break

            try:
                data = resp.json()
                job_details = data.get("jobDetails", [])
                if not job_details:
                    break

                for item in job_details:
                    title = item.get("title", "").strip()
                    company = item.get("companyName", "").strip() or "Confidential"
                    
                    # Placeholders
                    placeholders = item.get("placeholders", [])
                    exp_text, salary_text, loc_text = None, None, None
                    for ph in placeholders:
                        p_type = ph.get("type")
                        if p_type == "experience":
                            exp_text = ph.get("label")
                        elif p_type == "salary":
                            salary_text = ph.get("label")
                        elif p_type == "location":
                            loc_text = ph.get("label")

                    # Location fallback
                    location = loc_text or item.get("location", "Not Specified")
                    if isinstance(location, list):
                        location = ", ".join(location)

                    # Skills / Tags
                    tags = item.get("tagsAndSkills", "")
                    skills = [s.strip() for s in tags.split(",") if s.strip()] if isinstance(tags, str) else []

                    # URL
                    job_id = item.get("jobId", "")
                    job_url = f"https://www.naukri.com{item.get('jdURL', '')}" if item.get("jdURL") else f"https://www.naukri.com/job-listings-{job_id}"

                    # Experience and Salary
                    exp_min, exp_max, _ = self.parse_experience(exp_text or "")
                    sal_min, sal_max, currency, _ = self.parse_salary(salary_text or "")

                    # Work mode
                    work_mode = self.detect_work_mode(f"{title} {location} {tags}")
                    if query.remote_only and work_mode != WorkMode.REMOTE and "remote" not in location.lower():
                        continue

                    # Posted date
                    posted_date = item.get("createdDate") or item.get("footerPlaceholderLabel")

                    job = JobPost(
                        title=title,
                        company=company,
                        location=location,
                        work_mode=work_mode,
                        experience_min=exp_min,
                        experience_max=exp_max,
                        experience_text=exp_text,
                        salary_min=sal_min,
                        salary_max=sal_max,
                        salary_currency=currency,
                        salary_text=salary_text,
                        skills=skills,
                        description=item.get("jobDescription", ""),
                        url=job_url,
                        source_portal="Naukri",
                        posted_date=str(posted_date) if posted_date else None,
                        raw_data={"jobId": job_id},
                    )
                    jobs.append(job)
                    if len(jobs) >= limit:
                        break

                page += 1
                time.sleep(1.0)
            except Exception as e:
                logger.error(f"Error parsing Naukri API response: {e}")
                break

        elapsed = time.time() - start_time
        return ScrapeResult(
            portal="Naukri",
            success=len(jobs) > 0 or error_msg is None,
            total_found=len(jobs),
            jobs=jobs,
            error_message=error_msg,
            execution_time_seconds=round(elapsed, 2),
        )

    def _scrape_html_fallback(self, query: SearchQuery) -> list[JobPost]:
        """Fallback HTML scraping for Naukri search pages."""
        jobs: list[JobPost] = []
        clean_kw = query.keywords.replace(" ", "-")
        url = f"https://www.naukri.com/{clean_kw}-jobs"
        if query.location:
            url += f"-in-{query.location.replace(' ', '-')}"

        soup = self.client.get_soup(url)
        if not soup:
            return jobs

        articles = soup.find_all("article", class_=lambda c: c and "jobTuple" in c) or soup.find_all("div", class_="srp-jobtuple-wrapper")
        for art in articles[:query.limit]:
            try:
                title_elem = art.find("a", class_="title")
                comp_elem = art.find("a", class_="comp-name") or art.find(class_="subTitle")
                loc_elem = art.find(class_="loc-wrap") or art.find(class_="location")
                exp_elem = art.find(class_="exp-wrap") or art.find(class_="experience")
                sal_elem = art.find(class_="sal-wrap") or art.find(class_="salary")

                if not title_elem:
                    continue

                title = title_elem.get_text(strip=True)
                company = comp_elem.get_text(strip=True) if comp_elem else "Company"
                location = loc_elem.get_text(strip=True) if loc_elem else "Not Specified"
                job_url = title_elem.get("href", "")

                exp_min, exp_max, exp_text = self.parse_experience(exp_elem.get_text(strip=True) if exp_elem else "")
                sal_min, sal_max, cur, sal_text = self.parse_salary(sal_elem.get_text(strip=True) if sal_elem else "")

                jobs.append(
                    JobPost(
                        title=title,
                        company=company,
                        location=location,
                        work_mode=self.detect_work_mode(f"{title} {location}"),
                        experience_min=exp_min,
                        experience_max=exp_max,
                        experience_text=exp_text,
                        salary_min=sal_min,
                        salary_max=sal_max,
                        salary_currency=cur,
                        salary_text=sal_text,
                        url=job_url,
                        source_portal="Naukri",
                    )
                )
            except Exception as e:
                logger.debug(f"Error parsing HTML Naukri card: {e}")
                continue

        return jobs
