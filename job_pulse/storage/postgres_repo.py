import json
import logging
import time
from contextlib import contextmanager
from typing import List, Optional, Dict, Any, Generator, Tuple

import psycopg2
import psycopg2.pool
import psycopg2.extras

from job_pulse.utils.time_utils import get_ist_iso
from job_pulse.storage.base import JobRepository
from job_pulse.models import (
    JobPost,
    HiringPost,
    WorkMode,
    CompanyTarget,
    RadarAlertLog,
    DiscoveryAlertLog,
    StoryIngestionLog,
)

logger = logging.getLogger("job_pulse.storage.postgres")

# psycopg2 error classes worth a single reconnect-and-retry (transient network blips,
# a connection Supabase's pooler recycled underneath us, etc). Anything else propagates.
_TRANSIENT_ERRORS = (psycopg2.OperationalError, psycopg2.InterfaceError)


class PostgresJobRepository(JobRepository):
    """
    Postgres/Supabase-backed JobRepository. Mirrors SQLiteJobRepository's behavior
    method-for-method so callers never need to branch on which backend is active.

    Connect via a pooled DSN - for Supabase, use the transaction pooler endpoint
    (port 6543, `?pgbouncer=true` in the connection string) rather than the direct
    connection (port 5432): this class opens/returns a connection per call, the same
    "connect, do one thing, release" pattern the SQLite backend uses, and the direct
    port's connection cap is too low to sustain that pattern under real scraper/radar
    concurrency.
    """

    def __init__(
        self,
        database_url: str,
        minconn: int = 1,
        maxconn: int = 10,
        init_default_targets: bool = False,
    ):
        if not database_url:
            raise ValueError("PostgresJobRepository requires a non-empty database_url (DATABASE_URL).")
        self._pool = psycopg2.pool.ThreadedConnectionPool(minconn, maxconn, dsn=database_url)
        self._init_db(init_default_targets=init_default_targets)

    @contextmanager
    def _get_conn(self, retries: int = 2) -> Generator[Any, None, None]:
        """Borrow a pooled connection; commit on success, rollback on error, always return it."""
        last_err: Optional[Exception] = None
        for attempt in range(retries + 1):
            conn = None
            try:
                conn = self._pool.getconn()
                conn.cursor_factory = psycopg2.extras.RealDictCursor
                yield conn
                conn.commit()
                return
            except _TRANSIENT_ERRORS as e:
                last_err = e
                if conn is not None:
                    try:
                        self._pool.putconn(conn, close=True)
                    except Exception:
                        pass
                    conn = None
                if attempt < retries:
                    logger.warning(f"Postgres connection error ({e}); retrying ({attempt + 1}/{retries})...")
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise
            except Exception:
                if conn is not None:
                    conn.rollback()
                raise
            finally:
                if conn is not None:
                    self._pool.putconn(conn)
        if last_err:
            raise last_err

    def _cursor(self, conn):
        return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # ==========================================
    # Schema initialization
    # ==========================================

    def _init_db(self, init_default_targets: bool = False) -> None:
        try:
            with self._get_conn() as conn:
                cursor = self._cursor(conn)
                cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    location TEXT,
                    work_mode TEXT,
                    role_type TEXT DEFAULT 'Non-Technical',
                    is_internship BOOLEAN DEFAULT FALSE,
                    category TEXT DEFAULT 'General',
                    experience_min DOUBLE PRECISION,
                    experience_max DOUBLE PRECISION,
                    experience_text TEXT,
                    salary_min DOUBLE PRECISION,
                    salary_max DOUBLE PRECISION,
                    salary_currency TEXT,
                    salary_text TEXT,
                    skills JSONB DEFAULT '[]'::jsonb,
                    description TEXT,
                    url TEXT NOT NULL,
                    source_portal TEXT NOT NULL,
                    posted_date TEXT,
                    scraped_at TEXT NOT NULL,
                    dedup_group_id TEXT,
                    is_favorite BOOLEAN DEFAULT FALSE,
                    status TEXT DEFAULT 'new',
                    raw_data JSONB
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
                    is_favorite BOOLEAN DEFAULT FALSE,
                    status TEXT DEFAULT 'new'
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS search_runs (
                    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    keywords TEXT NOT NULL,
                    location TEXT,
                    portals TEXT,
                    total_found INTEGER,
                    execution_time DOUBLE PRECISION
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS company_targets (
                    id TEXT PRIMARY KEY,
                    company_name TEXT NOT NULL,
                    normalized_name TEXT,
                    career_url TEXT,
                    keywords TEXT,
                    channels JSONB DEFAULT '[]'::jsonb,
                    is_active BOOLEAN DEFAULT TRUE,
                    source TEXT DEFAULT 'manual',
                    source_row_id TEXT,
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
                CREATE TABLE IF NOT EXISTS story_ingestion_log (
                    id TEXT PRIMARY KEY,
                    sheet_row_hash TEXT NOT NULL UNIQUE,
                    story_date TEXT,
                    main_company TEXT NOT NULL,
                    competitors JSONB DEFAULT '[]'::jsonb,
                    targets_created JSONB DEFAULT '[]'::jsonb,
                    status TEXT DEFAULT 'processed',
                    error_message TEXT,
                    processed_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    role TEXT DEFAULT 'member',
                    is_active BOOLEAN DEFAULT TRUE,
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
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_targets_normalized_name ON company_targets(normalized_name)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_radar_item_email ON radar_alert_logs(item_id, recipient_email)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_discovery_item_email ON discovery_alert_logs(item_id, recipient_email)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_story_log_hash ON story_ingestion_log(sheet_row_hash)")

            cursor.execute("SELECT id FROM users WHERE username = 'admin'")
            if not cursor.fetchone():
                import os
                import secrets
                from job_pulse.security import hash_password
                default_pwd = os.environ.get("ADMIN_PASSWORD")
                if not default_pwd:
                    if os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("TESTING"):
                        default_pwd = "cmplibe@2026"
                    else:
                        default_pwd = secrets.token_urlsafe(16)
                        logger.warning(f"ADMIN_PASSWORD not set in environment. Generated one-time admin password: {default_pwd}")
                p_hash, salt = hash_password(default_pwd)
                cursor.execute(
                    "INSERT INTO users (username, password_hash, salt, role, is_active, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                    ("admin", p_hash, salt, "admin", True, get_ist_iso()),
                )

            if init_default_targets:
                cursor.execute("SELECT COUNT(*) as cnt FROM company_targets")
                if cursor.fetchone()["cnt"] == 0:
                    from job_pulse.models import normalize_company_key
                    default_targets = [
                        ("target_jumbotail", "Jumbotail", "https://jumbotail.com/careers", "software, developer, engineer, intern, analyst", ["career_page", "linkedin_posts", "portal"]),
                        ("target_paytm", "Paytm", "https://paytm.com/careers", "software, engineer, developer, operations, executive", ["career_page", "linkedin_posts", "portal"]),
                        ("target_khatabook", "Khatabook", "https://khatabook.com/careers", "engineer, developer, product, intern", ["career_page", "linkedin_posts", "portal"]),
                    ]
                    now_str = get_ist_iso()
                    for tid, name, url, kw, ch in default_targets:
                        cursor.execute(
                            """
                            INSERT INTO company_targets (id, company_name, normalized_name, career_url, keywords, channels, is_active, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s)
                            """,
                            (tid, name, normalize_company_key(name), url, kw, psycopg2.extras.Json(ch), now_str),
                        )
        except psycopg2.IntegrityError:
            # Catalog race condition on concurrent worker startup - tables already exist
            pass

    # ==========================================
    # Jobs
    # ==========================================

    def save_job(self, job: JobPost, dedup_group_id: Optional[str] = None) -> bool:
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute("SELECT id FROM jobs WHERE id = %s", (job.id,))
            exists = cursor.fetchone() is not None

            cursor.execute(
                """
                INSERT INTO jobs (
                    id, title, company, location, work_mode, role_type, is_internship, category,
                    experience_min, experience_max, experience_text,
                    salary_min, salary_max, salary_currency, salary_text,
                    skills, description, url, source_portal,
                    posted_date, scraped_at, dedup_group_id, raw_data
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
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
                    bool(job.is_internship),
                    job.category or "General",
                    job.experience_min,
                    job.experience_max,
                    job.experience_text,
                    job.salary_min,
                    job.salary_max,
                    job.salary_currency,
                    job.salary_text,
                    psycopg2.extras.Json(job.skills or []),
                    job.description,
                    job.url,
                    job.source_portal,
                    job.posted_date or "Recently Posted",
                    job.scraped_at,
                    dedup_group_id,
                    psycopg2.extras.Json(job.raw_data) if job.raw_data else None,
                ),
            )
            return not exists

    def save_jobs_batch(self, jobs: List[JobPost]) -> int:
        new_count = 0
        for job in jobs:
            if self.save_job(job):
                new_count += 1
        return new_count

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
        query = "SELECT * FROM jobs WHERE 1=1"
        params: list = []

        # NOTE: Postgres's LIKE is case-sensitive (unlike SQLite's default LIKE) - use
        # ILIKE throughout so free-text search behaves the same as it did on SQLite.
        if keywords:
            query += " AND (title ILIKE %s OR company ILIKE %s OR skills::text ILIKE %s OR description ILIKE %s)"
            term = f"%{keywords}%"
            params.extend([term, term, term, term])

        if company:
            query += " AND company ILIKE %s"
            params.append(f"%{company}%")

        if location and location.lower() not in ["india", "all", "any", ""]:
            query += " AND location ILIKE %s"
            params.append(f"%{location}%")

        if portal and portal.lower() not in ["all", ""]:
            p_low = portal.lower()
            if p_low in ["career", "ats", "career pages / ats"]:
                query += " AND (source_portal ILIKE '%greenhouse%' OR source_portal ILIKE '%lever%' OR source_portal ILIKE '%ashby%' OR source_portal ILIKE '%workday%' OR source_portal ILIKE '%smartrecruiters%' OR source_portal ILIKE '%career%')"
            else:
                query += " AND source_portal ILIKE %s"
                params.append(f"%{p_low}%")

        if work_mode and work_mode not in ["All", ""]:
            query += " AND work_mode = %s"
            params.append(work_mode)

        if role_type and role_type.lower() not in ["all", ""]:
            if role_type.lower() == "technical":
                query += " AND (role_type = 'Technical' OR category = 'Tech')"
            elif role_type.lower() in ["non-technical", "non_technical", "nontech"]:
                query += " AND (role_type = 'Non-Technical' OR category != 'Tech')"

        if is_internship is True or experience_level == "internship":
            query += " AND (is_internship = TRUE OR title ILIKE '%intern%' OR title ILIKE '%trainee%' OR experience_text ILIKE '%intern%' OR experience_text ILIKE '%fresher%')"
        elif experience_level == "0-2":
            query += " AND ((experience_min <= 2 AND experience_min >= 0) OR (experience_max <= 2 AND experience_max >= 0) OR experience_text ILIKE '%0-2%' OR experience_text ILIKE '%0-1%' OR experience_text ILIKE '%1-2%' OR experience_text ILIKE '%fresher%' OR title ILIKE '%fresher%' OR title ILIKE '%entry%' OR title ILIKE '%junior%')"
        elif experience_level == "3-5":
            query += " AND ((experience_min <= 5 AND experience_max >= 2) OR (experience_min >= 2 AND experience_min <= 5) OR (experience_max >= 3 AND experience_max <= 6) OR experience_text ILIKE '%3-5%' OR experience_text ILIKE '%3 to 5%' OR experience_text ILIKE '%4-5%' OR experience_text ILIKE '%3 yrs%' OR experience_text ILIKE '%4 yrs%' OR experience_text ILIKE '%5 yrs%' OR title ILIKE '%mid%' OR title ILIKE '%senior%' OR title ILIKE '%lead%')"
        elif experience_level == "6-10":
            query += " AND (experience_min >= 5 OR experience_max >= 6 OR experience_text ILIKE '%6-10%' OR experience_text ILIKE '%7-10%' OR experience_text ILIKE '%6+%' OR experience_text ILIKE '%7+%' OR experience_text ILIKE '%8+%' OR title ILIKE '%lead%' OR title ILIKE '%principal%' OR title ILIKE '%manager%')"
        elif experience_level == "10+":
            query += " AND (experience_min >= 10 OR experience_text ILIKE '%10+%' OR experience_text ILIKE '%12+%' OR title ILIKE '%director%' OR title ILIKE '%head%' OR title ILIKE '%vp%')"

        if status:
            query += " AND status = %s"
            params.append(status)

        if favorite_only:
            query += " AND is_favorite = TRUE"

        query += " ORDER BY scraped_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute(query, params)
            results = []
            for row in cursor.fetchall():
                item = dict(row)
                item["skills"] = item.get("skills") or []  # JSONB already deserialized
                results.append(item)
            return results

    def update_job_status(self, job_id: str, status: str) -> bool:
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute("UPDATE jobs SET status = %s WHERE id = %s", (status, job_id))
            return cursor.rowcount > 0

    def toggle_favorite(self, job_id: str) -> bool:
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute("UPDATE jobs SET is_favorite = NOT is_favorite WHERE id = %s", (job_id,))
            return cursor.rowcount > 0

    def delete_job(self, job_id: str) -> bool:
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute("DELETE FROM jobs WHERE id = %s", (job_id,))
            return cursor.rowcount > 0

    # ==========================================
    # Hiring Posts
    # ==========================================

    def save_hiring_post(self, post: HiringPost) -> bool:
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute("SELECT id FROM hiring_posts WHERE id = %s", (post.id,))
            exists = cursor.fetchone() is not None

            cursor.execute(
                """
                INSERT INTO hiring_posts (
                    id, poster_name, poster_title, poster_profile_url,
                    company, role_title, post_text, post_url,
                    contact_email, contact_phone, location, posted_date, scraped_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    post_text=excluded.post_text,
                    contact_email=COALESCE(excluded.contact_email, hiring_posts.contact_email),
                    contact_phone=COALESCE(excluded.contact_phone, hiring_posts.contact_phone)
                """,
                (
                    post.id, post.poster_name, post.poster_title, post.poster_profile_url,
                    post.company, post.role_title, post.post_text, post.post_url,
                    post.contact_email, post.contact_phone, post.location, post.posted_date, post.scraped_at,
                ),
            )
            return not exists

    def save_hiring_posts_batch(self, posts: List[HiringPost]) -> int:
        new_count = 0
        for p in posts:
            if self.save_hiring_post(p):
                new_count += 1
        return new_count

    def get_hiring_posts(
        self,
        keywords: Optional[str] = None,
        location: Optional[str] = None,
        company: Optional[str] = None,
        role_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM hiring_posts WHERE 1=1"
        params: list = []

        if keywords:
            query += " AND (role_title ILIKE %s OR post_text ILIKE %s OR poster_name ILIKE %s)"
            term = f"%{keywords}%"
            params.extend([term, term, term])

        if company:
            query += " AND company ILIKE %s"
            params.append(f"%{company}%")

        if location and location.lower() not in ["india", "all", ""]:
            query += " AND location ILIKE %s"
            params.append(f"%{location}%")

        if role_type and role_type.lower() not in ["all", ""]:
            if role_type.lower() == "technical":
                query += " AND role_type = 'Technical'"
            elif role_type.lower() in ["non-technical", "non_technical", "nontech"]:
                query += " AND role_type = 'Non-Technical'"

        query += " ORDER BY scraped_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])

        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]

    # ==========================================
    # Search run logging & stats
    # ==========================================

    def log_search_run(self, keywords: str, location: str, portals: List[str], total_found: int, exec_time: float) -> None:
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute(
                "INSERT INTO search_runs (timestamp, keywords, location, portals, total_found, execution_time) VALUES (%s, %s, %s, %s, %s, %s)",
                (get_ist_iso(), keywords, location, ",".join(portals), total_found, exec_time),
            )

    def get_stats(self) -> Dict[str, Any]:
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
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

    # ==========================================
    # Target Company Radar
    # ==========================================

    def save_company_target(self, target: CompanyTarget) -> bool:
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute("SELECT id FROM company_targets WHERE id = %s", (target.id,))
            exists = cursor.fetchone() is not None

            cursor.execute(
                """
                INSERT INTO company_targets (
                    id, company_name, normalized_name, career_url, keywords, channels,
                    is_active, source, source_row_id, last_scanned_at, last_found_count, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    company_name=excluded.company_name,
                    normalized_name=excluded.normalized_name,
                    career_url=excluded.career_url,
                    keywords=excluded.keywords,
                    channels=excluded.channels,
                    is_active=excluded.is_active
                """,
                (
                    target.id,
                    target.company_name,
                    target.normalized_name,
                    target.career_url or "",
                    target.keywords or "",
                    psycopg2.extras.Json(target.channels or []),
                    bool(target.is_active),
                    target.source or "manual",
                    target.source_row_id,
                    target.last_scanned_at,
                    target.last_found_count,
                    target.created_at,
                ),
            )
            return not exists

    def get_company_targets(self, active_only: bool = False) -> List[Dict[str, Any]]:
        query = "SELECT * FROM company_targets"
        if active_only:
            query += " WHERE is_active = TRUE"
        query += " ORDER BY created_at DESC"

        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute(query)
            results = []
            for r in cursor.fetchall():
                item = dict(r)
                item["channels"] = item.get("channels") or []
                results.append(item)
            return results

    def get_company_target(self, target_id: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute("SELECT * FROM company_targets WHERE id = %s", (target_id,))
            row = cursor.fetchone()
            if not row:
                return None
            item = dict(row)
            item["channels"] = item.get("channels") or []
            return item

    def update_company_target_scan(self, target_id: str, found_count: int) -> None:
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute(
                "UPDATE company_targets SET last_scanned_at = %s, last_found_count = %s WHERE id = %s",
                (get_ist_iso(), found_count, target_id),
            )

    def toggle_company_target(self, target_id: str) -> bool:
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute("UPDATE company_targets SET is_active = NOT is_active WHERE id = %s", (target_id,))
            return cursor.rowcount > 0

    def delete_company_target(self, target_id: str) -> bool:
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute("DELETE FROM company_targets WHERE id = %s", (target_id,))
            return cursor.rowcount > 0

    # ==========================================
    # Target Radar Alert Logs
    # ==========================================

    def is_alert_already_sent(self, item_id: str, recipient_email: str) -> bool:
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute(
                "SELECT id FROM radar_alert_logs WHERE item_id = %s AND recipient_email = %s",
                (item_id, recipient_email),
            )
            return cursor.fetchone() is not None

    def save_radar_alert_log(self, alert_log: RadarAlertLog) -> bool:
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute(
                """
                INSERT INTO radar_alert_logs (
                    id, company_id, item_type, item_id, title, company, url, source,
                    experience_text, location, emailed_at, recipient_email
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    alert_log.id, alert_log.company_id, alert_log.item_type, alert_log.item_id,
                    alert_log.title, alert_log.company, alert_log.url, alert_log.source,
                    alert_log.experience_text, alert_log.location, alert_log.emailed_at, alert_log.recipient_email,
                ),
            )
            return cursor.rowcount > 0

    def get_radar_alert_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute("SELECT * FROM radar_alert_logs ORDER BY emailed_at DESC LIMIT %s", (limit,))
            return [dict(r) for r in cursor.fetchall()]

    # ==========================================
    # All-India Discovery Alert Logs
    # ==========================================

    def is_discovery_alert_already_sent(self, item_id: str, recipient_email: str) -> bool:
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute(
                "SELECT id FROM discovery_alert_logs WHERE item_id = %s AND recipient_email = %s",
                (item_id, recipient_email),
            )
            return cursor.fetchone() is not None

    def save_discovery_alert_log(self, alert_log: DiscoveryAlertLog) -> bool:
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute(
                """
                INSERT INTO discovery_alert_logs (
                    id, item_type, item_id, title, company, url, source,
                    role_type, experience_text, location, emailed_at, recipient_email
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    alert_log.id, alert_log.item_type, alert_log.item_id, alert_log.title,
                    alert_log.company, alert_log.url, alert_log.source, alert_log.role_type or "Non-Technical",
                    alert_log.experience_text, alert_log.location, alert_log.emailed_at, alert_log.recipient_email,
                ),
            )
            return cursor.rowcount > 0

    def get_discovery_alert_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute("SELECT * FROM discovery_alert_logs ORDER BY emailed_at DESC LIMIT %s", (limit,))
            return [dict(r) for r in cursor.fetchall()]

    # ==========================================
    # Google Sheets Settings
    # ==========================================

    def get_sheets_config(self) -> Dict[str, Any]:
        import os
        from job_pulse.config import DEFAULT_GOOGLE_SHEETS_SPREADSHEET_ID, DEFAULT_GOOGLE_SHEETS_CREDS_PATH
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
            cursor = self._cursor(conn)
            cursor.execute("SELECT key, value FROM sheets_settings")
            for r in cursor.fetchall():
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
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            for k, v in config_dict.items():
                val_str = str(v) if v is not None else ""
                cursor.execute(
                    "INSERT INTO sheets_settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value=excluded.value",
                    (str(k), val_str),
                )
            return True

    def update_sheets_sync_stats(self, synced_count: int) -> None:
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            now = get_ist_iso()
            cursor.execute(
                "INSERT INTO sheets_settings (key, value) VALUES ('last_synced_at', %s) ON CONFLICT (key) DO UPDATE SET value=excluded.value",
                (now,),
            )
            cursor.execute(
                "INSERT INTO sheets_settings (key, value) VALUES ('last_synced_count', %s) ON CONFLICT (key) DO UPDATE SET value=excluded.value",
                (str(synced_count),),
            )

    # ==========================================
    # Email & Dual Radar Configuration
    # ==========================================

    def get_email_config(self) -> Dict[str, Any]:
        import os
        from job_pulse.config import (
            DEFAULT_SMTP_HOST, DEFAULT_SMTP_PORT, DEFAULT_SMTP_USER, DEFAULT_SMTP_PASSWORD,
            DEFAULT_SENDER_EMAIL, DEFAULT_RECIPIENT_EMAIL, DEFAULT_ALL_INDIA_RECIPIENT_EMAIL,
            DEFAULT_RADAR_INTERVAL_MINUTES, DEFAULT_ALL_INDIA_RADAR_INTERVAL_MINUTES,
        )
        defaults = {
            "smtp_host": DEFAULT_SMTP_HOST,
            "smtp_port": DEFAULT_SMTP_PORT,
            "smtp_user": DEFAULT_SMTP_USER,
            "smtp_password": DEFAULT_SMTP_PASSWORD,
            "sender_email": DEFAULT_SENDER_EMAIL,
            "recipient_email": DEFAULT_RECIPIENT_EMAIL,
            "is_enabled": os.getenv("RADAR_IS_ENABLED", "false").lower() in ["true", "1", "yes"],
            "check_interval_minutes": DEFAULT_RADAR_INTERVAL_MINUTES,
            "all_india_recipient": DEFAULT_ALL_INDIA_RECIPIENT_EMAIL or DEFAULT_RECIPIENT_EMAIL,
            "all_india_is_enabled": os.getenv("ALL_INDIA_RADAR_IS_ENABLED", "false").lower() in ["true", "1", "yes"],
            "all_india_interval_minutes": DEFAULT_ALL_INDIA_RADAR_INTERVAL_MINUTES,
            "all_india_keywords": "developer, engineer, manager, recruiter, analyst, intern, fresher, executive, operations, sales",
            "all_india_locations": "India, Bangalore, Mumbai, Delhi, Gurgaon, Noida, Hyderabad, Pune, Chennai, Remote",
            "all_india_role_types": "all",
        }
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute("SELECT key, value FROM radar_settings")
            for r in cursor.fetchall():
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
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            for k, v in config_dict.items():
                cursor.execute(
                    "INSERT INTO radar_settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value=excluded.value",
                    (str(k), str(v)),
                )
            return True

    # ==========================================
    # User Authentication & Team Security
    # ==========================================

    def verify_user_credentials(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        from job_pulse.security import verify_password
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute(
                "SELECT id, username, password_hash, salt, role, is_active FROM users WHERE username = %s",
                (username.strip(),),
            )
            row = cursor.fetchone()
            if not row:
                return None
            if not row["is_active"]:
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
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute("SELECT role FROM users WHERE username = %s", (username.strip(),))
            row = cursor.fetchone()
            return row["role"] if row else None

    def add_user(self, username: str, password: str, role: str = "member") -> Tuple[bool, str]:
        from job_pulse.security import hash_password
        uname = username.strip()
        if not uname or len(uname) < 3:
            return False, "Username must be at least 3 characters long."
        if not password or len(password) < 6:
            return False, "Password must be at least 6 characters long."
        role_clean = "admin" if role.lower() == "admin" else "member"

        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute("SELECT id FROM users WHERE username = %s", (uname,))
            if cursor.fetchone():
                return False, f"Username '{uname}' is already taken."

            p_hash, salt = hash_password(password)
            cursor.execute(
                "INSERT INTO users (username, password_hash, salt, role, is_active, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                (uname, p_hash, salt, role_clean, True, get_ist_iso()),
            )
            return True, f"User '{uname}' ({role_clean}) created successfully."

    def change_user_password(self, username: str, old_password: str, new_password: str) -> Tuple[bool, str]:
        from job_pulse.security import verify_password, hash_password
        if not new_password or len(new_password) < 6:
            return False, "New password must be at least 6 characters long."
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute("SELECT password_hash, salt FROM users WHERE username = %s", (username.strip(),))
            row = cursor.fetchone()
            if not row:
                return False, "User not found."
            if not verify_password(old_password, row["password_hash"], row["salt"]):
                return False, "Current password is incorrect."

            p_hash, salt = hash_password(new_password)
            cursor.execute(
                "UPDATE users SET password_hash = %s, salt = %s WHERE username = %s",
                (p_hash, salt, username.strip()),
            )
            return True, "Password updated successfully."

    def admin_reset_user_password(self, target_username: str, new_password: str) -> Tuple[bool, str]:
        from job_pulse.security import hash_password
        if not new_password or len(new_password) < 6:
            return False, "New password must be at least 6 characters long."
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute("SELECT id FROM users WHERE username = %s", (target_username.strip(),))
            if not cursor.fetchone():
                return False, f"User '{target_username}' not found."

            p_hash, salt = hash_password(new_password)
            cursor.execute(
                "UPDATE users SET password_hash = %s, salt = %s WHERE username = %s",
                (p_hash, salt, target_username.strip()),
            )
            return True, f"Password for '{target_username}' has been reset successfully."

    def admin_toggle_user_status(self, target_username: str, requesting_username: str) -> Tuple[bool, str]:
        if target_username.strip() == requesting_username.strip():
            return False, "You cannot deactivate your own logged-in account."
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute("SELECT is_active FROM users WHERE username = %s", (target_username.strip(),))
            row = cursor.fetchone()
            if not row:
                return False, f"User '{target_username}' not found."

            new_status = not row["is_active"]
            cursor.execute("UPDATE users SET is_active = %s WHERE username = %s", (new_status, target_username.strip()))
            status_text = "activated" if new_status else "deactivated"
            return True, f"User '{target_username}' has been {status_text}."

    def admin_delete_user(self, target_username: str, requesting_username: str) -> Tuple[bool, str]:
        if target_username.strip() == requesting_username.strip():
            return False, "You cannot delete your own account."
        if target_username.strip().lower() == "admin":
            return False, "The default 'admin' account cannot be deleted."

        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute("SELECT id FROM users WHERE username = %s", (target_username.strip(),))
            if not cursor.fetchone():
                return False, f"User '{target_username}' not found."

            cursor.execute("DELETE FROM users WHERE username = %s", (target_username.strip(),))
            return True, f"User '{target_username}' deleted successfully."

    def update_user_last_login(self, username: str) -> None:
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute("UPDATE users SET last_login_at = %s WHERE username = %s", (get_ist_iso(), username.strip()))

    def get_users_list(self) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute("SELECT id, username, role, is_active, created_at, last_login_at FROM users ORDER BY created_at ASC")
            return [dict(r) for r in cursor.fetchall()]

    # ==========================================
    # Story Ingestion (automated company discovery)
    # ==========================================

    def is_story_row_processed(self, row_hash: str) -> bool:
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute("SELECT id FROM story_ingestion_log WHERE sheet_row_hash = %s", (row_hash,))
            return cursor.fetchone() is not None

    def log_story_ingestion(self, log: StoryIngestionLog) -> bool:
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute(
                """
                INSERT INTO story_ingestion_log (
                    id, sheet_row_hash, story_date, main_company, competitors,
                    targets_created, status, error_message, processed_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (sheet_row_hash) DO UPDATE SET
                    status=excluded.status,
                    targets_created=excluded.targets_created,
                    error_message=excluded.error_message,
                    processed_at=excluded.processed_at
                """,
                (
                    log.id, log.sheet_row_hash, log.story_date, log.main_company,
                    psycopg2.extras.Json(log.competitors or []),
                    psycopg2.extras.Json(log.targets_created or []),
                    log.status, log.error_message, log.processed_at,
                ),
            )
            return True

    def get_story_ingestion_logs(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = self._cursor(conn)
            cursor.execute("SELECT * FROM story_ingestion_log ORDER BY processed_at DESC LIMIT %s", (limit,))
            results = []
            for r in cursor.fetchall():
                item = dict(r)
                item["competitors"] = item.get("competitors") or []
                item["targets_created"] = item.get("targets_created") or []
                results.append(item)
            return results

    def close(self) -> None:
        """Close all pooled connections - call on app shutdown."""
        self._pool.closeall()
