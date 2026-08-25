import time
import logging
from job_pulse.models import JobPost, SearchQuery, ScrapeResult, WorkMode
from job_pulse.scrapers.base import BaseScraper

logger = logging.getLogger("job_pulse.scraper.foundit")


class FounditScraper(BaseScraper):
    """Scraper for Foundit (formerly Monster India / Global)."""

    def __init__(self, client=None):
        super().__init__(client)
        self.portal_name = "foundit"
        self.api_url = "https://www.foundit.in/middleware/jobsearch"

    def search(self, query: SearchQuery) -> ScrapeResult:
        start_time = time.time()
        jobs: list[JobPost] = []
        error_msg = None
        limit = min(query.limit, 100)
        start = 0

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.foundit.in/srp/results",
            "Content-Type": "application/json",
        }

        while len(jobs) < limit:
            payload = {
                "query": query.keywords,
                "locations": [query.location] if query.location else [],
                "start": start,
                "limit": min(20, limit - len(jobs)),
                "filter": {"quickFilters": ["wfh"]} if query.remote_only else {},
            }

            resp = self.client.post(self.api_url, json_data=payload, headers=headers)
            if not resp or resp.status_code != 200:
                # If API fails or blocks, attempt HTML search fallback
                if not jobs:
                    jobs = self._scrape_html_fallback(query)
                    if not jobs and resp:
                        error_msg = f"Foundit returned HTTP {resp.status_code}"
                break

            try:
                data = resp.json()
                results = data.get("jobSearchResponse", {}).get("data", []) or data.get("data", [])
                if not results:
                    break

                for item in results:
                    title = item.get("title") or item.get("jobTitle") or ""
                    comp_info = item.get("company", {})
                    company = comp_info.get("name") if isinstance(comp_info, dict) else str(comp_info) or item.get("companyName", "Company")

                    # Location
                    locs = item.get("locations", [])
                    location = ", ".join([l.get("city", "") if isinstance(l, dict) else str(l) for l in locs]) if locs else item.get("location", "Not Specified")

                    # Experience
                    min_exp = item.get("minimumExperience", {}).get("years") if isinstance(item.get("minimumExperience"), dict) else item.get("minimumExperience")
                    max_exp = item.get("maximumExperience", {}).get("years") if isinstance(item.get("maximumExperience"), dict) else item.get("maximumExperience")
                    exp_text = f"{min_exp or 0}-{max_exp or ''} Yrs" if min_exp is not None or max_exp is not None else None

                    # Salary
                    min_sal = item.get("minimumSalary", {}).get("amount") if isinstance(item.get("minimumSalary"), dict) else item.get("minimumSalary")
                    max_sal = item.get("maximumSalary", {}).get("amount") if isinstance(item.get("maximumSalary"), dict) else item.get("maximumSalary")
                    sal_cur = item.get("currency", "INR")
                    sal_text = f"{min_sal}-{max_sal} {sal_cur}" if min_sal or max_sal else None

                    # Skills
                    skills_raw = item.get("skills", [])
                    skills = [s.get("text", "") if isinstance(s, dict) else str(s) for s in skills_raw if s]

                    # URL
                    job_url = item.get("redirectUrl") or f"https://www.foundit.in/job-detail/{item.get('jobId', '')}"
                    posted_date = item.get("postedAt") or item.get("postedDate")

                    work_mode = self.detect_work_mode(f"{title} {location}")
                    if query.remote_only and work_mode != WorkMode.REMOTE and "remote" not in location.lower():
                        continue

                    job = JobPost(
                        title=title.strip(),
                        company=company.strip(),
                        location=location.strip() or "Not Specified",
                        work_mode=work_mode,
                        experience_min=float(min_exp) if min_exp is not None else None,
                        experience_max=float(max_exp) if max_exp is not None else None,
                        experience_text=exp_text,
                        salary_min=float(min_sal) if min_sal is not None else None,
                        salary_max=float(max_sal) if max_sal is not None else None,
                        salary_currency=sal_cur,
                        salary_text=sal_text,
                        skills=skills,
                        description=item.get("description", "") or item.get("jobDescription", ""),
                        url=job_url,
                        source_portal="Foundit (Monster)",
                        posted_date=str(posted_date) if posted_date else None,
                    )
                    jobs.append(job)
                    if len(jobs) >= limit:
                        break

                start += 20
                time.sleep(1.0)
            except Exception as e:
                logger.error(f"Error parsing Foundit response: {e}")
                break

        elapsed = time.time() - start_time
        return ScrapeResult(
            portal="Foundit (Monster)",
            success=len(jobs) > 0 or error_msg is None,
            total_found=len(jobs),
            jobs=jobs,
            error_message=error_msg,
            execution_time_seconds=round(elapsed, 2),
        )

    def _scrape_html_fallback(self, query: SearchQuery) -> list[JobPost]:
        """Fallback HTML scraping for Foundit SRP."""
        jobs: list[JobPost] = []
        kw = query.keywords.replace(" ", "-")
        url = f"https://www.foundit.in/srp/results?query={kw}"
        if query.location:
            url += f"&locations={query.location}"

        soup = self.client.get_soup(url)
        if not soup:
            return jobs

        cards = soup.find_all("div", class_=lambda c: c and "srpResultCard" in c)
        for card in cards[:query.limit]:
            try:
                title_elem = card.find(class_=lambda c: c and "cardTitle" in c) or card.find("h3")
                comp_elem = card.find(class_=lambda c: c and "companyName" in c)
                loc_elem = card.find(class_=lambda c: c and "location" in c)
                exp_elem = card.find(class_=lambda c: c and "experience" in c)
                sal_elem = card.find(class_=lambda c: c and "salary" in c)
                link_elem = card.find("a")

                if not title_elem:
                    continue

                title = title_elem.get_text(strip=True)
                company = comp_elem.get_text(strip=True) if comp_elem else "Company"
                location = loc_elem.get_text(strip=True) if loc_elem else "Not Specified"
                job_url = link_elem.get("href", "") if link_elem else url
                if job_url.startswith("/"):
                    job_url = "https://www.foundit.in" + job_url

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
                        source_portal="Foundit (Monster)",
                    )
                )
            except Exception as e:
                logger.debug(f"Error parsing Foundit card: {e}")
                continue

        return jobs
