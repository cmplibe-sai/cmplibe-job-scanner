from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
import hashlib
import re
from job_pulse.utils.time_utils import get_ist_iso


class WorkMode(str, Enum):
    REMOTE = "Remote"
    HYBRID = "Hybrid"
    ONSITE = "On-site"
    UNKNOWN = "Not Specified"


class RoleType(str, Enum):
    TECHNICAL = "Technical"
    NON_TECHNICAL = "Non-Technical"


class PortalType(str, Enum):
    LINKEDIN = "linkedin"
    LINKEDIN_POSTS = "linkedin_posts"
    INTERNSHALA = "internshala"
    UNSTOP = "unstop"
    NAUKRI = "naukri"
    FOUNDIT = "foundit"
    SHINE = "shine"
    INDEED = "indeed"
    CAREER_PAGE = "career_page"


def generate_job_id(source: str, company: str, title: str, location: str = "") -> str:
    """Generate a deterministic hash ID for deduplication."""
    norm_comp = re.sub(r"[^\w\s]", "", (company or "").lower()).strip()
    norm_title = re.sub(r"[^\w\s]", "", (title or "").lower()).strip()
    norm_loc = re.sub(r"[^\w\s]", "", (location or "").lower()).strip()
    raw = f"{source}:{norm_comp}:{norm_title}:{norm_loc}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


TECH_KEYWORDS = {
    "developer", "engineer", "software", "frontend", "front end", "backend", "back end",
    "fullstack", "full stack", "python", "java", "golang", "c++", "react", "node", "devops",
    "sre", "cloud", "data engineer", "data scientist", "machine learning", "ai", "nlp",
    "llm", "deep learning", "qa", "tester", "sdet", "android", "ios", "flutter", "database",
    "architect", "sysadmin", "cybersecurity", "security analyst", "data analyst", "decision science",
    "etl", "sql developer", "programmer", "linux", "aws", "azure", "gcp", "docker", "kubernetes"
}

NON_TECH_KEYWORDS = {
    "recruiter", "talent acquisition", "hr", "human resource", "sales", "business development",
    "bde", "bdm", "account manager", "category manager", "operations", "finance", "accountant",
    "marketing", "seo", "content writer", "copywriter", "customer service", "customer support",
    "customer success", "trainer", "retail", "supply chain", "logistics", "procurement", "admin",
    "legal", "compliance", "telecaller", "telesales", "executive assistant", "cashier"
}


def classify_role_type(title: str, skills: List[str] = None) -> RoleType:
    """Automatically classify a job role as Technical or Non-Technical."""
    text = (title or "").lower()
    
    # Check explicit non-technical signals first
    if any(re.search(rf"\b{re.escape(k)}\b", text) for k in NON_TECH_KEYWORDS):
        return RoleType.NON_TECHNICAL
        
    # Check technical signals
    if any(re.search(rf"\b{re.escape(k)}\b", text) for k in TECH_KEYWORDS):
        return RoleType.TECHNICAL
        
    if skills:
        skills_text = " ".join(skills).lower()
        if any(re.search(rf"\b{re.escape(k)}\b", skills_text) for k in TECH_KEYWORDS):
            return RoleType.TECHNICAL
            
