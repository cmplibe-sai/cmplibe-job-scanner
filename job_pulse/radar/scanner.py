import logging
import time
import re
from typing import List, Dict, Any, Optional
from job_pulse.models import CompanyTarget, JobPost, HiringPost, SearchQuery, RadarAlertLog
from job_pulse.storage.db import JobDatabase
from job_pulse.scrapers.career_pages import CareerPageScraper
from job_pulse.scrapers.linkedin import LinkedInScraper
from job_pulse.scrapers.internshala import InternshalaScraper
from job_pulse.scrapers.unstop import UnstopScraper
from job_pulse.scrapers.shine import ShineScraper
from job_pulse.scrapers.linkedin_posts import LinkedInPostsScraper
from job_pulse.pipeline.deduplicator import JobDeduplicator
from job_pulse.radar.notifier import RadarEmailNotifier
from job_pulse.pipeline.sheets_sync import GoogleSheetsManager

logger = logging.getLogger("job_pulse.radar.scanner")


class CompanyRadarScanner:
    """
    Scans watched target companies across ATS, Portals, and Social Feeds.
    Performs delta tracking to identify only newly announced openings and dispatches email alerts.
    """

    @staticmethod
    def is_company_match(job_company: str, target_company: str) -> bool:
        """
        Verify if a scraped job's company name belongs to the target company.
        Handles variations like 'Khatabook Technologies Pvt Ltd' vs 'Khatabook',
        'Paytm Payments Services Ltd' vs 'Paytm', 'REA India Pvt Ltd' vs 'REA Group', etc.
        Prevents false positive substring matches (e.g. 'REA' inside 'Greater Than Equal').
        """
        if not job_company or not target_company:
            return False

        def _clean_name(name: str) -> str:
            n = name.lower()
            noise_patterns = [
                r"\bprivate\s*limited\b", r"\bpvt\s*ltd\b", r"\blimited\b", r"\bltd\b",
                r"\btechnologies\b", r"\btechnology\b", r"\bservices\b", r"\bsolutions\b",
                r"\bcorporation\b", r"\bcorp\b", r"\binc\b", r"\bllc\b", r"\bglobal\b",
                r"\bindia\b", r"\bapp\b", r"\blabs?\b", r"\bgroup\b", r"\bsoftware\b"
            ]
            for pat in noise_patterns:
                n = re.sub(pat, " ", n)
            n = re.sub(r"[^\w\s]", " ", n)
            return " ".join(n.split()).strip()

        clean_job_comp = _clean_name(job_company) or job_company.lower().strip()
        clean_target = _clean_name(target_company) or target_company.lower().strip()

        if not clean_job_comp or not clean_target:
            return False

        # Exact match
        if clean_target == clean_job_comp:
            return True

        # Word boundary exact match (e.g. \brea\b in 'rea group', but NOT in 'greater')
        if re.search(rf"\b{re.escape(clean_target)}\b", clean_job_comp) or \
           re.search(rf"\b{re.escape(clean_job_comp)}\b", clean_target):
            return True

        # Check significant tokens: all target tokens must be present as distinct words
        target_tokens = [t for t in clean_target.split() if len(t) >= 2]
        comp_tokens = set(clean_job_comp.split())
        if target_tokens and all(tok in comp_tokens for tok in target_tokens):
            return True

        return False

    def __init__(self, db: Optional[JobDatabase] = None):
        self.db = db or JobDatabase()
        self.career_scraper = CareerPageScraper()
        self.linkedin_scraper = LinkedInScraper()
        self.internshala_scraper = InternshalaScraper()
        self.unstop_scraper = UnstopScraper()
        self.shine_scraper = ShineScraper()
        self.posts_scraper = LinkedInPostsScraper()

    def scan_target(self, target: CompanyTarget, send_email: bool = True) -> Dict[str, Any]:
        """Scan a single company across multiple channels and email new delta opportunities."""
        c_name = target.company_name.strip()
        logger.info(f"Starting Radar scan for target company: {c_name}")
        
        all_jobs: List[JobPost] = []
        all_posts: List[HiringPost] = []
        errors: List[str] = []

        # 1. Direct Career Page / ATS Crawler
        if target.career_url and "ats" in target.channels:
            try:
                c_jobs = self.career_scraper.scrape_url(
                    url=target.career_url,
                    keyword_filter=target.keywords or "",
                    company_override=c_name,
                )
                all_jobs.extend(c_jobs)
                logger.info(f"Career page crawl found {len(c_jobs)} jobs for {c_name}")
            except Exception as e:
                err = f"Career page error for {c_name}: {e}"
                logger.warning(err)
                errors.append(err)

        # 2. Multi-Portal Searches (Broad search: all experience levels, freshers, internships, mid, senior)
        portal_query = SearchQuery(
            keywords=target.keywords or "",
            company_name=c_name,
            search_type="company",
            experience_level=None,  # Capture ALL levels (Freshers 0-1 Y, Internships, Experienced)
            limit=50,
        )

        # LinkedIn Jobs
        if "linkedin" in target.channels:
            try:
                res = self.linkedin_scraper.search(portal_query)
                if res.jobs:
                    all_jobs.extend(res.jobs)
            except Exception as e:
                errors.append(f"LinkedIn error: {e}")

        # Internshala (For internships & fresher entry-level opportunities)
        if "internshala" in target.channels:
            try:
                res = self.internshala_scraper.search(portal_query)
                if res.jobs:
                    all_jobs.extend(res.jobs)
            except Exception as e:
                errors.append(f"Internshala error: {e}")

        # Unstop (For graduate & student opportunities)
        if "unstop" in target.channels:
            try:
                res = self.unstop_scraper.search(portal_query)
                if res.jobs:
                    all_jobs.extend(res.jobs)
            except Exception as e:
                errors.append(f"Unstop error: {e}")

        # Shine
        if "shine" in target.channels:
            try:
                res = self.shine_scraper.search(portal_query)
                if res.jobs:
                    all_jobs.extend(res.jobs)
            except Exception as e:
                errors.append(f"Shine error: {e}")

        # 3. Social Media & Recruiter Feeds (LinkedIn hiring posts)
        if "social_posts" in target.channels:
            try:
                res = self.posts_scraper.search(portal_query)
                if res.hiring_posts:
                    all_posts.extend(res.hiring_posts)
            except Exception as e:
                errors.append(f"Social posts error: {e}")

        # 4. Strict Company Match Filter: ensure jobs actually belong to the target company
        matched_jobs = [j for j in all_jobs if self.is_company_match(j.company, c_name)]
        # Filter out non-job navigation links, department cards, and overview pages
        valid_matched_jobs = [
            j for j in matched_jobs 
            if RadarEmailNotifier._is_valid_job_for_email(j.model_dump(), target_company=c_name)
        ]
        matched_posts = [
            p for p in all_posts 
            if self.is_company_match(p.company, c_name) or (c_name.lower() in (p.post_text or "").lower())
        ]

        # Deduplicate jobs
        unique_jobs, _ = JobDeduplicator.process_and_deduplicate(valid_matched_jobs)

        # Save to database
        self.db.save_jobs_batch(unique_jobs)
        self.db.save_hiring_posts_batch(matched_posts)

        # Update last scan on target
        total_found = len(unique_jobs) + len(matched_posts)
        self.db.update_company_target_scan(target.id, total_found)

        # 5. Delta Engine: Filter out previously emailed items
        email_config = self.db.get_email_config()
        recipient = email_config.get("recipient_email", "").strip()

        new_jobs_to_email = []
        new_posts_to_email = []

        if recipient:
            for j in unique_jobs:
                if not self.db.is_alert_already_sent(j.id, recipient):
                    new_jobs_to_email.append(j.model_dump())

            for p in matched_posts:
                if not self.db.is_alert_already_sent(p.id, recipient):
                    new_posts_to_email.append(p.model_dump())

        email_status = "No recipient configured"
        if send_email and recipient and (new_jobs_to_email or new_posts_to_email):
            if email_config.get("is_enabled", False) or send_email:
                success, msg = RadarEmailNotifier.send_radar_alert(
                    company_name=c_name,
                    new_jobs=new_jobs_to_email,
                    new_posts=new_posts_to_email,
                    recipient=recipient,
                    config=email_config,
                )
                email_status = msg
                if success:
                    # Log alerts as sent so they won't be re-emailed
                    for item in new_jobs_to_email:
                        log_entry = RadarAlertLog(
                            company_id=target.id,
                            item_type="job",
                            item_id=item["id"],
                            title=item["title"],
                            company=item["company"],
                            url=item["url"],
                            source=item["source_portal"],
                            experience_text=item.get("experience_text"),
                            location=item.get("location"),
                            recipient_email=recipient,
                        )
                        self.db.save_radar_alert_log(log_entry)

                    for item in new_posts_to_email:
                        log_entry = RadarAlertLog(
                            company_id=target.id,
                            item_type="post",
                            item_id=item["id"],
                            title=f"Post by {item['poster_name']}: {item['role_title']}",
                            company=item["company"],
                            url=item["post_url"],
                            source="LinkedIn Recruiter Post",
                            location=item.get("location"),
                            recipient_email=recipient,
                        )
                        self.db.save_radar_alert_log(log_entry)
            else:
                email_status = "Email alerts disabled in settings"

        # Live Google Sheets Synchronization for Target Company Radar
        sheets_config = self.db.get_sheets_config()
        if sheets_config.get("is_enabled") and sheets_config.get("spreadsheet_id_or_url"):
            try:
                raw_jobs = [j.model_dump() for j in unique_jobs]
                raw_posts = [p.model_dump() for p in matched_posts]
                ok_j, cnt_j, _ = GoogleSheetsManager.sync_jobs(
                    jobs=raw_jobs,
                    config=sheets_config,
                    sheet_name=sheets_config.get("sheet_name_target_radar", "Target Company Radar"),
                )
                ok_p, cnt_p, _ = GoogleSheetsManager.sync_hiring_posts(
                    posts=raw_posts,
                    config=sheets_config,
                    sheet_name=sheets_config.get("sheet_name_hiring_posts", "Recruiter Posts"),
                )
                if (cnt_j + cnt_p) > 0:
                    self.db.update_sheets_sync_stats(cnt_j + cnt_p)
            except Exception as e:
                logger.warning(f"Target company Google Sheets sync error: {e}")

        return {
            "company_id": target.id,
            "company_name": c_name,
            "total_jobs_found": len(unique_jobs),
            "total_posts_found": len(all_posts),
            "new_jobs_detected": len(new_jobs_to_email),
            "new_posts_detected": len(new_posts_to_email),
            "email_status": email_status,
            "errors": errors,
        }

    def scan_all_targets(self, send_email: bool = True) -> List[Dict[str, Any]]:
        """Scan all active targets in the Radar watchlist."""
        targets = self.db.get_company_targets(active_only=True)
        results = []
        for t_dict in targets:
            try:
                target_obj = CompanyTarget(**t_dict)
                res = self.scan_target(target_obj, send_email=send_email)
                results.append(res)
            except Exception as e:
                logger.error(f"Error scanning target {t_dict.get('company_name')}: {e}")
                results.append({
                    "company_name": t_dict.get("company_name"),
                    "error": str(e)
                })
        return results
