import pytest
from pathlib import Path
from job_pulse.storage.db import JobDatabase
from job_pulse.models import CompanyTarget, RadarAlertLog, JobPost, HiringPost
from job_pulse.radar.notifier import RadarEmailNotifier
from job_pulse.radar.scanner import CompanyRadarScanner


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_jobpulse.db"
    return JobDatabase(db_path=db_file)


def test_company_target_crud(temp_db):
    target = CompanyTarget(
        company_name="Stripe",
        career_url="https://stripe.com/jobs",
        keywords="engineer",
        channels=["ats", "linkedin"],
    )
    is_new = temp_db.save_company_target(target)
    assert is_new is True

    targets = temp_db.get_company_targets()
    assert len(targets) == 1
    assert targets[0]["company_name"] == "Stripe"
    assert targets[0]["is_active"] is True

    # Toggle active
    temp_db.toggle_company_target(target.id)
    updated = temp_db.get_company_target(target.id)
    assert updated["is_active"] is False

    # Delete
    deleted = temp_db.delete_company_target(target.id)
    assert deleted is True
    assert len(temp_db.get_company_targets()) == 0


def test_radar_alert_logging_and_delta(temp_db):
    log_entry = RadarAlertLog(
        company_id="target_123",
        item_type="job",
        item_id="job_abc_1",
        title="Software Engineer - Fresher",
        company="Stripe",
        url="https://stripe.com/jobs/1",
        source="Greenhouse",
        recipient_email="candidate@example.com",
    )
    
    assert temp_db.is_alert_already_sent("job_abc_1", "candidate@example.com") is False
    temp_db.save_radar_alert_log(log_entry)
    assert temp_db.is_alert_already_sent("job_abc_1", "candidate@example.com") is True
    assert temp_db.is_alert_already_sent("job_abc_1", "other@example.com") is False


def test_email_config_storage(temp_db):
    cfg = temp_db.get_email_config()
    assert "smtp_host" in cfg
    assert cfg["is_enabled"] is False

    temp_db.save_email_config({
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_user": "test@gmail.com",
        "recipient_email": "alerts@test.com",
        "is_enabled": True,
        "check_interval_minutes": 30,
    })

    updated = temp_db.get_email_config()
    assert updated["recipient_email"] == "alerts@test.com"
    assert updated["is_enabled"] is True
    assert updated["check_interval_minutes"] == 30


def test_resilient_experience_filtering(temp_db):
    job1 = JobPost(
        title="Category Manager",
        company="Jumbotail",
        url="https://jumbotail.com/job1",
        source_portal="LinkedIn",
        experience_text="3-5 Yrs",
    )
    job2 = JobPost(
        title="Junior Recruiter / Fresher",
        company="Swiggy",
        url="https://swiggy.com/job2",
        source_portal="Internshala",
        is_internship=True,
    )
    temp_db.save_jobs_batch([job1, job2])

    # Search with 3-5 experience level
    exp_jobs = temp_db.get_jobs(experience_level="3-5")
    assert len(exp_jobs) == 1
    assert exp_jobs[0]["title"] == "Category Manager"

    # Search with internship
    intern_jobs = temp_db.get_jobs(experience_level="internship")
    assert len(intern_jobs) == 1
    assert "Junior Recruiter" in intern_jobs[0]["title"]

    # Search with all
    all_j = temp_db.get_jobs()
    assert len(all_j) == 2


def test_job_title_validation():
    from job_pulse.scrapers.career_pages import CareerPageScraper
    scraper = CareerPageScraper()

    # Should reject non-job navigation / tool titles
    invalid_examples = [
        "Newsroom",
        "Blog",
        "GST Calculator",
        "EMI Calculator",
        "(current)",
        "Privacy Policy",
        "Terms of Service",
        "About Us",
        "Contact Us",
        "Download App",
        "FAQ",
    ]
    for bad in invalid_examples:
        assert scraper._is_valid_job_title(bad) is False, f"Expected '{bad}' to be rejected"

    # Should accept valid role titles
    valid_examples = [
        "Home Loan Executive (Nagpur)",
        "Intern - Insurance Vertical (India)",
        "Founding Sales Leader (FinTech & B2B)",
        "Senior Software Engineer",
        "HR Recruiter",
        "Category Manager",
    ]
    for good in valid_examples:
        assert scraper._is_valid_job_title(good) is True, f"Expected '{good}' to be accepted"


def test_notifier_location_and_mode_cleaning():
    # Test unknown work mode and city
    job1 = {"location": "Nagpur", "work_mode": "WorkMode.UNKNOWN"}
    loc1 = RadarEmailNotifier._format_location_and_mode(job1)
    assert loc1 == "📍 Nagpur"
    assert "WorkMode" not in loc1
    assert "UNKNOWN" not in loc1

    # Test unspecified location with Remote
    job2 = {"location": "Not Specified", "work_mode": "WorkMode.REMOTE"}
    loc2 = RadarEmailNotifier._format_location_and_mode(job2)
    assert "Remote" in loc2
    assert "WorkMode" not in loc2

    # Test totally empty
    job3 = {"location": "", "work_mode": "UNKNOWN"}
    loc3 = RadarEmailNotifier._format_location_and_mode(job3)
    assert loc3 == "📍 Location: As Announced"


