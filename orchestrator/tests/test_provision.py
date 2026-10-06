"""Each project's cloud resources, made by the platform, against fake Vercel and Render APIs.

The two fakes record every request and answer as the providers' references
describe, so what is proved is what the platform asks for: a Vercel project with
its domain claimed before any deployment, a Render service on the free plan by
name (Render's own default is paid), never deploying on a push, its first deploy
cancelled, and all of it kept per project and reused. With an Atlas connection,
the project also gets its own database and a user for it alone, against a fake
Atlas that answers as Atlas does. Nothing leaves this process.
"""

import json

import httpx
import pytest
from orchestrator.crypto import decrypt, encrypt
from orchestrator.db import store
from orchestrator.deploy import provision as provisioning
from orchestrator.deploy.provision import ProvisionFailed, provision, slug_of
from orchestrator.graph.deployment_nodes import _cloud_settings
from sdlc_contracts import AtlasDatabase, CodeRepository, RepositoryPointer

from .atlas_fake import CLIENT_ID, CLUSTER, HOST, PROJECT, SECRET, FakeAtlas
from .conftest import DATABASE_URL, needs_db, refuse_the_developers_store

pytestmark = needs_db

SECRET_KEY = "a test secret with enough entropy to stand in for a real one"
OWNER = "u_test_cloud_provision"
TOKENS = {"vercel": "not-a-real-vercel-token-7a8b", "render": "rnd_not_a_real_key_9c0d"}


