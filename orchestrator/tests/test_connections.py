"""The credential store: encrypted at rest, metadata only on the wire.

The one property everything here defends: the token value exists in exactly
two places, the create request and the ciphertext. Not in a response, not in
the audit log, not in a log line, not in an error. Several tests plant the
value somewhere hostile and assert it did not come back out.
"""

import logging
from collections.abc import AsyncIterator

import httpx
import pytest
from orchestrator.api.deps import current_owner
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.errors import DomainError
from orchestrator.main import create_app, lifespan_for_tests

from orchestrator import crypto

from .conftest import DATABASE_URL, TEST_OWNER_ID, needs_db, refuse_the_developers_store

pytestmark = needs_db

#: Never a real credential shape: GitHub revokes real looking tokens it sees
#: in public code, and a test that trips that scanner is a test that deletes
#: somebody's token.
PLANTED = "not-a-real-token-a1b2c3d4e5"


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, lifespan_factory=lifespan_for_tests)
    # Never the developer's identity: the cleanup below deletes a token
    # and a settings row, and both are shared with the running
    # development server through one database.
    app.dependency_overrides[current_owner] = lambda: TEST_OWNER_ID
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            try:
                yield c
            finally:
                # The development database is a shared Neon branch: leave no
                # connection or ciphertext behind for the next test run to see.
                async with app.state.pool.connection() as conn:
                    await store.delete_secret(
                        conn, f"{refuse_the_developers_store(TEST_OWNER_ID)}:github"
                    )
                    body = await store.settings_body(conn, TEST_OWNER_ID)
                    body.pop("connections", None)
                    await store.put_settings_body(conn, TEST_OWNER_ID, body)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url=DATABASE_URL,
        database_direct_url=DATABASE_URL,
        secret_key="a test secret with enough entropy to stand in for a real one",
    )


class TestTheCrypto:
    def test_a_value_survives_the_round_trip(self) -> None:
        ciphertext = crypto.encrypt("some secret key", PLANTED)
        assert crypto.decrypt("some secret key", ciphertext) == PLANTED

    def test_the_ciphertext_does_not_contain_the_value(self) -> None:
        ciphertext = crypto.encrypt("some secret key", PLANTED)
        assert PLANTED.encode() not in ciphertext

    def test_an_empty_secret_refuses_instead_of_storing_plaintext(self) -> None:
        with pytest.raises(DomainError) as error:
            crypto.encrypt("", PLANTED)
        assert "SECRET_KEY" in error.value.message
        assert error.value.status_code == 503

    def test_a_changed_secret_names_the_real_problem(self) -> None:
        ciphertext = crypto.encrypt("the first key", PLANTED)
        with pytest.raises(DomainError) as error:
            crypto.decrypt("a different key", ciphertext)
        # "Invalid token" would send someone to debug the GitHub token; the
        # actual fix is reconnecting so the value re-encrypts.
        assert "SECRET_KEY changed" in error.value.message
        assert PLANTED not in error.value.message

    def test_redaction_blanks_every_given_secret(self) -> None:
        text = f"upstream said: {PLANTED} is over its rate limit"
        assert PLANTED not in crypto.redacted(text, PLANTED)
        assert "[redacted]" in crypto.redacted(text, PLANTED)


class TestTheConnectionFlow:
    async def test_create_list_revoke(self, client: httpx.AsyncClient) -> None:
        created = await client.post("/connections", json={"provider": "github", "token": PLANTED})
        assert created.status_code == 201
        assert created.json()["provider"] == "github"
        assert created.json()["connected"] is True

        listed = await client.get("/connections")
        assert listed.status_code == 200
        providers = [c["provider"] for c in listed.json()["connections"]]
        assert providers == ["github"]

        revoked = await client.delete("/connections/github")
        assert revoked.status_code == 204
        assert (await client.get("/connections")).json()["connections"] == []

    async def test_the_ciphertext_lands_and_is_not_the_value(
        self, client: httpx.AsyncClient
    ) -> None:
        await client.post("/connections", json={"provider": "github", "token": PLANTED})
        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            stored = await store.get_secret(conn, f"{TEST_OWNER_ID}:github")
        assert stored is not None
        assert PLANTED.encode() not in stored

    async def test_an_unknown_provider_is_refused_with_the_known_set(
        self, client: httpx.AsyncClient
    ) -> None:
        response = await client.post(
            "/connections", json={"provider": "database", "token": PLANTED}
        )
        assert response.status_code == 409
        assert "github, vercel, render" in response.json()["error"]

    async def test_revoking_what_does_not_exist_is_a_404(self, client: httpx.AsyncClient) -> None:
        assert (await client.delete("/connections/github")).status_code == 404