def test_job_url_validation():
    from job_pulse.scrapers.career_pages import CareerPageScraper
    scraper = CareerPageScraper()

    # Should reject loan EMI, recharge, products, and root URLs
    invalid_urls = [
        "https://paytm.com/loan-emi-payment/easy-home-finance-limited",
        "https://paytm.com/recharge",
        "https://paytm.com/electricity-bill-payment",
        "https://paytm.com/loans-credit-cards/personal-loan/",
        "https://paytm.com/",
        "https://khatabook.com/privacy-policy",
        "https://swiggy.com/about",
    ]
    for url in invalid_urls:
        assert scraper._is_valid_job_url(url, "https://paytm.com") is False, f"Expected '{url}' to be rejected"

    # Should accept valid career / opening URLs
    valid_urls = [
        "https://jobs.lever.co/paytm/abc-123-xyz",
        "https://boards.greenhouse.io/swiggy/jobs/998877",
        "https://jumbotail.com/careers/category-manager/",
        "https://www.shine.com/jobs/home-loan-executive-nagpur/19274828",
        "https://internshala.com/job/detail/sales-executive-1234",
    ]
    for url in valid_urls:
        assert scraper._is_valid_job_url(url, "https://company.com") is True, f"Expected '{url}' to be accepted"


def test_notifier_email_job_validation():
    # Test valid job
    valid_job = {
        "title": "Software Engineer (Backend)",
        "url": "https://jobs.lever.co/paytm/123",
        "company": "Paytm",
    }
    assert RadarEmailNotifier._is_valid_job_for_email(valid_job) is True

    # Test invalid job with loan URL and lender name
    fake_job_1 = {
        "title": "Easy Home Finance Limited",
        "url": "https://paytm.com/loan-emi-payment/easy-home-finance-limited",
        "company": "Paytm",
    }
    assert RadarEmailNotifier._is_valid_job_for_email(fake_job_1) is False

    # Test invalid job with homepage URL
    fake_job_2 = {
        "title": "Category Manager",
        "url": "https://paytm.com/",
        "company": "Paytm",
    }
    assert RadarEmailNotifier._is_valid_job_for_email(fake_job_2) is False


def test_discovery_alert_logging_and_delta(temp_db):
    from job_pulse.models import DiscoveryAlertLog
    log_entry = DiscoveryAlertLog(
        item_type="job",
        item_id="job_india_101",
        title="Category Manager",
        company="Flipkart",
        url="https://flipkart.com/jobs/101",
        source="Naukri",
        role_type="Non-Technical",
        recipient_email="allindia.jobs@example.com",
    )

    assert temp_db.is_discovery_alert_already_sent("job_india_101", "allindia.jobs@example.com") is False
    temp_db.save_discovery_alert_log(log_entry)
    assert temp_db.is_discovery_alert_already_sent("job_india_101", "allindia.jobs@example.com") is True
    assert temp_db.is_discovery_alert_already_sent("job_india_101", "other@example.com") is False

    logs = temp_db.get_discovery_alert_logs()
    assert len(logs) == 1
    assert logs[0]["company"] == "Flipkart"
    assert logs[0]["role_type"] == "Non-Technical"


def test_dual_email_config_saving_and_loading(temp_db):
    temp_db.save_email_config({
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "smtp_user": "scanner@cmplibe.com",
        "recipient_email": "watchlist.alerts@cmplibe.com",
        "is_enabled": True,
        "check_interval_minutes": 60,
        "all_india_recipient": "allindia.alerts@cmplibe.com",
        "all_india_is_enabled": True,
        "all_india_interval_minutes": 120,
        "all_india_keywords": "developer, hr, analyst",
    })

    cfg = temp_db.get_email_config()
    assert cfg["recipient_email"] == "watchlist.alerts@cmplibe.com"
    assert cfg["is_enabled"] is True
    assert cfg["check_interval_minutes"] == 60
    assert cfg["all_india_recipient"] == "allindia.alerts@cmplibe.com"
    assert cfg["all_india_is_enabled"] is True
    assert cfg["all_india_interval_minutes"] == 120
    assert "developer" in cfg["all_india_keywords"]


def test_all_india_discovery_scanner_run(temp_db):
    from unittest.mock import MagicMock
    from job_pulse.radar.discovery_scanner import AllIndiaDiscoveryScanner

    mock_orchestrator = MagicMock()
    mock_orchestrator.run.return_value = {
        "total_scraped": 2,
        "unique_jobs": 2,
        "new_stored": 2,
        "total_hiring_posts": 1,
        "execution_time_seconds": 1.2,
        "jobs": [
            {
                "id": "job_pan_1",
                "title": "Software Engineer",
                "company": "Swiggy",
                "location": "Bangalore",
                "url": "https://jobs.lever.co/swiggy/1",
                "source_portal": "LinkedIn",
                "role_type": "Technical",
            },
            {
                "id": "job_pan_2",
                "title": "HR Recruiter",
                "company": "Zepto",
                "location": "Mumbai",
                "url": "https://zepto.in/careers/2",
                "source_portal": "Naukri",
                "role_type": "Non-Technical",
            },
        ],
        "hiring_posts": [
            {
                "id": "post_pan_1",
                "role_title": "BDE Intern",
                "poster_name": "Rohan HR",
                "company": "Zomato",
                "location": "Delhi",
                "post_url": "https://linkedin.com/post/1",
                "post_text": "Hiring freshers for BD role!",
            }
        ],
        "portal_results": {},
    }

    scanner = AllIndiaDiscoveryScanner(db=temp_db, orchestrator=mock_orchestrator)
    res = scanner.scan_all_india(send_email=False, sync_sheets=False)

    assert res["total_scraped"] == 2
    assert res["unique_jobs"] == 2
    assert res["total_hiring_posts"] == 1
    assert res["new_jobs_emailed"] == 2
    assert res["new_posts_emailed"] == 1



