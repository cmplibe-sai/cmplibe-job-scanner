from .base import BaseScraper
from .linkedin import LinkedInScraper
from .linkedin_posts import LinkedInPostsScraper
from .internshala import InternshalaScraper
from .unstop import UnstopScraper
from .naukri import NaukriScraper
from .foundit import FounditScraper
from .shine import ShineScraper
from .indeed import IndeedScraper
from .career_pages import CareerPageScraper

SCRAPER_MAP = {
    "linkedin": LinkedInScraper,
    "linkedin_posts": LinkedInPostsScraper,
    "internshala": InternshalaScraper,
    "unstop": UnstopScraper,
    "shine": ShineScraper,
    "naukri": NaukriScraper,
    "foundit": FounditScraper,
    "indeed": IndeedScraper,
    "career_page": CareerPageScraper,
}

__all__ = [
    "BaseScraper",
    "LinkedInScraper",
    "LinkedInPostsScraper",
    "InternshalaScraper",
    "UnstopScraper",
    "NaukriScraper",
    "FounditScraper",
    "ShineScraper",
    "IndeedScraper",
    "CareerPageScraper",
    "SCRAPER_MAP",
]
