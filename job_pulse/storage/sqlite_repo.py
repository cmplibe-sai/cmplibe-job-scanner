from job_pulse.storage.base import JobRepository
from job_pulse.storage.db import JobDatabase


class SQLiteJobRepository(JobDatabase, JobRepository):
    """
    SQLite-backed JobRepository - local development and test fallback.

    Deliberately a thin subclass rather than a re-implementation: JobDatabase already
    implements every method JobRepository declares (same names, same signatures), so
    Python's MRO resolves all of them to JobDatabase's existing, tested logic. This
    avoids duplicating ~35 methods and any risk of behavior drift between "the real
    SQLite logic" and "the SQLite implementation of the interface" - there's only one.
    """
    pass
