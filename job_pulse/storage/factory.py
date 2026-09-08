import os
import logging

from job_pulse.storage.base import JobRepository

logger = logging.getLogger("job_pulse.storage.factory")

_repository_singleton: "JobRepository | None" = None


def get_repository(force_new: bool = False, **kwargs) -> JobRepository:
    """
    Return the active JobRepository, selected by the DATABASE_URL environment variable:
      - DATABASE_URL set (e.g. Supabase's pooler connection string) -> PostgresJobRepository
      - otherwise -> SQLiteJobRepository (local dev / testing fallback)

    Returns a process-wide singleton by default (a fresh psycopg2 pool per call would
    defeat the point of pooling) - pass force_new=True to bypass it, e.g. in tests that
    need an isolated database.
    """
    global _repository_singleton
    if _repository_singleton is not None and not force_new:
        return _repository_singleton

    database_url = os.getenv("DATABASE_URL", "").strip()
    if database_url:
        from job_pulse.storage.postgres_repo import PostgresJobRepository
        logger.info("DATABASE_URL is set - using PostgresJobRepository (Supabase).")
        repo = PostgresJobRepository(database_url=database_url, **kwargs)
    else:
        from job_pulse.storage.sqlite_repo import SQLiteJobRepository
        logger.info("DATABASE_URL is not set - using SQLiteJobRepository (local fallback).")
        repo = SQLiteJobRepository(**kwargs)

    if not force_new:
        _repository_singleton = repo
    return repo
