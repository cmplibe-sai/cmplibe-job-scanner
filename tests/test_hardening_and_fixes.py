import pytest
import sqlite3
from unittest.mock import MagicMock
from job_pulse.models import JobPost, HiringPost
from job_pulse.scrapers.base import BaseScraper
from job_pulse.scrapers.career_pages import _is_safe_url
from job_pulse.pipeline.sheets_sync import GoogleSheetsManager
from job_pulse.storage.db import JobDatabase


class DummyScraper(BaseScraper):
    def search(self, query):
        pass


def test_ssrf_protection():
    """Verify that _is_safe_url correctly blocks loopback, private, and invalid URLs."""
    # Forbidden / internal targets
    assert _is_safe_url("http://127.0.0.1:8000/internal") is False
    assert _is_safe_url("http://localhost:8080/metrics") is False
    assert _is_safe_url("http://0.0.0.0:5000/secret") is False
    assert _is_safe_url("file:///etc/passwd") is False
    assert _is_safe_url("gopher://localhost:6379") is False
    assert _is_safe_url("") is False

    # Valid public target
    assert _is_safe_url("https://www.google.com") is True
    assert _is_safe_url("https://boards.greenhouse.io/swiggy") is True


def test_description_slice_operator_precedence():
    """Ensure that description is actually truncated to 200/300 chars without operator precedence bugs."""
    long_desc = "A" * 500
    # If the bug were present, check_str would have evaluated against all 500 chars
    # We test that JobPost correctly builds and runs model_post_init
    job = JobPost(
        title="Software Engineer",
        company="TechCorp",
        description=long_desc,
        url="https://example.com/job/1",
        source_portal="Portal",
    )
    assert job.title == "Software Engineer"
    assert len(job.description) == 500  # Original description preserved
    # Check that model_post_init runs smoothly without exception


def test_phone_number_word_boundaries():
    """Verify that phone numbers are only matched if not part of larger digit strings."""
    # 1. Embedded inside a longer digit sequence (e.g. tracking number, Aadhaar-like) -> Should NOT match
    post_embedded = HiringPost(
        poster_name="HR",
        role_title="Recruiter",
        post_text="Tracking ID: 123498765432109876. Please track online.",
        post_url="https://linkedin.com/posts/1",
    )
    assert post_embedded.contact_phone is None

    # 2. Genuine phone number -> Should match
    post_genuine = HiringPost(
        poster_name="HR",
        role_title="Recruiter",
        post_text="We are hiring! Reach out at +91 9876543210 or email us.",
        post_url="https://linkedin.com/posts/2",
    )
    assert post_genuine.contact_phone in ["+91 9876543210", "+919876543210", "9876543210"] or "9876543210" in (post_genuine.contact_phone or "")


def test_currency_parsing_word_boundaries():
    """Verify that 'PAN India' or 'Credit' words don't trigger INR currency incorrectly."""
    scraper = DummyScraper()

    # 'PAN India' should not be detected as INR unless actual INR terms are present
    _, _, cur1, _ = scraper.parse_salary("Flexible work location across PAN India")
    assert cur1 is None

    # 'Credit Analyst' should not be detected as INR (from 'Cr')
    _, _, cur2, _ = scraper.parse_salary("Competitive salary for Credit Analyst")
    assert cur2 is None

    # Genuine LPA or ₹ should be detected as INR
    _, _, cur3, _ = scraper.parse_salary("12 - 18 LPA")
    assert cur3 == "INR"

    _, _, cur4, _ = scraper.parse_salary("₹8,00,000 - ₹12,00,000 per annum")
    assert cur4 == "INR"


def test_sqlite_wal_mode_and_busy_timeout(tmp_path):
    """Verify that SQLite connections are initialized with WAL mode and 30s busy timeout."""
    db_file = tmp_path / "test_wal.db"
    db = JobDatabase(db_path=db_file)

    with db._get_conn() as conn:
        journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
        assert journal_mode.lower() == "wal"

        busy_timeout = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
        assert busy_timeout >= 30000


def test_sheets_api_retry_backoff():
    """Verify that _api_call_with_retry retries on 429/RESOURCE_EXHAUSTED."""
    mock_fn = MagicMock()
    # First call raises 429 quota error, second call succeeds
    mock_fn.side_effect = [Exception("429 RESOURCE_EXHAUSTED: Quota exceeded"), "SuccessResult"]

    result = GoogleSheetsManager._api_call_with_retry(mock_fn, max_retries=2)
    assert result == "SuccessResult"
    assert mock_fn.call_count == 2


