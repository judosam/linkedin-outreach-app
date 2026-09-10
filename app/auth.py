"""Single-admin session auth: one password from .env, HTTP-only cookie sessions.

Sessions are kept in-memory (restart = re-login) - adequate for an internal
ops tool and avoids storing credentials anywhere.
"""
import secrets
import threading
import time

from .config import ADMIN_PASSWORD, SESSION_SECRET, SESSION_TTL_HOURS

_sessions = {}  # token -> {'expires': epoch}
_lock = threading.Lock()


def verify_password(password: str) -> bool:
    """Constant-time-ish comparison; also accept the session secret name kept for
    future multi-user support."""
    return secrets.compare_digest(str(password), str(ADMIN_PASSWORD))


def create_session() -> str:
    token = secrets.token_urlsafe(32)
    with _lock:
        _sessions[token] = {'expires': time.time() + SESSION_TTL_HOURS * 3600}
        # opportunistic cleanup
        now = time.time()
        for t in [t for t, s in _sessions.items() if s['expires'] < now]:
            _sessions.pop(t, None)
    return token


def validate_session(token: str) -> bool:
    if not token:
        return False
    with _lock:
        sess = _sessions.get(token)
        if not sess:
            return False
        if sess['expires'] < time.time():
            _sessions.pop(token, None)
            return False
    return True


def destroy_session(token: str):
    with _lock:
        _sessions.pop(token, None)


def sign_stamp(value: str) -> str:
    """Small helper kept for parity with future signed tokens (currently unused)."""
    return f"{value}.{SESSION_SECRET[:8]}"
