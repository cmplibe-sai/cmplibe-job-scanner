import re
import hashlib
from typing import List, Dict, Tuple
from job_pulse.models import JobPost


class JobDeduplicator:
    """Detects and groups duplicate job posts across multiple portals."""

    @staticmethod
    def normalize_company(company: str) -> str:
        if not company:
            return ""
        c = company.lower()
        # Remove common corporate suffixes
        c = re.sub(r"\b(pvt\.?|ltd\.?|llc\.?|inc\.?|corp\.?|corporation|technologies|solutions|services|systems|group)\b", "", c)
        c = re.sub(r"[^\w\s]", "", c)
        return " ".join(c.split())

    @staticmethod
    def normalize_title(title: str) -> str:
        if not title:
            return ""
        t = title.lower()
        # Clean special chars and brackets
        t = re.sub(r"[\(\[\{].*?[\)\]\}]", "", t)
        t = re.sub(r"[^\w\s]", " ", t)
        return " ".join(t.split())

    @classmethod
    def get_cluster_hash(cls, job: JobPost) -> str:
        """Compute a cluster hash for matching identical jobs across platforms."""
        n_comp = cls.normalize_company(job.company)
        n_title = cls.normalize_title(job.title)
        key = f"{n_comp}:::{n_title}"
        return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]

    @classmethod
    def process_and_deduplicate(cls, jobs: List[JobPost]) -> Tuple[List[JobPost], Dict[str, List[JobPost]]]:
        """
        Groups jobs by cluster hash and returns unique primary jobs + cluster map.
        """
        clusters: Dict[str, List[JobPost]] = {}
        for job in jobs:
            c_hash = cls.get_cluster_hash(job)
            if c_hash not in clusters:
                clusters[c_hash] = []
            clusters[c_hash].append(job)

        unique_jobs: List[JobPost] = []
        for c_hash, cluster_jobs in clusters.items():
            # Pick the job with most details (e.g. description or salary) as primary
            primary = max(cluster_jobs, key=lambda j: len(j.description) + (50 if j.salary_text else 0) + (30 if j.skills else 0))
            unique_jobs.append(primary)

        return unique_jobs, clusters
