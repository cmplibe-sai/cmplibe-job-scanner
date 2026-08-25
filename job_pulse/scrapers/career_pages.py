import time
import logging
import json
import re
from urllib.parse import urlparse, urljoin
from typing import List, Optional
from bs4 import BeautifulSoup
from job_pulse.models import JobPost, SearchQuery, ScrapeResult, WorkMode
from job_pulse.scrapers.base import BaseScraper

logger = logging.getLogger("job_pulse.scraper.career_page")


class CareerPageScraper(BaseScraper):
    """
    Universal Company Career Page & ATS Scraper.
    Supports Greenhouse, Lever, Ashby, Workday, SmartRecruiters,
    and Generic Company Career Portals (e.g. Jumbotail, Swiggy, custom ATS).
    """

    def __init__(self, client=None):
        super().__init__(client)
        self.portal_name = "career_page"

    def search(self, query: SearchQuery) -> ScrapeResult:
        start_time = time.time()
        all_jobs: list[JobPost] = []
        errors = []

        career_urls = query.career_urls or []
        if not career_urls and (query.keywords.startswith("http://") or query.keywords.startswith("https://")):
            career_urls = [query.keywords]

        if not career_urls:
            return ScrapeResult(
                portal="Career Pages / ATS",
                success=True,
                total_found=0,
                jobs=[],
                error_message="No career page URLs provided.",
                execution_time_seconds=0.0,
            )

        for target_url in career_urls:
            try:
                jobs = self.scrape_url(
                    target_url,
                    keyword_filter=query.keywords if not query.keywords.startswith("http") else "",
                    company_override=query.company_name or ""
                )
                all_jobs.extend(jobs)
            except Exception as e:
                err = f"Failed to scrape {target_url}: {e}"
                logger.error(err)
                errors.append(err)

        elapsed = time.time() - start_time
        return ScrapeResult(
            portal="Career Pages / ATS",
            success=len(all_jobs) > 0 or not errors,
            total_found=len(all_jobs),
            jobs=all_jobs,
            error_message="; ".join(errors) if errors else None,
            execution_time_seconds=round(elapsed, 2),
        )

    def scrape_url(self, url: str, keyword_filter: str = "", company_override: str = "") -> List[JobPost]:
        """Auto-detect ATS or fall back to verified generic career crawler."""
        url_lower = url.lower()

        if "greenhouse.io" in url_lower:
            return self._scrape_greenhouse(url, keyword_filter, company_override)
        elif "lever.co" in url_lower:
            return self._scrape_lever(url, keyword_filter, company_override)
        elif "ashbyhq.com" in url_lower:
            return self._scrape_ashby(url, keyword_filter, company_override)
        elif "smartrecruiters.com" in url_lower:
            return self._scrape_smartrecruiters(url, keyword_filter, company_override)
        elif "myworkdayjobs.com" in url_lower:
            return self._scrape_workday(url, keyword_filter, company_override)
        else:
            return self._scrape_generic_page(url, keyword_filter, company_override)

    def _scrape_greenhouse(self, url: str, keyword_filter: str = "", company_override: str = "") -> List[JobPost]:
        """Scrape Greenhouse public board API."""
        jobs: list[JobPost] = []
        match = re.search(r"greenhouse\.io/(?:embed/job_board/|v1/boards/)?([a-zA-Z0-9_\-]+)", url)
        board_token = match.group(1) if match else url.rstrip("/").split("/")[-1]
        company = company_override or board_token.replace("-", " ").title()

        api_url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
        resp = self.client.get(api_url)
        if not resp or resp.status_code != 200:
            return self._scrape_generic_page(url, keyword_filter, company_override)

        try:
            data = resp.json()
            for item in data.get("jobs", []):
                title = item.get("title", "").strip()
                if not self._is_valid_job_title(title, url):
                    continue
                if keyword_filter and not self._matches_filter(title, keyword_filter):
                    continue

                loc_info = item.get("location", {})
                location = loc_info.get("name", "Not Specified") if isinstance(loc_info, dict) else str(loc_info)
                job_url = item.get("absolute_url") or f"https://boards.greenhouse.io/{board_token}/jobs/{item.get('id')}"
                updated = item.get("updated_at")

                jobs.append(
                    JobPost(
                        title=title,
                        company=company,
                        location=location,
                        work_mode=self.detect_work_mode(f"{title} {location}"),
                        url=job_url,
                        source_portal=f"Greenhouse ({company})",
                        posted_date=updated,
                    )
                )
        except Exception as e:
            logger.error(f"Greenhouse parse error: {e}")
        return jobs

    def _scrape_lever(self, url: str, keyword_filter: str = "", company_override: str = "") -> List[JobPost]:
        """Scrape Lever public API."""
        jobs: list[JobPost] = []
        match = re.search(r"jobs\.lever\.co/([a-zA-Z0-9_\-]+)", url)
        company_slug = match.group(1) if match else url.rstrip("/").split("/")[-1]
        company = company_override or company_slug.replace("-", " ").title()

        api_url = f"https://api.lever.co/v0/postings/{company_slug}?mode=json"
        resp = self.client.get(api_url)
        if not resp or resp.status_code != 200:
            return self._scrape_generic_page(url, keyword_filter, company_override)

        try:
            data = resp.json()
            for item in data:
                title = item.get("text", "").strip()
                if not self._is_valid_job_title(title, url):
                    continue
                if keyword_filter and not self._matches_filter(title, keyword_filter):
                    continue

                cats = item.get("categories", {})
                location = cats.get("location") or cats.get("workplaceType") or "Not Specified"
                work_mode_str = cats.get("workplaceType", "")
                job_url = item.get("hostedUrl") or item.get("applyUrl") or url

                jobs.append(
                    JobPost(
                        title=title,
                        company=company,
                        location=location,
                        work_mode=self.detect_work_mode(f"{title} {location} {work_mode_str}"),
                        url=job_url,
                        source_portal=f"Lever ({company})",
                        posted_date=str(item.get("createdAt")),
                    )
                )
        except Exception as e:
            logger.error(f"Lever parse error: {e}")
        return jobs

    def _scrape_ashby(self, url: str, keyword_filter: str = "", company_override: str = "") -> List[JobPost]:
        """Scrape Ashby public API."""
        jobs: list[JobPost] = []
        match = re.search(r"jobs\.ashbyhq\.com/([a-zA-Z0-9_\-]+)", url)
        board_slug = match.group(1) if match else url.rstrip("/").split("/")[-1]
        company = company_override or board_slug.replace("-", " ").title()

        api_url = f"https://api.ashbyhq.com/posting-api/job-board/{board_slug}"
        resp = self.client.get(api_url)
        if not resp or resp.status_code != 200:
            return self._scrape_generic_page(url, keyword_filter, company_override)

        try:
            data = resp.json()
            for item in data.get("jobs", []):
                title = item.get("title", "").strip()
                if not self._is_valid_job_title(title, url):
                    continue
                if keyword_filter and not self._matches_filter(title, keyword_filter):
                    continue

                location = item.get("locationName", "Not Specified")
                job_url = item.get("jobUrl") or f"https://jobs.ashbyhq.com/{board_slug}/{item.get('id')}"

                jobs.append(
                    JobPost(
                        title=title,
                        company=company,
                        location=location,
                        work_mode=self.detect_work_mode(f"{title} {location} {item.get('isRemote', '')}"),
                        url=job_url,
                        source_portal=f"Ashby ({company})",
                        posted_date=item.get("publishedAt"),
                    )
                )
        except Exception as e:
            logger.error(f"Ashby parse error: {e}")
        return jobs

    def _scrape_smartrecruiters(self, url: str, keyword_filter: str = "", company_override: str = "") -> List[JobPost]:
        """Scrape SmartRecruiters public API."""
        jobs: list[JobPost] = []
        match = re.search(r"smartrecruiters\.com/([a-zA-Z0-9_\-]+)", url)
        company_slug = match.group(1) if match else url.rstrip("/").split("/")[-1]
        company = company_override or company_slug.replace("-", " ").title()

        api_url = f"https://api.smartrecruiters.com/v1/companies/{company_slug}/postings"
        resp = self.client.get(api_url)
        if not resp or resp.status_code != 200:
            return self._scrape_generic_page(url, keyword_filter, company_override)

        try:
            data = resp.json()
            for item in data.get("content", []):
                title = item.get("name", "").strip()
                if not self._is_valid_job_title(title, url):
                    continue
                if keyword_filter and not self._matches_filter(title, keyword_filter):
                    continue

                loc = item.get("location", {})
                location = f"{loc.get('city', '')}, {loc.get('country', '')}".strip(", ") or "Not Specified"
                job_url = f"https://jobs.smartrecruiters.com/{company_slug}/{item.get('id')}"

                jobs.append(
                    JobPost(
                        title=title,
                        company=company,
                        location=location,
                        work_mode=self.detect_work_mode(f"{title} {location}"),
                        url=job_url,
                        source_portal=f"SmartRecruiters ({company})",
                        posted_date=item.get("releasedDate"),
                    )
                )
        except Exception as e:
            logger.error(f"SmartRecruiters parse error: {e}")
        return jobs

    def _scrape_workday(self, url: str, keyword_filter: str = "", company_override: str = "") -> List[JobPost]:
        """Scrape Workday CXS endpoints or HTML."""
        jobs: list[JobPost] = []
        parsed = urlparse(url)
        host = parsed.netloc
        path_parts = [p for p in parsed.path.split("/") if p]
        
        if len(path_parts) >= 2:
            tenant = path_parts[0]
            site = path_parts[1]
            company = company_override or tenant.title()
            api_url = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
            payload = {"appliedFacets": {}, "limit": 50, "offset": 0, "searchText": keyword_filter}
            resp = self.client.post(api_url, json_data=payload)
            if resp and resp.status_code == 200:
                try:
                    data = resp.json()
                    for item in data.get("jobPostings", []):
                        title = item.get("title", "").strip()
                        if not self._is_valid_job_title(title, url):
                            continue
                        loc = item.get("locationsText", "Not Specified")
                        external_path = item.get("externalPath", "")
                        job_url = f"https://{host}/{tenant}/{site}{external_path}" if external_path else url
                        jobs.append(
                            JobPost(
                                title=title,
                                company=company,
                                location=loc,
                                work_mode=self.detect_work_mode(f"{title} {loc}"),
                                url=job_url,
                                source_portal=f"Workday ({company})",
                                posted_date=item.get("postedOn"),
                            )
                        )
                    if jobs:
                        return jobs
                except Exception:
                    pass

        return self._scrape_generic_page(url, keyword_filter, company_override)

    def _is_valid_job_url(self, full_url: str, base_url: str = "") -> bool:
        """Validate that a URL points to a specific job opening, not a homepage, retail service, or non-job page."""
        if not full_url or full_url.startswith("#") or full_url.startswith("javascript:") or full_url.startswith("mailto:") or full_url.startswith("tel:"):
            return False

        # Must not equal the parent homepage or base domain
        norm_full = full_url.rstrip("/").lower()
        norm_base = base_url.rstrip("/").lower()
        if norm_full == norm_base:
            return False

        parsed = urlparse(full_url)
        path = parsed.path.strip("/").lower()

        # Reject root paths or general landing slugs
        if path in ["", "home", "en", "in", "about", "about-us", "who-we-are", "contact", "contact-us", "services", "products"]:
            return False

        # Reject consumer, fintech, recharge, commerce, and media paths
        forbidden_path_terms = [
            "loan-emi", "recharge", "bill-payment", "electricity", "water-bill", "gas-bill",
            "challan", "ticket", "tickets", "flight", "bus", "train", "hotel", "movie",
            "credit-card", "loans", "personal-loan", "credit-score", "money-transfer",
            "online-payments", "instore-payments", "merchant", "offers", "shop", "store",
            "cart", "checkout", "payment", "login", "signin", "signup", "download",
            "privacy", "terms", "policy", "faq", "help", "newsroom", "blog", "press",
            "investor", "tools", "calculator", "/teams/", "/team/", "/life/", "/culture/",
            "/benefits/", "/locations/", "/diversity/", "/values/", "/people/"
        ]
        if any(term in path or term in norm_full for term in forbidden_path_terms):
            return False

        # Exclude common external social networks
        if any(s in norm_full for s in ["facebook.com", "twitter.com", "x.com", "instagram.com", "youtube.com", "play.google.com", "apps.apple.com"]):
            return False

        return True

    def _is_valid_job_title(self, title: str, url: str = "") -> bool:
        """Strict validation to ensure an extracted string is a real job role and not a company, lender, service, or tool."""
        from job_pulse.models import is_valid_job_listing
        return is_valid_job_listing(title=title, url=url)

    def _resolve_career_url(self, url: str) -> Optional[str]:
        """
        If given a generic corporate homepage (e.g. https://paytm.com), resolve the dedicated career page
        (e.g. https://paytm.com/careers or https://jobs.lever.co/paytm).
        If no dedicated career page exists on a retail homepage, returns None to avoid scraping retail products.
        """
        url_low = url.lower().rstrip("/")
        parsed = urlparse(url)
        path = parsed.path.strip("/").lower()

        # If URL already points to a careers or ATS path
        if any(p in path for p in ["career", "careers", "jobs", "job", "openings", "positions", "join-us", "work-with-us"]) or \
           any(ats in parsed.netloc for ats in ["lever.co", "greenhouse.io", "ashbyhq.com", "smartrecruiters.com", "workday"]):
            return url

        # If it's a root domain/homepage, fetch HTML and look for career portal links
        soup = self.client.get_soup(url)
        if not soup:
            return None

        career_patterns = [r"\bcareers?\b", r"\bjobs?\b", r"\bwork\s*with\s*us\b", r"\bjoin\s*(?:us|our\s*team)\b", r"\bopenings\b"]
        
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            text = a.get_text(strip=True).lower()
            href_low = href.lower()

            if any(re.search(pat, text) for pat in career_patterns) or any(re.search(pat, href_low) for pat in career_patterns):
                # Avoid mailto or anchor jump
                if not href.startswith("#") and not href.startswith("mailto:"):
                    resolved = urljoin(url, href)
                    if resolved.rstrip("/").lower() != url_low:
                        return resolved

        return None

    def _scrape_generic_page(self, url: str, keyword_filter: str = "", company_override: str = "") -> List[JobPost]:
        """
        Universal DOM / JSON-LD / HTML heuristic crawler.
        Strictly operates on verified careers portals, ensuring valid job titles and application URLs.
        """
        jobs: list[JobPost] = []
        
        # 1. Resolve career URL if a generic homepage was passed
        target_url = self._resolve_career_url(url)
        if not target_url:
            logger.info(f"No dedicated careers portal found for '{url}'. Skipping homepage crawl to prevent capturing retail/product links.")
            return jobs

        soup = self.client.get_soup(target_url)
        if not soup:
            return jobs

        parsed_domain = urlparse(target_url).netloc.replace("www.", "").split(".")[0].title()
        company = company_override or parsed_domain

        # 2. Try JSON-LD JobPosting schema
        scripts = soup.find_all("script", type="application/ld+json")
        for s in scripts:
            try:
                data = json.loads(s.string or "")
                items = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
                if isinstance(data, dict) and "@graph" in data:
                    items = data["@graph"]

                for item in items:
                    if isinstance(item, dict) and item.get("@type") == "JobPosting":
                        title = item.get("title", "").strip()
                        if not self._is_valid_job_title(title, target_url):
                            continue
                        if keyword_filter and not self._matches_filter(title, keyword_filter):
                            continue

                        hiring_org = item.get("hiringOrganization", {})
                        comp = hiring_org.get("name") if isinstance(hiring_org, dict) else company
                        loc_obj = item.get("jobLocation", {})
                        loc = "Not Specified"
                        if isinstance(loc_obj, dict):
                            addr = loc_obj.get("address", {})
                            loc = addr.get("addressLocality") or addr.get("addressRegion") or "Not Specified" if isinstance(addr, dict) else str(loc_obj)

                        job_url = item.get("url") or target_url
                        jobs.append(
                            JobPost(
                                title=title,
                                company=comp or company,
                                location=loc,
                                work_mode=self.detect_work_mode(f"{title} {loc}"),
                                url=urljoin(target_url, job_url),
                                source_portal=f"Career Site ({company})",
                                posted_date=item.get("datePosted"),
                            )
                        )
            except Exception:
                continue

        if jobs:
            return jobs

        # 3. Comprehensive DOM link and card crawler
        seen_urls = set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            btn_text = a.get_text(strip=True)
            raw_title = a.get("title", "").strip()

            full_url = urljoin(target_url, href)

            # Validate URL is a genuine job application link
            if not self._is_valid_job_url(full_url, target_url):
                continue

            norm_full = full_url.rstrip("/").lower()
            if norm_full in seen_urls:
                continue

            title = ""
            generic_words = {"view job", "apply", "apply now", "learn more", "read more", "careers", "career", "home", "details", "explore", "openings", "join us", "view opening"}
            if raw_title and raw_title.lower() not in generic_words:
                title = raw_title

            if not title and btn_text and len(btn_text) > 3 and btn_text.lower() not in generic_words:
                title = btn_text

            if not title:
                parent_row = a.find_parent(class_=lambda c: c and any(cls in str(c) for cls in ["row", "vc_row", "wpb_row", "job-item", "career-card", "job-card", "item", "post"])) or a.find_parent(["div", "li", "tr", "article", "section"])
                if parent_row:
                    for elem in parent_row.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "strong", "span", "p", "div"]):
                        t = elem.get_text(strip=True)
                        if t and 4 <= len(t) <= 90 and t.lower() not in generic_words and not elem.find("a"):
                            if self._is_valid_job_title(t, full_url):
                                title = t
                                break

            # Validate extracted title
            if not self._is_valid_job_title(title, full_url):
                continue

            if keyword_filter and not self._matches_filter(title, keyword_filter):
                continue

            seen_urls.add(norm_full)
            jobs.append(
                JobPost(
                    title=title,
                    company=company,
                    location="Not Specified",
                    work_mode=self.detect_work_mode(title),
                    url=full_url,
                    source_portal=f"Career Site ({company})",
                )
            )

        return jobs

    def _matches_filter(self, text: str, query: str) -> bool:
        if not query:
            return True
        terms = [t.strip().lower() for t in query.split() if t.strip()]
        text_lower = text.lower()
        return any(t in text_lower for t in terms)
