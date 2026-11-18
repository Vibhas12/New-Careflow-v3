"""Password hashing (argon2), opaque session tokens and a simple login-failure limiter."""
import hashlib
import secrets
import threading
import time
from collections import defaultdict, deque

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_ph = PasswordHasher()


def hash_password(pw: str) -> str:
    return _ph.hash(pw)


def verify_password(pw: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        return _ph.verify(stored, pw)
    except (VerificationError, InvalidHashError):
        return False


def new_session_token() -> tuple[str, str]:
    """Returns (token sent to the browser in an HttpOnly cookie, sha256 hash stored in the database)."""
    tok = secrets.token_urlsafe(32)
    return tok, token_hash(tok)


def token_hash(tok: str) -> str:
    return hashlib.sha256(tok.encode()).hexdigest()


class LoginLimiter:
    """In-process limiter: N failures per account in a sliding window. Use Redis for multi-instance deployments."""

    def __init__(self):
        self._fails: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def _trim(self, key: str, window: float):
        q = self._fails[key]
        while q and q[0] < time.monotonic() - window:
            q.popleft()
        return q

    def blocked(self, key: str, max_failures: int, window_s: float) -> bool:
        with self._lock:
            return len(self._trim(key, window_s)) >= max_failures

    def fail(self, key: str):
        with self._lock:
            self._fails[key].append(time.monotonic())

    def reset(self, key: str | None = None):
        with self._lock:
            self._fails.clear() if key is None else self._fails.pop(key, None)


login_limiter = LoginLimiter()
