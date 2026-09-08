import re
from typing import List, Optional, Tuple

# Phrases that read as a company name but aren't one - reject exact matches after cleaning.
NOISE_PHRASES = {
    "other players", "other player", "others", "various", "various players",
    "several startups", "several players", "many more", "and more", "and others",
    "similar companies", "similar players", "competitors", "rivals", "peers",
    "tbd", "n/a", "na", "none", "unknown", "not disclosed", "not applicable",
    "regional players", "local players", "industry peers", "many others",
    "other startups", "other companies", "etc", "etc.",
}

# Leading words that mark a fragment as a vague reference rather than a real name
# (e.g. "other food-delivery players", "various fintech startups").
NOISE_PREFIXES = ("other ", "various ", "several ", "many ", "some ", "few ", "all ", "top ")

_BULLET_PREFIX = re.compile(r"^\s*(?:[-*•]|\d+[\.\)])\s*")
_BRACKETED = re.compile(r"[\(\[\{][^\)\]\}]*[\)\]\}]")
_AND_AMP_SPLIT = re.compile(r"\s+and\s+|\s*&\s+", re.IGNORECASE)


def clean_company_name(raw: str) -> Optional[str]:
    """
    Validate and clean a single extracted company-name candidate.
    Returns the cleaned display name, or None if it's noise / not a plausible company name.
    """
    if not raw:
        return None

    s = raw.strip()
    s = _BULLET_PREFIX.sub("", s)
    s = _BRACKETED.sub("", s).strip()  # drop "(food delivery)"-style parentheticals
    s = s.strip(" \"'.-–—")

    if not s:
        return None

    s_low = s.lower()
    if s_low in NOISE_PHRASES:
        return None
    if any(s_low.startswith(p) for p in NOISE_PREFIXES):
        return None
    if len(s) < 2 or len(s) > 60:
        return None
    if not re.search(r"[A-Za-z]", s):
        # Reject fragments with no letters at all (stray punctuation/numbers)
        return None

    return s


def split_competitor_text(raw: str) -> List[str]:
    """
    Split a free-text competitor cell (comma/semicolon/newline/pipe separated, sometimes
    joined with "and"/"&") into individual candidate name strings. Does not validate or
    clean the candidates - call clean_company_name() on each result.
    """
    if not raw:
        return []

    text = raw.replace("\n", ",").replace("|", ",").replace(";", ",")
    parts = [p.strip() for p in text.split(",") if p.strip()]
    # Strip a leftover Oxford-comma connector, e.g. "Blinkit, Swiggy, and Zepto"
    # splits to ["Blinkit", "Swiggy", "and Zepto"] - drop the leading "and"/"or".
    parts = [re.sub(r"^(?:and|or)\s+", "", p, flags=re.IGNORECASE).strip() for p in parts]
    parts = [p for p in parts if p]

    # Expand any remaining "X and Y" / "X & Y" fragments that weren't comma-separated.
    # This can occasionally over-split a legitimate "&"-in-name company (e.g. "Tata & Sons"),
    # which is an accepted tradeoff for correctly splitting "Zomato and Swiggy" style lists.
    expanded: List[str] = []
    for part in parts:
        subparts = _AND_AMP_SPLIT.split(part)
        expanded.extend(sp.strip() for sp in subparts if sp.strip())

    return expanded


def extract_companies_from_story_row(
    row: List[str],
    main_company_col: int = 8,
    competitors_col: int = 9,
) -> Tuple[Optional[str], List[str]]:
    """
    Extract and clean the main company (Column I, index 8) and competitor list
    (Column J, index 9) from a single row of the "cMPLi Dip Stories" sheet.

    Returns (main_company, competitors). main_company is None if the row has no
    usable company name (caller should skip the row). Competitors are de-duplicated
    against each other and against the main company using the same normalization
    CompanyRadarScanner.is_company_match() relies on, so "Byju's" and "BYJU'S
    Learning Pvt Ltd" in the same cell collapse to one entry.
    """
    if len(row) <= main_company_col:
        return None, []

    main_raw = row[main_company_col] if main_company_col < len(row) else ""
    main_company = clean_company_name(main_raw)
    if not main_company:
        return None, []

    competitors_raw = row[competitors_col] if competitors_col < len(row) else ""
    candidates = split_competitor_text(competitors_raw)

    # Local import: story_ingestion is a one-way dependency on scanner.py (scanner.py
    # does not import this module), so this avoids any risk of a circular import at
    # module load time while keeping the dedup logic identical to the live radar matcher.
    from job_pulse.radar.scanner import CompanyRadarScanner

    competitors: List[str] = []
    for cand in candidates:
        cleaned = clean_company_name(cand)
        if not cleaned:
            continue
        if CompanyRadarScanner.is_company_match(cleaned, main_company):
            continue  # e.g. "BYJU'S Learning Pvt Ltd" collapses into main company "Byju's"
        if any(CompanyRadarScanner.is_company_match(cleaned, existing) for existing in competitors):
            continue  # duplicate within the competitor list itself
        competitors.append(cleaned)

    return main_company, competitors
