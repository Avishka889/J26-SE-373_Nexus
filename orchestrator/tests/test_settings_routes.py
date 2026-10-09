"""The settings routes and the GitHub probe: secret free, derived, honest.

The probe is tested through httpx.MockTransport so no request leaves the
process: each test states exactly what GitHub would have answered and asserts
what the verdict honestly may claim from it.
"""

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
from orchestrator.api.deps import current_owner
from orchestrator.api.settings import PHOTO_MAX_CHARS
from orchestrator.clients.c4 import HttpC4
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.main import create_app, lifespan_for_tests
from orchestrator.probes import probe_github

from .conftest import DATABASE_URL, TEST_OWNER_ID, needs_db, refuse_the_developers_store
from .test_connections import PLANTED

pytestmark = needs_db


def _github_answering(
    status: int, *, scopes: str | None = None, login: str = "vinozhan"
) -> httpx.AsyncClient:
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/user"
        # The probe must send the token; that is the one place it may travel.
        assert request.headers["authorization"] == f"Bearer {PLANTED}"
        headers = {} if scopes is None else {"x-oauth-scopes": scopes}
        return httpx.Response(status, json={"login": login}, headers=headers)

    return httpx.AsyncClient(transport=httpx.MockTransport(handle))


class TestTheProbe:
    async def test_classic_with_both_scopes_is_suitable(self) -> None:
        async with _github_answering(200, scopes="repo, workflow") as client:
            probe = await probe_github(PLANTED, client=client)
        assert probe.verdict == "SUITABLE"
        assert probe.login == "vinozhan"
        assert probe.token_kind == "classic"
        assert probe.scopes == ["repo", "workflow"]

    async def test_classic_missing_workflow_is_workable_and_says_which(self) -> None:
        async with _github_answering(200, scopes="repo") as client:
            probe = await probe_github(PLANTED, client=client)
        assert probe.verdict == "WORKABLE"
        assert "workflow" in probe.reason

    async def test_fine_grained_reports_that_scopes_cannot_be_read(self) -> None:
        async with _github_answering(200, scopes=None) as client:
            probe = await probe_github(PLANTED, client=client)
        assert probe.verdict == "WORKABLE"
        assert probe.token_kind == "fine-grained"
        assert probe.scopes == []
        assert "cannot be verified" in probe.reason

    async def test_a_bad_token_is_unusable(self) -> None:
        async with _github_answering(401) as client:
            probe = await probe_github(PLANTED, client=client)
        assert probe.verdict == "UNUSABLE"

    async def test_a_network_failure_never_echoes_the_token(self) -> None:
        def explode(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(f"proxy rejected credential {PLANTED}", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(explode)) as client:
            probe = await probe_github(PLANTED, client=client)
        assert probe.verdict == "UNUSABLE"
        assert PLANTED not in probe.reason
        assert "[redacted]" in probe.reason


class _SameAtEveryLevel:
    """A component on a provider that takes no thinking setting, as an OpenAI model is."""

    thinking = "default"

    def thinking_for(self, level: str) -> str:
        return "default"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url=DATABASE_URL,
        database_direct_url=DATABASE_URL,
        secret_key="a test secret with enough entropy to stand in for a real one",
    )


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, lifespan_factory=lifespan_for_tests)
    # Never the developer's identity: the cleanup below deletes a token
    # and a settings row, and both are shared with the running
    # development server through one database.
    app.dependency_overrides[current_owner] = lambda: TEST_OWNER_ID
    async with app.router.lifespan_context(app):
        app.state.github_client = _github_answering(200, scopes="repo, workflow")
        # Each phase's client is built from the configuration, as in production,
        # and answers as a DeepSeek client does, whose requests a level changes;
        # a canned component otherwise names no model and says nothing about
        # thinking.
        for key, component in app.state.clients.items():
            component.model = getattr(settings, f"{key}_model")
            component.thinking = "disabled"
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            try:
                yield c
            finally:
                await app.state.github_client.aclose()
                async with app.state.pool.connection() as conn:
                    await store.delete_secret(
                        conn, f"{refuse_the_developers_store(TEST_OWNER_ID)}:github"
                    )
                    await store.put_settings_body(conn, TEST_OWNER_ID, {})


