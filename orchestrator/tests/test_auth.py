"""Sign-in: accounts, sessions, and nothing answered without one.

Before this, `current_owner` returned one constant and the login form set a
flag in the browser: any address and any password opened every project. These
tests drive the real dependency, with the test lifespan's signed-in override
removed, so a request carries only what a browser would: its cookie.
"""

import secrets
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from orchestrator.api.deps import current_user
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.main import create_app, lifespan_for_tests

from .conftest import DATABASE_URL, needs_db

pytestmark = needs_db

PASSWORD = "correct horse battery staple"


@pytest.fixture
def unclaimed() -> str:
    """An identity from before sign-in that only this test may adopt."""
    return f"u_unclaimed_{secrets.token_hex(4)}"


@pytest.fixture
def settings(tmp_path: Path, unclaimed: str) -> Settings:
    assert DATABASE_URL is not None
    return Settings(
        database_url=DATABASE_URL,
        database_direct_url=DATABASE_URL,
        c3_workspace_root=str(tmp_path / "workspaces"),
        pre_sign_in_owner_id=unclaimed,
    )


class Browser:
    """One browser: its own cookie jar against the one app."""

    def __init__(self, app: Any) -> None:
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        )

    async def register(self, email: str, name: str = "Ada Reviewer") -> httpx.Response:
        return await self.client.post(
            "/auth/register", json={"name": name, "email": email, "password": PASSWORD}
        )

    async def login(self, email: str, password: str = PASSWORD) -> httpx.Response:
        return await self.client.post("/auth/login", json={"email": email, "password": password})


@pytest.fixture
async def app(settings: Settings, unclaimed: str) -> AsyncIterator[Any]:
    app = create_app(settings, lifespan_factory=lifespan_for_tests)
    async with app.router.lifespan_context(app):
        # The real dependency: a request is signed in by its cookie or not at all.
        app.dependency_overrides.pop(current_user, None)
        async with app.state.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO app.users (id, email, name) VALUES (%s, %s, %s)",
                (unclaimed, f"{unclaimed}@localhost", "Local development"),
            )
            await store.create_project(conn, name="Made before sign-in", owner_id=unclaimed)
        app.state.emails = []
        try:
            yield app
        finally:
            async with app.state.pool.connection() as conn:
                ids = [unclaimed]
                for email in app.state.emails:
                    user = await store.user_by_email(conn, email)
                    if user is not None:
                        ids.append(user["id"])
                await conn.execute("DELETE FROM app.projects WHERE owner_id = ANY(%s)", (ids,))
                await conn.execute("DELETE FROM app.settings WHERE id = ANY(%s)", (ids,))
                await conn.execute("DELETE FROM app.users WHERE id = ANY(%s)", (ids,))


def email_for(app: Any, name: str) -> str:
    email = f"{name}-{secrets.token_hex(4)}@example.com"
    app.state.emails.append(email)
    return email


async def test_the_first_account_takes_over_the_projects_made_before_sign_in(app: Any) -> None:
    owner = Browser(app)

    answer = await owner.register(email_for(app, "first"))

    assert answer.status_code == 201
    assert answer.json()["adopted"] is True
    projects = (await owner.client.get("/projects")).json()
    assert [project["name"] for project in projects] == ["Made before sign-in"]


async def test_a_later_account_starts_with_nothing_of_anyone_elses(app: Any) -> None:
    await Browser(app).register(email_for(app, "first"))
    later = Browser(app)

    answer = await later.register(email_for(app, "later"))

    assert answer.status_code == 201
    assert answer.json()["adopted"] is False
    assert (await later.client.get("/projects")).json() == []


async def test_an_email_registers_once_whatever_its_case(app: Any) -> None:
    email = email_for(app, "once")
    await Browser(app).register(email)

    answer = await Browser(app).register(email.upper())

    assert answer.status_code == 409
    assert answer.json()["error"] == "An account with that email already exists. Sign in instead."


async def test_a_wrong_password_and_an_unknown_email_read_the_same(app: Any) -> None:
    email = email_for(app, "known")
    await Browser(app).register(email)

    wrong = await Browser(app).login(email, "not the password")
    unknown = await Browser(app).login(email_for(app, "nobody"))

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"] == unknown.json()["error"]
    assert wrong.json()["error"] == "That email and password do not match an account."


async def test_signing_in_sets_a_session_the_page_cannot_read(app: Any) -> None:
    email = email_for(app, "session")
    await Browser(app).register(email)
    browser = Browser(app)

    answer = await browser.login(email)

    cookie = answer.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    me = await browser.client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == email
    assert "password_hash" not in me.json()["user"]


async def test_nothing_else_answers_without_a_session(app: Any) -> None:
    stranger = Browser(app)

    projects = await stranger.client.get("/projects")
    settings = await stranger.client.get("/settings")
    health = await stranger.client.get("/health")

    assert projects.status_code == settings.status_code == 401
    assert projects.json()["error"] == "Sign in to continue."
    assert health.status_code == 200


async def test_signing_out_ends_the_session(app: Any) -> None:
    browser = Browser(app)
    await browser.register(email_for(app, "leaving"))

    answer = await browser.client.post("/auth/logout")

    assert answer.status_code == 204
    assert (await browser.client.get("/auth/me")).status_code == 401


async def test_the_database_holds_neither_the_password_nor_the_token(app: Any) -> None:
    email = email_for(app, "stored")
    browser = Browser(app)
    answer = await browser.register(email)
    token = answer.cookies.get("sdlc_session")
    assert token

    async with app.state.pool.connection() as conn:
        user = await store.user_by_email(conn, email)
        assert user is not None
        stored = await conn.execute(
            "SELECT token_hash FROM app.sessions WHERE user_id = %s", (user["id"],)
        )
        hashes = [row[0] for row in await stored.fetchall()]

    assert user["password_hash"].startswith("$argon2")
    assert PASSWORD not in user["password_hash"]
    assert hashes and token not in hashes


