from unittest.mock import patch
import pytest

from job_pulse.storage.sqlite_repo import SQLiteJobRepository
from job_pulse.radar.story_worker import compute_row_hash, sync_companies_from_stories
from job_pulse.models import CompanyTarget


@pytest.fixture
def repo(tmp_path):
    return SQLiteJobRepository(db_path=tmp_path / "story_worker_test.db")


def _story_row(main_company, competitors, extra_cols=8):
    return [""] * extra_cols + [main_company, competitors]


def test_compute_row_hash_stable_and_sensitive_to_content():
    row = ["a", "b", "c"]
    assert compute_row_hash("Sheet1", row) == compute_row_hash("Sheet1", row)
    assert compute_row_hash("Sheet1", row) != compute_row_hash("Sheet1", ["a", "b", "d"])
    assert compute_row_hash("Sheet1", row) != compute_row_hash("Sheet2", row)


@patch("job_pulse.radar.story_worker.discover_company_homepage", return_value=None)
@patch("job_pulse.pipeline.sheets_sync.GoogleSheetsManager.read_worksheet_rows")
def test_sync_registers_main_company_and_competitors_as_new_targets(mock_read, mock_discover, repo):
    mock_read.return_value = [
        ["header"] * 10,
        _story_row("Zepto", "Blinkit, Swiggy Instamart"),
    ]

    stats = sync_companies_from_stories(repo, sheets_config={"credentials_json": "fake"})

    assert stats["rows_scanned"] == 1
    assert stats["rows_processed"] == 1
    assert stats["targets_created"] == 3  # Zepto + Blinkit + Swiggy Instamart
    assert stats["errors"] == []

    names = {t["company_name"] for t in repo.get_company_targets()}
    assert names == {"Zepto", "Blinkit", "Swiggy Instamart"}
    for t in repo.get_company_targets():
        assert t["source"] == "story_ingestion"


@patch("job_pulse.radar.story_worker.discover_company_homepage", return_value=None)
@patch("job_pulse.pipeline.sheets_sync.GoogleSheetsManager.read_worksheet_rows")
def test_sync_does_not_duplicate_existing_watched_target(mock_read, mock_discover, repo):
    # "Byju's Learning Pvt Ltd" is already a manually-added target.
    repo.save_company_target(CompanyTarget(company_name="Byju's Learning Pvt Ltd", source="manual"))

    mock_read.return_value = [
        ["header"] * 10,
        _story_row("Byju's", "Toppr"),  # main company is a name-variant of the existing target
    ]

    stats = sync_companies_from_stories(repo, sheets_config={"credentials_json": "fake"})

    assert stats["targets_created"] == 1  # only Toppr is new; Byju's collapses into the existing target
    names = {t["company_name"] for t in repo.get_company_targets()}
    assert names == {"Byju's Learning Pvt Ltd", "Toppr"}


@patch("job_pulse.radar.story_worker.discover_company_homepage", return_value=None)
@patch("job_pulse.pipeline.sheets_sync.GoogleSheetsManager.read_worksheet_rows")
def test_sync_skips_already_processed_rows_on_second_run(mock_read, mock_discover, repo):
    mock_read.return_value = [
        ["header"] * 10,
        _story_row("Zepto", "Blinkit"),
    ]

    first = sync_companies_from_stories(repo, sheets_config={"credentials_json": "fake"})
    second = sync_companies_from_stories(repo, sheets_config={"credentials_json": "fake"})

    assert first["rows_processed"] == 1
    assert second["rows_processed"] == 0  # already-processed row is skipped, not re-ingested
    assert len(repo.get_company_targets()) == 2  # no duplicate targets from the second run


@patch("job_pulse.radar.story_worker.discover_company_homepage", return_value=None)
@patch("job_pulse.pipeline.sheets_sync.GoogleSheetsManager.read_worksheet_rows")
def test_sync_logs_rows_with_no_usable_company_name_as_skipped(mock_read, mock_discover, repo):
    mock_read.return_value = [
        ["header"] * 10,
        _story_row("", "Blinkit"),  # blank main company - unusable row
    ]

    stats = sync_companies_from_stories(repo, sheets_config={"credentials_json": "fake"})

    assert stats["rows_skipped"] == 1
    assert stats["targets_created"] == 0
    logs = repo.get_story_ingestion_logs()
    assert len(logs) == 1
    assert logs[0]["status"] == "skipped"


@patch("job_pulse.radar.story_worker.discover_company_homepage", return_value=None)
@patch("job_pulse.pipeline.sheets_sync.GoogleSheetsManager.read_worksheet_rows")
def test_sync_respects_max_rows_per_run(mock_read, mock_discover, repo):
    mock_read.return_value = [["header"] * 10] + [
        _story_row(f"Company{i}", "") for i in range(5)
    ]

    stats = sync_companies_from_stories(repo, sheets_config={"credentials_json": "fake"}, max_rows_per_run=2)

    assert stats["rows_scanned"] == 2
    assert stats["rows_processed"] == 2
    assert len(repo.get_company_targets()) == 2


@patch("job_pulse.pipeline.sheets_sync.GoogleSheetsManager.read_worksheet_rows", side_effect=RuntimeError("sheet not shared with service account"))
def test_sync_handles_sheet_read_failure_gracefully(mock_read, repo):
    stats = sync_companies_from_stories(repo, sheets_config={"credentials_json": "fake"})
    assert stats["rows_scanned"] == 0
    assert len(stats["errors"]) == 1