class TestFieldsSavedTogether:
    """Each field saves itself when the typing stops, so pasting into three fields of a
    section in quick succession sends three saves at once. Each read the section, merged
    its one field and wrote the whole section back, so the last one undid the others,
    and the Atlas fields came back empty while the page showed them typed."""

    async def test_three_fields_of_one_section_saved_at_once_all_stay(
        self, client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Every save reads before any writes, as three saves sent together do on a
        # busy server: the window between a read and its write, held open.
        read = store.settings_body

        async def slow_read(conn, owner):
            body = await read(conn, owner)
            await asyncio.sleep(0.05)
            return body

        monkeypatch.setattr(store, "settings_body", slow_read)
        fields = {
            "projectId": "66f0c0ffee0123456789abcd",
            "cluster": "Cluster0",
            "clientId": "mdb_sa_id_0123456789abcdef01234567",
        }

        answers = await asyncio.gather(
            *(
                client.patch("/settings/database", json={key: value})
                for key, value in fields.items()
            )
        )

        assert [answer.status_code for answer in answers] == [200, 200, 200]
        stored = (await client.get("/settings")).json()["database"]
        assert {key: stored[key] for key in fields} == fields


class TestTheSettingsRoutes:
    async def test_defaults_come_back_for_a_fresh_owner(self, client: httpx.AsyncClient) -> None:
        state = (await client.get("/settings")).json()
        assert set(state) == {"git", "vercel", "render", "database", "ai", "profile"}
        assert state["git"]["connected"] is False
        assert state["git"]["scopes"] == []

    async def test_a_section_patch_persists_and_answers_the_whole_state(
        self, client: httpx.AsyncClient
    ) -> None:
        answer = await client.patch("/settings/git", json={"defaultOrg": "vinozhan"})
        assert answer.status_code == 200
        assert answer.json()["git"]["defaultOrg"] == "vinozhan"
        again = (await client.get("/settings")).json()
        assert again["git"]["defaultOrg"] == "vinozhan"

    async def test_a_token_in_a_settings_patch_is_refused_with_directions(
        self, client: httpx.AsyncClient
    ) -> None:
        answer = await client.patch("/settings/git", json={"token": PLANTED})
        assert answer.status_code == 409
        assert "/connections" in answer.json()["error"]
        # And nothing was stored on the way to the refusal.
        state = (await client.get("/settings")).json()
        assert PLANTED not in str(state)

    async def test_the_client_side_connected_boolean_is_refused(
        self, client: httpx.AsyncClient
    ) -> None:
        answer = await client.patch("/settings/git", json={"connected": True})
        assert answer.status_code == 409
        assert "derived" in answer.json()["error"]

    async def test_an_unknown_field_is_refused_by_the_contract(
        self, client: httpx.AsyncClient
    ) -> None:
        answer = await client.patch("/settings/git", json={"favouriteColour": "blue"})
        assert answer.status_code in (400, 409, 422)

    async def test_connected_derives_from_the_connections_store(
        self, client: httpx.AsyncClient
    ) -> None:
        before = (await client.get("/settings")).json()
        assert before["git"]["connected"] is False

        created = await client.post("/connections", json={"provider": "github", "token": PLANTED})
        assert created.status_code == 201
        assert created.json()["probe"]["verdict"] == "SUITABLE"

        after = (await client.get("/settings")).json()
        assert after["git"]["connected"] is True
        assert after["git"]["scopes"] == ["repo", "workflow"]

        await client.delete("/connections/github")
        revoked = (await client.get("/settings")).json()
        assert revoked["git"]["connected"] is False

    async def test_the_whole_state_patch_route_works_and_audits(
        self, client: httpx.AsyncClient
    ) -> None:
        answer = await client.patch(
            "/settings", json={"profile": {"name": "Sampath"}, "ai": {"temperature": 0.3}}
        )
        assert answer.status_code == 200
        assert answer.json()["profile"]["name"] == "Sampath"
        assert answer.json()["ai"]["temperature"] == 0.3
        audit = (await client.get("/audit")).json()
        actions = [e["action"] for e in audit]
        assert "Updated profile settings" in actions
        assert "Updated ai settings" in actions


class TestTheProfilePhoto:
    """The photo is kept in the settings, and every settings read returns it. A 2 MB
    file was accepted and became a 2.7 MB string on each read; the browser now sends
    a small square, and the server keeps no more than a small photo."""

    async def test_a_small_photo_is_kept(self, client: httpx.AsyncClient) -> None:
        photo = "data:image/jpeg;base64," + "A" * 40_000

        answer = await client.patch("/settings/profile", json={"avatarUrl": photo})

        assert answer.status_code == 200, answer.text
        assert (await client.get("/settings")).json()["profile"]["avatarUrl"] == photo

    async def test_a_photo_over_the_limit_is_refused_and_not_kept(
        self, client: httpx.AsyncClient
    ) -> None:
        photo = "data:image/png;base64," + "A" * PHOTO_MAX_CHARS

        answer = await client.patch("/settings/profile", json={"avatarUrl": photo})

        assert answer.status_code == 409
        assert "too large" in answer.json()["error"]
        assert (await client.get("/settings")).json()["profile"]["avatarUrl"] is None

    async def test_a_web_address_is_not_a_photo(self, client: httpx.AsyncClient) -> None:
        answer = await client.patch(
            "/settings", json={"profile": {"avatarUrl": "https://tracker.example/pixel.png"}}
        )

        assert answer.status_code == 409
        assert (await client.get("/settings")).json()["profile"]["avatarUrl"] is None

    async def test_the_photo_can_be_removed(self, client: httpx.AsyncClient) -> None:
        await client.patch("/settings/profile", json={"avatarUrl": "data:image/jpeg;base64,AAAA"})

        answer = await client.patch("/settings/profile", json={"avatarUrl": None})

        assert answer.status_code == 200, answer.text
        assert answer.json()["profile"]["avatarUrl"] is None


class TestTheModelsEachPhaseRuns:
    """The AI Model tab offered OpenAI and Claude and saved a choice nothing read:
    every run used the model the orchestrator was configured with. The tab now
    shows that configuration, read from the server, and offers nothing to save."""

    async def test_each_phase_names_its_configured_model(self, client: httpx.AsyncClient) -> None:
        configured = client.app.state.settings  # type: ignore[attr-defined]

        answer = await client.get("/settings/models")

        assert answer.status_code == 200, answer.text
        assert [(row["phase"], row["model"]) for row in answer.json()] == [
            ("Requirements and Design", configured.c1_model),
            ("Code Generation", configured.c2_model),
            ("Testing and Security", configured.c3_model),
            ("Deployment", configured.c4_model),
        ]

    async def test_each_phase_says_how_hard_it_is_set_to_think(
        self, client: httpx.AsyncClient
    ) -> None:
        # The switch is configuration, read at startup like the model, and the
        # tab shows it rather than leaving a reader to guess from a run.
        app = client.app  # type: ignore[attr-defined]
        app.state.settings = app.state.settings.model_copy(update={"c2_thinking": "high"})

        answer = (await client.get("/settings/models")).json()

        assert {row["phase"]: row["thinking"] for row in answer} == {
            "Requirements and Design": "off",
            "Code Generation": "high",
            "Testing and Security": "off",
            "Deployment": "off",
        }

    async def test_a_level_the_account_chose_is_the_phases_and_says_so(
        self, client: httpx.AsyncClient
    ) -> None:
        # Chosen in Settings and saved with the account (3B); the next run starts
        # at it. The others stay as configured, and say they were not chosen.
        chosen = {"design": "high", "code": None, "testing": None, "deployment": None}
        saved = await client.patch("/settings/ai", json={"thinking": chosen})
        assert saved.status_code == 200, saved.text

        answer = (await client.get("/settings/models")).json()

        by_key = {row["key"]: row for row in answer}
        assert set(by_key) == {"design", "code", "testing", "deployment"}
        assert (by_key["design"]["thinking"], by_key["design"]["thinkingChosen"]) == ("high", True)
        assert (by_key["code"]["thinking"], by_key["code"]["thinkingChosen"]) == ("off", False)
        assert all(row["thinkingApplies"] for row in answer)

    async def test_a_phase_run_over_http_is_not_offered_a_choice_it_would_ignore(
        self, client: httpx.AsyncClient
    ) -> None:
        # A separate service thinks as its own configuration says, so a level
        # chosen here would be a choice nothing reads, and this process cannot
        # say what that service sends.
        app = client.app  # type: ignore[attr-defined]
        app.state.clients["c4"] = HttpC4("http://c4.invalid")
        chosen = {"design": None, "code": None, "testing": None, "deployment": "high"}
        await client.patch("/settings/ai", json={"thinking": chosen})

        answer = (await client.get("/settings/models")).json()

        assert {row["key"]: row["thinkingApplies"] for row in answer} == {
            "design": True,
            "code": True,
            "testing": True,
            "deployment": False,
        }
        deployment = answer[-1]
        assert (deployment["thinking"], deployment["thinkingChosen"]) == (None, False)
        # Nor which model it runs: the service is named rather than a model this
        # process merely configured.
        assert deployment["model"] == "whatever http://c4.invalid is running"

    async def test_a_model_that_takes_no_thinking_setting_is_not_offered_one(
        self, client: httpx.AsyncClient
    ) -> None:
        # A provider outside DeepSeek's is sent the same request at every level,
        # so the phase says what that request says rather than a level.
        app = client.app  # type: ignore[attr-defined]
        app.state.clients["c3"] = _SameAtEveryLevel()

        answer = (await client.get("/settings/models")).json()

        testing = next(row for row in answer if row["key"] == "testing")
        assert (testing["thinkingApplies"], testing["thinking"]) == (False, "default")

    async def test_a_level_that_is_not_one_of_the_four_is_not_saved(
        self, client: httpx.AsyncClient
    ) -> None:
        chosen = {"design": "medium", "code": None, "testing": None, "deployment": None}

        refused = await client.patch("/settings/ai", json={"thinking": chosen})

        assert 400 <= refused.status_code < 500, refused.text
        answer = (await client.get("/settings/models")).json()
        assert all(row["thinkingChosen"] is False for row in answer)

    async def test_each_phase_says_what_its_newest_recorded_run_ran_on(
        self, client: httpx.AsyncClient
    ) -> None:
        # The configuration says what the next run will use; only a run says
        # what one did use, so the tab shows both (0014).
        app = client.app  # type: ignore[attr-defined]
        async with app.state.pool.connection() as conn:
            await conn.execute(
                "INSERT INTO app.users (id, email, name) VALUES (%s, %s, %s) "
                "ON CONFLICT DO NOTHING",
                (TEST_OWNER_ID, "settings-test@example.invalid", "Settings test"),
            )
            project = await store.create_project(conn, name="Recorded run", owner_id=TEST_OWNER_ID)
            recorded = await store.create_run(
                conn, project_id=project["id"], requirements_version=1
            )
            await store.record_run_setup(
                conn, recorded["id"], model="deepseek:deepseek-flash", thinking="disabled"
            )
            # Newer, and from before runs recorded anything: not what the phase
            # last ran on, only a run that cannot say. A minute later, since
            # both rows were written in one transaction and would otherwise tie.
            unrecorded = await store.create_run(
                conn, project_id=project["id"], requirements_version=1
            )
            await conn.execute(
                "UPDATE app.runs SET started_at = started_at + interval '1 minute' WHERE id = %s",
                (unrecorded["id"],),
            )
        try:
            answer = (await client.get("/settings/models")).json()
        finally:
            async with app.state.pool.connection() as conn:
                await store.delete_project(conn, project["id"], owner_id=TEST_OWNER_ID)

        design = next(row for row in answer if row["phase"] == "Requirements and Design")
        assert design["lastRun"]["model"] == "deepseek:deepseek-flash"
        assert design["lastRun"]["thinking"] == "disabled"
        assert design["lastRun"]["project"] == "Recorded run"
        assert design["lastRun"]["startedAt"]
