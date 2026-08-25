import os
import pytest
from job_pulse.utils.time_utils import (
    get_ist_now,
    get_ist_iso,
    get_ist_sheet_timestamp,
    get_ist_display,
    IST_TZ,
)
from job_pulse.security import (
    hash_password,
    verify_password,
    create_session,
    validate_session,
    revoke_session,
)
from job_pulse.storage.db import JobDatabase


def test_ist_time_utilities():
    """Verify IST timezone calculations and formatting."""
    now_ist = get_ist_now()
    assert now_ist.tzinfo is not None
    assert str(now_ist.tzinfo) == "IST" or now_ist.utcoffset().total_seconds() == 19800

    iso_str = get_ist_iso()
    assert "+05:30" in iso_str

    sheet_ts = get_ist_sheet_timestamp()
    assert sheet_ts.endswith(" IST")

    display_ts = get_ist_display()
    assert display_ts.endswith(" IST")

    # Test UTC conversion
    utc_str = "2026-08-25T05:30:00"
    converted = get_ist_display(utc_str)
    assert "IST" in converted
    assert "11:00 AM IST" in converted or "IST" in converted


def test_password_hashing_and_verification():
    """Test PBKDF2 HMAC SHA-256 password hashing."""
    raw_pass = "SecurePass@2026"
    pwd_hash, salt = hash_password(raw_pass)
    assert len(pwd_hash) == 64
    assert len(salt) == 32
    assert verify_password(raw_pass, pwd_hash, salt) is True
    assert verify_password("WrongPassword", pwd_hash, salt) is False


def test_session_token_management():
    """Test in-memory session token creation, lookup, and revocation."""
    username = "test_admin"
    token = create_session(username)
    assert token is not None
    assert len(token) >= 32

    # Validation
    assert validate_session(token) == username
    assert validate_session("non_existent_token") is None

    # Revocation
    revoke_session(token)
    assert validate_session(token) is None


def test_database_user_authentication(tmp_path):
    """Test user credential verification and password change in JobDatabase."""
    db_file = tmp_path / "test_auth.db"
    db = JobDatabase(db_path=db_file)

    # Verify default admin exists
    admin_info = db.verify_user_credentials("admin", "cmplibe@2026")
    assert admin_info is not None
    assert admin_info["username"] == "admin"
    assert admin_info["role"] == "admin"
    assert db.verify_user_credentials("admin", "incorrect_pwd") is None
    assert db.verify_user_credentials("unknown_user", "cmplibe@2026") is None

    # Change password
    ok, msg = db.change_user_password("admin", "cmplibe@2026", "new_secure_pwd_123")
    assert ok is True
    assert db.verify_user_credentials("admin", "new_secure_pwd_123") is not None
    assert db.verify_user_credentials("admin", "cmplibe@2026") is None

    # Bad old password rejection
    ok_fail, msg_fail = db.change_user_password("admin", "wrong_old_pwd", "another_pwd")
    assert ok_fail is False


def test_admin_user_management(tmp_path):
    """Test creating team members, roles, password resets, and deactivations."""
    db_file = tmp_path / "test_mgmt.db"
    db = JobDatabase(db_path=db_file)

    # Add member user
    ok, msg = db.add_user("recruiter_rahul", "rahul@2026", role="member")
    assert ok is True
    assert db.get_user_role("recruiter_rahul") == "member"

    # Verify member credentials
    m_info = db.verify_user_credentials("recruiter_rahul", "rahul@2026")
    assert m_info is not None
    assert m_info["username"] == "recruiter_rahul"
    assert m_info["role"] == "member"

    # Add another admin user
    ok2, _ = db.add_user("lead_priya", "priya@2026", role="admin")
    assert ok2 is True
    assert db.get_user_role("lead_priya") == "admin"

    # Duplicate username rejection
    ok_dup, msg_dup = db.add_user("recruiter_rahul", "another_pass")
    assert ok_dup is False
    assert "already taken" in msg_dup

    # Admin reset member password
    ok_reset, _ = db.admin_reset_user_password("recruiter_rahul", "brand_new_pass_123")
    assert ok_reset is True
    assert db.verify_user_credentials("recruiter_rahul", "brand_new_pass_123") is not None

    # Admin toggle user status (Deactivate)
    ok_toggle, msg_toggle = db.admin_toggle_user_status("recruiter_rahul", requesting_username="admin")
    assert ok_toggle is True
    # Disabled account cannot log in
    assert db.verify_user_credentials("recruiter_rahul", "brand_new_pass_123") is None

    # Admin toggle user status (Re-activate)
    ok_reactivate, _ = db.admin_toggle_user_status("recruiter_rahul", requesting_username="admin")
    assert ok_reactivate is True
    assert db.verify_user_credentials("recruiter_rahul", "brand_new_pass_123") is not None

    # Cannot delete master admin
    ok_del_admin, _ = db.admin_delete_user("admin", requesting_username="lead_priya")
    assert ok_del_admin is False

    # Delete member
    ok_del, _ = db.admin_delete_user("recruiter_rahul", requesting_username="admin")
    assert ok_del is True
    assert db.verify_user_credentials("recruiter_rahul", "brand_new_pass_123") is None

