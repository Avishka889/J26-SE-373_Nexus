"""The release targets' connections: probed once, stored encrypted, and never repeated back.

Every provider is answered by a mock transport, so nothing here reaches Vercel,
Render or GitHub. The deploy hook's probe is shown never to call anything,
because calling a deploy hook deploys; GitHub's capability is read from the
repository's visibility and the owner's plan, and a plan that cannot be read is
treated as Free.
"""

import json
from collections.abc import AsyncIterator

import httpx
import pytest
from orchestrator.api.deps import current_owner
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.main import create_app, lifespan_for_tests
from orchestrator.probes import (
    probe_render,
    probe_render_deploy_hook,
    probe_vercel,
    repository_protection,
)

from .atlas_fake import CLIENT_ID, CLUSTER, PROJECT, SECRET, FakeAtlas
from .conftest import DATABASE_URL, TEST_OWNER_ID, needs_db, refuse_the_developers_store

PLANTED = "not-a-real-token-f6e5d4c3b2"
HOOK = "https://api.render.com/deploy/srv-abc123?key=not-a-real-key-9z8y"


def _answering(routes: dict[str, httpx.Response]) -> httpx.AsyncClient:
    def answer(request: httpx.Request) -> httpx.Response:
        for prefix, response in routes.items():
            if str(request.url).startswith(prefix):
                return response
        return httpx.Response(404, json={"message": "no such route in this test"})

    return httpx.AsyncClient(transport=httpx.MockTransport(answer))


VERCEL_USER = {"user": {"id": "u1", "username": "presenter", "email": "p@example.com"}}
RENDER_OWNERS = [{"owner": {"id": "tea-1", "name": "Presenter's workspace", "type": "user"}}]


