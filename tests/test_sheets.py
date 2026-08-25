import pytest
import json
from unittest.mock import MagicMock, patch
from job_pulse.pipeline.sheets_sync import GoogleSheetsManager
from job_pulse.storage.db import JobDatabase
from job_pulse.models import JobPost, HiringPost, GoogleSheetsConfig


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_sheets.db"
    return JobDatabase(db_path=db_file)


def test_extract_spreadsheet_id():
    # Test from full URL
    url = "https://docs.google.com/spreadsheets/d/1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms/edit#gid=0"
    extracted = GoogleSheetsManager.extract_spreadsheet_id(url)
    assert extracted == "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"

    # Test from bare ID
    bare_id = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
    extracted_bare = GoogleSheetsManager.extract_spreadsheet_id(bare_id)
    assert extracted_bare == bare_id

    # Test empty
    assert GoogleSheetsManager.extract_spreadsheet_id("") == ""


def test_format_job_row():
    job = {
        "id": "job_12345",
        "title": "Senior Python Developer",
        "company": "Swiggy",
        "location": "Bangalore",
        "work_mode": "Hybrid",
        "role_type": "Technical",
        "is_internship": False,
        "experience_text": "3-5 Yrs",
        "salary_text": "₹18-24 LPA",
        "source_portal": "LinkedIn Jobs",
        "posted_date": "1 day ago",
        "url": "https://linkedin.com/jobs/view/12345",
    }
    row = GoogleSheetsManager.format_job_row(job)
    assert len(row) == 13
    assert row[0] == "job_12345"
    assert row[1] == "Senior Python Developer"
    assert row[2] == "Swiggy"
    assert row[3] == "Bangalore"
    assert row[4] == "Hybrid"
    assert row[5] == "Technical"
    assert row[6] == "No (Regular)"
    assert row[7] == "3-5 Yrs"
    assert row[8] == "₹18-24 LPA"
    assert row[9] == "LinkedIn Jobs"
    assert row[11] == "https://linkedin.com/jobs/view/12345"


def test_format_post_row():
    post = {
        "id": "post_9988",
        "role_title": "HR Recruiter",
        "poster_name": "Priya Sharma",
        "company": "Zepto",
        "location": "Mumbai",
        "contact_email": "priya.recruiter@zepto.in",
        "contact_phone": "+919876543210",
        "post_text": "We are actively hiring 5 HR recruiters in Mumbai! Drop resume.",
        "post_url": "https://linkedin.com/feed/update/urn:li:activity:123",
    }
    row = GoogleSheetsManager.format_post_row(post)
    assert len(row) == 10
    assert row[0] == "post_9988"
    assert row[1] == "HR Recruiter"
    assert row[2] == "Priya Sharma"
    assert row[3] == "Zepto"
    assert row[5] == "priya.recruiter@zepto.in"
    assert row[6] == "+919876543210"
    assert row[8] == "https://linkedin.com/feed/update/urn:li:activity:123"


def test_sheets_config_db_storage(temp_db):
    config = temp_db.get_sheets_config()
    assert config["is_enabled"] is False
    assert config["sheet_name_all_india"] == "All-India Jobs"

    temp_db.save_sheets_config({
        "is_enabled": True,
        "spreadsheet_id_or_url": "1A2B3C4D5E6F7G8H9I0J",
        "sheet_name_all_india": "Pan-India Jobs",
        "sheet_name_target_radar": "Watchlist Radar",
        "sheet_name_hiring_posts": "HR Posts",
        "auto_sync_on_scrape": True,
    })

    updated = temp_db.get_sheets_config()
    assert updated["is_enabled"] is True
    assert updated["spreadsheet_id_or_url"] == "1A2B3C4D5E6F7G8H9I0J"
    assert updated["sheet_name_all_india"] == "Pan-India Jobs"
    assert updated["auto_sync_on_scrape"] is True

    # Test sync stats update
    temp_db.update_sheets_sync_stats(25)
    updated_stats = temp_db.get_sheets_config()
    assert updated_stats["last_synced_count"] == 25
    assert updated_stats["last_synced_at"] is not None


@patch("job_pulse.pipeline.sheets_sync.GoogleSheetsManager._get_client_and_sheet")
def test_sync_jobs_with_mock_sheet(mock_get_client_and_sheet):
    mock_worksheet = MagicMock()
    # Mock existing header and one existing job ID
    mock_worksheet.col_values.return_value = ["Job ID", "job_existing_1"]
    
    mock_spreadsheet = MagicMock()
    mock_spreadsheet.worksheet.return_value = mock_worksheet
    mock_get_client_and_sheet.return_value = (MagicMock(), mock_spreadsheet)

    config = {
        "spreadsheet_id_or_url": "dummy_id",
        "credentials_json": '{"dummy": "creds"}',
        "sheet_name_all_india": "All-India Jobs",
    }

    jobs = [
        {"id": "job_existing_1", "title": "Existing Software Role", "company": "Co1", "url": "https://company1.com/jobs/1"},
        {"id": "job_new_2", "title": "New Python Developer", "company": "Co2", "location": "Bangalore", "url": "https://company2.com/jobs/2"},
        {"id": "job_new_3", "title": "New HR Recruiter", "company": "Co3", "location": "Delhi", "url": "https://company3.com/jobs/3"},
    ]

    success, count, msg = GoogleSheetsManager.sync_jobs(jobs, config)
    assert success is True
    assert count == 2  # job_existing_1 skipped, job_new_2 and job_new_3 appended
    assert mock_worksheet.append_rows.called
    assert "Successfully synced 2 new opportunities" in msg
