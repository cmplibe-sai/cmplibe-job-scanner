"""
End-to-End Live HTTP Integration Test against running FastAPI server
for Team Portal Authentication, Admin User Management, and Role-Based Access Control.
"""
import requests

BASE_URL = "http://127.0.0.1:8000"

def test_full_auth_and_user_mgmt_flow():
    session = requests.Session()

    print("1. Testing unauthenticated access...")
    res = session.get(f"{BASE_URL}/api/auth/me")
    assert res.status_code == 200
    assert res.json()["authenticated"] is False
    print("   -> OK: Unauthenticated status returned false.")

    res = session.get(f"{BASE_URL}/api/auth/users")
    assert res.status_code == 401
    print("   -> OK: Protected endpoint returned 401 Unauthorized.")

    print("2. Logging in as Master Admin...")
    login_res = session.post(f"{BASE_URL}/api/auth/login", json={"username": "admin", "password": "cmplibe@2026"})
    assert login_res.status_code == 200, f"Login failed: {login_res.text}"
    login_data = login_res.json()
    assert login_data["success"] is True
    assert login_data["role"] == "admin"
    print("   -> OK: Admin authenticated successfully, session cookie received.")

    print("3. Checking /api/auth/me with admin session...")
    res = session.get(f"{BASE_URL}/api/auth/me")
    assert res.status_code == 200
    assert res.json()["authenticated"] is True
    assert res.json()["role"] == "admin"
    print("   -> OK: Role confirmed as 'admin'.")

    print("4. Admin creating a new team member account (member_rahul)...")
    res = session.post(
        f"{BASE_URL}/api/auth/users",
        json={"username": "member_rahul", "password": "rahul@password123", "role": "member"}
    )
    assert res.status_code == 200
    assert res.json()["success"] is True
    print("   -> OK: Team member 'member_rahul' created.")

    print("5. Admin listing all team accounts...")
    res = session.get(f"{BASE_URL}/api/auth/users")
    assert res.status_code == 200
    users = res.json()["users"]
    usernames = [u["username"] for u in users]
    assert "admin" in usernames
    assert "member_rahul" in usernames
    print(f"   -> OK: User list retrieved: {usernames}")

    print("6. Member logging in with their new credentials in a separate session...")
    member_session = requests.Session()
    member_login = member_session.post(f"{BASE_URL}/api/auth/login", json={"username": "member_rahul", "password": "rahul@password123"})
    assert member_login.status_code == 200
    assert member_login.json()["role"] == "member"
    print("   -> OK: Member logged in successfully.")

    print("7. Verifying member cannot access admin endpoints (RBAC Guard)...")
    res = member_session.get(f"{BASE_URL}/api/auth/users")
    assert res.status_code == 403
    assert "Admin privileges required" in res.json()["detail"]

    res = member_session.post(f"{BASE_URL}/api/auth/users", json={"username": "hacker", "password": "123", "role": "admin"})
    assert res.status_code == 403
    print("   -> OK: Non-admin correctly rejected with 403 Forbidden.")

    print("8. Admin resetting member's password...")
    res = session.post(
        f"{BASE_URL}/api/auth/users/member_rahul/reset-password",
        json={"new_password": "updated_rahul_pwd_2026"}
    )
    assert res.status_code == 200
    print("   -> OK: Password reset successfully.")

    # Member logs in with new password
    res = requests.post(f"{BASE_URL}/api/auth/login", json={"username": "member_rahul", "password": "updated_rahul_pwd_2026"})
    assert res.status_code == 200
    print("   -> OK: Login with reset password verified.")

    print("9. Admin disabling member account...")
    res = session.post(f"{BASE_URL}/api/auth/users/member_rahul/toggle-status")
    assert res.status_code == 200
    print("   -> OK: User account disabled.")

    # Disabled account is blocked from login
    res = requests.post(f"{BASE_URL}/api/auth/login", json={"username": "member_rahul", "password": "updated_rahul_pwd_2026"})
    assert res.status_code == 401
    print("   -> OK: Disabled user blocked from login.")

    print("10. Admin deleting member account...")
    res = session.delete(f"{BASE_URL}/api/auth/users/member_rahul")
    assert res.status_code == 200
    print("   -> OK: Member account deleted.")

    print("11. Admin logging out...")
    res = session.post(f"{BASE_URL}/api/auth/logout")
    assert res.status_code == 200
    print("   -> OK: Admin session logged out.")

    print("\n[SUCCESS] ALL 11 END-TO-END HTTP INTEGRATION CHECKS PASSED PERFECTLY!")

if __name__ == "__main__":
    test_full_auth_and_user_mgmt_flow()
