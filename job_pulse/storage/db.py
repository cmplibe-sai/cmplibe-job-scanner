import sqlite3
import json
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any, Generator, Tuple
from contextlib import contextmanager
from datetime import datetime
from job_pulse.utils.time_utils import get_ist_iso, get_ist_now
from job_pulse.config import (
    DATABASE_PATH,
    DEFAULT_SMTP_HOST,
    DEFAULT_SMTP_PORT,
    DEFAULT_SMTP_USER,
    DEFAULT_SMTP_PASSWORD,
    DEFAULT_SENDER_EMAIL,
    DEFAULT_RECIPIENT_EMAIL,
    DEFAULT_ALL_INDIA_RECIPIENT_EMAIL,
    DEFAULT_RADAR_INTERVAL_MINUTES,
    DEFAULT_ALL_INDIA_RADAR_INTERVAL_MINUTES,
    DEFAULT_GOOGLE_SHEETS_SPREADSHEET_ID,
    DEFAULT_GOOGLE_SHEETS_CREDS_PATH,
)
from job_pulse.models import (
    JobPost,
    HiringPost,
    WorkMode,
    CompanyTarget,
    RadarAlertLog,
    DiscoveryAlertLog,
    EmailConfig,
    GoogleSheetsConfig,
)

logger = logging.getLogger("job_pulse.storage")


