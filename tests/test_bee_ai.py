"""
Tests for Bee 🐝 AI Assistant knowledge retrieval and intent matching engine.
"""

import pytest
from job_pulse.ai.bee_assistant import BeeAssistant


def test_bee_assistant_greeting():
    res = BeeAssistant.answer_question("hello", user_role="admin")
    assert "Bee" in res["reply"]
    assert "Administrator" in res["reply"]
    assert len(res["suggestions"]) > 0


def test_bee_assistant_add_target_company():
    res = BeeAssistant.answer_question("How do I add a new target company?", user_role="member")
    assert "Target Company Radar" in res["reply"]
    assert res["action"] is not None
    assert res["action"]["tab"] == "radar"


def test_bee_assistant_search_jobs():
    res = BeeAssistant.answer_question("How to search opportunities across portals?", user_role="member")
    assert "Opportunity Explorer" in res["reply"]
    assert res["action"]["tab"] == "explorer"


def test_bee_assistant_google_sheets():
    res = BeeAssistant.answer_question("How does Google Sheets Live Sync work?", user_role="member")
    assert "Google Sheet" in res["reply"]
    assert res["action"]["tab"] == "sheets"


def test_bee_assistant_admin_role_note_for_members():
    res = BeeAssistant.answer_question("how do I configure email alerts and smtp?", user_role="member")
    assert "Administrators" in res["reply"]


def test_bee_assistant_fallback():
    res = BeeAssistant.answer_question("xyz random quantum mechanical formula 123", user_role="member")
    assert "couldn't find an exact match" in res["reply"]
    assert len(res["suggestions"]) > 0
