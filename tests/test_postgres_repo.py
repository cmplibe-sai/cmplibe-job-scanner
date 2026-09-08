"""
Unit tests for PostgresJobRepository's Python-level control flow (connection pooling,
commit/rollback/retry behavior, JobRepository interface conformance) using a mocked
psycopg2 pool - there is no live Postgres/Supabase instance available in this
environment, so these do NOT validate that the SQL is accepted by a real Postgres
server. Run test_factory_selects_postgres_when_database_url_set's sibling smoke test
against a real Supabase DATABASE_URL before relying on this in production.
"""
from unittest.mock import MagicMock, patch
import pytest

from job_pulse.storage.base import JobRepository


def _make_mock_pool():
    """A fake psycopg2 ThreadedConnectionPool whose connections/cursors are MagicMocks
    that respond to fetchone()/fetchall() with harmless defaults."""
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = None
    mock_cursor.fetchall.return_value = []
    mock_cursor.rowcount = 1

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    mock_pool = MagicMock()
    mock_pool.getconn.return_value = mock_conn
    return mock_pool, mock_conn, mock_cursor


@patch("job_pulse.storage.postgres_repo.psycopg2.pool.ThreadedConnectionPool")
def test_postgres_repository_conforms_to_interface(mock_pool_cls):
    mock_pool, mock_conn, mock_cursor = _make_mock_pool()
    mock_pool_cls.return_value = mock_pool

    from job_pulse.storage.postgres_repo import PostgresJobRepository
    repo = PostgresJobRepository(database_url="postgresql://user:pass@localhost:5432/test")

    assert isinstance(repo, JobRepository)
    # _init_db should have created tables and checked/created the admin user
    assert mock_cursor.execute.call_count > 10


@patch("job_pulse.storage.postgres_repo.psycopg2.pool.ThreadedConnectionPool")
def test_get_conn_commits_on_success_and_returns_connection(mock_pool_cls):
    mock_pool, mock_conn, mock_cursor = _make_mock_pool()
    mock_pool_cls.return_value = mock_pool

    from job_pulse.storage.postgres_repo import PostgresJobRepository
    repo = PostgresJobRepository(database_url="postgresql://user:pass@localhost:5432/test")

    mock_conn.commit.reset_mock()
    mock_pool.putconn.reset_mock()

    with repo._get_conn() as conn:
        conn.cursor().execute("SELECT 1")

    mock_conn.commit.assert_called_once()
    mock_pool.putconn.assert_called_once_with(mock_conn)


@patch("job_pulse.storage.postgres_repo.psycopg2.pool.ThreadedConnectionPool")
def test_get_conn_rolls_back_on_non_transient_error(mock_pool_cls):
    mock_pool, mock_conn, mock_cursor = _make_mock_pool()
    mock_pool_cls.return_value = mock_pool

    from job_pulse.storage.postgres_repo import PostgresJobRepository
    repo = PostgresJobRepository(database_url="postgresql://user:pass@localhost:5432/test")

    mock_conn.rollback.reset_mock()
    mock_conn.commit.reset_mock()

    with pytest.raises(ValueError):
        with repo._get_conn() as conn:
            raise ValueError("simulated application error")

    mock_conn.rollback.assert_called_once()
    mock_conn.commit.assert_not_called()


@patch("job_pulse.storage.postgres_repo.psycopg2.pool.ThreadedConnectionPool")
def test_toggle_favorite_and_delete_job_return_bool_from_rowcount(mock_pool_cls):
    mock_pool, mock_conn, mock_cursor = _make_mock_pool()
    mock_pool_cls.return_value = mock_pool

    from job_pulse.storage.postgres_repo import PostgresJobRepository
    repo = PostgresJobRepository(database_url="postgresql://user:pass@localhost:5432/test")

    mock_cursor.rowcount = 1
    assert repo.toggle_favorite("job123") is True

    mock_cursor.rowcount = 0
    assert repo.delete_job("job123") is False


def test_postgres_repository_requires_database_url():
    from job_pulse.storage.postgres_repo import PostgresJobRepository
    with pytest.raises(ValueError):
        PostgresJobRepository(database_url="")
