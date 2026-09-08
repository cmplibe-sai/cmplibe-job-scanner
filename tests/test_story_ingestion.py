from job_pulse.radar.story_ingestion import (
    clean_company_name,
    split_competitor_text,
    extract_companies_from_story_row,
)
from job_pulse.radar.scanner import CompanyRadarScanner


def test_clean_company_name_rejects_noise():
    assert clean_company_name("other food-delivery players") is None
    assert clean_company_name("Various fintech startups") is None
    assert clean_company_name("TBD") is None
    assert clean_company_name("N/A") is None
    assert clean_company_name("") is None
    assert clean_company_name("   ") is None
    assert clean_company_name("---") is None  # no letters


def test_clean_company_name_strips_noise_around_valid_names():
    assert clean_company_name("- Zomato") == "Zomato"
    assert clean_company_name("1. Swiggy") == "Swiggy"
    assert clean_company_name("Zomato (food delivery)") == "Zomato"
    assert clean_company_name('"Byju\'s"') == "Byju's"


def test_split_competitor_text_handles_delimiters():
    assert split_competitor_text("Zomato, Swiggy, Dunzo") == ["Zomato", "Swiggy", "Dunzo"]
    assert split_competitor_text("Zomato; Swiggy| Dunzo") == ["Zomato", "Swiggy", "Dunzo"]
    assert split_competitor_text("Zomato and Swiggy") == ["Zomato", "Swiggy"]
    assert split_competitor_text("Zomato & Swiggy") == ["Zomato", "Swiggy"]
    assert split_competitor_text("") == []


def test_extract_companies_from_story_row_end_to_end():
    row = [""] * 8 + [
        "Zepto",
        "Blinkit, Swiggy Instamart, and other quick-commerce players",
    ]
    main, competitors = extract_companies_from_story_row(row)
    assert main == "Zepto"
    assert competitors == ["Blinkit", "Swiggy Instamart"]


def test_extract_companies_dedupes_against_main_and_within_list():
    row = [""] * 8 + [
        "Byju's",
        "BYJU'S Learning Pvt Ltd, Toppr, Toppr, Unacademy",
    ]
    main, competitors = extract_companies_from_story_row(row)
    assert main == "Byju's"
    # BYJU'S Learning Pvt Ltd collapses into the main company and is dropped;
    # duplicate "Toppr" entries collapse to one.
    assert competitors == ["Toppr", "Unacademy"]


def test_extract_companies_from_story_row_skips_rows_without_main_company():
    row = [""] * 8 + ["", "Some Competitor"]
    main, competitors = extract_companies_from_story_row(row)
    assert main is None
    assert competitors == []


def test_extract_companies_row_too_short_is_skipped():
    row = ["A", "B"]
    main, competitors = extract_companies_from_story_row(row)
    assert main is None
    assert competitors == []


def test_normalize_company_key_shared_with_is_company_match():
    """The ingestion parser's dedup key must stay consistent with the existing radar matcher."""
    assert CompanyRadarScanner.is_company_match("Byju's Learning Pvt Ltd", "Byju's") is True
    assert CompanyRadarScanner.is_company_match("Greater Than Equal Technologies", "REA Group") is False
