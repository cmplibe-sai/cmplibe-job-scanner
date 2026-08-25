import time
import logging
import json
from urllib.parse import quote_plus
from job_pulse.models import JobPost, SearchQuery, ScrapeResult, WorkMode
from job_pulse.scrapers.base import BaseScraper

logger = logging.getLogger("job_pulse.scraper.shine")


class ShineScraper(BaseScraper):
    """Scraper for Shine.com jobs."""

    def __init__(self, client=None):
        super().__init__(client)
        self.portal_name = "shine"
        self.api_url = "https://www.shine.com/api/v2/jobs/search/"

    def search(self, query: SearchQuery) -> ScrapeResult:
        start_time = time.time()
        jobs: list[JobPost] = []
        error_msg = None
        limit = min(query.limit, 100)

        search_term = (query.keywords or query.company_name or "").strip()
        kw_slug = search_term.replace(" ", "-").lower() if search_term else "all"
        url = f"https://www.shine.com/job-search/{kw_slug}-jobs"
        if query.location and query.location.lower() not in ["india", "all", ""]:
            url += f"-in-{query.location.replace(' ', '-').lower()}"

        soup = self.client.get_soup(url)
        if soup:
            next_script = soup.find("script", id="__NEXT_DATA__")
            if next_script and next_script.string:
                try:
                    data = json.loads(next_script.string)
                    jsrp = data.get("props", {}).get("pageProps", {}).get("initialState", {}).get("jsrp", {})
                    results = jsrp.get("searchresult", {}).get("data", {}).get("results", [])
                    for item in results:
                        title = str(item.get("jJT") or item.get("job_title") or "").strip()
                        company = str(item.get("jCName") or item.get("company_name") or "Company").strip()

                        if query.company_name:
                            from job_pulse.radar.scanner import CompanyRadarScanner
                            if not CompanyRadarScanner.is_company_match(company, query.company_name):
                                continue
                        
                        raw_loc = item.get("jLoc") or "Not Specified"
                        if isinstance(raw_loc, list):
                            location = ", ".join([str(l) for l in raw_loc if l])
                        else:
                            location = str(raw_loc)
                        
                        sal_text = str(item.get("jSal")) if item.get("jSal") else None
                        exp_text = str(item.get("jExp")) if item.get("jExp") else None
                        desc = str(item.get("jJD") or "")
                        slug = str(item.get("jSlug") or "").strip().lstrip("/")
                        job_id = str(item.get("id") or "").strip()
                        if slug:
                            if job_id and not slug.endswith(job_id) and "/" not in slug:
                                job_url = f"https://www.shine.com/jobs/{slug}/{job_id}"
                            else:
                                job_url = f"https://www.shine.com/jobs/{slug}"
                        elif job_id:
                            job_url = f"https://www.shine.com/jobs/{job_id}"
                        else:
                            job_url = url
                        
                        raw_kwd = item.get("jKwd") or ""
                        if isinstance(raw_kwd, list):
                            skills = [str(k).strip() for k in raw_kwd if str(k).strip()]
                        else:
                            skills = [str(k).strip() for k in str(raw_kwd).split(",") if str(k).strip()]

                        exp_min, exp_max, _ = self.parse_experience(exp_text or "")
                        sal_min, sal_max, cur, _ = self.parse_salary(sal_text or "")

                        work_mode = self.detect_work_mode(f"{title} {location} {desc}")
                        if query.remote_only and work_mode != WorkMode.REMOTE and "remote" not in location.lower():
                            continue

                        jobs.append(
                            JobPost(
                                title=title,
                                company=company,
                                location=location,
                                work_mode=work_mode,
                                experience_min=exp_min,
                                experience_max=exp_max,
                                experience_text=exp_text,
                                salary_min=sal_min,
                                salary_max=sal_max,
                                salary_currency=cur,
                                salary_text=sal_text,
                                skills=skills,
                                description=desc,
                                url=job_url,
                                source_portal="Shine",
                                posted_date=str(item.get("jPDate")) if item.get("jPDate") else None,
                            )
                        )
                        if len(jobs) >= limit:
                            break
                except Exception as e:
                    logger.debug(f"Error parsing Shine SSR data: {e}")

        # Fallback to HTML elements if SSR didn't populate
        if not jobs and soup:
            jobs = self._scrape_html(query)

        elapsed = time.time() - start_time
        return ScrapeResult(
            portal="Shine",
            success=len(jobs) > 0 or error_msg is None,
            total_found=len(jobs),
            jobs=jobs[:limit],
            error_message=error_msg,
            execution_time_seconds=round(elapsed, 2),
        )

    def _scrape_html(self, query: SearchQuery) -> list[JobPost]:
        """Scrape Shine search results from HTML."""
        jobs: list[JobPost] = []
        kw_slug = query.keywords.replace(" ", "-")
        url = f"https://www.shine.com/job-search/{kw_slug}-jobs"
        if query.location:
            url += f"-in-{query.location.replace(' ', '-')}"

        soup = self.client.get_soup(url)
        if not soup:
            return jobs

        cards = soup.find_all("div", class_=lambda c: c and "jobCard" in c) or soup.find_all("div", class_=lambda c: c and "parentClass" in c)
        for card in cards[:query.limit]:
            try:
                title_elem = card.find("h2") or card.find("a", class_=lambda c: c and "jobTitle" in c)
                comp_elem = card.find("div", class_=lambda c: c and "companyName" in c) or card.find("span", class_=lambda c: c and "company" in c)
                loc_elem = card.find("div", class_=lambda c: c and "loc" in c) or card.find("span", class_=lambda c: c and "loc" in c)
                exp_elem = card.find("div", class_=lambda c: c and "exp" in c) or card.find("span", class_=lambda c: c and "exp" in c)
                sal_elem = card.find("div", class_=lambda c: c and "sal" in c) or card.find("span", class_=lambda c: c and "sal" in c)

                if not title_elem:
                    continue

                title = title_elem.get_text(strip=True)
                company = comp_elem.get_text(strip=True) if comp_elem else "Company"
                location = loc_elem.get_text(strip=True) if loc_elem else "Not Specified"

                link = title_elem.find("a") if title_elem.name != "a" else title_elem
                job_url = link.get("href", "") if link else url
                if job_url.startswith("/"):
                    job_url = "https://www.shine.com" + job_url

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
                        source_portal="Shine",
                    )
                )
            except Exception as e:
                logger.debug(f"Error parsing Shine HTML card: {e}")
                continue

        return jobs