class FakeVercel:
    """Vercel's projects and domains, for one account."""

    def __init__(self, *, taken: frozenset[str] = frozenset(), gives_a_domain: bool = True) -> None:
        self.projects: dict[str, dict] = {}
        self.domains: dict[str, set[str]] = {}
        self.taken = taken
        #: Vercel gives a new project `<name>.vercel.app` as it creates it, as the
        #: first live cloud run found; False plays a project made without one.
        self.gives_a_domain = gives_a_domain
        self.requests: list[tuple[str, str, object]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        method, path = request.method, request.url.path
        self.requests.append((method, path, body))
        if method == "GET" and path.startswith("/v9/projects/") and path.endswith("/domains"):
            project_id = path.split("/")[3]
            names = sorted(self.domains.get(project_id, set()))
            return httpx.Response(200, json={"domains": [{"name": n} for n in names]})
        if method == "GET" and path.startswith("/v9/projects/"):
            key = path.rsplit("/", 1)[1]
            found = self.projects.get(key) or next(
                (p for p in self.projects.values() if p["name"] == key), None
            )
            return httpx.Response(200, json=found) if found else httpx.Response(404, json={})
        if (method, path) == ("POST", "/v11/projects"):
            project = {"id": f"prj_{len(self.projects) + 1}", "accountId": "team_acc", **body}
            self.projects[project["id"]] = project
            if self.gives_a_domain and f"{body['name']}.vercel.app" not in self.taken:
                self.domains[project["id"]] = {f"{body['name']}.vercel.app"}
            return httpx.Response(200, json=project)
        if method == "POST" and path.endswith("/domains"):
            project_id, name = path.split("/")[3], body["name"]
            if name in self.taken:
                return httpx.Response(409, json={"error": {"message": "already assigned"}})
            if name in self.domains.setdefault(project_id, set()):
                return httpx.Response(400, json={"error": {"message": "already exists"}})
            self.domains[project_id].add(name)
            return httpx.Response(200, json={"name": name, "verified": True})
        return httpx.Response(404, json={"message": f"{method} {path} is not faked"})

    def asked(self, method: str, suffix: str) -> list[object]:
        return [body for m, path, body in self.requests if m == method and path.endswith(suffix)]


class FakeRender:
    """Render's workspaces, services and deploys, for one workspace."""

    def __init__(self, *, refuse_repository: bool = False, refuse_variables: bool = False) -> None:
        self.services: dict[str, dict] = {}
        self.refuse_repository = refuse_repository
        self.refuse_variables = refuse_variables
        #: Each service's environment variables, as Render keeps them.
        self.env: dict[str, dict[str, str]] = {}
        self.requests: list[tuple[str, str, object]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        method, path = request.method, request.url.path
        self.requests.append((method, path, body))
        if (method, path) == ("GET", "/v1/owners"):
            return httpx.Response(200, json=[{"owner": {"id": "tea-1", "name": "sampath"}}])
        if (method, path) == ("GET", "/v1/services"):
            name = request.url.params.get("name")
            return httpx.Response(
                200,
                json=[{"service": s} for s in self.services.values() if s["name"] == name],
            )
        if "/env-vars/" in path:
            service_id, key = path.split("/")[3], path.rsplit("/", 1)[1]
            if service_id not in self.services:
                return httpx.Response(404, json={"message": "service not found"})
            if method == "PUT":
                if self.refuse_variables:
                    # Render's answers carry the variable's value.
                    return httpx.Response(400, json={"message": f"bad value {body['value']}"})
                self.env.setdefault(service_id, {})[key] = body["value"]
                return httpx.Response(200, json={"key": key, "value": body["value"]})
            if method == "DELETE":
                found = self.env.get(service_id, {}).pop(key, None)
                return httpx.Response(204) if found else httpx.Response(404, json={})
        if method == "GET" and path.startswith("/v1/services/"):
            found = self.services.get(path.rsplit("/", 1)[1])
            return httpx.Response(200, json=found) if found else httpx.Response(404, json={})
        if (method, path) == ("POST", "/v1/services"):
            if self.refuse_repository:
                return httpx.Response(400, json={"message": "repository not found"})
            service = {
                "id": f"srv-{len(self.services) + 1}",
                "name": body["name"],
                "dashboardUrl": "https://dashboard.render.com/web/srv-1",
                "serviceDetails": {"url": f"https://{body['name']}.onrender.com"},
            }
            self.services[service["id"]] = service
            return httpx.Response(201, json={"service": service, "deployId": "dep-first"})
        if method == "POST" and path.endswith("/cancel"):
            return httpx.Response(200, json={"id": "dep-first", "status": "canceled"})
        return httpx.Response(404, json={"message": f"{method} {path} is not faked"})

    def asked(self, method: str, suffix: str) -> list[object]:
        return [body for m, path, body in self.requests if m == method and path.endswith(suffix)]


@pytest.fixture
async def pool(settings):
    from orchestrator.db.pool import create_app_pool

    pool = create_app_pool(DATABASE_URL, max_size=2)
    await pool.open(wait=True)
    try:
        yield pool
    finally:
        await pool.close()


async def _project(pool, *, tokens: dict[str, str] = TOKENS) -> str:
    owner = refuse_the_developers_store(OWNER)
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO app.users (id, email, name) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (owner, "cloud-provision-test@example.invalid", "Cloud provision test"),
        )
        row = await store.create_project(conn, name="Provision case", owner_id=owner)
        for provider, value in tokens.items():
            await store.put_secret(conn, f"{owner}:{provider}", encrypt(SECRET_KEY, value))
        await store.put_settings_section(
            conn, owner, ("settings", "render"), {"region": "singapore"}
        )
        code = CodeRepository(
            version=1,
            repository=RepositoryPointer(
                owner="presenter",
                name="calculator",
                default_branch="main",
                commit_sha="1" * 40,
                url="https://github.com/presenter/calculator",
            ),
        )
        await store.put_artefact(
            conn,
            project_id=row["id"],
            kind="code-repository",
            version=1,
            body=code.model_dump(by_alias=True, mode="json"),
        )
    return row["id"]


@pytest.fixture
async def project(pool):
    project_id = await _project(pool)
    try:
        yield project_id
    finally:
        await _forget(pool, project_id)


async def _forget(pool, project_id: str) -> None:
    async with pool.connection() as conn:
        await store.delete_project(conn, project_id, owner_id=OWNER)
        for provider in (*TOKENS, "atlas", f"atlas-database:{project_id}"):
            await store.delete_secret(conn, f"{OWNER}:{provider}")
        body = await store.settings_body(conn, OWNER)
        for section in ("cloud", "settings"):
            body.pop(section, None)
        await store.put_settings_body(conn, OWNER, body)
        await conn.execute("DELETE FROM app.users WHERE id = %s", (OWNER,))


async def _provision(
    pool,
    project_id: str,
    vercel: FakeVercel,
    render: FakeRender,
    atlas: FakeAtlas | None = None,
    *,
    code_version: int = 1,
):
    v = httpx.AsyncClient(transport=httpx.MockTransport(vercel.handle))
    r = httpx.AsyncClient(transport=httpx.MockTransport(render.handle))
    a = (atlas or FakeAtlas()).client()
    try:
        return await provision(
            pool,
            project_id,
            owner=OWNER,
            secret_key=SECRET_KEY,
            code_version=code_version,
            vercel=v,
            render=r,
            atlas=a,
        )
    finally:
        await v.aclose()
        await r.aclose()
        await a.aclose()


async def _connect_atlas(pool, **settings: str) -> None:
    """The account's Atlas connection: the secret stored encrypted, the rest as settings."""
    async with pool.connection() as conn:
        await store.put_secret(conn, f"{OWNER}:atlas", encrypt(SECRET_KEY, SECRET))
        await store.put_settings_section(
            conn,
            OWNER,
            ("settings", "database"),
            {
                "provider": "mongodb_atlas",
                "clientId": CLIENT_ID,
                "projectId": PROJECT,
                "cluster": CLUSTER,
                **settings,
            },
        )


async def _kept_password(pool, project_id: str) -> str:
    async with pool.connection() as conn:
        stored = await store.get_secret(conn, f"{OWNER}:atlas-database:{project_id}")
    assert stored is not None
    return decrypt(SECRET_KEY, stored)


class TestAFirstCloudAnalysis:
    async def test_it_makes_both_and_takes_the_address_vercel_gave_the_project(
        self, pool, project
    ) -> None:
        vercel, render = FakeVercel(), FakeRender()
        made = await _provision(pool, project, vercel, render)

        name = slug_of(project)
        assert vercel.asked("POST", "/v11/projects") == [{"name": name, "framework": None}]
        assert vercel.asked("POST", "/domains") == [], "no second address beside the one it has"
        assert made.vercel.origin == f"https://{name}.vercel.app"
        assert (made.vercel.project_id, made.vercel.org_id) == ("prj_1", "team_acc")
        assert made.render.origin == f"https://{name}-api.onrender.com"
        assert made.render.owner_id == "tea-1"

    async def test_the_service_is_free_never_deploys_on_a_push_and_is_health_checked(
        self, pool, project
    ) -> None:
        render = FakeRender()
        await _provision(pool, project, FakeVercel(), render)

        [created] = render.asked("POST", "/v1/services")
        assert created["serviceDetails"]["plan"] == "free", "Render's own default is a paid plan"
        assert created["autoDeployTrigger"] == "off"
        assert created["serviceDetails"]["healthCheckPath"] == "/release.json"
        assert created["serviceDetails"]["runtime"] == "docker"
        assert created["serviceDetails"]["region"] == "singapore"
        assert created["repo"] == "https://github.com/presenter/calculator"
        assert created["branch"] == "main"

    async def test_a_version_an_accepted_fix_wrote_is_found_in_the_repository_it_patched(
        self, pool, project
    ) -> None:
        """Not pushed on its own yet, it has no pointer: the repository is the
        project's either way, which the version it patched names."""
        async with pool.connection() as conn:
            await store.put_artefact(
                conn,
                project_id=project,
                kind="code-repository",
                version=2,
                body=CodeRepository(
                    version=2, not_pushed_reason="written by applying an accepted fix"
                ).model_dump(by_alias=True, mode="json"),
            )
            await store.put_overlay(
                conn,
                project_id=project,
                version=1,
                kind="remediation_decision",
                target_id="fix-1",
                value={"decision": "accepted", "appliedCodeVersion": 2, "patchedCodeVersion": 1},
                by="presenter",
            )
        render = FakeRender()

        await _provision(pool, project, FakeVercel(), render, code_version=2)

        [created] = render.asked("POST", "/v1/services")
        assert created["repo"] == "https://github.com/presenter/calculator"

    async def test_the_repository_is_found_through_the_code_the_analysis_is_of(
        self, pool, project
    ) -> None:
        """The next sprint's code may not be on GitHub yet, and it is not what this
        analysis releases: the tested version's push names the repository. The
        newest version was asked instead, and the analysis stopped there."""
        async with pool.connection() as conn:
            await store.put_artefact(
                conn,
                project_id=project,
                kind="code-repository",
                version=2,
                body=CodeRepository(
                    version=2, not_pushed_reason="not pushed: GitHub answered 502"
                ).model_dump(by_alias=True, mode="json"),
            )
        render = FakeRender()

        await _provision(pool, project, FakeVercel(), render, code_version=1)

        [created] = render.asked("POST", "/v1/services")
        assert created["repo"] == "https://github.com/presenter/calculator"

    async def test_the_deploy_render_starts_on_creation_is_cancelled(self, pool, project) -> None:
        render = FakeRender()
        await _provision(pool, project, FakeVercel(), render)
        assert [path for m, path, _ in render.requests if path.endswith("/cancel")] == [
            "/v1/services/srv-1/deploys/dep-first/cancel"
        ]

    async def test_what_it_made_is_kept_per_project_and_reused(self, pool, project) -> None:
        vercel, render = FakeVercel(), FakeRender()
        first = await _provision(pool, project, vercel, render)
        again = await _provision(pool, project, vercel, render)

        assert again == first
        assert len(vercel.asked("POST", "/v11/projects")) == 1
        assert len(render.asked("POST", "/v1/services")) == 1
        async with pool.connection() as conn:
            body = await store.settings_body(conn, OWNER)
        assert body["cloud"][project]["render"]["serviceId"] == "srv-1"


class TestWhatTheProvidersSay:
    async def test_a_project_without_an_address_has_one_claimed(self, pool, project) -> None:
        vercel = FakeVercel(gives_a_domain=False)
        made = await _provision(pool, project, vercel, FakeRender())
        name = slug_of(project)
        assert vercel.asked("POST", "/domains") == [{"name": f"{name}.vercel.app"}]
        assert made.vercel.origin == f"https://{name}.vercel.app"

    async def test_a_taken_domain_falls_back_to_the_projects_variant(self, pool, project) -> None:
        name = slug_of(project)
        made = await _provision(
            pool,
            project,
            FakeVercel(taken=frozenset({f"{name}.vercel.app"}), gives_a_domain=False),
            FakeRender(),
        )
        assert made.vercel.origin.startswith(f"https://{name}-")
        assert made.vercel.origin.endswith(".vercel.app")

    async def test_a_service_the_provider_lost_is_made_again(self, pool, project) -> None:
        render = FakeRender()
        await _provision(pool, project, FakeVercel(), render)
        render.services.clear()

        again = await _provision(pool, project, FakeVercel(), render)

        assert len(render.asked("POST", "/v1/services")) == 2
        assert again.render.service_id == "srv-1"

    async def test_a_repository_render_cannot_read_says_what_to_do(self, pool, project) -> None:
        with pytest.raises(ProvisionFailed) as refused:
            await _provision(pool, project, FakeVercel(), FakeRender(refuse_repository=True))
        message = str(refused.value)
        assert "give it access to https://github.com/presenter/calculator" in message
        assert TOKENS["render"] not in message

    async def test_without_the_tokens_it_says_which_to_add(self, pool) -> None:
        project_id = await _project(pool, tokens={"render": TOKENS["render"]})
        try:
            with pytest.raises(ProvisionFailed, match="add the Vercel token in Settings"):
                await _provision(pool, project_id, FakeVercel(), FakeRender())
        finally:
            await _forget(pool, project_id)


class TestTheProjectsOwnDatabase:
    async def test_it_gets_a_database_and_a_user_for_that_database_alone(
        self, pool, project
    ) -> None:
        await _connect_atlas(pool)
        atlas, render = FakeAtlas(), FakeRender()

        made = await _provision(pool, project, FakeVercel(), render, atlas)

        name = slug_of(project)
        username = f"app-{name}"
        assert made.database == AtlasDatabase(
            cluster=CLUSTER,
            host=HOST,
            database=name,
            username=username,
            service_id=made.render.service_id,
        )
        user = atlas.users[username]
        assert user["databaseName"] == "admin"
        assert user["roles"] == [{"databaseName": name, "roleName": "readWrite"}]
        assert user["scopes"] == [{"name": CLUSTER, "type": "CLUSTER"}]
        password = await _kept_password(pool, project)
        assert atlas.passwords[username] == password
        assert len(password) == 48 and all(c in "0123456789abcdef" for c in password)
        assert render.env[made.render.service_id]["MONGODB_URL"] == (
            f"mongodb+srv://{username}:{password}@{HOST}/{name}"
            f"?retryWrites=true&w=majority&appName={name}"
        )
        assert atlas.revoked == atlas.issued, "every token it made is revoked"

    async def test_the_password_reaches_only_atlas_render_and_the_secrets_store(
        self, pool, project
    ) -> None:
        await _connect_atlas(pool)
        made = await _provision(pool, project, FakeVercel(), FakeRender())

        password = await _kept_password(pool, project)
        async with pool.connection() as conn:
            body = await store.settings_body(conn, OWNER)
            audit = await store.audit_trail(conn, project_id=project)
        assert password not in json.dumps(body)
        assert password not in made.model_dump_json()
        assert all(password not in json.dumps(row, default=str) for row in audit)
        assert any("MongoDB database" in str(row.get("detail")) for row in audit)

    async def test_a_second_analysis_keeps_the_password_and_puts_a_hand_edited_user_back(
        self, pool, project
    ) -> None:
        await _connect_atlas(pool)
        atlas, render = FakeAtlas(), FakeRender()
        first = await _provision(pool, project, FakeVercel(), render, atlas)
        username = f"app-{slug_of(project)}"
        atlas.users[username]["roles"] = [{"databaseName": "admin", "roleName": "atlasAdmin"}]
        url = render.env[first.render.service_id]["MONGODB_URL"]

        again = await _provision(pool, project, FakeVercel(), render, atlas)

        assert again == first
        assert atlas.users[username]["roles"] == [
            {"databaseName": slug_of(project), "roleName": "readWrite"}
        ]
        assert render.env[first.render.service_id]["MONGODB_URL"] == url

    async def test_a_password_the_platform_lost_is_replaced_everywhere(self, pool, project) -> None:
        await _connect_atlas(pool)
        atlas, render = FakeAtlas(), FakeRender()
        first = await _provision(pool, project, FakeVercel(), render, atlas)
        old = await _kept_password(pool, project)
        async with pool.connection() as conn:
            await store.delete_secret(conn, f"{OWNER}:atlas-database:{project}")

        await _provision(pool, project, FakeVercel(), render, atlas)

        new = await _kept_password(pool, project)
        username = f"app-{slug_of(project)}"
        assert new != old
        assert atlas.passwords[username] == new
        assert f":{new}@" in render.env[first.render.service_id]["MONGODB_URL"]

    async def test_without_the_connection_the_app_keeps_memory_and_the_variable_is_taken_off(
        self, pool, project
    ) -> None:
        await _connect_atlas(pool)
        render = FakeRender()
        first = await _provision(pool, project, FakeVercel(), render)
        assert "MONGODB_URL" in render.env[first.render.service_id]
        async with pool.connection() as conn:
            await store.delete_secret(conn, f"{OWNER}:atlas")

        again = await _provision(pool, project, FakeVercel(), render)

        assert again.database is None
        assert "MONGODB_URL" not in render.env[first.render.service_id]
        async with pool.connection() as conn:
            audit = await store.audit_trail(conn, project_id=project)
        assert any("keeps its records in memory" in str(row.get("detail")) for row in audit)

    async def test_without_any_atlas_connection_nothing_is_asked_of_atlas(
        self, pool, project
    ) -> None:
        atlas, render = FakeAtlas(), FakeRender()

        made = await _provision(pool, project, FakeVercel(), render, atlas)

        assert made.database is None
        assert atlas.calls == []
        assert render.env == {}

    async def test_a_connection_missing_its_settings_says_what_to_add(self, pool, project) -> None:
        await _connect_atlas(pool, projectId="")

        with pytest.raises(ProvisionFailed, match="needs the Atlas project ID in Settings"):
            await _provision(pool, project, FakeVercel(), FakeRender())

    async def test_a_refusal_that_repeats_the_connection_string_does_not_leak_it(
        self, pool, project
    ) -> None:
        await _connect_atlas(pool)

        with pytest.raises(ProvisionFailed) as refused:
            await _provision(pool, project, FakeVercel(), FakeRender(refuse_variables=True))

        password = await _kept_password(pool, project)
        message = str(refused.value)
        assert "set MONGODB_URL" in message
        assert password not in message and "[redacted]" in message


class TestTheAnalysisAsksForItsOwnCode:
    async def test_the_run_provisions_for_the_code_its_tests_measured(
        self, pool, project, monkeypatch
    ) -> None:
        """The run handed provisioning nothing, and provisioning asked for the
        newest code: the next sprint's, which this analysis does not release.
        Asked here without Vercel or Render: the request is the evidence."""
        async with pool.connection() as conn:
            await store.put_artefact(
                conn,
                project_id=project,
                kind="code-repository",
                version=2,
                body=CodeRepository(
                    version=2, not_pushed_reason="not pushed: GitHub answered 502"
                ).model_dump(by_alias=True, mode="json"),
            )
        asked: dict = {}

        class Asked(Exception):
            pass

        async def provision_for(pool, project_id: str, **kwargs):
            asked.update(kwargs, project_id=project_id)
            raise Asked

        monkeypatch.setattr(provisioning, "provision", provision_for)

        with pytest.raises(Asked):
            await _cloud_settings(pool, object(), {"project_id": project, "code_version": 1})

        assert asked["project_id"] == project and asked["code_version"] == 1