def is_valid_job_listing(title: str, url: str = "", company: str = "", target_company: str = "") -> bool:
    """
    Universal, ultra-strict gatekeeper to ensure an item is a genuine, actionable employment opening.
    Rejects:
    1. Navigation links, CTA buttons, and informational articles:
       - 'Learn more about...', 'Find out more', 'More about Life at...', 'How to apply',
         'Join us', 'Explore teams', 'About our hiring process', etc.
    2. Single-word broad departments or category landing pages:
       - 'Product', 'Design', 'Technology', 'Customer', 'Marketing', 'Sales', 'Engineering',
         'Finance', 'Legal', 'Operations', 'Data', 'People', 'Culture', 'Life', 'Teams', etc.
    3. Corporate tools, calculators, marketing promos, and retail services:
       - 'GST Calculator', 'Personal Loan', 'Recharge', 'Bill Payment', 'Flight Ticket', etc.
    4. Overview URLs or non-job endpoints:
       - URLs pointing to /teams/, /life/, /culture/, /benefits/, /about/, /diversity/, etc.
    5. Company mismatches:
       - E.g. 'Greater Than Equal To Technologies' when target is 'REA India'.
    6. Empty or invalid titles (< 4 chars or > 90 chars).
    """
    if not title or len(title.strip()) < 4 or len(title.strip()) > 90:
        return False

    t_clean = title.strip()
    t_low = t_clean.lower()

    # Rule 1: Action phrases, sentences, department overviews
    invalid_prefixes = (
        "learn more", "find out", "more about", "read more", "work at", "join our",
        "join us", "explore", "life at", "about us", "contact us", "why work",
        "our values", "our culture", "our team", "meet our", "view all", "see all",
        "discover", "what we do", "who we are", "how we work", "working at", "working in",
        "about our", "how to apply", "our hiring", "search jobs", "all openings",
        "browse jobs", "back to", "click here", "read the", "get in touch"
    )
    if any(t_low.startswith(p) for p in invalid_prefixes) or "learn more about" in t_low or "more about life" in t_low:
        return False

    # Rule 2: Single-word broad departments / categories without role designation
    single_word_departments = {
        "marketing", "technology", "product", "design", "customer", "engineering",
        "sales", "finance", "legal", "operations", "people", "culture", "life",
        "teams", "leadership", "careers", "jobs", "openings", "opportunities",
        "business", "strategy", "data", "it", "corporate", "commercial", "digital",
        "services", "solutions", "delivery", "logistics", "supply chain", "work",
        "workplace", "global", "management", "administration", "human resources",
        "about", "team", "overview", "hiring", "open roles", "current openings",
        "students", "graduates", "university", "experienced", "early careers"
    }
    if t_low in single_word_departments:
        return False

    # Rule 3: Known website pages, calculators, tools, lenders, retail terms
    forbidden_exact = {
        "home", "about", "about us", "who we are", "our story", "newsroom", "news room", "news",
        "blog", "blogs", "calculator", "calculators", "gst calculator", "emi calculator", "sip calculator",
        "fd calculator", "rd calculator", "tds calculator", "tax calculator", "income tax calculator",
        "current", "(current)", "privacy", "privacy policy", "terms", "terms of use", "terms & conditions",
        "terms and conditions", "cookie", "cookies", "cookie policy", "pricing", "plans", "pricing plans",
        "login", "sign in", "signup", "sign up", "register", "download", "download app", "press", "media",
        "investors", "investor relations", "faq", "faqs", "help", "help center", "support", "customer support",
        "features", "solutions", "products", "services", "resources", "community", "partners", "sitemap",
        "case studies", "overview", "leadership", "security", "legal", "compliance", "merchants", "customers",
        "user guide", "tutorials", "documentation", "api", "api docs", "feedback", "explore", "learn more",
        "read more", "view all", "view more", "all rights reserved", "copyright", "navigation", "menu",
        "header", "footer", "get started", "book a demo", "request demo", "contact", "contact us",
        "mobile recharge", "electricity bill", "dth recharge", "loan emi", "credit card", "flight tickets"
    }
    if t_low in forbidden_exact:
        return False

    # Rule 4: Regex check for company entities, lenders, and retail services
    invalid_patterns = [
        r"\blimited\b", r"\bpvt\s*ltd\b", r"\bprivate\s*limited\b", r"\bllc\b", r"\binc\.?\b",
        r"\bcorp\.?\b", r"\bcorporation\b", r"\blender\b", r"\brecharge\b", r"\bbill\s*payment\b",
        r"\bticket\b", r"\btickets\b", r"\bdownload\s*app\b", r"\bsign\s*in\b", r"\bsign\s*up\b",
        r"\bsend\s*money\b", r"\bpersonal\s*loan\b", r"\bcalculator\b", r"\bprivacy\s*policy\b",
        r"\bterms\s*(?:of|&|and)\b", r"\ball\s*rights\s*reserved\b", r"\bmore\s*about\b",
        r"\blearn\s*more\b", r"\bfind\s*out\b", r"\bworking\s*in\b"
    ]
    if any(re.search(pat, t_low) for pat in invalid_patterns):
        return False

    # Rule 5: URL validation
    if url:
        url_clean = url.strip().lower()
        if not url_clean or url_clean in ["#", "", "javascript:void(0)"] or url_clean.startswith("javascript:"):
            return False

        forbidden_url_paths = [
            "loan-emi", "recharge", "bill-payment", "electricity", "water-bill", "gas-bill",
            "challan", "tickets", "flight", "bus", "train", "hotel", "movie", "credit-card",
            "loans-credit-cards", "personal-loan", "credit-score", "money-transfer",
            "online-payments", "instore-payments", "merchant", "offers", "shop", "store",
            "cart", "checkout", "payment", "login", "signin", "signup", "download",
            "privacy", "terms", "policy", "faq", "help", "newsroom", "blog", "calculator",
            "/teams/", "/team/", "/life/", "/culture/", "/benefits/", "/locations/",
            "/diversity/", "/values/", "/people/", "/about-us/", "/about/"
        ]
        if any(term in url_clean for term in forbidden_url_paths):
            return False

        # Disallow plain root domain URLs as job links (e.g. https://company.com/)
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        if not path and not parsed.query and not any(ats in parsed.netloc for ats in ["lever.co", "greenhouse.io", "ashbyhq.com"]):
            return False

    # Rule 6: Target company matching if specified
    if target_company and company:
        from job_pulse.radar.scanner import CompanyRadarScanner
        if not CompanyRadarScanner.is_company_match(company, target_company):
            return False

    # Rule 7: Positive role designation verification
    role_designations = [
        "engineer", "developer", "manager", "lead", "executive", "intern", "internship",
        "analyst", "associate", "specialist", "recruiter", "representative", "head",
        "director", "officer", "designer", "architect", "consultant", "coordinator",
        "administrator", "assistant", "technician", "writer", "advisor", "trainee",
        "apprentice", "fellow", "scientist", "operator", "telecaller", "staff",
        "fresher", "sales", "hr", "accountant", "auditor", "qa", "sdet", "devops",
        "frontend", "backend", "fullstack", "data", "operations",
        "business development", "bdm", "bde", "founder", "vp", "avp", "gm",
        "category manager", "account manager", "growth manager", "copywriter", "underwriter",
        "customer success", "support executive", "sales executive", "talent acquisition"
    ]
    return any(re.search(rf"\b{re.escape(sig)}\b", t_low) for sig in role_designations)


