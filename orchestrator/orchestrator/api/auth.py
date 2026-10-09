"""Sign-in: register, sign in, sign out, and who is signed in.

The only routes that answer without a session. Everything else depends on
`current_user`, which reads the cookie these set.
"""

from typing import Any

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, Field, field_validator

from .. import accounts
from ..config import Settings
from ..db import store
from ..errors import Conflict, DomainError
from .deps import CurrentUser, Db

router = APIRouter(prefix="/auth", tags=["auth"])

#: One sentence for a wrong email and a wrong password alike: which one was
#: wrong is exactly what an attacker wants to know.
WRONG_CREDENTIALS = "That email and password do not match an account."


def _email(value: str) -> str:
    email = accounts.normalised_email(value)
    local, at, domain = email.partition("@")
    if not (local and at and "." in domain and " " not in email):
        raise ValueError("Enter an email address, such as you@example.com.")
    return email


class Registration(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: str = Field(max_length=254)
    # A floor that refuses the trivially guessable, and a ceiling that keeps a
    # hash from being a way to spend the server's time.
    password: str = Field(min_length=8, max_length=1024)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        name = " ".join(value.split())
        if not name:
            raise ValueError("Enter your name.")
        return name

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        return _email(value)


class Credentials(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("email")
    @classmethod
    def _valid_email(cls, value: str) -> str:
        return accounts.normalised_email(value)


def _public(user: dict[str, Any]) -> dict[str, Any]:
    """What the browser may know about an account: never the hash."""
    return {"id": user["id"], "email": user["email"], "name": user["name"]}


async def _start_session(
    conn: Any, response: Response, user: dict[str, Any], settings: Settings
) -> None:
    token = accounts.new_session_token()
    await store.create_session(
        conn,
        token_hash=accounts.token_hash(token),
        user_id=user["id"],
        days=settings.session_days,
    )
    response.set_cookie(
        accounts.SESSION_COOKIE,
        token,
        max_age=settings.session_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(
    body: Registration, request: Request, response: Response, conn: Db
) -> dict[str, Any]:
    """Create an account and sign it in.

    The first account takes over the identity from before sign-in, and with it
    every project, setting and connection made then; `adopted` says it did.
    """
    if await store.user_by_email(conn, body.email) is not None:
        raise Conflict("An account with that email already exists. Sign in instead.")
    settings: Settings = request.app.state.settings
    hashed = accounts.hash_password(body.password)
    adopted = await store.adopt_unclaimed_owner(
        conn,
        owner_id=settings.pre_sign_in_owner_id,
        email=body.email,
        name=body.name,
        password_hash=hashed,
    )
    user = adopted or await store.create_user(
        conn,
        user_id=accounts.new_user_id(),
        email=body.email,
        name=body.name,
        password_hash=hashed,
    )
    await _start_session(conn, response, user, settings)
    await store.record(
        conn,
        actor=accounts.display_name(user),
        action="Created an account",
        target=body.email,
        category="security",
        detail="Took over the projects made before sign-in." if adopted else "",
        owner_id=user["id"],
    )
    return {"user": _public(user), "adopted": adopted is not None}


@router.post("/login")
async def login(
    body: Credentials, request: Request, response: Response, conn: Db
) -> dict[str, Any]:
    throttle: accounts.SignInThrottle = request.app.state.sign_in_throttle
    throttle.check(body.email)
    user = await store.user_by_email(conn, body.email)
    if not accounts.verify_password(body.password, user["password_hash"] if user else None):
        throttle.failed(body.email)
        raise DomainError(WRONG_CREDENTIALS, status_code=status.HTTP_401_UNAUTHORIZED)
    assert user is not None
    throttle.cleared(body.email)
    await _start_session(conn, response, user, request.app.state.settings)
    return {"user": _public(user)}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, conn: Db) -> None:
    token = request.cookies.get(accounts.SESSION_COOKIE)
    if token:
        await store.delete_session(conn, accounts.token_hash(token))
    settings: Settings = request.app.state.settings
    response.delete_cookie(
        accounts.SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
    )


@router.get("/me")
async def me(user: CurrentUser) -> dict[str, Any]:
    return {"user": _public(user)}