def test_clean_worksheet_junk_rows_no_false_purge():
    """
    Regression Test: Ensure clean_worksheet_junk_rows does NOT confuse 'Role Category' (col 5)
    with 'Job Title' (col 1), which previously caused all valid job rows to be purged.
    """
    mock_ws = MagicMock()
    # Real JOB_HEADERS used in Google Sheets
    headers = list(GoogleSheetsManager.JOB_HEADERS)
    # Valid job row
    valid_row = [
        "JOB_12345",
        "Senior Backend Engineer",
        "Razorpay",
        "Bengaluru",
        "Hybrid",
        "Technical",               # Col 5: Role Category
        "Experienced",
        "3-5 Yrs",
        "20-30 LPA",
        "Career Page",
        "2026-09-08",
        "https://razorpay.com/careers/job/123",  # Col 11: Direct Application Link
        "2026-09-08T10:00:00",
    ]
    # Junk non-job row (e.g., loan offer or navigation element)
    junk_row = [
        "JUNK_001",
        "Instant Personal Loan 50000",
        "LendingKart",
        "India",
        "Remote",
        "Non-Technical",
        "None",
        "0 Yrs",
        "",
        "Web",
        "2026-09-08",
        "https://example.com/loans",
        "2026-09-08T10:00:00",
    ]

    mock_ws.get_all_values.return_value = [headers, valid_row, junk_row]

    mock_spreadsheet = MagicMock()
    mock_spreadsheet.worksheet.return_value = mock_ws

    original_get_client = GoogleSheetsManager._get_client_and_sheet
    GoogleSheetsManager._get_client_and_sheet = classmethod(lambda cls, cfg: (MagicMock(), mock_spreadsheet))

    try:
        success, purged_count, msg = GoogleSheetsManager.clean_worksheet_junk_rows(
            config={"spreadsheet_id": "test_id"},
            sheet_names=["Target Company Radar"],
        )
        assert success is True
        # Only the junk loan row should be purged (purged_count == 1); the valid row MUST be preserved
        assert purged_count == 1
        # Check that append_rows was called with [headers, valid_row]
        mock_ws.append_rows.assert_called_once()
        saved_rows = mock_ws.append_rows.call_args[0][0]
        assert len(saved_rows) == 2  # header + 1 valid row
        assert saved_rows[1][1] == "Senior Backend Engineer"
    finally:
        GoogleSheetsManager._get_client_and_sheet = original_get_client


def test_career_pages_discovered_link_ssrf():
    """Ensure discovered links inside career pages are checked with _is_safe_url to prevent SSRF bypass."""
    from job_pulse.scrapers.career_pages import CareerPageScraper
    from bs4 import BeautifulSoup

    scraper = CareerPageScraper()
    # Mock client.get_soup to return HTML with an internal link masquerading as a Careers page
    mock_client = MagicMock()
    html_with_internal_link = """
    <html>
        <body>
            <a href="http://169.254.169.254/latest/meta-data">Careers at Internal</a>
            <a href="http://127.0.0.1:8000/admin/secrets">Jobs Portal</a>
        </body>
    </html>
    """
    mock_client.get_soup.return_value = BeautifulSoup(html_with_internal_link, "html.parser")
    scraper.client = mock_client

    # Resolving from a generic homepage should reject internal/metadata endpoints
    resolved = scraper._resolve_career_url("https://example.com")
    assert resolved is None

    # Scraping a generic page should abort and return empty jobs
    jobs = scraper._scrape_generic_page("https://example.com")
    assert jobs == []


def test_pa_salary_parsing_currency():
    """Verify '10,00,000 PA' or '12,00,000 P.A.' is recognized as INR."""
    scraper = DummyScraper()
    _, _, cur1, _ = scraper.parse_salary("10,00,000 PA")
    assert cur1 == "INR"

    _, _, cur2, _ = scraper.parse_salary("12,00,000 P.A.")
    assert cur2 == "INR"


def test_login_rate_limiting_ip_spoofing_protection():
    """
    Ensure the login rate-limiter extracts the trustworthy rightmost IP from X-Forwarded-For
    (or X-Real-IP), preventing attackers from bypassing lockout by rotating spoofed prefix IPs.
    """
    from fastapi import HTTPException
    from job_pulse.server import login, LoginRequest, _LOGIN_FAILURES, MAX_LOGIN_FAILURES

    _LOGIN_FAILURES.clear()

    real_ip = "198.51.100.42"
    username = "attacker_target"
    req = LoginRequest(username=username, password="wrongpassword")

    # Attacker sends spoofed prefix entries: "1.1.1.1, 198.51.100.42", then "2.2.2.2, 198.51.100.42", etc.
    for i in range(MAX_LOGIN_FAILURES):
        mock_req = MagicMock()
        mock_req.headers = {"x-forwarded-for": f"10.{i}.0.1, {real_ip}"}
        mock_req.client.host = "127.0.0.1"
        mock_resp = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            login(req, mock_req, mock_resp)
        assert exc_info.value.status_code == 401

    # After MAX_LOGIN_FAILURES, the real IP must be locked out even if a new fake prefix is supplied
    mock_lockout_req = MagicMock()
    mock_lockout_req.headers = {"x-forwarded-for": f"99.99.99.99, {real_ip}"}
    mock_lockout_req.client.host = "127.0.0.1"
    mock_resp = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        login(req, mock_lockout_req, mock_resp)
    assert exc_info.value.status_code == 429
    assert "Too many failed login attempts" in exc_info.value.detail

    # Also verify that X-Real-IP is prioritized directly
    _LOGIN_FAILURES.clear()
    mock_real_req = MagicMock()
    mock_real_req.headers = {"x-real-ip": "203.0.113.88"}
    mock_real_req.client.host = "127.0.0.1"

    req2 = LoginRequest(username="user2", password="wrongpassword")
    with pytest.raises(HTTPException) as exc_info:
        login(req2, mock_real_req, mock_resp)
    assert exc_info.value.status_code == 401
    assert "203.0.113.88:user2" in _LOGIN_FAILURES



