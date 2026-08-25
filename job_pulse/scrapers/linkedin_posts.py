import time
import logging
import re
import urllib.parse
import base64
from typing import List, Optional
from bs4 import BeautifulSoup
from job_pulse.models import HiringPost, SearchQuery, ScrapeResult
from job_pulse.scrapers.base import BaseScraper

logger = logging.getLogger("job_pulse.scraper.linkedin_posts")


class LinkedInPostsScraper(BaseScraper):
    """
    Scraper for LinkedIn feed updates & posts where HRs, recruiters and hiring managers
    announce job vacancies and requirements in their personal posts.
    """

    def __init__(self, client=None):
        super().__init__(client)
        self.portal_name = "linkedin_posts"

    def search(self, query: SearchQuery) -> ScrapeResult:
        start_time = time.time()
        posts: List[HiringPost] = []
        error_msg = None
        limit = min(query.limit, 50)

        # Build search query for recruiter announcements
        kw = query.keywords.strip()
        loc = query.location.strip()
        company = query.company_name.strip() if query.company_name else ""
        
        search_terms = []
        if company:
            search_terms.append(f'"{company}"')
        if kw:
            search_terms.append(f'"{kw}"')
        if loc and loc.lower() != "all":
            search_terms.append(f'"{loc}"')

        term_str = " ".join(search_terms)
        q_bing = f'site:linkedin.com/posts "hiring" {term_str}'.strip()

        # 1. Search via Bing
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://www.bing.com/",
        }

        resp = self.client.get(f"https://www.bing.com/search?q={urllib.parse.quote_plus(q_bing)}", headers=headers)
        if resp and resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "lxml")
            results = soup.find_all("li", class_="b_algo")
            for res in results:
                try:
                    h2 = res.find("h2")
                    caption = res.find("div", class_="b_caption") or res.find("p")
                    link = h2.find("a") if h2 else None
                    if not h2 or not link:
                        continue

                    raw_title = h2.get_text(strip=True)
                    snippet_text = caption.get_text(strip=True) if caption else ""
                    href = link.get("href", "")

                    # Unpack Bing base64 redirect
                    real_url = href
                    if "u=a1" in href:
                        m = re.search(r"u=a1([a-zA-Z0-9_\-]+)", href)
                        if m:
                            try:
                                padded = m.group(1) + "=" * (-len(m.group(1)) % 4)
                                real_url = base64.b64decode(padded).decode("utf-8", errors="ignore")
                            except Exception:
                                pass

                    if "linkedin.com/posts/" not in real_url and "linkedin.com/feed/update/" not in real_url and "linkedin.com/in/" not in real_url:
                        continue

                    # Parse Poster Name and Role Title
                    poster_name = "Recruiter / Hiring Manager"
                    role_title = kw or "Open Position"
                    if " on LinkedIn:" in raw_title:
                        parts = raw_title.split(" on LinkedIn:", 1)
                        poster_name = parts[0].strip()
                        role_title = parts[1].strip().lstrip("- :|")
                    elif " - " in raw_title:
                        parts = raw_title.split(" - ", 1)
                        poster_name = parts[0].strip()
                        role_title = parts[1].strip()

                    # Extract profile URL if available
                    poster_profile = None
                    if "/posts/" in real_url:
                        match_u = re.search(r"linkedin\.com/posts/([a-zA-Z0-9_\-]+)", real_url)
                        if match_u and "-activity-" in match_u.group(1):
                            user_slug = match_u.group(1).split("-activity-")[0]
                            poster_profile = f"https://www.linkedin.com/in/{user_slug}"
                    elif "/in/" in real_url:
                        poster_profile = real_url.split("?")[0]

                    # Extract emails
                    contact_email = None
                    m_email = re.search(r"[\w\.\-]+@[\w\.\-]+\.[a-zA-Z]{2,}", snippet_text)
                    if m_email:
                        contact_email = m_email.group(0)

                    # Extract phone / whatsapp
                    contact_phone = None
                    m_phone = re.search(r"(?:\+91[\-\s]?)?[6-9]\d{9}", snippet_text)
                    if m_phone:
                        contact_phone = m_phone.group(0)

                    post_obj = HiringPost(
                        poster_name=poster_name,
                        poster_title="Talent Acquisition / Hiring Team",
                        poster_profile_url=poster_profile,
                        company=company or "Hiring Organization",
                        role_title=role_title,
                        post_text=snippet_text,
                        post_url=real_url,
                        contact_email=contact_email,
                        contact_phone=contact_phone,
                        location=loc or "India",
                    )
                    posts.append(post_obj)
                    if len(posts) >= limit:
                        break
                except Exception as e:
                    logger.debug(f"Error parsing post: {e}")
                    continue

        elapsed = time.time() - start_time
        return ScrapeResult(
            portal="LinkedIn Hiring Posts",
            success=len(posts) > 0 or error_msg is None,
            total_found=len(posts),
            jobs=[],
            hiring_posts=posts,
            error_message=error_msg,
            execution_time_seconds=round(elapsed, 2),
        )