import ast
import json


def clean_location_string(raw: Any) -> str:
    """
    Sanitize location into a clean, human-readable city/state/region string.
    Handles:
    - Python dictionaries: {'city': 'Mumbai', 'state': 'Maharashtra', 'country': 'India'} -> 'Mumbai, Maharashtra'
    - Stringified dicts: "{'id': 1822505, 'city': 'Mumbai', 'state': 'Maharashtra' ...}" -> 'Mumbai, Maharashtra'
    - JSON strings: '{"city": "Bangalore"}' -> 'Bangalore'
    - Lists of locations: [{'city': 'Noida'}, {'city': 'Delhi'}] -> 'Noida, Delhi'
    - Redundant noise / repeated tokens: 'Bengaluru, Karn, India, India' -> 'Bengaluru, Karnataka'
    - Enum / code remnants: 'WorkMode.UNKNOWN', 'None', 'null', 'not specified' -> 'Not Specified'
    """
    if raw is None:
        return "Not Specified"

    if isinstance(raw, dict):
        city = str(raw.get("city") or raw.get("name") or raw.get("addressLocality") or "").strip()
        state = str(raw.get("state") or raw.get("addressRegion") or "").strip()
        country = str(raw.get("country") or raw.get("addressCountry") or "").strip()
        parts = [p for p in [city, state] if p and p.lower() not in ["none", "null", "nan", "not specified", "unknown"]]
        if not parts and country and country.lower() not in ["none", "null", "nan", "not specified"]:
            parts.append(country)
        return ", ".join(parts) if parts else "Not Specified"

    if isinstance(raw, list):
        cleaned_items = [clean_location_string(i) for i in raw if i]
        valid_items = [i for i in cleaned_items if i and i.lower() not in ["not specified", "as announced", "none", "null", "unknown"]]
        return ", ".join(dict.fromkeys(valid_items)) if valid_items else "Not Specified"

    s = str(raw).strip()
    if not s or s.lower() in ["none", "null", "unknown", "not specified", "n/a", "workmode.unknown", "nan", ""]:
        return "Not Specified"

    # If it's a stringified dict or json: e.g. "{'id': 1822505, 'city': 'Mumbai', ...}"
    if s.startswith("{") and ("city" in s or "state" in s or "country" in s or "name" in s):
        try:
            parsed = ast.literal_eval(s)
            if isinstance(parsed, (dict, list)):
                return clean_location_string(parsed)
        except Exception:
            pass
        try:
            parsed = json.loads(s)
            if isinstance(parsed, (dict, list)):
                return clean_location_string(parsed)
        except Exception:
            pass
        # Fallback regex extraction
        city_m = re.search(r"['\"]city['\"]\s*:\s*['\"]([^'\"]+)['\"]", s)
        state_m = re.search(r"['\"]state['\"]\s*:\s*['\"]([^'\"]+)['\"]", s)
        parts = []
        if city_m:
            parts.append(city_m.group(1).strip())
        if state_m:
            parts.append(state_m.group(1).strip())
        if parts:
            return ", ".join(parts)

    # Clean state abbreviations and common truncated words
    s = re.sub(r"\bKarn\b", "Karnataka", s, flags=re.IGNORECASE)
    s = re.sub(r"\bMahar\b", "Maharashtra", s, flags=re.IGNORECASE)
    s = re.sub(r"\bTelang\b", "Telangana", s, flags=re.IGNORECASE)
    s = re.sub(r"\bTamiln\b", "Tamil Nadu", s, flags=re.IGNORECASE)

    # Remove duplicated tokens while preserving order
    tokens = [t.strip() for t in s.split(",") if t.strip()]
    cleaned_tokens = list(dict.fromkeys(tokens))
    return ", ".join(cleaned_tokens) if cleaned_tokens else "Not Specified"


