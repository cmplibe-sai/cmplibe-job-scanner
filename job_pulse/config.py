from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

# Auto-load .env file if present in project root
_env_file = BASE_DIR / ".env"
if _env_file.is_file():
    try:
        with open(_env_file, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    _k, _v = _k.strip(), _v.strip().strip("'\"")
                    if _k and _k not in os.environ:
                        os.environ[_k] = _v
    except Exception:
        pass

# Safe DATA_DIR determination with non-root Linux permission fallback
_env_data_dir = os.getenv("DATA_DIR")
if _env_data_dir:
    try:
        DATA_DIR = Path(_env_data_dir)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    except (PermissionError, OSError):
        DATA_DIR = BASE_DIR / "data"
        DATA_DIR.mkdir(parents=True, exist_ok=True)
else:
    DATA_DIR = BASE_DIR / "data"
    DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_PATH = DATA_DIR / "jobpulse.db"

# Scraper Network Configuration
DEFAULT_TIMEOUT = 15
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_BACKOFF = 1.5
DEFAULT_REQUEST_DELAY = 1.0  # seconds between requests to avoid rate limits

# User-Agent rotation pool
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.3; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0"
]

# Supported Portals
PORTALS = {
    "linkedin": "LinkedIn Jobs",
    "internshala": "Internshala",
    "unstop": "Unstop",
    "shine": "Shine.com",
    "naukri": "Naukri.com",
    "foundit": "Foundit (Monster)",
    "indeed": "Indeed",
    "linkedin_posts": "LinkedIn Recruiter Posts",
    "career_page": "Company Career Page / ATS",
}

# Email & Radar Defaults
DEFAULT_SMTP_HOST = os.getenv("SMTP_HOST", "resend")
DEFAULT_SMTP_PORT = int(os.getenv("SMTP_PORT", "443"))
DEFAULT_SMTP_USER = os.getenv("SMTP_USER", "resend")
DEFAULT_SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", os.getenv("RESEND_API_KEY", ""))
DEFAULT_SENDER_EMAIL = os.getenv("SENDER_EMAIL", "cMPLiBe AIScanner <earlitalent@cmplibe.com>")
DEFAULT_RECIPIENT_EMAIL = os.getenv("RECIPIENT_EMAIL", "cmplibesai@gmail.com, cmplibecynthiya@gmail.com")  # Target Company Radar recipient
DEFAULT_ALL_INDIA_RECIPIENT_EMAIL = os.getenv("ALL_INDIA_RECIPIENT_EMAIL", "cmplibesai@gmail.com, cmplibecynthiya@gmail.com")  # All-India Opportunity Alert recipient
DEFAULT_RADAR_INTERVAL_MINUTES = int(os.getenv("RADAR_INTERVAL_MINUTES", "60"))
DEFAULT_ALL_INDIA_RADAR_INTERVAL_MINUTES = int(os.getenv("ALL_INDIA_RADAR_INTERVAL_MINUTES", "120"))

# Google Sheets Live Sync Defaults
DEFAULT_GOOGLE_SHEETS_SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "1oMa1z0RilDuXmIKtgmOiY7FzudXVlI9pPKzwwMrU_4g")
DEFAULT_GOOGLE_SHEETS_CREDS_PATH = os.getenv("GOOGLE_SHEETS_CREDS_PATH", "")
DEFAULT_GOOGLE_SHEETS_CREDENTIALS_JSON = os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON", "")

# Automated Company Discovery: "cMPLi Dip Stories" source sheet
STORY_INGESTION_ENABLED = os.getenv("STORY_INGESTION_ENABLED", "false").lower() in ("true", "1", "yes")
STORY_SHEET_ID = os.getenv("STORY_SHEET_ID", "1LUO0XD1r8NgXTvry8BraCGqoirIvS8zVJPlIiXMauZA")
STORY_SHEET_NAME = os.getenv("STORY_SHEET_NAME", "cMPLi Dip Stories")
STORY_MAIN_COMPANY_COL = int(os.getenv("STORY_MAIN_COMPANY_COL", "8"))  # Column I (0-indexed)
STORY_COMPETITORS_COL = int(os.getenv("STORY_COMPETITORS_COL", "9"))  # Column J (0-indexed)
STORY_INGESTION_INTERVAL_MINUTES = int(os.getenv("STORY_INGESTION_INTERVAL_MINUTES", "360"))  # every 6h, Mon-Sat cadence


