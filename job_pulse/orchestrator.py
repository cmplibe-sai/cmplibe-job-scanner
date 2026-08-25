import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Callable, Optional, Any
from job_pulse.models import SearchQuery, ScrapeResult, JobPost, HiringPost
from job_pulse.scrapers import SCRAPER_MAP, CareerPageScraper, LinkedInPostsScraper
from job_pulse.storage.db import JobDatabase
from job_pulse.pipeline.deduplicator import JobDeduplicator

logger = logging.getLogger("job_pulse.orchestrator")


class ScraperOrchestrator:
    """Orchestrates parallel execution of job and hiring post scrapers with deduplication and storage."""

    def __init__(self, db: Optional[JobDatabase] = None):
        self.db = db or JobDatabase()

    def run(
        self,
        query: SearchQuery,
        progress_callback: Optional[Callable[[str, ScrapeResult], None]] = None,
        max_workers: int = 6,
    ) -> Dict[str, Any]:
        start_time = time.time()
        results: Dict[str, ScrapeResult] = {}
        all_raw_jobs: List[JobPost] = []
        all_hiring_posts: List[HiringPost] = []

        # If search_type is company, adapt keywords
        if query.search_type == "company" or query.company_name:
            c_name = query.company_name or query.keywords
            query.company_name = c_name

        # Select scraper instances
        active_scrapers = {}
        for portal_key in query.portals:
            if portal_key in SCRAPER_MAP:
                active_scrapers[portal_key] = SCRAPER_MAP[portal_key]()

        if query.career_urls and "career_page" not in active_scrapers:
            active_scrapers["career_page"] = CareerPageScraper()

        if query.include_linkedin_posts and "linkedin_posts" not in active_scrapers:
            active_scrapers["linkedin_posts"] = LinkedInPostsScraper()

        # Run scrapers in parallel
        with ThreadPoolExecutor(max_workers=min(max_workers, max(1, len(active_scrapers)))) as executor:
            future_to_portal = {
                executor.submit(scraper.search, query): portal_name
                for portal_name, scraper in active_scrapers.items()
            }

            for future in as_completed(future_to_portal):
                portal_name = future_to_portal[future]
                try:
                    result = future.result()
                    results[portal_name] = result
                    if result.jobs:
                        all_raw_jobs.extend(result.jobs)
                    if result.hiring_posts:
                        all_hiring_posts.extend(result.hiring_posts)
                    if progress_callback:
                        progress_callback(portal_name, result)
                except Exception as e:
                    logger.error(f"Error in scraper '{portal_name}': {e}")
                    res = ScrapeResult(
                        portal=portal_name,
                        success=False,
                        total_found=0,
                        jobs=[],
                        hiring_posts=[],
                        error_message=str(e),
                    )
                    results[portal_name] = res
                    if progress_callback:
                        progress_callback(portal_name, res)

        # Cross-portal deduplication
        unique_jobs, clusters = JobDeduplicator.process_and_deduplicate(all_raw_jobs)

        # Store in database with dedup cluster ID
        new_jobs_count = 0
        for cluster_id, cluster_list in clusters.items():
            for job in cluster_list:
                if self.db.save_job(job, dedup_group_id=cluster_id):
                    new_jobs_count += 1

        # Store hiring posts
        new_posts_count = self.db.save_hiring_posts_batch(all_hiring_posts)

        total_time = round(time.time() - start_time, 2)

        # Log search run
        self.db.log_search_run(
            keywords=query.keywords,
            location=query.location,
            portals=list(active_scrapers.keys()),
            total_found=len(all_raw_jobs) + len(all_hiring_posts),
            exec_time=total_time,
        )

        return {
            "total_scraped": len(all_raw_jobs),
            "unique_jobs": len(unique_jobs),
            "new_stored": new_jobs_count,
            "total_hiring_posts": len(all_hiring_posts),
            "new_posts_stored": new_posts_count,
            "execution_time_seconds": total_time,
            "portal_results": results,
            "jobs": [j.model_dump() for j in unique_jobs],
            "hiring_posts": [p.model_dump() for p in all_hiring_posts],
        }
