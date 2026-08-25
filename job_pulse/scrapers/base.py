from abc import ABC, abstractmethod
import re
import time
import logging
from typing import Optional, List, Tuple
from job_pulse.models import JobPost, SearchQuery, ScrapeResult, WorkMode
from job_pulse.network.client import StealthClient

logger = logging.getLogger("job_pulse.scraper")


class BaseScraper(ABC):
    """Abstract Base Class for all portal scrapers."""

    def __init__(self, client: Optional[StealthClient] = None):
        self.client = client or StealthClient()
        self.portal_name: str = "base"

    @abstractmethod
    def search(self, query: SearchQuery) -> ScrapeResult:
        """Execute job search and return ScrapeResult."""
        pass

    def detect_work_mode(self, text: str) -> WorkMode:
        """Infer work mode (Remote, Hybrid, Onsite) from text."""
        lowered = text.lower()
        if any(term in lowered for term in ["remote", "work from home", "wfh", "anywhere"]):
            return WorkMode.REMOTE
        elif any(term in lowered for term in ["hybrid", "flexible work"]):
            return WorkMode.HYBRID
        elif any(term in lowered for term in ["on-site", "onsite", "in-office", "office only"]):
            return WorkMode.ONSITE
        return WorkMode.UNKNOWN

    def parse_experience(self, text: str) -> Tuple[Optional[float], Optional[float], Optional[str]]:
        """Parse experience range from strings like '3-5 Yrs', '2+ years', '0 - 1 years'."""
        if not text:
            return None, None, None
        text_clean = text.strip()
        # Match 'X - Y yrs' or 'X-Y years'
        range_match = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", text_clean)
        if range_match:
            try:
                return float(range_match.group(1)), float(range_match.group(2)), text_clean
            except ValueError:
                pass
        # Match 'X+ yrs'
        plus_match = re.search(r"(\d+(?:\.\d+)?)\s*\+\s*(?:yrs|years|year)?", text_clean, re.IGNORECASE)
        if plus_match:
            try:
                return float(plus_match.group(1)), None, text_clean
            except ValueError:
                pass
        return None, None, text_clean

    def parse_salary(self, text: str) -> Tuple[Optional[float], Optional[float], Optional[str], Optional[str]]:
        """Parse salary range and currency from string."""
        if not text or any(k in text.lower() for k in ["not disclosed", "confidential", "best in industry"]):
            return None, None, None, text
        
        currency = "INR" if any(c in text for c in ["₹", "INR", "Lacs", "PA", "LPA", "Cr"]) else "USD" if "$" in text else "EUR" if "€" in text else "GBP" if "£" in text else None
        
        # Check LPA (e.g. 5-10 LPA, 15 - 25 Lacs PA)
        lpa_match = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*(?:lpa|lac|lakh)", text, re.IGNORECASE)
        if lpa_match:
            try:
                min_val = float(lpa_match.group(1)) * 100000
                max_val = float(lpa_match.group(2)) * 100000
                return min_val, max_val, "INR", text.strip()
            except ValueError:
                pass

        # Generic numbers range
        range_match = re.search(r"(\d[\d,.]*)\s*-\s*(\d[\d,.]*)", text)
        if range_match:
            try:
                min_s = range_match.group(1).replace(",", "")
                max_s = range_match.group(2).replace(",", "")
                return float(min_s), float(max_s), currency, text.strip()
            except ValueError:
                pass

        return None, None, currency, text.strip() if text else None