class JobPost(BaseModel):
    id: str = Field(default="")
    title: str
    company: str
    location: str = "Not Specified"
    work_mode: WorkMode = WorkMode.UNKNOWN
    role_type: RoleType = RoleType.NON_TECHNICAL
    is_internship: bool = False
    category: Optional[str] = "General"
    experience_min: Optional[float] = None
    experience_max: Optional[float] = None
    experience_text: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = "INR"
    salary_text: Optional[str] = None
    skills: List[str] = Field(default_factory=list)
    description: str = ""
    url: str
    source_portal: str
    posted_date: Optional[str] = "Recently Posted"
    scraped_at: str = Field(default_factory=get_ist_iso)
    raw_data: Optional[Dict[str, Any]] = None

    def model_post_init(self, __context: Any) -> None:
        # Sanitize location
        self.location = clean_location_string(self.location)

        if not self.id:
            self.id = generate_job_id(
                self.source_portal, self.company, self.title, self.location
            )
        # Classify Technical vs Non-Technical
        self.role_type = classify_role_type(self.title, self.skills)
        
        # Auto detect internship / fresher signals
        check_str = f"{self.title} {self.experience_text or ''} {self.description or ''[:200]}".lower()
        if any(term in check_str for term in ["intern", "internship", "trainee", "fresher", "apprentice", "graduate engineer trainee", "campus"]):
            self.is_internship = True

        # Extract numeric experience if not already set
        if self.experience_min is None or self.experience_max is None:
            text_to_search = f"{self.experience_text or ''} {self.title} {self.description or ''[:300]}"
            # Match patterns like "3-5 Yrs", "2 to 6 years", "0-1 yr"
            m_range = re.search(r"(\d+)\s*(?:-|to)\s*(\d+)\s*(?:yrs?|years?|yoe)", text_to_search, re.IGNORECASE)
            if m_range:
                self.experience_min = float(m_range.group(1))
                self.experience_max = float(m_range.group(2))
                if not self.experience_text:
                    self.experience_text = f"{m_range.group(1)}-{m_range.group(2)} Yrs"
            else:
                m_plus = re.search(r"(\d+)\+\s*(?:yrs?|years?|yoe)", text_to_search, re.IGNORECASE)
                if m_plus:
                    self.experience_min = float(m_plus.group(1))
                    if not self.experience_text:
                        self.experience_text = f"{m_plus.group(1)}+ Yrs"


class HiringPost(BaseModel):
    """Represents a job requirement posted by HR, recruiter or hiring manager in LinkedIn feed."""
    id: str = Field(default="")
    poster_name: str = "Recruiter / Hiring Manager"
    poster_title: Optional[str] = None
    poster_profile_url: Optional[str] = None
    company: str = "Company"
    role_title: str = "Hiring Opportunity"
    role_type: RoleType = RoleType.NON_TECHNICAL
    location: str = "Not Specified"
    post_text: str = ""
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    post_url: str
    posted_date: Optional[str] = "Recently Posted"
    scraped_at: str = Field(default_factory=get_ist_iso)

    def model_post_init(self, __context: Any) -> None:
        self.location = clean_location_string(self.location)
        if not self.id:
            raw = f"post:{self.poster_name}:{self.role_title}:{self.post_url}"
            self.id = hashlib.md5(raw.encode("utf-8")).hexdigest()
        self.role_type = classify_role_type(self.role_title)
        if not self.contact_email and self.post_text:
            m = re.search(r"[\w\.\-]+@[\w\.\-]+\.[a-zA-Z]{2,}", self.post_text)
            if m:
                self.contact_email = m.group(0)
        if not self.contact_phone and self.post_text:
            m_phone = re.search(r"(?:\+91[\-\s]?)?[6-9]\d{9}", self.post_text)
            if m_phone:
                self.contact_phone = m_phone.group(0)


