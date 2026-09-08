import re
import time
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime

logger = logging.getLogger("job_pulse.pipeline.sheets_sync")

try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False
    gspread = None
    Credentials = None


class GoogleSheetsManager:
    """
    Manages live real-time synchronization between cMPLiBe AIScanner and Google Sheets.
    Supports Google Cloud Service Account authentication & Webhook syncing with automated
    worksheet initialization, deduplication by Job ID, and structured formatting.
    """

    @classmethod
    def _api_call_with_retry(cls, fn, *args, max_retries: int = 4, **kwargs):
        """Execute a Google Sheets / gspread call with exponential backoff on 429/RESOURCE_EXHAUSTED."""
        for attempt in range(max_retries):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                err_str = str(e).upper()
                if any(term in err_str for term in ["429", "RESOURCE_EXHAUSTED", "RATE_LIMIT", "QUOTA"]):
                    if attempt < max_retries - 1:
                        wait = (2 ** attempt) * 1.5 + 0.5
                        logger.warning(f"Google Sheets API rate-limited ({e}). Retrying in {wait:.1f}s (Attempt {attempt+1}/{max_retries})...")
                        time.sleep(wait)
                        continue
                raise

    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    JOB_HEADERS = [
        "Job ID",
        "Job Title",
        "Company",
        "Location",
        "Work Mode",
        "Role Category",
        "Internship / Entry",
        "Experience Required",
        "Salary / Compensation",
        "Source Portal",
        "Posted Date",
        "Direct Application Link",
        "Sync Timestamp",
    ]

    POST_HEADERS = [
        "Post ID",
        "Role Title",
        "Recruiter / Poster",
        "Company",
        "Location",
        "Contact Email",
        "Contact Phone",
        "Post Snippet",
        "LinkedIn Post URL",
        "Sync Timestamp",
    ]

    @staticmethod
    def extract_spreadsheet_id(input_str: str) -> str:
        """Extract spreadsheet ID from either a bare ID or a full Google Sheet URL."""
        if not input_str:
            return ""
        input_str = input_str.strip()
        # Check if full URL
        m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", input_str)
        if m:
            return m.group(1)
        # Check if bare ID (alphanumeric with dashes/underscores, usually 30-60 chars)
        if re.match(r"^[a-zA-Z0-9-_]{20,80}$", input_str):
            return input_str
        return input_str

    @classmethod
    def _authorize_client(cls, config: Dict[str, Any]):
        """
        Resolve service-account credentials (request config, then GOOGLE_SHEETS_CREDS_PATH,
        then DEFAULT_GOOGLE_SHEETS_CREDS_PATH, then GOOGLE_SHEETS_CREDENTIALS_JSON / its
        default) and return an authorized gspread client. Shared by every method that
        needs to talk to Sheets, so the fallback chain only lives in one place.
        """
        if not GSPREAD_AVAILABLE:
            raise RuntimeError("gspread or google-auth package is not installed.")

        import os
        creds_data = (config.get("credentials_json") or "").strip()
        if not creds_data:
            from job_pulse.config import DEFAULT_GOOGLE_SHEETS_CREDS_PATH, DEFAULT_GOOGLE_SHEETS_CREDENTIALS_JSON
            creds_data = (
                os.getenv("GOOGLE_SHEETS_CREDS_PATH", "").strip()
                or DEFAULT_GOOGLE_SHEETS_CREDS_PATH
                or os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON", "").strip()
                or DEFAULT_GOOGLE_SHEETS_CREDENTIALS_JSON
            )
        creds_data = creds_data.strip("'\"")

        if not creds_data:
            raise ValueError("Google Service Account credentials (JSON or file path) are missing.")

        # Attempt 1: Check if creds_data is a file path
        creds_obj = None
        creds_path = Path(creds_data)
        if creds_path.exists() and creds_path.is_file():
            creds_obj = Credentials.from_service_account_file(str(creds_path), scopes=cls.SCOPES)
        else:
            # Attempt 2: Parse as JSON string
            try:
                info = json.loads(creds_data)
                creds_obj = Credentials.from_service_account_info(info, scopes=cls.SCOPES)
            except json.JSONDecodeError:
                raise ValueError("Credentials must be a valid JSON string or existing file path.")

        return gspread.authorize(creds_obj)

    @classmethod
    def _get_client_and_sheet(cls, config: Dict[str, Any]):
        """Authenticate and return (gspread_client, spreadsheet_obj) for the configured sync target."""
        import os
        client = cls._authorize_client(config)

        sheet_id_or_url = (config.get("spreadsheet_id_or_url") or "").strip()
        if not sheet_id_or_url:
            from job_pulse.config import DEFAULT_GOOGLE_SHEETS_SPREADSHEET_ID
            sheet_id_or_url = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "").strip() or DEFAULT_GOOGLE_SHEETS_SPREADSHEET_ID

        sheet_id = cls.extract_spreadsheet_id(sheet_id_or_url)
        if not sheet_id:
            raise ValueError("Google Spreadsheet ID or URL is missing.")

        spreadsheet = client.open_by_key(sheet_id)
        return client, spreadsheet

    @classmethod
    def read_worksheet_rows(
        cls,
        config: Dict[str, Any],
        spreadsheet_id: str,
        sheet_name: str,
    ) -> List[List[str]]:
        """
        Read all raw rows (including the header row) from an arbitrary worksheet, using
        the same service-account credentials (and the same env-var fallback chain) as
        job/post sync but a different, explicit spreadsheet ID - for reading external
        source sheets (e.g. a news-story sheet) rather than the app's own configured
        sync target.
        """
        client = cls._authorize_client(config)
        sheet_id = cls.extract_spreadsheet_id(spreadsheet_id)
        spreadsheet = client.open_by_key(sheet_id)
        worksheet = spreadsheet.worksheet(sheet_name)
        return worksheet.get_all_values()

    @classmethod
    def test_connection(cls, config: Dict[str, Any]) -> Tuple[bool, str]:
        """Test authentication and spreadsheet accessibility."""
        try:
            _, spreadsheet = cls._get_client_and_sheet(config)
            title = spreadsheet.title
            return True, f"Successfully connected to Google Sheet: '{title}'"
        except Exception as e:
            logger.error(f"Google Sheets test connection failed: {e}")
            return False, f"Connection failed: {str(e)}"

    @classmethod
    def _get_or_create_worksheet(cls, spreadsheet, title: str, headers: List[str]):
        """Get an existing worksheet or create it with formatted headers."""
        try:
            ws = spreadsheet.worksheet(title)
        except gspread.exceptions.WorksheetNotFound:
            ws = spreadsheet.add_worksheet(title=title, rows="500", cols=str(max(15, len(headers))))
            ws.append_row(headers, value_input_option="USER_ENTERED")
            # Try to format header row
            try:
                ws.freeze(rows=1)
            except Exception:
                pass
            return ws

        # If worksheet exists but is empty, add headers
        existing_rows = ws.row_values(1)
        if not existing_rows:
            ws.append_row(headers, value_input_option="USER_ENTERED")
            try:
                ws.freeze(rows=1)
            except Exception:
                pass

        return ws

    @classmethod
    def format_job_row(cls, job: Dict[str, Any]) -> List[str]:
        """Convert a job dictionary or JobPost object into spreadsheet row format."""
        from job_pulse.models import clean_location_string
        job_id = str(job.get("id") or "")
        title = str(job.get("title") or "")
        company = str(job.get("company") or "")
        location = clean_location_string(job.get("location"))
        
        raw_mode = str(job.get("work_mode") or "").replace("WorkMode.", "").strip()
        if not raw_mode or raw_mode.lower() in ["unknown", "not specified", "none", "null"]:
            work_mode = "Not Disclosed"
        else:
            work_mode = raw_mode.title()

        raw_role = str(job.get("role_type") or "").replace("RoleType.", "").strip().upper()
        if "TECH" in raw_role and "NON" not in raw_role:
            role_type = "Technical"
        else:
            role_type = "Non-Technical"

        is_intern = "Yes (Internship/Fresher)" if job.get("is_internship") else "No (Regular)"
        exp = str(job.get("experience_text") or "")
        if not exp and job.get("experience_min") is not None:
            exp = f"{job['experience_min']}-{job.get('experience_max', '+')} Yrs"
        elif not exp:
            exp = "All Experience Levels"
            
        salary = str(job.get("salary_text") or "Not Disclosed")
        portal = str(job.get("source_portal") or "")
        posted_date = str(job.get("posted_date") or "Recently Posted")
        url = str(job.get("url") or "")
        from job_pulse.utils.time_utils import get_ist_sheet_timestamp
        sync_time = get_ist_sheet_timestamp()

        return [
            job_id,
            title,
            company,
            location,
            work_mode,
            role_type,
            is_intern,
            exp,
            salary,
            portal,
            posted_date,
            url,
            sync_time,
        ]

    @classmethod
    def format_post_row(cls, post: Dict[str, Any]) -> List[str]:
        """Convert a hiring post into spreadsheet row format."""
        from job_pulse.models import clean_location_string
        from job_pulse.utils.time_utils import get_ist_sheet_timestamp
        post_id = str(post.get("id") or "")
        role_title = str(post.get("role_title") or "")
        poster = str(post.get("poster_name") or "HR / Recruiter")
        company = str(post.get("company") or "")
        location = clean_location_string(post.get("location"))
        email = str(post.get("contact_email") or "")
        phone = str(post.get("contact_phone") or "")
        snippet = (post.get("post_text") or "").replace("\n", " ")[:300]
        url = str(post.get("post_url") or "")
        sync_time = get_ist_sheet_timestamp()

        return [
            post_id,
            role_title,
            poster,
            company,
            location,
            email,
            phone,
            snippet,
            url,
            sync_time,
        ]

    @classmethod
    def sync_jobs(
        cls,
        jobs: List[Dict[str, Any]],
        config: Dict[str, Any],
        sheet_name: Optional[str] = None,
    ) -> Tuple[bool, int, str]:
        """
        Synchronize a batch of jobs to Google Sheets with automatic ID deduplication.
        Returns (success, new_rows_appended_count, message).
        """
        if not jobs:
            return True, 0, "No jobs to sync."

        try:
            from job_pulse.radar.notifier import RadarEmailNotifier
            _, spreadsheet = cls._get_client_and_sheet(config)
            target_sheet_name = sheet_name or config.get("sheet_name_all_india", "All-India Jobs")
            worksheet = cls._get_or_create_worksheet(spreadsheet, target_sheet_name, cls.JOB_HEADERS)

            # Get existing Job IDs in Column A (Row 2 onwards) with retry
            col_a_values = cls._api_call_with_retry(worksheet.col_values, 1)
            existing_ids = set(col_a_values[1:]) if len(col_a_values) > 1 else set()

            new_rows = []
            for j in jobs:
                # Reject invalid website / navigation links
                if not RadarEmailNotifier._is_valid_job_for_email(j):
                    continue
                j_id = str(j.get("id") or "")
                if j_id and j_id not in existing_ids:
                    new_rows.append(cls.format_job_row(j))
                    existing_ids.add(j_id)

            if not new_rows:
                return True, 0, f"All {len(jobs)} jobs already exist or are filtered in sheet '{target_sheet_name}'."

            # Batch append new rows with retry
            cls._api_call_with_retry(worksheet.append_rows, new_rows, value_input_option="USER_ENTERED")
            logger.info(f"Successfully appended {len(new_rows)} new job rows to Google Sheet '{target_sheet_name}'")
            return True, len(new_rows), f"Successfully synced {len(new_rows)} new opportunities to Google Sheet."

        except Exception as e:
            logger.error(f"Failed to sync jobs to Google Sheets: {e}")
            return False, 0, f"Google Sheets sync failed: {str(e)}"

    @classmethod
    def sync_hiring_posts(
        cls,
        posts: List[Dict[str, Any]],
        config: Dict[str, Any],
        sheet_name: Optional[str] = None,
    ) -> Tuple[bool, int, str]:
        """Synchronize LinkedIn/HR hiring posts to Google Sheets with deduplication."""
        if not posts:
            return True, 0, "No hiring posts to sync."

        try:
            _, spreadsheet = cls._get_client_and_sheet(config)
            target_sheet_name = sheet_name or config.get("sheet_name_hiring_posts", "Recruiter Posts")
            worksheet = cls._get_or_create_worksheet(spreadsheet, target_sheet_name, cls.POST_HEADERS)

            col_a_values = cls._api_call_with_retry(worksheet.col_values, 1)
            existing_ids = set(col_a_values[1:]) if len(col_a_values) > 1 else set()

            new_rows = []
            for p in posts:
                p_id = str(p.get("id") or "")
                if p_id and p_id not in existing_ids:
                    new_rows.append(cls.format_post_row(p))
                    existing_ids.add(p_id)

            if not new_rows:
                return True, 0, f"All {len(posts)} recruiter posts already exist in sheet '{target_sheet_name}'."

            cls._api_call_with_retry(worksheet.append_rows, new_rows, value_input_option="USER_ENTERED")
            logger.info(f"Successfully appended {len(new_rows)} new recruiter post rows to Google Sheet '{target_sheet_name}'")
            return True, len(new_rows), f"Successfully synced {len(new_rows)} recruiter posts to Google Sheet."

        except Exception as e:
            logger.error(f"Failed to sync hiring posts to Google Sheets: {e}")
            return False, 0, f"Google Sheets posts sync failed: {str(e)}"

    @classmethod
    def clean_worksheet_junk_rows(
        cls,
        config: Dict[str, Any],
        sheet_names: Optional[List[str]] = None,
    ) -> Tuple[bool, int, str]:
        """
        Scan Google Sheet worksheet(s), identify and purge non-job navigation links,
        department overview cards, and invalid entries, keeping only genuine jobs.
        """
        try:
            from job_pulse.models import is_valid_job_listing
            _, spreadsheet = cls._get_client_and_sheet(config)
            
            if not sheet_names:
                sheet_names = [
                    config.get("sheet_name_target_radar") or "Target Company Radar",
                    config.get("sheet_name_all_india") or "All-India Jobs",
                ]

            total_purged = 0
            for name in sheet_names:
                try:
                    ws = spreadsheet.worksheet(name)
                except Exception:
                    continue

                all_rows = cls._api_call_with_retry(ws.get_all_values)
                if not all_rows or len(all_rows) <= 1:
                    continue

                header = all_rows[0] if all_rows[0] else cls.JOB_HEADERS
                header_lower = [str(h).lower().strip() for h in header]

                # Dynamically resolve column indices
                title_idx = 1
                company_idx = 2
                url_idx = 11
                for idx, col_name in enumerate(header_lower):
                    if col_name in ("job title", "role title", "title"):
                        title_idx = idx
                    elif col_name in ("company", "company name", "recruiter / company"):
                        company_idx = idx
                    elif any(k in col_name for k in ["link", "url"]):
                        url_idx = idx

                valid_rows = []
                for row in all_rows[1:]:
                    if len(row) < 2:
                        continue
                    title = row[title_idx].strip() if len(row) > title_idx else ""
                    company = row[company_idx].strip() if len(row) > company_idx else ""
                    url = row[url_idx].strip() if len(row) > url_idx else ""
                    
                    if is_valid_job_listing(title=title, url=url, company=company):
                        valid_rows.append(row)
                    else:
                        total_purged += 1

                if len(valid_rows) != len(all_rows) - 1:
                    cls._api_call_with_retry(ws.clear)
                    cls._api_call_with_retry(ws.append_rows, [header] + valid_rows, value_input_option="USER_ENTERED")
                    try:
                        ws.freeze(rows=1)
                    except Exception:
                        pass
                    logger.info(f"Cleaned {len(all_rows) - 1 - len(valid_rows)} invalid rows from '{name}'.")

            return True, total_purged, f"Successfully cleaned {total_purged} non-job items from Google Sheet."
        except Exception as e:
            logger.error(f"Failed to clean Google Sheet: {e}")
            return False, 0, f"Failed to clean Google Sheet: {str(e)}"
