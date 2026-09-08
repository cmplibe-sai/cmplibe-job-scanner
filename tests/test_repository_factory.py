import os
from unittest.mock import patch


def test_factory_falls_back_to_sqlite_when_no_database_url(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import job_pulse.storage.factory as factory
    factory._repository_singleton = None

    from job_pulse.storage.sqlite_repo import SQLiteJobRepository
    repo = factory.get_repository(force_new=True, db_path=tmp_path / "fallback.db")
    assert isinstance(repo, SQLiteJobRepository)


@patch("job_pulse.storage.postgres_repo.psycopg2.pool.ThreadedConnectionPool")
def test_factory_selects_postgres_when_database_url_set(mock_pool_cls, monkeypatch):
    from unittest.mock import MagicMock
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_cursor.fetchall.return_value = []
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_pool = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    mock_pool_cls.return_value = mock_pool

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@localhost:6543/postgres?pgbouncer=true")
    import job_pulse.storage.factory as factory
    factory._repository_singleton = None

    from job_pulse.storage.postgres_repo import PostgresJobRepository
    repo = factory.get_repository(force_new=True)
    assert isinstance(repo, PostgresJobRepository)

    factory._repository_singleton = None


def test_factory_returns_singleton_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    import job_pulse.storage.factory as factory
    factory._repository_singleton = None

    repo1 = factory.get_repository(db_path=tmp_path / "singleton.db")
    repo2 = factory.get_repository()
    assert repo1 is repo2

    factory._repository_singleton = None
