import pytest
from job_pulse.models import JobPost, SearchQuery, WorkMode, generate_job_id
from job_pulse.pipeline.deduplicator import JobDeduplicator
from job_pulse.storage.db import JobDatabase
from pathlib import Path
import tempfile
import os


def test_job_id_generation():
    id1 = generate_job_id("linkedin", "Google", "Senior Python Engineer", "Mountain View, CA")
    id2 = generate_job_id("linkedin", "google", "senior python engineer", "mountain view, ca")
    assert id1 == id2


def test_deduplicator():
    job1 = JobPost(
        title="Senior Python Developer (Remote)",
        company="Microsoft Corp",
        location="Remote, India",
        url="https://linkedin.com/jobs/1",
        source_portal="LinkedIn",
        description="We are hiring a python dev...",
    )
    job2 = JobPost(
        title="Senior Python Developer",
        company="Microsoft Pvt Ltd",
        location="India",
        url="https://naukri.com/jobs/2",
        source_portal="Naukri",
        salary_text="20-30 LPA",
    )
    
    unique_jobs, clusters = JobDeduplicator.process_and_deduplicate([job1, job2])
    assert len(unique_jobs) == 1
    assert len(clusters) == 1


def test_storage_crud():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_jobs.db"
        db = JobDatabase(db_path=db_path)

        job = JobPost(
            title="AI Engineer",
            company="DeepMind",
            location="London",
            work_mode=WorkMode.HYBRID,
            skills=["PyTorch", "Python", "LLMs"],
            url="https://deepmind.google/careers/1",
            source_portal="Career Site",
        )

        # Test insert
        is_new = db.save_job(job)
        assert is_new is True

        # Test duplicate insert
        is_new_again = db.save_job(job)
        assert is_new_again is False

        # Query
        jobs = db.get_jobs(keywords="AI Engineer")
        assert len(jobs) == 1
        assert jobs[0]["title"] == "AI Engineer"
        assert "PyTorch" in jobs[0]["skills"]

        # Favorite toggle
        db.toggle_favorite(job.id)
        fav_jobs = db.get_jobs(favorite_only=True)
        assert len(fav_jobs) == 1

        # Stats
        stats = db.get_stats()
        assert stats["total_jobs"] == 1
        assert stats["total_companies"] == 1


def test_csv_exporter_with_role_type():
    from job_pulse.pipeline.exporter import JobExporter
    import csv

    with tempfile.TemporaryDirectory() as tmpdir:
        csv_file = Path(tmpdir) / "test_export.csv"
        jobs = [
            {
                "title": "Software Engineer",
                "company": "Google",
                "role_type": "Technical",
                "location": "Bangalore",
                "work_mode": "Hybrid",
                "url": "https://google.com/jobs/1",
                "source_portal": "Career Site",
                "posted_date": "2 days ago",
                "skills": ["Python", "C++"],
            },
            {
                "title": "Category Manager",
                "company": "Jumbotail",
                "location": "Bangalore",
                "work_mode": "On-site",
                "url": "https://jumbotail.com/jobs/2",
                "source_portal": "Career Site",
                "posted_date": "Recently Posted",
            }
        ]
        JobExporter.to_csv(jobs, csv_file)
        assert csv_file.exists()
        
        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 2
            assert "role_type" in rows[0]
            assert rows[0]["role_type"] == "Technical"
            assert rows[1]["role_type"] == "Non-Technical"
            assert rows[0]["location"] == "Bangalore"
