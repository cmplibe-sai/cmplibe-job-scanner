import hashlib
import os
import secrets
import time
from typing import Dict, Optional, Tuple

# In-memory active session store: session_token -> {"username": str, "expires_at": float}
_ACTIVE_SESSIONS: Dict[str, Dict] = {}
SESSION_DURATION_SECONDS = 7 * 24 * 3600  # 7 days


def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """
    Hash a password using PBKDF2 HMAC SHA-256 with 100,000 iterations.
    Returns (hex_hash, hex_salt).
    """
    if not salt:
        salt_bytes = os.urandom(16)
        salt = salt_bytes.hex()
    else:
        salt_bytes = bytes.fromhex(salt)

    pwd_bytes = password.encode("utf-8")
    key = hashlib.pbkdf2_hmac("sha256", pwd_bytes, salt_bytes, 100000)
    return key.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    """Verify a plain-text password against stored PBKDF2 hash and salt."""
    try:
        derived_hash, _ = hash_password(password, salt=salt)
        return secrets.compare_digest(derived_hash, password_hash)
    except Exception:
        return False


def create_session(username: str) -> str:
    """Generate a new secure session token and register it."""
    token = secrets.token_urlsafe(32)
    expires_at = time.time() + SESSION_DURATION_SECONDS
    _ACTIVE_SESSIONS[token] = {
        "username": username,
        "expires_at": expires_at,
        "created_at": time.time(),
    }
    return token


def validate_session(token: Optional[str]) -> Optional[str]:
    """
    Validate a session token.
    Returns username if valid and active, None otherwise.
    """
    if not token or token not in _ACTIVE_SESSIONS:
        return None

    sess = _ACTIVE_SESSIONS[token]
    if time.time() > sess["expires_at"]:
        _ACTIVE_SESSIONS.pop(token, None)
        return None

    return sess["username"]


def revoke_session(token: Optional[str]) -> None:
    """Invalidate and remove an active session token."""
    if token:
        _ACTIVE_SESSIONS.pop(token, None)


def clean_expired_sessions() -> None:
    """Purge any expired sessions from memory."""
    now = time.time()
    expired_keys = [k for k, v in _ACTIVE_SESSIONS.items() if now > v["expires_at"]]
    for k in expired_keys:
        _ACTIVE_SESSIONS.pop(k, None)