class TestTheProbes:
    async def test_vercel_names_the_account_or_says_what_it_could_not_check(self) -> None:
        ok = await probe_vercel(
            PLANTED,
            client=_answering(
                {"https://api.vercel.com/v2/user": httpx.Response(200, json=VERCEL_USER)}
            ),
        )
        assert (ok.verdict, ok.account) == ("SUITABLE", "presenter")
        limited = await probe_vercel(
            PLANTED,
            client=_answering(
                {
                    "https://api.vercel.com/v2/user": httpx.Response(
                        200, json={"user": {"id": "u1", "username": "presenter", "limited": True}}
                    )
                }
            ),
        )
        assert limited.verdict == "WORKABLE" and "limited" in limited.reason
        refused = await probe_vercel(
            PLANTED, client=_answering({"https://api.vercel.com": httpx.Response(401)})
        )
        assert refused.verdict == "UNUSABLE"

    async def test_render_names_the_workspace(self) -> None:
        ok = await probe_render(
            PLANTED,
            client=_answering(
                {"https://api.render.com/v1/owners": httpx.Response(200, json=RENDER_OWNERS)}
            ),
        )
        assert (ok.verdict, ok.account) == ("SUITABLE", "Presenter's workspace")
        empty = await probe_render(
            PLANTED,
            client=_answering({"https://api.render.com/v1/owners": httpx.Response(200, json=[])}),
        )
        assert empty.verdict == "WORKABLE"

    async def test_an_upstream_error_carrying_the_token_is_redacted(self) -> None:
        def failing(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError(f"proxy refused {PLANTED}")

        probe = await probe_render(
            PLANTED, client=httpx.AsyncClient(transport=httpx.MockTransport(failing))
        )
        assert probe.verdict == "UNUSABLE" and PLANTED not in probe.reason

    async def test_a_deploy_hook_is_checked_by_its_shape_and_never_called(self) -> None:
        calls: list[str] = []

        def recording(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            return httpx.Response(200)

        client = httpx.AsyncClient(transport=httpx.MockTransport(recording))
        good = await probe_render_deploy_hook(HOOK, client=client)
        bad = await probe_render_deploy_hook("https://example.com/deploy", client=client)
        assert (good.verdict, good.account) == ("WORKABLE", "srv-abc123")
        assert "key" not in (good.account or "") and "not-a-real-key" not in good.reason
        assert bad.verdict == "UNUSABLE" and calls == []


REPO = "https://api.github.com/repos/presenter/app"


class TestWhatGithubCanEnforce:
    @pytest.mark.parametrize(
        ("repository", "account", "expected"),
        [
            ({"private": False, "owner": {"type": "User"}}, {}, "configured"),
            (
                {"private": True, "owner": {"type": "User"}},
                {"login": "presenter", "plan": {"name": "free"}},
                "unavailable-private-repo",
            ),
            (
                {"private": True, "owner": {"type": "User"}},
                {"login": "presenter", "plan": {"name": "pro"}},
                "unavailable-plan",
            ),
            (
                {"private": True, "owner": {"type": "Organization"}},
                {"login": "presenter", "plan": {"name": "enterprise"}},
                "configured",
            ),
            (
                {"private": True, "owner": {"type": "User"}},
                {"login": "somebody-else", "plan": {"name": "enterprise"}},
                "unavailable-private-repo",
            ),
        ],
    )
    async def test_the_lock_follows_visibility_and_plan(
        self, repository, account, expected
    ) -> None:
        client = _answering(
            {
                REPO: httpx.Response(200, json=repository),
                "https://api.github.com/user": httpx.Response(200, json=account),
                "https://api.github.com/orgs/presenter": httpx.Response(200, json=account),
            }
        )
        protection, reason = await repository_protection(PLANTED, "presenter", "app", client=client)
        assert protection == expected and reason

    async def test_a_repository_that_cannot_be_read_is_not_relied_on(self) -> None:
        protection, reason = await repository_protection(
            PLANTED, "presenter", "app", client=_answering({REPO: httpx.Response(404)})
        )
        assert protection == "unavailable-private-repo" and "404" in reason


PROVIDERS = ("vercel", "render", "render-deploy-hook", "atlas")


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, lifespan_factory=lifespan_for_tests)
    app.dependency_overrides[current_owner] = lambda: TEST_OWNER_ID
    async with app.router.lifespan_context(app):
        app.state.github_client = _answering(
            {
                "https://api.vercel.com/v2/user": httpx.Response(200, json=VERCEL_USER),
                "https://api.render.com/v1/owners": httpx.Response(200, json=RENDER_OWNERS),
            }
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            try:
                yield c
            finally:
                async with app.state.pool.connection() as conn:
                    for provider in PROVIDERS:
                        await store.delete_secret(
                            conn, f"{refuse_the_developers_store(TEST_OWNER_ID)}:{provider}"
                        )
                    body = await store.settings_body(conn, TEST_OWNER_ID)
                    body.pop("connections", None)
                    await store.put_settings_body(conn, TEST_OWNER_ID, body)
                await app.state.github_client.aclose()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url=DATABASE_URL,
        database_direct_url=DATABASE_URL,
        secret_key="a test secret with enough entropy to stand in for a real one",
    )


@needs_db
class TestTheConnections:
    async def test_each_release_target_connects_and_its_value_never_comes_back(
        self, client: httpx.AsyncClient
    ) -> None:
        for provider, token in (
            ("vercel", PLANTED),
            ("render", PLANTED),
            ("render-deploy-hook", HOOK),
        ):
            created = await client.post("/connections", json={"provider": provider, "token": token})
            assert created.status_code == 201, created.text
            assert token not in created.text
        listed = await client.get("/connections")
        verdicts = {c["provider"]: c["probe"]["verdict"] for c in listed.json()["connections"]}
        assert verdicts == {
            "vercel": "SUITABLE",
            "render": "SUITABLE",
            "render-deploy-hook": "WORKABLE",
        }
        assert PLANTED not in listed.text and HOOK not in listed.text

    async def test_the_settings_say_which_targets_are_connected(
        self, client: httpx.AsyncClient
    ) -> None:
        await client.post("/connections", json={"provider": "vercel", "token": PLANTED})
        view = (await client.get("/settings")).json()
        assert view["vercel"]["connected"] is True and view["render"]["connected"] is False


@needs_db
class TestTheAtlasConnection:
    async def test_it_is_probed_with_the_accounts_atlas_settings_and_never_repeated(
        self, client: httpx.AsyncClient
    ) -> None:
        app = client.app  # type: ignore[attr-defined]
        await app.state.github_client.aclose()
        app.state.github_client = FakeAtlas().client()
        try:
            patched = await client.patch(
                "/settings/database",
                json={
                    "provider": "mongodb_atlas",
                    "clientId": CLIENT_ID,
                    "projectId": PROJECT,
                    "cluster": CLUSTER,
                },
            )
            assert patched.status_code == 200, patched.text

            created = await client.post("/connections", json={"provider": "atlas", "token": SECRET})

            assert created.status_code == 201, created.text
            assert created.json()["probe"]["verdict"] == "SUITABLE"
            assert SECRET not in created.text
            view = (await client.get("/settings")).json()
            assert view["database"]["connected"] is True
            assert view["database"]["clientId"] == CLIENT_ID
            assert SECRET not in json.dumps(view)
        finally:
            async with app.state.pool.connection() as conn:
                body = await store.settings_body(conn, TEST_OWNER_ID)
                body.get("settings", {}).pop("database", None)
                await store.put_settings_body(conn, TEST_OWNER_ID, body)

    async def test_a_check_made_with_other_identifiers_is_not_kept(
        self, client: httpx.AsyncClient
    ) -> None:
        """The check found a cluster with the identifiers it was given; once they
        change, its verdict is about something else, and it read as current."""
        app = client.app  # type: ignore[attr-defined]
        await app.state.github_client.aclose()
        app.state.github_client = FakeAtlas().client()
        identifiers = {"provider": "mongodb_atlas", "clientId": CLIENT_ID, "projectId": PROJECT}
        try:
            await client.patch("/settings/database", json={**identifiers, "cluster": CLUSTER})
            await client.post("/connections", json={"provider": "atlas", "token": SECRET})

            same = await client.patch("/settings/database", json={"cluster": CLUSTER})
            kept = await self._atlas(client)
            changed = await client.patch("/settings/database", json={"cluster": "Elsewhere0"})
            dropped = await self._atlas(client)

            assert same.status_code == changed.status_code == 200
            assert kept["probe"]["verdict"] == "SUITABLE", "an unchanged value keeps the check"
            assert dropped["probe"] is None
        finally:
            await client.delete("/connections/atlas")
            async with app.state.pool.connection() as conn:
                body = await store.settings_body(conn, TEST_OWNER_ID)
                body.get("settings", {}).pop("database", None)
                await store.put_settings_body(conn, TEST_OWNER_ID, body)

    async def _atlas(self, client: httpx.AsyncClient) -> dict:
        listed = (await client.get("/connections")).json()["connections"]
        return next(one for one in listed if one["provider"] == "atlas")
