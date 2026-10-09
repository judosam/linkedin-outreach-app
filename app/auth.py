"""Multi-user session auth backed by the DB `users` table.

- Passwords: PBKDF2-SHA256 (per-user salt, 260k iterations), stdlib only.
- Sessions: in-memory HTTP-only cookie tokens (restart = re-login, by design —
  no credential material is ever persisted in session storage).
- Roles: 'admin' manages users & dangerous operations; 'campaign_manager'
  can do everything except user management.
- Bootstrap: on first run a single admin is created from OCC_ADMIN_USERNAME /
  OCC_ADMIN_PASSWORD so the deployed instance is never locked out.
"""
import hashlib
import secrets
import threading
import time

from .config import SESSION_TTL_HOURS

PBKDF2_ITERATIONS = 260_000

_sessions = {}  # token -> {'user_id': int, 'expires': epoch}
_lock = threading.Lock()


# --- password hashing -------------------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        'sha256', password.encode(), salt.encode(), PBKDF2_ITERATIONS
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def check_password(password: str, stored: str) -> bool:
    """Constant-time verification; supports legacy plain env-seeded values."""
    if not stored:
        return False
    try:
        algo, iterations, salt, digest = stored.split('$', 3)
    except ValueError:
        # Legacy/env-seeded plaintext (pre-migration) — verified as plain text
        # once, then the caller re-hashes on first successful change.
        return secrets.compare_digest(password.encode(), stored.encode())
    if algo != 'pbkdf2_sha256':
        return False
    calc = hashlib.pbkdf2_hmac(
        'sha256', password.encode(), salt.encode(), int(iterations)
    ).hex()
    return secrets.compare_digest(calc, digest)


# --- sessions ---------------------------------------------------------------

def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with _lock:
        _sessions[token] = {'user_id': user_id, 'expires': time.time() + SESSION_TTL_HOURS * 3600}
        now = time.time()
        for t in [t for t, s in _sessions.items() if s['expires'] < now]:
            _sessions.pop(t, None)
    return token


def session_user_id(token: str) -> int | None:
    if not token:
        return None
    with _lock:
        sess = _sessions.get(token)
        if not sess:
            return None
        if sess['expires'] < time.time():
            _sessions.pop(token, None)
            return None
        return sess['user_id']


def destroy_session(token: str):
    with _lock:
        _sessions.pop(token, None)


def destroy_user_sessions(user_id: int):
    """Log a user out everywhere (after deactivation / password change)."""
    with _lock:
        for t in [t for t, s in _sessions.items() if s.get('user_id') == user_id]:
            _sessions.pop(t, None)
