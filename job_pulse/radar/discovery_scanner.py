import logging
import time
from typing import List, Dict, Any, Optional
from job_pulse.models import SearchQuery, JobPost, HiringPost, DiscoveryAlertLog
from job_pulse.storage.db import JobDatabase
from job_pulse.orchestrator import ScraperOrchestrator
from job_pulse.radar.notifier import RadarEmailNotifier
from job_pulse.pipeline.sheets_sync import GoogleSheetsManager

logger = logging.getLogger("job_pulse.radar.discovery_scanner")


class AllIndiaDiscoveryScanner:
    """
    Scans employment portals & recruiter networks across India for newly posted opportunities.
    Identifies unseen openings, dispatches dedicated All-India email digests, and live-syncs to Google Sheets.
    """

    def __init__(self, db: Optional[JobDatabase] = None, orchestrator: Optional[ScraperOrchestrator] = None):
        self.db = db or JobDatabase()
        self.orchestrator = orchestrator or ScraperOrchestrator(db=self.db)

    def scan_all_india(
        self,
        keywords: Optional[str] = None,
        location: str = "India",
        role_type: str = "all",
        experience_level: Optional[str] = None,
        limit_per_portal: int = 35,
        send_email: bool = True,
        sync_sheets: bool = True,
    ) -> Dict[str, Any]:
        """
        Execute broad All-India scan across portals, filter deltas, dispatch email alert,
        and synchronize newly discovered jobs into Google Sheets live.
        """
        start_time = time.time()
        email_config = self.db.get_email_config()
        recipient = (email_config.get("all_india_recipient") or email_config.get("recipient_email", "")).strip()

        search_kw = keywords or email_config.get("all_india_keywords", "developer, engineer, manager, recruiter, analyst, intern, fresher")
        target_loc = location or email_config.get("all_india_locations", "India")

        logger.info(f"Starting All-India Opportunity Radar scan [Keywords: '{search_kw}', Location: '{target_loc}']")

        query = SearchQuery(
            keywords=search_kw,
            location=target_loc,
            search_type="role",
            role_type=role_type,
            experience_level=experience_level,
            limit=limit_per_portal,
            portals=["linkedin", "internshala", "unstop", "shine", "naukri", "foundit", "indeed", "linkedin_posts"],
            include_linkedin_posts=True,
        )

        scrape_res = self.orchestrator.run(query)
        all_jobs = scrape_res.get("jobs", [])
        all_posts = scrape_res.get("hiring_posts", [])

        # 1. Delta identification for email alerts
        new_jobs_to_email: List[Dict[str, Any]] = []
        new_posts_to_email: List[Dict[str, Any]] = []

        if recipient:
            for j in all_jobs:
                j_id = j.get("id")
                if j_id and not self.db.is_discovery_alert_already_sent(j_id, recipient):
                    new_jobs_to_email.append(j)

            for p in all_posts:
                p_id = p.get("id")
                if p_id and not self.db.is_discovery_alert_already_sent(p_id, recipient):
                    new_posts_to_email.append(p)
        else:
            new_jobs_to_email = all_jobs
            new_posts_to_email = all_posts

        # 2. Email Dispatch
        email_status = "No recipient email configured for All-India alerts."
        if send_email and recipient and (new_jobs_to_email or new_posts_to_email):
            if email_config.get("all_india_is_enabled", False) or send_email:
                success, msg = RadarEmailNotifier.send_all_india_alert(
                    new_jobs=new_jobs_to_email,
                    new_posts=new_posts_to_email,
                    recipient=recipient,
                    config=email_config,
                )
                email_status = msg
                if success:
                    # Log dispatched items
                    for item in new_jobs_to_email:
                        log_entry = DiscoveryAlertLog(
                            item_type="job",
                            item_id=item["id"],
                            title=item["title"],
                            company=item["company"],
                            url=item["url"],
                            source=item.get("source_portal", "Portal"),
                            role_type=item.get("role_type", "Non-Technical"),
                            experience_text=item.get("experience_text"),
                            location=item.get("location"),
                            recipient_email=recipient,
                        )
                        self.db.save_discovery_alert_log(log_entry)

                    for item in new_posts_to_email:
                        log_entry = DiscoveryAlertLog(
                            item_type="post",
                            item_id=item["id"],
                            title=f"Post by {item['poster_name']}: {item['role_title']}",
                            company=item.get("company", "Company"),
                            url=item.get("post_url", "#"),
                            source="LinkedIn Recruiter Post",
                            role_type="Non-Technical",
                            location=item.get("location"),
                            recipient_email=recipient,
                        )
                        self.db.save_discovery_alert_log(log_entry)
            else:
                email_status = "All-India Email alerts disabled in settings."

        # 3. Live Google Sheets Synchronization
        sheets_status = "Google Sheets sync disabled or not configured."
        synced_jobs_count = 0
        synced_posts_count = 0

        if sync_sheets:
            sheets_config = self.db.get_sheets_config()
            if sheets_config.get("is_enabled") and sheets_config.get("spreadsheet_id_or_url"):
                try:
                    ok_j, cnt_j, msg_j = GoogleSheetsManager.sync_jobs(
                        jobs=all_jobs,
                        config=sheets_config,
                        sheet_name=sheets_config.get("sheet_name_all_india", "All-India Jobs"),
                    )
                    synced_jobs_count = cnt_j

                    ok_p, cnt_p, msg_p = GoogleSheetsManager.sync_hiring_posts(
                        posts=all_posts,
                        config=sheets_config,
                        sheet_name=sheets_config.get("sheet_name_hiring_posts", "Recruiter Posts"),
                    )
                    synced_posts_count = cnt_p

                    total_synced = cnt_j + cnt_p
                    if total_synced > 0:
                        self.db.update_sheets_sync_stats(total_synced)
                    sheets_status = f"Synced {cnt_j} job(s) and {cnt_p} post(s) to Google Sheets."
                except Exception as e:
                    sheets_status = f"Google Sheets sync error: {e}"
                    logger.warning(sheets_status)

        total_time = round(time.time() - start_time, 2)

        return {
            "total_scraped": scrape_res.get("total_scraped", 0),
            "unique_jobs": scrape_res.get("unique_jobs", 0),
            "new_stored": scrape_res.get("new_stored", 0),
            "total_hiring_posts": scrape_res.get("total_hiring_posts", 0),
            "new_jobs_emailed": len(new_jobs_to_email),
            "new_posts_emailed": len(new_posts_to_email),
            "email_status": email_status,
            "sheets_status": sheets_status,
            "synced_jobs_to_sheets": synced_jobs_count,
            "synced_posts_to_sheets": synced_posts_count,
            "execution_time_seconds": total_time,
            "portal_results": scrape_res.get("portal_results", {}),
        }