class SearchQuery(BaseModel):
    keywords: str = ""
    location: str = ""
    company_name: Optional[str] = None
    search_type: str = "role"  # 'role' or 'company'
    role_type: Optional[str] = "all"  # 'all', 'technical', 'non_technical'
    experience_level: Optional[str] = None  # 'internship', '0-2', '3-5', '6-10', '10+'
    category: Optional[str] = "all"
    remote_only: bool = False
    internship_only: bool = False
    include_linkedin_posts: bool = True
    limit: int = 50
    portals: List[str] = Field(
        default_factory=lambda: ["linkedin", "internshala", "unstop", "shine", "naukri", "foundit", "indeed", "linkedin_posts"]
    )
    career_urls: List[str] = Field(default_factory=list)


class ScrapeResult(BaseModel):
    portal: str
    success: bool
    total_found: int
    jobs: List[JobPost] = Field(default_factory=list)
    hiring_posts: List[HiringPost] = Field(default_factory=list)
    error_message: Optional[str] = None
    execution_time_seconds: float = 0.0


class CompanyTarget(BaseModel):
    """Target company watched by the Radar for new jobs, posts and social updates."""
    id: str = Field(default="")
    company_name: str
    career_url: Optional[str] = ""
    keywords: Optional[str] = ""
    channels: List[str] = Field(
        default_factory=lambda: ["ats", "linkedin", "internshala", "unstop", "shine", "social_posts"]
    )
    is_active: bool = True
    last_scanned_at: Optional[str] = None
    last_found_count: int = 0
    created_at: str = Field(default_factory=get_ist_iso)

    def model_post_init(self, __context: Any) -> None:
        if not self.id:
            raw = f"target:{self.company_name.strip().lower()}"
            self.id = hashlib.md5(raw.encode("utf-8")).hexdigest()


class RadarAlertLog(BaseModel):
    """Log record of opportunities/posts emailed to prevent duplicates."""
    id: str = Field(default="")
    company_id: str
    item_type: str = "job"  # 'job' or 'post'
    item_id: str
    title: str
    company: str
    url: str
    source: str
    experience_text: Optional[str] = None
    location: Optional[str] = None
    emailed_at: str = Field(default_factory=get_ist_iso)
    recipient_email: str = ""

    def model_post_init(self, __context: Any) -> None:
        if not self.id:
            raw = f"alert:{self.item_id}:{self.recipient_email}"
            self.id = hashlib.md5(raw.encode("utf-8")).hexdigest()


class DiscoveryAlertLog(BaseModel):
    """Log record of broad All-India discovery opportunities emailed to prevent duplicates."""
    id: str = Field(default="")
    item_type: str = "job"  # 'job' or 'post'
    item_id: str
    title: str
    company: str
    url: str
    source: str
    role_type: Optional[str] = "Non-Technical"
    experience_text: Optional[str] = None
    location: Optional[str] = None
    emailed_at: str = Field(default_factory=get_ist_iso)
    recipient_email: str = ""

    def model_post_init(self, __context: Any) -> None:
        if not self.id:
            raw = f"discovery_alert:{self.item_id}:{self.recipient_email}"
            self.id = hashlib.md5(raw.encode("utf-8")).hexdigest()


class EmailConfig(BaseModel):
    """Configuration for SMTP email notifications, Target Radar, and All-India Discovery Radar."""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    sender_email: str = ""
    # Radar 1: Target Company Watchlist Alert settings
    recipient_email: str = ""  # Target Company Radar recipient
    is_enabled: bool = False
    check_interval_minutes: int = 60

    # Radar 2: All-India Multi-Portal Discovery Alert settings
    all_india_recipient: str = ""  # Dedicated recipient for all-India discovery alerts
    all_india_is_enabled: bool = False
    all_india_interval_minutes: int = 120
    all_india_keywords: str = "developer, engineer, manager, recruiter, analyst, intern, fresher, executive, operations, sales"
    all_india_locations: str = "India, Bangalore, Mumbai, Delhi, Gurgaon, Noida, Hyderabad, Pune, Chennai, Remote"
    all_india_role_types: str = "all"  # 'all', 'technical', 'non_technical'


class GoogleSheetsConfig(BaseModel):
    """Configuration for Live Google Sheets synchronization."""
    is_enabled: bool = False
    auth_mode: str = "service_account"  # 'service_account' or 'webhook'
    credentials_json: str = ""  # File path to service_account.json OR pasted JSON content
    spreadsheet_id_or_url: str = ""  # Spreadsheet ID or full Google Sheet URL
    sheet_name_all_india: str = "All-India Jobs"
    sheet_name_target_radar: str = "Target Company Radar"
    sheet_name_hiring_posts: str = "Recruiter Posts"
    auto_sync_on_scrape: bool = True
    last_synced_at: Optional[str] = None
    last_synced_count: int = 0


