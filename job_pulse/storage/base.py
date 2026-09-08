from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, Tuple

from job_pulse.models import (
    JobPost,
    HiringPost,
    CompanyTarget,
    RadarAlertLog,
    DiscoveryAlertLog,
    StoryIngestionLog,
)


class JobRepository(ABC):
    """
    Storage-backend-agnostic interface for cMPLiBe AIScanner.

    Every backend (SQLite for local dev/testing, Postgres/Supabase for production)
    implements this contract so callers (server.py, orchestrator.py, radar/*.py)
    never need to know which one is active - see job_pulse/storage/factory.py.
    """

    # ==========================================
    # Jobs
    # ==========================================

    @abstractmethod
    def save_job(self, job: JobPost, dedup_group_id: Optional[str] = None) -> bool:
        """Insert or update a job post. Returns True if newly inserted."""

    @abstractmethod
    def save_jobs_batch(self, jobs: List[JobPost]) -> int:
        """Save a batch of jobs. Returns count of newly inserted rows."""

    @abstractmethod
    def get_jobs(
        self,
        keywords: Optional[str] = None,
        location: Optional[str] = None,
        company: Optional[str] = None,
        portal: Optional[str] = None,
        work_mode: Optional[str] = None,
        role_type: Optional[str] = None,
        experience_level: Optional[str] = None,
        is_internship: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
        status: Optional[str] = None,
        favorite_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """Query jobs with resilient multi-facet filtering."""

    @abstractmethod
    def update_job_status(self, job_id: str, status: str) -> bool: ...

    @abstractmethod
    def toggle_favorite(self, job_id: str) -> bool: ...

    @abstractmethod
    def delete_job(self, job_id: str) -> bool: ...

    # ==========================================
    # Hiring Posts
    # ==========================================

    @abstractmethod
    def save_hiring_post(self, post: HiringPost) -> bool:
        """Insert or update a hiring post. Returns True if newly inserted."""

    @abstractmethod
    def save_hiring_posts_batch(self, posts: List[HiringPost]) -> int: ...

    @abstractmethod
    def get_hiring_posts(
        self,
        keywords: Optional[str] = None,
        location: Optional[str] = None,
        company: Optional[str] = None,
        role_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]: ...

    # ==========================================
    # Search run logging & stats
    # ==========================================

    @abstractmethod
    def log_search_run(self, keywords: str, location: str, portals: List[str], total_found: int, exec_time: float) -> None: ...

    @abstractmethod
    def get_stats(self) -> Dict[str, Any]: ...

    # ==========================================
    # Target Company Radar
    # ==========================================

    @abstractmethod
    def save_company_target(self, target: CompanyTarget) -> bool:
        """Add or update a target company in the Radar watchlist. Returns True if newly inserted."""

    @abstractmethod
    def get_company_targets(self, active_only: bool = False) -> List[Dict[str, Any]]: ...

    @abstractmethod
    def get_company_target(self, target_id: str) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    def update_company_target_scan(self, target_id: str, found_count: int) -> None: ...

    @abstractmethod
    def toggle_company_target(self, target_id: str) -> bool: ...

    @abstractmethod
    def delete_company_target(self, target_id: str) -> bool: ...

    # ==========================================
    # Target Radar Alert Logs
    # ==========================================

    @abstractmethod
    def is_alert_already_sent(self, item_id: str, recipient_email: str) -> bool: ...

    @abstractmethod
    def save_radar_alert_log(self, alert_log: RadarAlertLog) -> bool: ...

    @abstractmethod
    def get_radar_alert_logs(self, limit: int = 100) -> List[Dict[str, Any]]: ...

    # ==========================================
    # All-India Discovery Alert Logs
    # ==========================================

    @abstractmethod
    def is_discovery_alert_already_sent(self, item_id: str, recipient_email: str) -> bool: ...

    @abstractmethod
    def save_discovery_alert_log(self, alert_log: DiscoveryAlertLog) -> bool: ...

    @abstractmethod
    def get_discovery_alert_logs(self, limit: int = 100) -> List[Dict[str, Any]]: ...

    # ==========================================
    # Google Sheets Settings
    # ==========================================

    @abstractmethod
    def get_sheets_config(self) -> Dict[str, Any]: ...

    @abstractmethod
    def save_sheets_config(self, config_dict: Dict[str, Any]) -> bool: ...

    @abstractmethod
    def update_sheets_sync_stats(self, synced_count: int) -> None: ...

    # ==========================================
    # Email & Dual Radar Configuration
    # ==========================================

    @abstractmethod
    def get_email_config(self) -> Dict[str, Any]: ...

    @abstractmethod
    def save_email_config(self, config_dict: Dict[str, Any]) -> bool: ...

    # ==========================================
    # User Authentication & Team Security
    # ==========================================

    @abstractmethod
    def verify_user_credentials(self, username: str, password: str) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    def get_user_role(self, username: str) -> Optional[str]: ...

    @abstractmethod
    def add_user(self, username: str, password: str, role: str = "member") -> Tuple[bool, str]: ...

    @abstractmethod
    def change_user_password(self, username: str, old_password: str, new_password: str) -> Tuple[bool, str]: ...

    @abstractmethod
    def admin_reset_user_password(self, target_username: str, new_password: str) -> Tuple[bool, str]: ...

    @abstractmethod
    def admin_toggle_user_status(self, target_username: str, requesting_username: str) -> Tuple[bool, str]: ...

    @abstractmethod
    def admin_delete_user(self, target_username: str, requesting_username: str) -> Tuple[bool, str]: ...

    @abstractmethod
    def update_user_last_login(self, username: str) -> None: ...

    @abstractmethod
    def get_users_list(self) -> List[Dict[str, Any]]: ...

    # ==========================================
    # Story Ingestion (automated company discovery)
    # ==========================================

    @abstractmethod
    def is_story_row_processed(self, row_hash: str) -> bool:
        """Check whether a 'cMPLi Dip Stories' sheet row has already been ingested."""

    @abstractmethod
    def log_story_ingestion(self, log: StoryIngestionLog) -> bool:
        """Record the outcome of processing one story-sheet row (idempotency watermark)."""

    @abstractmethod
    def get_story_ingestion_logs(self, limit: int = 100) -> List[Dict[str, Any]]: ...