class TestTheValueNeverLeaves:
    async def test_not_in_any_response_body(self, client: httpx.AsyncClient) -> None:
        created = await client.post("/connections", json={"provider": "github", "token": PLANTED})
        listed = await client.get("/connections")
        assert PLANTED not in created.text
        assert PLANTED not in listed.text

    async def test_not_in_the_audit_log(self, client: httpx.AsyncClient) -> None:
        await client.post("/connections", json={"provider": "github", "token": PLANTED})
        await client.delete("/connections/github")
        audit = await client.get("/audit")
        assert PLANTED not in audit.text
        # And the events themselves exist, so the check above is not vacuous.
        actions = [e["action"] for e in audit.json()]
        assert "Connected GitHub" in actions
        assert "Removed the GitHub connection" in actions

    async def test_not_in_the_logs(
        self, client: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.DEBUG):
            await client.post("/connections", json={"provider": "github", "token": PLANTED})
            await client.get("/connections")
        assert PLANTED not in caplog.text

    async def test_not_in_the_settings_body(self, client: httpx.AsyncClient) -> None:
        """The metadata row must hold no value derived field: not a prefix, not
        a suffix, not a length. Metadata that narrows a secret is a slow leak."""
        await client.post("/connections", json={"provider": "github", "token": PLANTED})
        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            body = await store.settings_body(conn, TEST_OWNER_ID)
        flattened = str(body)
        assert PLANTED not in flattened
        assert PLANTED[:8] not in flattened


class TestTwoWritersToOneRow:
    """A settings patch and a connection share one jsonb row.

    Both used to be written by reading the row, changing it in Python and
    writing the whole thing back, which loses every update that landed in
    between. The default organisation field patches on every keystroke, so a
    reader holding a copy of the row while a connection is stored is not
    hypothetical: seventeen patches in two and a half seconds appear in one
    real audit log.

    This is hardening rather than a diagnosis. The credential disappearance it
    was found while investigating turned out to be explicit revokes, visible in
    both the audit log and the HTTP access log. The lost update below is real,
    reproducible and now closed, and it was never shown to have bitten anyone.
    """

    async def test_a_stale_writer_no_longer_erases_another_path(self, client) -> None:
        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            # A reader takes its copy, exactly as a keystroke patch does.
            stale = await store.settings_body(conn, TEST_OWNER_ID)
            git = stale.get("settings", {}).get("git", {})

            # A connection is stored while that copy is held.
            await store.put_settings_section(
                conn,
                TEST_OWNER_ID,
                ("connections", "github"),
                {"provider": "github", "scopes": ["repo"]},
            )

            # And only now does the holder write what it read.
            await store.put_settings_section(
                conn, TEST_OWNER_ID, ("settings", "git"), {**git, "defaultOrg": "late"}
            )

            after = await store.settings_body(conn, TEST_OWNER_ID)

        assert after.get("connections", {}).get("github") is not None, (
            "a write from a stale read erased a connection stored while it was held"
        )
        assert after["settings"]["git"]["defaultOrg"] == "late"

    async def test_removing_one_path_leaves_the_other(self, client) -> None:
        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            await store.put_settings_section(
                conn, TEST_OWNER_ID, ("settings", "git"), {"defaultOrg": "vinozhan"}
            )
            await store.put_settings_section(
                conn, TEST_OWNER_ID, ("connections", "github"), {"provider": "github"}
            )
            await store.delete_settings_section(conn, TEST_OWNER_ID, ("connections", "github"))
            after = await store.settings_body(conn, TEST_OWNER_ID)

        assert after.get("connections", {}).get("github") is None
        assert after["settings"]["git"]["defaultOrg"] == "vinozhan", (
            "revoking a connection took the settings with it"
        )

    async def test_the_ordinary_sequence_still_works_through_the_routes(self, client) -> None:
        created = await client.post("/connections", json={"provider": "github", "token": PLANTED})
        assert created.status_code == 201, created.text
        patched = await client.patch("/settings/git", json={"defaultOrg": "vinozhan"})
        assert patched.status_code == 200, patched.text

        listed = (await client.get("/connections")).json()["connections"]
        assert [c["provider"] for c in listed] == ["github"]
        settings = (await client.get("/settings")).json()
        assert settings["git"]["connected"] is True
        assert settings["git"]["defaultOrg"] == "vinozhan"