async def test_repeated_wrong_passwords_are_refused_for_a_while(app: Any) -> None:
    email = email_for(app, "guessed")
    await Browser(app).register(email)
    guesser = Browser(app)
    for _ in range(5):
        await guesser.login(email, "a guess")

    answer = await guesser.login(email)

    assert answer.status_code == 429
    assert "Too many wrong passwords" in answer.json()["error"]


async def test_one_account_never_reads_anothers_audit(app: Any) -> None:
    first = Browser(app)
    await first.register(email_for(app, "first"))
    await first.client.patch("/settings/profile", json={"workspace": "First's workspace"})
    second = Browser(app)
    await second.register(email_for(app, "second"))

    theirs = (await second.client.get("/audit")).json()
    activity = (await second.client.get("/activity")).json()

    assert all(entry["action"] != "Updated profile settings" for entry in theirs)
    assert all(entry["title"] != "Updated profile settings" for entry in activity)
    assert (await first.client.get("/audit")).json()


async def test_a_registration_reads_its_own_refusal(app: Any) -> None:
    answer = await Browser(app).client.post(
        "/auth/register", json={"name": "Ada", "email": "not-an-email", "password": PASSWORD}
    )

    assert answer.status_code == 422
    assert answer.json()["error"] == "Enter an email address, such as you@example.com."


async def test_a_refused_password_is_never_sent_back(app: Any) -> None:
    answer = await Browser(app).client.post(
        "/auth/register",
        json={"name": "Ada", "email": email_for(app, "short"), "password": "hunter2"},
    )

    assert answer.status_code == 422
    assert "hunter2" not in answer.text


async def test_a_settings_change_is_recorded_under_the_accounts_name(app: Any) -> None:
    browser = Browser(app)
    await browser.register(email_for(app, "acting"), name="Ada Reviewer")

    await browser.client.patch("/settings/profile", json={"workspace": "Studio"})

    entry = (await browser.client.get("/audit")).json()[0]
    assert entry["action"] == "Updated profile settings"
    assert entry["actor"] == "Ada Reviewer"


async def test_the_profile_name_is_the_accounts_name(app: Any) -> None:
    browser = Browser(app)
    await browser.register(email_for(app, "renamed"), name="Ada")

    answer = await browser.client.patch("/settings/profile", json={"name": "  Ada   Lovelace "})

    assert answer.status_code == 200
    assert answer.json()["profile"]["name"] == "Ada Lovelace"
    assert (await browser.client.get("/auth/me")).json()["user"]["name"] == "Ada Lovelace"


async def test_the_sign_in_email_is_not_changed_from_the_profile(app: Any) -> None:
    email = email_for(app, "kept")
    browser = Browser(app)
    await browser.register(email)

    refused = await browser.client.patch(
        "/settings/profile", json={"email": "elsewhere@example.com"}
    )
    same = await browser.client.patch("/settings/profile", json={"email": email.upper()})

    assert refused.status_code == 409
    assert (
        refused.json()["error"]
        == "The email is the one you sign in with, so it cannot be changed here."
    )
    assert same.status_code == 200
    assert (await browser.client.get("/settings")).json()["profile"]["email"] == email


async def _waiting_review(app: Any, browser: Browser) -> tuple[str, str]:
    """A project of this browser's account whose design run waits at its review."""
    created = await browser.client.post("/projects", json={"name": "Ledger", "description": ""})
    project_id = created.json()["id"]
    await browser.client.patch(
        f"/projects/{project_id}", json={"requirementText": "Someone records a payment."}
    )
    run_id = (await browser.client.get("/runs", params={"project": project_id})).json()[0]["id"]
    await app.state.supervisor.advance(uuid.UUID(run_id))
    gate = (await browser.client.get("/gates", params={"project": project_id})).json()[0]
    return run_id, gate["id"]


async def test_one_account_never_sees_anothers_runs_or_reviews(app: Any) -> None:
    owner = Browser(app)
    await owner.register(email_for(app, "owner"))
    run_id, _ = await _waiting_review(app, owner)
    other = Browser(app)
    await other.register(email_for(app, "other"))

    runs = (await other.client.get("/runs")).json()
    one = await other.client.get(f"/runs/{run_id}")
    gates = (await other.client.get("/gates")).json()

    assert all(run["id"] != run_id for run in runs)
    assert one.status_code == 404
    assert gates == []


async def test_one_account_never_decides_anothers_review(app: Any) -> None:
    owner = Browser(app)
    await owner.register(email_for(app, "owner"))
    _, gate_id = await _waiting_review(app, owner)
    other = Browser(app)
    await other.register(email_for(app, "other"))

    approved = await other.client.post(f"/gates/{gate_id}/approve", json={})
    changed = await other.client.post(
        f"/gates/{gate_id}/request-changes", json={"note": "not yours to change"}
    )

    assert approved.status_code == changed.status_code == 404
    assert [gate["id"] for gate in (await owner.client.get("/gates")).json()] == [gate_id]


async def test_one_account_is_never_told_of_anothers_reviews(app: Any) -> None:
    owner = Browser(app)
    await owner.register(email_for(app, "owner"))
    await _waiting_review(app, owner)
    other = Browser(app)
    await other.register(email_for(app, "other"))

    assert [item["kind"] for item in (await owner.client.get("/attention")).json()] == ["review"]
    assert (await other.client.get("/attention")).json() == []