class JobDatabase:
    """SQLite Database manager for job storage, deduplication, hiring posts, company radar, and query filtering."""

    def __init__(self, db_path: Optional[Path] = None, init_default_targets: bool = False):
        self.db_path = db_path or DATABASE_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db(init_default_targets=init_default_targets)

    @contextmanager
    def _get_conn(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self, init_default_targets: bool = False) -> None:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    location TEXT,
                    work_mode TEXT,
                    is_internship INTEGER DEFAULT 0,
                    category TEXT DEFAULT 'General',
                    experience_min REAL,
                    experience_max REAL,
                    experience_text TEXT,
                    salary_min REAL,
                    salary_max REAL,
                    salary_currency TEXT,
                    salary_text TEXT,
                    skills TEXT,
                    description TEXT,
                    url TEXT NOT NULL,
                    source_portal TEXT NOT NULL,
                    posted_date TEXT,
                    scraped_at TEXT NOT NULL,
                    dedup_group_id TEXT,
                    is_favorite INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'new',
                    raw_data TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS hiring_posts (
                    id TEXT PRIMARY KEY,
                    poster_name TEXT NOT NULL,
                    poster_title TEXT,
                    poster_profile_url TEXT,
                    company TEXT,
                    role_title TEXT NOT NULL,
                    post_text TEXT NOT NULL,
                    post_url TEXT NOT NULL,
                    contact_email TEXT,
                    contact_phone TEXT,
                    location TEXT,
                    posted_date TEXT,
                    scraped_at TEXT NOT NULL,
                    is_favorite INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'new'
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS search_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    keywords TEXT NOT NULL,
                    location TEXT,
                    portals TEXT,
                    total_found INTEGER,
                    execution_time REAL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS company_targets (
                    id TEXT PRIMARY KEY,
                    company_name TEXT NOT NULL,
                    career_url TEXT,
                    keywords TEXT,
                    channels TEXT,
                    is_active INTEGER DEFAULT 1,
                    last_scanned_at TEXT,
                    last_found_count INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS radar_alert_logs (
                    id TEXT PRIMARY KEY,
                    company_id TEXT NOT NULL,
                    item_type TEXT DEFAULT 'job',
                    item_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    url TEXT NOT NULL,
                    source TEXT NOT NULL,
                    experience_text TEXT,
                    location TEXT,
                    emailed_at TEXT NOT NULL,
                    recipient_email TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS radar_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS discovery_alert_logs (
                    id TEXT PRIMARY KEY,
                    item_type TEXT DEFAULT 'job',
                    item_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    url TEXT NOT NULL,
                    source TEXT NOT NULL,
                    role_type TEXT DEFAULT 'Non-Technical',
                    experience_text TEXT,
                    location TEXT,
                    emailed_at TEXT NOT NULL,
                    recipient_email TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS sheets_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    role TEXT DEFAULT 'member',
                    is_active INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_login_at TEXT
                )
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_portal ON jobs(source_portal)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_scraped ON jobs(scraped_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_dedup ON jobs(dedup_group_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_posts_company ON hiring_posts(company)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_targets_company ON company_targets(company_name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_radar_item_email ON radar_alert_logs(item_id, recipient_email)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_discovery_item_email ON discovery_alert_logs(item_id, recipient_email)")

            # Auto-migrate columns if database existed before
            cursor.execute("PRAGMA table_info(jobs)")
            cols = [r["name"] for r in cursor.fetchall()]
            if "is_internship" not in cols:
                cursor.execute("ALTER TABLE jobs ADD COLUMN is_internship INTEGER DEFAULT 0")
            if "category" not in cols:
                cursor.execute("ALTER TABLE jobs ADD COLUMN category TEXT DEFAULT 'General'")
            if "role_type" not in cols:
                cursor.execute("ALTER TABLE jobs ADD COLUMN role_type TEXT DEFAULT 'Non-Technical'")

            cursor.execute("PRAGMA table_info(users)")
            user_cols = [r["name"] for r in cursor.fetchall()]
            if "role" not in user_cols:
                cursor.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'member'")
            if "is_active" not in user_cols:
                cursor.execute("ALTER TABLE users ADD COLUMN is_active INTEGER DEFAULT 1")
            cursor.execute("UPDATE users SET role = 'admin' WHERE username = 'admin'")

            # Initialize default admin user if none exists
            cursor.execute("SELECT id FROM users WHERE username = 'admin'")
            if not cursor.fetchone():
                import os
                from job_pulse.security import hash_password
                default_pwd = os.environ.get("ADMIN_PASSWORD", "cmplibe@2026")
                p_hash, salt = hash_password(default_pwd)
                cursor.execute(
                    "INSERT INTO users (username, password_hash, salt, role, is_active, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    ("admin", p_hash, salt, "admin", 1, get_ist_iso()),
                )

            # Initialize default watchlist targets if requested and table is empty
            if init_default_targets:
                cursor.execute("SELECT COUNT(*) as cnt FROM company_targets")
                if cursor.fetchone()["cnt"] == 0:
                    default_targets = [
                        ("target_jumbotail", "Jumbotail", "https://jumbotail.com/careers", "software, developer, engineer, intern, analyst", json.dumps(["career_page", "linkedin_posts", "portal"])),
                        ("target_paytm", "Paytm", "https://paytm.com/careers", "software, engineer, developer, operations, executive", json.dumps(["career_page", "linkedin_posts", "portal"])),
                        ("target_khatabook", "Khatabook", "https://khatabook.com/careers", "engineer, developer, product, intern", json.dumps(["career_page", "linkedin_posts", "portal"])),
                    ]
                    now_str = get_ist_iso()
                    for tid, name, url, kw, ch in default_targets:
                        cursor.execute(
                            "INSERT INTO company_targets (id, company_name, career_url, keywords, channels, is_active, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
                            (tid, name, url, kw, ch, now_str),
                        )

            conn.commit()

    def save_job(self, job: JobPost, dedup_group_id: Optional[str] = None) -> bool:
        """Insert or update a job post. Returns True if newly inserted."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM jobs WHERE id = ?", (job.id,))
            exists = cursor.fetchone() is not None

            cursor.execute(
                """
                INSERT INTO jobs (
                    id, title, company, location, work_mode, role_type, is_internship, category,
                    experience_min, experience_max, experience_text,
                    salary_min, salary_max, salary_currency, salary_text,
                    skills, description, url, source_portal,
                    posted_date, scraped_at, dedup_group_id, raw_data
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    location=excluded.location,
                    role_type=excluded.role_type,
                    salary_min=excluded.salary_min,
                    salary_max=excluded.salary_max,
                    salary_text=excluded.salary_text,
                    posted_date=excluded.posted_date,
                    scraped_at=excluded.scraped_at,
                    dedup_group_id=COALESCE(excluded.dedup_group_id, jobs.dedup_group_id)
                """,
                (
                    job.id,
                    job.title,
                    job.company,
                    job.location,
                    job.work_mode.value if isinstance(job.work_mode, WorkMode) else str(job.work_mode),
                    job.role_type.value if hasattr(job.role_type, "value") else str(job.role_type),
                    1 if job.is_internship else 0,
                    job.category or "General",
                    job.experience_min,
                    job.experience_max,
                    job.experience_text,
                    job.salary_min,
                    job.salary_max,
                    job.salary_currency,
                    job.salary_text,
                    json.dumps(job.skills),
                    job.description,
                    job.url,
                    job.source_portal,
                    job.posted_date or "Recently Posted",
                    job.scraped_at,
                    dedup_group_id,
                    json.dumps(job.raw_data) if job.raw_data else None,
                ),
            )
            conn.commit()
            return not exists

    def save_jobs_batch(self, jobs: List[JobPost]) -> int:
        new_count = 0
        for job in jobs:
            if self.save_job(job):
                new_count += 1
        return new_count

    def save_hiring_post(self, post: HiringPost) -> bool:
        """Insert or update a hiring post from LinkedIn/HR."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM hiring_posts WHERE id = ?", (post.id,))
            exists = cursor.fetchone() is not None

            cursor.execute(
                """
                INSERT INTO hiring_posts (
                    id, poster_name, poster_title, poster_profile_url,
                    company, role_title, post_text, post_url,
                    contact_email, contact_phone, location, posted_date, scraped_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    post_text=excluded.post_text,
                    contact_email=COALESCE(excluded.contact_email, hiring_posts.contact_email),
                    contact_phone=COALESCE(excluded.contact_phone, hiring_posts.contact_phone)
                """,
                (
                    post.id,
                    post.poster_name,
                    post.poster_title,
                    post.poster_profile_url,
                    post.company,
                    post.role_title,
                    post.post_text,
                    post.post_url,
                    post.contact_email,
                    post.contact_phone,
                    post.location,
                    post.posted_date,
                    post.scraped_at,
                ),
            )
            conn.commit()
            return not exists

    def save_hiring_posts_batch(self, posts: List[HiringPost]) -> int:
        new_count = 0
        for p in posts:
            if self.save_hiring_post(p):
                new_count += 1
        return new_count

    def log_search_run(self, keywords: str, location: str, portals: List[str], total_found: int, exec_time: float):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO search_runs (timestamp, keywords, location, portals, total_found, execution_time)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    get_ist_iso(),
                    keywords,
                    location,
                    ",".join(portals),
                    total_found,
                    exec_time,
                ),
            )
            conn.commit()

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
        query = "SELECT * FROM jobs WHERE 1=1"
        params: list[Any] = []

        if keywords:
            query += " AND (title LIKE ? OR company LIKE ? OR skills LIKE ? OR description LIKE ?)"
            term = f"%{keywords}%"
            params.extend([term, term, term, term])

        if company:
            query += " AND company LIKE ?"
            params.append(f"%{company}%")

        if location and location.lower() not in ["india", "all", "any", ""]:
            query += " AND location LIKE ?"
            params.append(f"%{location}%")

        if portal and portal.lower() not in ["all", ""]:
            p_low = portal.lower()
            if p_low in ["career", "ats", "career pages / ats"]:
                query += " AND (LOWER(source_portal) LIKE '%greenhouse%' OR LOWER(source_portal) LIKE '%lever%' OR LOWER(source_portal) LIKE '%ashby%' OR LOWER(source_portal) LIKE '%workday%' OR LOWER(source_portal) LIKE '%smartrecruiters%' OR LOWER(source_portal) LIKE '%career%')"
            else:
                query += " AND LOWER(source_portal) LIKE ?"
                params.append(f"%{p_low}%")

        if work_mode and work_mode not in ["All", ""]:
            query += " AND work_mode = ?"
            params.append(work_mode)

        if role_type and role_type.lower() not in ["all", ""]:
            if role_type.lower() == "technical":
                query += " AND (role_type = 'Technical' OR category = 'Tech')"
            elif role_type.lower() in ["non-technical", "non_technical", "nontech"]:
                query += " AND (role_type = 'Non-Technical' OR category != 'Tech')"

        if is_internship is True or experience_level == "internship":
            query += " AND (is_internship = 1 OR title LIKE '%intern%' OR title LIKE '%trainee%' OR experience_text LIKE '%intern%' OR experience_text LIKE '%fresher%')"
        elif experience_level == "0-2":
            query += " AND ((experience_min <= 2 AND experience_min >= 0) OR (experience_max <= 2 AND experience_max >= 0) OR experience_text LIKE '%0-2%' OR experience_text LIKE '%0-1%' OR experience_text LIKE '%1-2%' OR experience_text LIKE '%fresher%' OR title LIKE '%fresher%' OR title LIKE '%entry%' OR title LIKE '%junior%')"
        elif experience_level == "3-5":
            query += " AND ((experience_min <= 5 AND experience_max >= 2) OR (experience_min >= 2 AND experience_min <= 5) OR (experience_max >= 3 AND experience_max <= 6) OR experience_text LIKE '%3-5%' OR experience_text LIKE '%3 to 5%' OR experience_text LIKE '%4-5%' OR experience_text LIKE '%3 yrs%' OR experience_text LIKE '%4 yrs%' OR experience_text LIKE '%5 yrs%' OR title LIKE '%mid%' OR title LIKE '%senior%' OR title LIKE '%lead%')"
        elif experience_level == "6-10":
            query += " AND (experience_min >= 5 OR experience_max >= 6 OR experience_text LIKE '%6-10%' OR experience_text LIKE '%7-10%' OR experience_text LIKE '%6+%' OR experience_text LIKE '%7+%' OR experience_text LIKE '%8+%' OR title LIKE '%lead%' OR title LIKE '%principal%' OR title LIKE '%manager%')"
        elif experience_level == "10+":
            query += " AND (experience_min >= 10 OR experience_text LIKE '%10+%' OR experience_text LIKE '%12+%' OR title LIKE '%director%' OR title LIKE '%head%' OR title LIKE '%vp%')"

        if status:
            query += " AND status = ?"
            params.append(status)

        if favorite_only:
            query += " AND is_favorite = 1"

        query += " ORDER BY scraped_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            results = []
            for row in rows:
                item = dict(row)
                try:
                    item["skills"] = json.loads(item["skills"]) if item["skills"] else []
                except Exception:
                    item["skills"] = []
                results.append(item)
            return results

    def get_hiring_posts(
        self,
        keywords: Optional[str] = None,
        location: Optional[str] = None,
        company: Optional[str] = None,
        role_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Query hiring posts from HRs and recruiters."""
        query = "SELECT * FROM hiring_posts WHERE 1=1"
        params: list[Any] = []

        if keywords:
            query += " AND (role_title LIKE ? OR post_text LIKE ? OR poster_name LIKE ?)"
            term = f"%{keywords}%"
            params.extend([term, term, term])

        if company:
            query += " AND company LIKE ?"
            params.append(f"%{company}%")

        if location and location.lower() not in ["india", "all", ""]:
            query += " AND location LIKE ?"
            params.append(f"%{location}%")

        if role_type and role_type.lower() not in ["all", ""]:
            if role_type.lower() == "technical":
                query += " AND role_type = 'Technical'"
            elif role_type.lower() in ["non-technical", "non_technical", "nontech"]:
                query += " AND role_type = 'Non-Technical'"

        query += " ORDER BY scraped_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]

    def get_stats(self) -> Dict[str, Any]:
        """Get aggregate metrics."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as total FROM jobs")
            total = cursor.fetchone()["total"]

            cursor.execute("SELECT COUNT(*) as total_posts FROM hiring_posts")
            total_posts = cursor.fetchone()["total_posts"]

            cursor.execute("SELECT source_portal, COUNT(*) as count FROM jobs GROUP BY source_portal")
            portal_counts = {r["source_portal"]: r["count"] for r in cursor.fetchall()}

            cursor.execute("SELECT work_mode, COUNT(*) as count FROM jobs GROUP BY work_mode")
            work_mode_counts = {r["work_mode"]: r["count"] for r in cursor.fetchall()}

            cursor.execute("SELECT role_type, COUNT(*) as count FROM jobs GROUP BY role_type")
            role_type_counts = {r["role_type"]: r["count"] for r in cursor.fetchall()}

            cursor.execute("SELECT COUNT(DISTINCT company) as total_companies FROM jobs")
            total_companies = cursor.fetchone()["total_companies"]

            return {
                "total_jobs": total,
                "total_hiring_posts": total_posts,
                "portal_breakdown": portal_counts,
                "work_mode_breakdown": work_mode_counts,
                "role_type_breakdown": role_type_counts,
                "total_companies": total_companies,
            }

    def update_job_status(self, job_id: str, status: str) -> bool:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
            conn.commit()
            return cursor.rowcount > 0

    def toggle_favorite(self, job_id: str) -> bool:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE jobs SET is_favorite = ((is_favorite | 1) - (is_favorite & 1)) WHERE id = ?", (job_id,))
            conn.commit()
            return cursor.rowcount > 0

    def delete_job(self, job_id: str) -> bool:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            conn.commit()
            return cursor.rowcount > 0

    # ==========================================
    # Target Company Radar & Alerts Storage
    # ==========================================

    def save_company_target(self, target: CompanyTarget) -> bool:
        """Add or update a target company in the Radar watchlist."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM company_targets WHERE id = ?", (target.id,))
            exists = cursor.fetchone() is not None

            cursor.execute(
                """
                INSERT INTO company_targets (
                    id, company_name, career_url, keywords, channels, is_active, last_scanned_at, last_found_count, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    company_name=excluded.company_name,
                    career_url=excluded.career_url,
                    keywords=excluded.keywords,
                    channels=excluded.channels,
                    is_active=excluded.is_active
                """,
                (
                    target.id,
                    target.company_name,
                    target.career_url or "",
                    target.keywords or "",
                    json.dumps(target.channels),
                    1 if target.is_active else 0,
                    target.last_scanned_at,
                    target.last_found_count,
                    target.created_at,
                ),
            )
            conn.commit()
            return not exists

    def get_company_targets(self, active_only: bool = False) -> List[Dict[str, Any]]:
        """Retrieve all or active watched companies."""
        query = "SELECT * FROM company_targets"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY created_at DESC"

        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
            results = []
            for r in rows:
                item = dict(r)
                try:
                    item["channels"] = json.loads(item["channels"]) if item["channels"] else []
                except Exception:
                    item["channels"] = []
                item["is_active"] = bool(item["is_active"])
                results.append(item)
            return results

    def get_company_target(self, target_id: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM company_targets WHERE id = ?", (target_id,))
            row = cursor.fetchone()
            if not row:
                return None
            item = dict(row)
            try:
                item["channels"] = json.loads(item["channels"]) if item["channels"] else []
            except Exception:
                item["channels"] = []
            item["is_active"] = bool(item["is_active"])
            return item

    def update_company_target_scan(self, target_id: str, found_count: int) -> None:
        """Update last scanned timestamp and found count for a company."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE company_targets
                SET last_scanned_at = ?, last_found_count = ?
                WHERE id = ?
                """,
                (get_ist_iso(), found_count, target_id),
            )
            conn.commit()

    def toggle_company_target(self, target_id: str) -> bool:
        """Toggle active state for a watched company."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE company_targets SET is_active = ((is_active | 1) - (is_active & 1)) WHERE id = ?",
                (target_id,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_company_target(self, target_id: str) -> bool:
        """Remove a target company from the radar."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM company_targets WHERE id = ?", (target_id,))
            conn.commit()
            return cursor.rowcount > 0

    def is_alert_already_sent(self, item_id: str, recipient_email: str) -> bool:
        """Check if an opportunity or post has already been emailed to recipient."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM radar_alert_logs WHERE item_id = ? AND recipient_email = ?",
                (item_id, recipient_email),
            )
            return cursor.fetchone() is not None

    def save_radar_alert_log(self, alert_log: RadarAlertLog) -> bool:
        """Record an alert as emailed to prevent duplicate notifications."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR IGNORE INTO radar_alert_logs (
                    id, company_id, item_type, item_id, title, company, url, source,
                    experience_text, location, emailed_at, recipient_email
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert_log.id,
                    alert_log.company_id,
                    alert_log.item_type,
                    alert_log.item_id,
                    alert_log.title,
                    alert_log.company,
                    alert_log.url,
                    alert_log.source,
                    alert_log.experience_text,
                    alert_log.location,
                    alert_log.emailed_at,
                    alert_log.recipient_email,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_radar_alert_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve recent sent radar alerts."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM radar_alert_logs ORDER BY emailed_at DESC LIMIT ?", (limit,))
            return [dict(r) for r in cursor.fetchall()]

    # ==========================================
    # All-India Discovery Radar & Alerts Storage
    # ==========================================

    def is_discovery_alert_already_sent(self, item_id: str, recipient_email: str) -> bool:
        """Check if an opportunity has already been emailed to recipient in All-India discovery alerts."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM discovery_alert_logs WHERE item_id = ? AND recipient_email = ?",
                (item_id, recipient_email),
            )
            return cursor.fetchone() is not None

    def save_discovery_alert_log(self, alert_log: DiscoveryAlertLog) -> bool:
        """Record a broad discovery alert as emailed to prevent duplicate notifications."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR IGNORE INTO discovery_alert_logs (
                    id, item_type, item_id, title, company, url, source,
                    role_type, experience_text, location, emailed_at, recipient_email
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert_log.id,
                    alert_log.item_type,
                    alert_log.item_id,
                    alert_log.title,
                    alert_log.company,
                    alert_log.url,
                    alert_log.source,
                    alert_log.role_type or "Non-Technical",
                    alert_log.experience_text,
                    alert_log.location,
                    alert_log.emailed_at,
                    alert_log.recipient_email,
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_discovery_alert_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Retrieve recent sent All-India discovery alerts."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM discovery_alert_logs ORDER BY emailed_at DESC LIMIT ?", (limit,))
            return [dict(r) for r in cursor.fetchall()]

    # ==========================================
    # Google Sheets Settings & Sync Stats Storage
    # ==========================================

    def get_sheets_config(self) -> Dict[str, Any]:
        """Fetch Google Sheets integration configuration."""
        import os
        defaults = {
            "is_enabled": os.getenv("SHEETS_IS_ENABLED", "false").lower() in ["true", "1", "yes"],
            "auth_mode": "service_account",
            "credentials_json": DEFAULT_GOOGLE_SHEETS_CREDS_PATH,
            "spreadsheet_id_or_url": DEFAULT_GOOGLE_SHEETS_SPREADSHEET_ID,
            "sheet_name_all_india": "All-India Jobs",
            "sheet_name_target_radar": "Target Company Radar",
            "sheet_name_hiring_posts": "Recruiter Posts",
            "auto_sync_on_scrape": True,
            "last_synced_at": None,
            "last_synced_count": 0,
        }
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM sheets_settings")
            rows = cursor.fetchall()
            for r in rows:
                k, v = r["key"], r["value"]
                if k in defaults:
                    if k in ["is_enabled", "auto_sync_on_scrape"]:
                        defaults[k] = v.lower() in ["true", "1", "yes"]
                    elif k == "last_synced_count":
                        defaults[k] = int(v) if v else 0
                    else:
                        defaults[k] = v
        return defaults

    def save_sheets_config(self, config_dict: Dict[str, Any]) -> bool:
        """Save Google Sheets integration settings to database."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            for k, v in config_dict.items():
                val_str = str(v) if v is not None else ""
                cursor.execute(
                    """
                    INSERT INTO sheets_settings (key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value
                    """,
                    (str(k), val_str),
                )
            conn.commit()
            return True

    def update_sheets_sync_stats(self, synced_count: int) -> None:
        """Update last sync timestamp and record count for Google Sheets in IST."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            now = get_ist_iso()
            cursor.execute(
                "INSERT INTO sheets_settings (key, value) VALUES ('last_synced_at', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (now,),
            )
            cursor.execute(
                "INSERT INTO sheets_settings (key, value) VALUES ('last_synced_count', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(synced_count),),
            )
            conn.commit()

    # ==========================================
    # Email & Dual Radar Configuration
    # ==========================================

    def get_email_config(self) -> Dict[str, Any]:
        """Fetch email notification, Target Radar, and All-India Discovery Radar settings."""
        import os
        defaults = {
            "smtp_host": DEFAULT_SMTP_HOST,
            "smtp_port": DEFAULT_SMTP_PORT,
            "smtp_user": DEFAULT_SMTP_USER,
            "smtp_password": DEFAULT_SMTP_PASSWORD,
            "sender_email": DEFAULT_SENDER_EMAIL,
            # Target Radar Recipient & Settings
            "recipient_email": DEFAULT_RECIPIENT_EMAIL,
            "is_enabled": os.getenv("RADAR_IS_ENABLED", "false").lower() in ["true", "1", "yes"],
            "check_interval_minutes": DEFAULT_RADAR_INTERVAL_MINUTES,
            # All-India Discovery Radar Recipient & Settings
            "all_india_recipient": DEFAULT_ALL_INDIA_RECIPIENT_EMAIL or DEFAULT_RECIPIENT_EMAIL,
            "all_india_is_enabled": os.getenv("ALL_INDIA_RADAR_IS_ENABLED", "false").lower() in ["true", "1", "yes"],
            "all_india_interval_minutes": DEFAULT_ALL_INDIA_RADAR_INTERVAL_MINUTES,
            "all_india_keywords": "developer, engineer, manager, recruiter, analyst, intern, fresher, executive, operations, sales",
            "all_india_locations": "India, Bangalore, Mumbai, Delhi, Gurgaon, Noida, Hyderabad, Pune, Chennai, Remote",
            "all_india_role_types": "all",
        }
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM radar_settings")
            rows = cursor.fetchall()
            for r in rows:
                k, v = r["key"], r["value"]
                if k in defaults:
                    if k in ["smtp_port", "check_interval_minutes", "all_india_interval_minutes"]:
                        try:
                            defaults[k] = int(v)
                        except Exception:
                            pass
                    elif k in ["is_enabled", "all_india_is_enabled"]:
                        defaults[k] = v.lower() in ["true", "1", "yes"]
                    else:
                        defaults[k] = v
        return defaults

    def save_email_config(self, config_dict: Dict[str, Any]) -> bool:
        """Save email notification and SMTP settings to database."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            for k, v in config_dict.items():
                cursor.execute(
                    """
                    INSERT INTO radar_settings (key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value
                    """,
                    (str(k), str(v)),
                )
            conn.commit()
            return True

    # ==========================================
    # User Authentication & Team Security
    # ==========================================

    def verify_user_credentials(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        """Verify username and password against users table. Returns user dict if valid and active, else None."""
        from job_pulse.security import verify_password
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, username, password_hash, salt, role, is_active FROM users WHERE username = ?", (username.strip(),))
            row = cursor.fetchone()
            if not row:
                return None
            if row["is_active"] != 1:
                return None
            if not verify_password(password, row["password_hash"], row["salt"]):
                return None
            return {
                "id": row["id"],
                "username": row["username"],
                "role": row["role"] or "member",
                "is_active": row["is_active"],
            }

    def get_user_role(self, username: str) -> Optional[str]:
        """Fetch role ('admin' or 'member') for a given username."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT role FROM users WHERE username = ?", (username.strip(),))
            row = cursor.fetchone()
            return row["role"] if row else None

    def add_user(self, username: str, password: str, role: str = "member") -> Tuple[bool, str]:
        """Add a new team user with username, password, and assigned role."""
        from job_pulse.security import hash_password
        uname = username.strip()
        if not uname or len(uname) < 3:
            return False, "Username must be at least 3 characters long."
        if not password or len(password) < 6:
            return False, "Password must be at least 6 characters long."
        role_clean = "admin" if role.lower() == "admin" else "member"

        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE username = ?", (uname,))
            if cursor.fetchone():
                return False, f"Username '{uname}' is already taken."

            p_hash, salt = hash_password(password)
            cursor.execute(
                "INSERT INTO users (username, password_hash, salt, role, is_active, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (uname, p_hash, salt, role_clean, 1, get_ist_iso()),
            )
            conn.commit()
            return True, f"User '{uname}' ({role_clean}) created successfully."

    def change_user_password(self, username: str, old_password: str, new_password: str) -> Tuple[bool, str]:
        """Change user password after verifying old password."""
        from job_pulse.security import verify_password, hash_password
        if not new_password or len(new_password) < 6:
            return False, "New password must be at least 6 characters long."
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT password_hash, salt FROM users WHERE username = ?", (username.strip(),))
            row = cursor.fetchone()
            if not row:
                return False, "User not found."
            if not verify_password(old_password, row["password_hash"], row["salt"]):
                return False, "Current password is incorrect."

            p_hash, salt = hash_password(new_password)
            cursor.execute(
                "UPDATE users SET password_hash = ?, salt = ? WHERE username = ?",
                (p_hash, salt, username.strip())
            )
            conn.commit()
            return True, "Password updated successfully."

    def admin_reset_user_password(self, target_username: str, new_password: str) -> Tuple[bool, str]:
        """Admin direct password reset for any team user."""
        from job_pulse.security import hash_password
        if not new_password or len(new_password) < 6:
            return False, "New password must be at least 6 characters long."
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE username = ?", (target_username.strip(),))
            if not cursor.fetchone():
                return False, f"User '{target_username}' not found."

            p_hash, salt = hash_password(new_password)
            cursor.execute(
                "UPDATE users SET password_hash = ?, salt = ? WHERE username = ?",
                (p_hash, salt, target_username.strip())
            )
            conn.commit()
            return True, f"Password for '{target_username}' has been reset successfully."

    def admin_toggle_user_status(self, target_username: str, requesting_username: str) -> Tuple[bool, str]:
        """Toggle active/inactive status for a user."""
        if target_username.strip() == requesting_username.strip():
            return False, "You cannot deactivate your own logged-in account."
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT is_active FROM users WHERE username = ?", (target_username.strip(),))
            row = cursor.fetchone()
            if not row:
                return False, f"User '{target_username}' not found."

            new_status = 0 if row["is_active"] == 1 else 1
            cursor.execute("UPDATE users SET is_active = ? WHERE username = ?", (new_status, target_username.strip()))
            conn.commit()
            status_text = "activated" if new_status == 1 else "deactivated"
            return True, f"User '{target_username}' has been {status_text}."

    def admin_delete_user(self, target_username: str, requesting_username: str) -> Tuple[bool, str]:
        """Delete a team user from the database."""
        if target_username.strip() == requesting_username.strip():
            return False, "You cannot delete your own account."
        if target_username.strip().lower() == "admin":
            return False, "The default 'admin' account cannot be deleted."

        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE username = ?", (target_username.strip(),))
            if not cursor.fetchone():
                return False, f"User '{target_username}' not found."

            cursor.execute("DELETE FROM users WHERE username = ?", (target_username.strip(),))
            conn.commit()
            return True, f"User '{target_username}' deleted successfully."

    def update_user_last_login(self, username: str) -> None:
        """Update last login timestamp in IST."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET last_login_at = ? WHERE username = ?",
                (get_ist_iso(), username.strip())
            )
            conn.commit()

    def get_users_list(self) -> List[Dict[str, Any]]:
        """Return list of registered team users."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, username, role, is_active, created_at, last_login_at FROM users ORDER BY created_at ASC")
            return [dict(r) for r in cursor.fetchall()]


