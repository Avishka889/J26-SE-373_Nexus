"""Accounts: passwords, session tokens and the sign-in throttle.

Passwords are hashed with Argon2 through `pwdlib`, as FastAPI's security
tutorial recommends, and an unknown email is checked against a dummy hash so a
wrong address takes as long to refuse as a wrong password: the timing never
says which emails have accounts.

A session is a random token in an HttpOnly cookie, never a bearer token in the
page: the architecture keeps every secret out of the browser's script, its
store and its storage, and a cookie the script cannot read is the one way to
sign a browser in that keeps to that. Only the token's SHA-256 is stored.
"""

import hashlib
import secrets
import time
from collections.abc import Callable
from typing import Any

from pwdlib import PasswordHash
from pwdlib.exceptions import PwdlibError

from .errors import DomainError

SESSION_COOKIE = "sdlc_session"

_hasher = PasswordHash.recommended()
#: Verified against when no account has the email, so both refusals cost the same.
_DUMMY_HASH = _hasher.hash("not the password of any account")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        _hasher.verify(password, _DUMMY_HASH)
        return False
    try:
        return _hasher.verify(password, password_hash)
    except PwdlibError:
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_user_id() -> str:
    return f"u_{secrets.token_hex(8)}"


def normalised_email(email: str) -> str:
    return email.strip().lower()


def display_name(user: dict[str, Any]) -> str:
    """The name an action is recorded under: the account's name, else its email."""
    return (user.get("name") or "").strip() or user.get("email", "")


class SignInThrottle:
    """Refuses an email after repeated wrong passwords, for a while.

    Kept in the process, which is the one the orchestrator runs as. Five wrong
    passwords within fifteen minutes refuse that email for the rest of the
    window; a right one clears the count.
    """

    def __init__(
        self,
        *,
        attempts: int = 5,
        window_seconds: float = 15 * 60,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._attempts = attempts
        self._window = window_seconds
        self._clock = clock
        self._failures: dict[str, list[float]] = {}

    def _recent(self, email: str) -> list[float]:
        cutoff = self._clock() - self._window
        recent = [at for at in self._failures.get(email, []) if at > cutoff]
        if recent:
            self._failures[email] = recent
        else:
            self._failures.pop(email, None)
        return recent

    def check(self, email: str) -> None:
        recent = self._recent(email)
        if len(recent) >= self._attempts:
            wait = max(1, round((recent[0] + self._window - self._clock()) / 60))
            raise DomainError(
                f"Too many wrong passwords for this account. Try again in {wait} "
                f"minute{'' if wait == 1 else 's'}.",
                status_code=429,
            )

    def failed(self, email: str) -> None:
        self._recent(email)
        self._failures.setdefault(email, []).append(self._clock())

    def cleared(self, email: str) -> None:
        self._failures.pop(email, None)
