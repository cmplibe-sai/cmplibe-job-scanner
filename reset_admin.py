#!/usr/bin/env python3
"""
cMPLiBe AIScanner - Admin Password Reset Tool
Usage:
    python reset_admin.py [new_password]

Example:
    python reset_admin.py
    python reset_admin.py cmplibe@2026
    python reset_admin.py MySecurePass2026
"""
import sys
import os
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Load .env file if available
try:
    from dotenv import load_dotenv
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        load_dotenv(env_file)
except ImportError:
    pass

from job_pulse.storage.factory import get_repository
from job_pulse.security import hash_password
from job_pulse.utils.time_utils import get_ist_iso


def main():
    new_password = sys.argv[1] if len(sys.argv) > 1 else (os.environ.get("ADMIN_PASSWORD") or "cmplibe@2026").strip()
    if not new_password:
        new_password = "cmplibe@2026"

    repo = get_repository(force_new=True)
    p_hash, salt = hash_password(new_password)
    now_str = get_ist_iso()

    # Supports both PostgresJobRepository and SQLite JobDatabase
    if hasattr(repo, "_cursor"):
        # Postgres repository
        with repo._get_conn() as conn:
            cursor = repo._cursor(conn)
            cursor.execute("SELECT id FROM users WHERE LOWER(username) = 'admin'")
            if cursor.fetchone():
                cursor.execute(
                    "UPDATE users SET password_hash = %s, salt = %s, role = 'admin', is_active = TRUE, last_login_at = %s WHERE LOWER(username) = 'admin'",
                    (p_hash, salt, now_str),
                )
            else:
                cursor.execute(
                    "INSERT INTO users (username, password_hash, salt, role, is_active, created_at, last_login_at) VALUES (%s, %s, %s, 'admin', TRUE, %s, %s)",
                    ("admin", p_hash, salt, now_str, now_str),
                )
        db_type = "PostgreSQL (Supabase)"
    else:
        # SQLite repository
        with repo._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE LOWER(username) = 'admin'")
            if cursor.fetchone():
                cursor.execute(
                    "UPDATE users SET password_hash = ?, salt = ?, role = 'admin', is_active = 1, last_login_at = ? WHERE LOWER(username) = 'admin'",
                    (p_hash, salt, now_str),
                )
            else:
                cursor.execute(
                    "INSERT INTO users (username, password_hash, salt, role, is_active, created_at, last_login_at) VALUES (?, ?, ?, 'admin', 1, ?, ?)",
                    ("admin", p_hash, salt, now_str, now_str),
                )
            conn.commit()
        db_type = "SQLite (Local data)"

    print("==================================================================")
    print("  [+] cMPLiBe AIScanner - Admin Account Credentials Synchronized")
    print("==================================================================")
    print(f"  Database:  {db_type}")
    print(f"  Username:  admin")
    print(f"  Password:  {new_password}")
    print(f"  Role:      admin")
    print(f"  Active:    True")
    print("==================================================================")
    print("  [>] You can now log into https://www.cmplibe.com/job-scanner/login")
    print("      using the username 'admin' and the password above.")
    print("==================================================================")


if __name__ == "__main__":
    main()
