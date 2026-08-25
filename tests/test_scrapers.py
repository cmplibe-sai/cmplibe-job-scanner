import pytest
from job_pulse.scrapers.base import BaseScraper
from job_pulse.scrapers.career_pages import CareerPageScraper
from job_pulse.scrapers.linkedin_posts import LinkedInPostsScraper
from job_pulse.models import WorkMode, SearchQuery, HiringPost, JobPost


class DummyScraper(BaseScraper):
    def search(self, query):
        pass


def test_experience_and_salary_parsing():
    scraper = DummyScraper()
    
    # Test Experience
    min_exp, max_exp, text = scraper.parse_experience("3 - 6 Yrs")
    assert min_exp == 3.0
    assert max_exp == 6.0

    min_exp2, max_exp2, text2 = scraper.parse_experience("5+ years")
    assert min_exp2 == 5.0
    assert max_exp2 is None

    # Test Salary LPA
    sal_min, sal_max, cur, _ = scraper.parse_salary("15 - 25 LPA")
    assert sal_min == 1500000.0
    assert sal_max == 2500000.0
    assert cur == "INR"

    # Test Work Mode detection
    assert scraper.detect_work_mode("Remote Marketing Manager") == WorkMode.REMOTE
    assert scraper.detect_work_mode("Hybrid HR Specialist") == WorkMode.HYBRID
    assert scraper.detect_work_mode("On-site Operations Lead") == WorkMode.ONSITE


def test_internship_auto_detection():
    job1 = JobPost(
        title="Marketing Intern (Summer 2026)",
        company="Zomato",
        url="https://zomato.com/careers/1",
        source_portal="LinkedIn",
    )
    assert job1.is_internship is True

    job2 = JobPost(
        title="Senior Category Manager",
        company="Jumbotail",
        url="https://jumbotail.com/category-manager/",
        source_portal="Career Site",
    )
    assert job2.is_internship is False


def test_hiring_post_contact_extraction():
    post = HiringPost(
        poster_name="Priya Sharma",
        role_title="Senior HR Recruiter",
        company="Swiggy",
        post_text="We are actively hiring for Senior HR Recruiters in Bangalore! Please share your CV at priya.sharma@swiggy.in or WhatsApp 9876543210.",
        post_url="https://www.linkedin.com/posts/priyasharma-activity-12345",
    )
    assert post.contact_email == "priya.sharma@swiggy.in"
    assert post.contact_phone == "9876543210"
    assert post.poster_name == "Priya Sharma"


def test_jumbotail_career_extraction():
    scraper = CareerPageScraper()
    jobs = scraper.scrape_url("https://jumbotail.com/careers/")
    assert len(jobs) >= 8
    titles = [j.title for j in jobs]
    # Verify both technical and non-technical roles were found
    assert any("category" in t.lower() or "finance" in t.lower() or "development" in t.lower() for t in titles)
    assert any("software" in t.lower() or "developer" in t.lower() for t in titles)
    for j in jobs:
        assert j.url.startswith("http")
        assert "linkedin.com/company" not in j.url


def test_shine_url_generation():
    from job_pulse.scrapers.shine import ShineScraper
    scraper = ShineScraper()
    q = SearchQuery(keywords="jumbotail", limit=5)
    res = scraper.search(q)
    assert res.portal == "Shine"
    for job in res.jobs:
        assert not job.url.endswith("/" + job.id + "/" + job.id)
        assert job.url.startswith("https://www.shine.com/jobs/")


def test_role_type_classification():
    from job_pulse.models import classify_role_type, RoleType
    assert classify_role_type("Software Development Engineer") == RoleType.TECHNICAL
    assert classify_role_type("Front End Developer (UI)") == RoleType.TECHNICAL
    assert classify_role_type("Category Manager") == RoleType.NON_TECHNICAL
    assert classify_role_type("Manager - Finance") == RoleType.NON_TECHNICAL
    assert classify_role_type("HR Recruiter") == RoleType.NON_TECHNICAL
    assert classify_role_type("Business Development Manager") == RoleType.NON_TECHNICAL


def test_internshala_and_unstop_scrapers():
    from job_pulse.scrapers.internshala import InternshalaScraper
    from job_pulse.scrapers.unstop import UnstopScraper
    from job_pulse.models import SearchQuery

    q = SearchQuery(keywords="Python", limit=5)
    
    unstop_scraper = UnstopScraper()
    res_unstop = unstop_scraper.search(q)
    assert res_unstop.portal == "Unstop"

    internshala_scraper = InternshalaScraper()
    res_intern = internshala_scraper.search(q)
    assert res_intern.portal == "Internshala"
