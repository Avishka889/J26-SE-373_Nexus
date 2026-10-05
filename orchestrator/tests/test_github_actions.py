"""The cloud executor against a fake GitHub: what it asks, in what order, and what it never sends.

A mock transport plays GitHub's REST API for one repository and records every
request; the real saga carries out a real cloud deploy plan through the adapter
and the orchestrator's own checks, which a scripted prober answers for both
origins. Nothing leaves this process. What is checked:

- the candidate is committed whole (the code, the tests and the layer) on the
  branch head, a version an accepted fix wrote included, and nothing is
  committed when the branch has moved on since C2 pushed;
- every secret reaches GitHub only sealed, and opens to its value with the key
  pair the fake holds, and no request body carries a value in the clear;
- the workflow is dispatched with the commit, the candidate hash and both
  origins, and followed to its end; GitHub is asked to name the run it started,
  and when it answers 204 the run is found by GitHub's own clock;
- where GitHub has reviewers the job waiting on production is approved with the
  platform's decision, and where it has no environments none is used;
- a workflow that fails after traffic moved leaves the release for a person.
"""

import base64
import json
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
from nacl.public import PrivateKey, SealedBox
from orchestrator.crypto import encrypt
from orchestrator.db import store
from orchestrator.deploy.adapters.checks import HttpChecks
from orchestrator.deploy.adapters.github_actions import GithubActions
from orchestrator.saga.executor import StepResult, run_deployment
from sdlc_contracts import (
    BuildStepReport,
    CloudResources,
    CodeRepository,
    DeployPlan,
    DeployStep,
    DeployTarget,
    EnvironmentProtection,
    ReleaseCandidate,
    RenderService,
    RepositoryPointer,
    RollbackPolicy,
    SmokeCheck,
    VercelProject,
)
from sdlc_contracts.deploy_rules import candidate_hash

from .conftest import DATABASE_URL, needs_db, refuse_the_developers_store

pytestmark = needs_db

NOW = datetime(2026, 9, 28, tzinfo=UTC)
SECRET_KEY = "a test secret with enough entropy to stand in for a real one"
C2_COMMIT = "1" * 40
NEW_COMMIT = "2" * 40
#: What C2 pushed, the tests C3 wrote beside it, and C4's layer: the candidate.
CODE = {"apps/api/src/app.ts": "export const app = 1;\n"}
TESTS = {"apps/api/src/__tests__/US-1.criteria.test.ts": "// the approved tests\n"}
FINGERPRINT = "apps/web/public/release.json"
BACKEND, FRONTEND = "https://tt-api.onrender.com", "https://tt.vercel.app"
VALUES = {
    "github": "not-a-real-github-token-1a2b",
    "vercel": "not-a-real-vercel-token-3c4d",
}
#: What the platform made for the project: its own Vercel project and Render service.
CLOUD = CloudResources(
    vercel=VercelProject(project_id="prj_1", org_id="team_1", name="tt", origin=FRONTEND),
    render=RenderService(service_id="srv-1", name="tt-api", origin=BACKEND, owner_id="tea-1"),
    created_at=NOW,
)
LAYER = {
    "Dockerfile": "FROM node\n",
    ".github/workflows/deploy.yml": "name: Deploy\n",
    FINGERPRINT: "{}\n",
}
CANDIDATE = candidate_hash({**CODE, **TESTS, **LAYER}, fingerprint=FINGERPRINT)


class FakeGithub:
    """GitHub's REST API for one repository, recording everything it is asked.

    A dispatch is answered as GitHub answers it on the API version the adapter
    pins: 200 naming the run only when the body asks for it, 204 with no body
    otherwise. `names_the_run=False` answers 204 even when asked, so the run
    must be found among the workflow's runs; `clock` sets GitHub's clock apart
    from this machine's. Each dispatch names its stage, `test` or `deploy`:
    `failing_stage` is the one whose run ends in failure, and `vanishing` the one
    whose run never appears among the workflow's runs.
    """

    def __init__(
        self,
        *,
        private: bool = True,
        plan: str = "free",
        head: str = C2_COMMIT,
        conclusion: str = "success",
        commits: dict[str, dict] | None = None,
        names_the_run: bool = True,
        runs_appear: bool = True,
        clock: timedelta = timedelta(0),
        failing_stage: str | None = None,
        vanishing: str | None = None,
        tags: dict[str, str] | None = None,
        releases_fail: bool = False,
    ) -> None:
        self.private, self.plan, self.head, self.conclusion = private, plan, head, conclusion
        self.failing_stage, self.vanishing = failing_stage, vanishing
        #: The stage each dispatch asked for, in order.
        self.stages: list[str] = []
        #: The repository's tags, by name, and the commit each names.
        self.tags = dict(tags or {})
        #: The GitHub releases asked for, as asked; `releases_fail` refuses them.
        self.releases: list[dict] = []
        self.releases_fail = releases_fail
        #: Commits by sha, beyond C2's; any other sha reads as a commit of C2's.
        self.commits = commits or {}
        self.names_the_run, self.runs_appear, self.clock = names_the_run, runs_appear, clock
        self.key = PrivateKey.generate()
        self.requests: list[tuple[str, str, object]] = []
        self.polls = 0
        self.dispatched = False
        #: The query of every listing of the workflow's runs.
        self.listings: list[dict[str, str]] = []

    def now(self) -> datetime:
        """GitHub's clock, which need not agree with this machine's."""
        return datetime.now(UTC) + self.clock

    def listed_runs(self) -> list[dict]:
        """The workflow's dispatched runs: an earlier one on the same head, one on another
        head created last, and the one the dispatch started, listed a moment after it."""
        now = self.now()

        def run(number: int, head: str, created: datetime) -> dict:
            return {
                "id": number,
                "head_sha": head,
                "created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "html_url": f"https://github.com/presenter/tracker/actions/runs/{number}",
            }

        runs = [
            run(8, "9" * 40, now + timedelta(seconds=1)),
            run(6, self.head, now - timedelta(hours=2)),
        ]
        appears = self.runs_appear and not (self.stages and self.stages[-1] == self.vanishing)
        if self.dispatched and appears and len(self.listings) > 1:
            runs.insert(1, run(7, self.head, now))
        return runs

    def opened(self, sealed: str) -> str:
        return SealedBox(self.key).decrypt(base64.b64decode(sealed)).decode()

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        method, path = request.method, request.url.path
        self.requests.append((method, path, body))
        repo = "/repos/presenter/tracker"
        if (method, path) == ("GET", repo):
            return httpx.Response(200, json={"private": self.private, "owner": {"type": "User"}})
        if (method, path) == ("GET", "/user"):
            return httpx.Response(200, json={"login": "presenter", "plan": {"name": self.plan}})
        if (method, path) == ("GET", "/users/presenter"):
            return httpx.Response(200, json={"id": 42})
        if (method, path) == ("GET", f"{repo}/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": self.head}})
        if method == "GET" and path.startswith(f"{repo}/git/commits/"):
            default = {"tree": {"sha": "tree-0"}, "message": "C2's push", "parents": []}
            return httpx.Response(200, json=self.commits.get(path.rsplit("/", 1)[1], default))
        if (method, path) == ("POST", f"{repo}/git/trees"):
            return httpx.Response(201, json={"sha": "tree-1"})
        if (method, path) == ("POST", f"{repo}/git/commits"):
            return httpx.Response(201, json={"sha": NEW_COMMIT})
        if (method, path) == ("PATCH", f"{repo}/git/refs/heads/main"):
            return httpx.Response(200, json={"object": {"sha": NEW_COMMIT}})
        if (method, path) == ("POST", f"{repo}/git/refs"):
            name = str((body or {}).get("ref", "")).removeprefix("refs/tags/")
            if name in self.tags:
                return httpx.Response(422, json={"message": "Reference already exists"})
            self.tags[name] = (body or {}).get("sha", "")
            return httpx.Response(201, json={"ref": f"refs/tags/{name}"})
        if (method, path) == ("POST", f"{repo}/releases"):
            if self.releases_fail:
                return httpx.Response(500, json={"message": "Server Error"})
            self.releases.append(body or {})
            tag = (body or {}).get("tag_name", "")
            return httpx.Response(
                201, json={"html_url": f"https://github.com/presenter/tracker/releases/tag/{tag}"}
            )
        if (method, path) == ("PUT", f"{repo}/environments/production"):
            return httpx.Response(200, json={"name": "production"})
        if method == "GET" and path.endswith("/secrets/public-key"):
            public = base64.b64encode(bytes(self.key.public_key)).decode()
            return httpx.Response(200, json={"key_id": "key-1", "key": public})
        if method == "PUT" and "/secrets/" in path:
            return httpx.Response(201)
        if (method, path) == ("POST", f"{repo}/actions/workflows/deploy.yml/dispatches"):
            self.dispatched = True
            self.stages.append(((body or {}).get("inputs") or {}).get("stage", ""))
            self.polls = 0
            if self.names_the_run and (body or {}).get("return_run_details") is True:
                return httpx.Response(
                    200,
                    json={
                        "workflow_run_id": 7,
                        "run_url": "https://api.github.com/run/7",
                        "html_url": "https://github.com/presenter/tracker/actions/runs/7",
                    },
                )
            return httpx.Response(204, headers={"date": format_datetime(self.now(), usegmt=True)})
        if (method, path) == ("GET", f"{repo}/actions/workflows/deploy.yml/runs"):
            self.listings.append(dict(request.url.params))
            return httpx.Response(200, json={"workflow_runs": self.listed_runs()})
        if (method, path) == ("GET", f"{repo}/actions/runs/7"):
            self.polls += 1
            if self.polls < 2:
                return httpx.Response(200, json={"status": "waiting"})
            failed = self.stages and self.stages[-1] == self.failing_stage
            conclusion = "failure" if failed else self.conclusion
            return httpx.Response(200, json={"status": "completed", "conclusion": conclusion})
        if path == f"{repo}/actions/runs/7/pending_deployments":
            if method == "GET":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "environment": {"id": 9, "name": "production"},
                            "current_user_can_approve": True,
                        }
                    ],
                )
            return httpx.Response(200, json=[])
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


#: Its own owner, with a user row of its own: a project needs one, and the
#: secrets and settings written here must never be the development server's.
OWNER = "u_test_cloud_release"


@pytest.fixture
async def project(pool):
    owner = refuse_the_developers_store(OWNER)
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO app.users (id, email, name) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (owner, "cloud-release-test@example.invalid", "Cloud release test"),
        )
        row = await store.create_project(conn, name="Cloud release case", owner_id=owner)
        for provider, value in VALUES.items():
            await store.put_secret(conn, f"{owner}:{provider}", encrypt(SECRET_KEY, value))
        await store.put_settings_section(
            conn, owner, ("cloud", row["id"]), CLOUD.model_dump(by_alias=True, mode="json")
        )
        await store.put_settings_section(
            conn,
            owner,
            ("connections", "github"),
            {"provider": "github", "probe": {"login": "presenter"}},
        )
    try:
        yield row["id"]
    finally:
        async with pool.connection() as conn:
            await store.delete_project(conn, row["id"], owner_id=owner)
            for provider in VALUES:
                await store.delete_secret(conn, f"{owner}:{provider}")
            body = await store.settings_body(conn, owner)
            body.pop("connections", None)
            body.pop("settings", None)
            body.pop("cloud", None)
            await store.put_settings_body(conn, owner, body)
            await conn.execute("DELETE FROM app.users WHERE id = %s", (owner,))


def _cloud_plan(project_id: str, candidate: str = CANDIDATE) -> DeployPlan:
    return DeployPlan(
        plan_id=f"{project_id}-deploy-v1",
        project_id=project_id,
        generated_by="test",
        generated_at=NOW,
        deploy_version=1,
        stack="mern",
        target="cloud",
        candidate_hash=candidate,
        targets=[DeployTarget(role="backend", provider="render", resource="the web service")],
        steps=[
            DeployStep(id="commit", label="Commit", provider="github"),
            DeployStep(
                id="secrets",
                label="Secrets",
                provider="github",
                depends_on="commit",
                compensation="delete the secrets this release created",
            ),
            DeployStep(id="test", label="Test", provider="github", depends_on="secrets"),
            DeployStep(
                id="backend",
                label="Backend",
                provider="render",
                depends_on="test",
                compensation="redeploy the verified release, once a person approves",
                moves_traffic=True,
            ),
            DeployStep(
                id="dispatch",
                label="Dispatch",
                provider="github",
                depends_on="backend",
                compensation="redeploy the verified release, once a person approves",
                moves_traffic=True,
            ),
            DeployStep(id="verify", label="Verify", depends_on="dispatch"),
        ],
        rollback=RollbackPolicy(note="application only"),
        environment_protection=EnvironmentProtection(github="unavailable-private-repo"),
    )


class FakeBackend:
    """The backend step, as the Render adapter answers it; that adapter is tested on its own."""

    def __init__(self) -> None:
        self.deployed: list[str] = []

    async def execute(self, ctx):
        commit = (
            (ctx.earlier.get("commit") or {}).get("commit")
            if ctx.step.id == "backend"
            else ctx.previous.commit_sha
        )
        self.deployed.append(commit)
        return StepResult(resource={"commit": commit}, log=f"deployed {commit[:12]}")

    async def compensate(self, ctx):
        return None

    async def find_existing(self, ctx):
        return None


async def _release(pool, project_id: str) -> str:
    candidate = ReleaseCandidate(
        version=1,
        generated_at=NOW,
        code_version=1,
        candidate_hash=CANDIDATE,
        image="sdlc-c4-tracker:v1",
        image_digest="sha256:" + "e" * 64,
        toolchain="scripted",
        isolation="scripted",
        steps=[BuildStepReport(name="image", command="docker build .", outcome="passed")],
        smoke=[SmokeCheck(path="/", ok=True), SmokeCheck(path="/tasks", ok=True)],
        fingerprint=CANDIDATE,
    )
    code = CodeRepository(
        version=1,
        repository=RepositoryPointer(
            owner="presenter",
            name="tracker",
            default_branch="main",
            commit_sha=C2_COMMIT,
            url="https://github.com/presenter/tracker",
        ),
    )
    async with pool.connection() as conn:
        for kind, version, body in (
            ("code-repository", 1, code),
            ("deploy-plan", 1, _cloud_plan(project_id)),
            ("release-candidate", 1, candidate),
        ):
            await store.put_artefact(
                conn,
                project_id=project_id,
                kind=kind,
                version=version,
                body=body.model_dump(by_alias=True, mode="json"),
            )
        await store.put_deploy_files(
            conn, project_id, version=1, stage_id="pipeline-generation", files=LAYER
        )
        await store.put_code_files(conn, project_id, version=1, stage_id="backend-code", files=CODE)
        await store.put_code_files(
            conn, project_id, version=1, stage_id="test-generation", files=TESTS
        )
        row, _ = await store.create_deployment(
            conn,
            project_id=project_id,
            deploy_version=1,
            kind="release",
            target="cloud",
            plan_id=f"{project_id}-deploy-v1",
            candidate_hash=CANDIDATE,
            idempotency_key=f"{project_id}-cloud",
            authorised={"kind": "gate", "by": "presenter", "gateId": "g-1", "goAhead": True},
            requested_by="presenter",
        )
    return row["id"]


#: Code version 2, as applying an accepted security fix over version 1 wrote it.
FIXED = {"apps/api/src/app.ts": "export const app = 1; // escaped\n"}
FIXED_CANDIDATE = candidate_hash({**FIXED, **TESTS, **LAYER}, fingerprint=FINGERPRINT)


async def _release_of_a_fix(pool, project_id: str) -> str:
    """A release of code version 2, which an accepted fix over version 1 wrote.

    Version 1 was pushed and is C2's commit. Version 2 never was, so it has no
    pointer of its own: before 2026-10-05 it carried version 1's, and the
    release committed on that commit's tree, without the fix.
    """
    candidate = ReleaseCandidate(
        version=1,
        generated_at=NOW,
        code_version=2,
        candidate_hash=FIXED_CANDIDATE,
        image="sdlc-c4-tracker:v2",
        image_digest="sha256:" + "f" * 64,
        toolchain="scripted",
        isolation="scripted",
        steps=[BuildStepReport(name="image", command="docker build .", outcome="passed")],
        smoke=[SmokeCheck(path="/", ok=True), SmokeCheck(path="/tasks", ok=True)],
        fingerprint=FIXED_CANDIDATE,
    )
    pushed = CodeRepository(
        version=1,
        repository=RepositoryPointer(
            owner="presenter",
            name="tracker",
            default_branch="main",
            commit_sha=C2_COMMIT,
            url="https://github.com/presenter/tracker",
        ),
    )
    fixed = CodeRepository(
        version=2,
        not_pushed_reason="written by applying an accepted security fix over code version 1",
    )
    async with pool.connection() as conn:
        for kind, version, body in (
            ("code-repository", 1, pushed),
            ("code-repository", 2, fixed),
            ("deploy-plan", 1, _cloud_plan(project_id, FIXED_CANDIDATE)),
            ("release-candidate", 1, candidate),
        ):
            await store.put_artefact(
                conn,
                project_id=project_id,
                kind=kind,
                version=version,
                body=body.model_dump(by_alias=True, mode="json"),
            )
        await store.put_deploy_files(
            conn, project_id, version=1, stage_id="pipeline-generation", files=LAYER
        )
        await store.put_code_files(conn, project_id, version=1, stage_id="backend-code", files=CODE)
        await store.put_code_files(
            conn, project_id, version=2, stage_id="backend-code", files=FIXED
        )
        await store.put_code_files(
            conn, project_id, version=2, stage_id="test-generation", files=TESTS
        )
        await store.put_overlay(
            conn,
            project_id=project_id,
            version=1,
            kind="remediation_decision",
            target_id="fix-CWE-89",
            value={"decision": "accepted", "appliedCodeVersion": 2, "patchedCodeVersion": 1},
            by="presenter",
        )
        row, _ = await store.create_deployment(
            conn,
            project_id=project_id,
            deploy_version=1,
            kind="release",
            target="cloud",
            plan_id=f"{project_id}-deploy-v1",
            candidate_hash=FIXED_CANDIDATE,
            idempotency_key=f"{project_id}-cloud-fix",
            authorised={"kind": "gate", "by": "presenter", "gateId": "g-1", "goAhead": True},
            requested_by="presenter",
        )
    return row["id"]


def _origins_serving(candidate_hash: str):
    async def prober(url: str, headers: dict[str, str]):
        if url.endswith("/release.json"):
            return 200, "application/json", json.dumps({"candidateHash": candidate_hash})
        if headers.get("Accept") == "application/json":
            return 200, "application/json; charset=utf-8", "[]"
        return 200, "text/html; charset=utf-8", "<!doctype html>"

    return prober


async def _run(
    pool,
    deployment_id,
    github: FakeGithub,
    serves: str = CANDIDATE,
    backend: FakeBackend | None = None,
    **options,
):
    client = httpx.AsyncClient(transport=httpx.MockTransport(github.handle))

    async def instant(seconds):
        return None

    async def allowed(conn, row):
        return []

    try:
        return await run_deployment(
            pool,
            deployment_id,
            adapters={
                "github": GithubActions(
                    pool=pool,
                    secret_key=SECRET_KEY,
                    client=client,
                    poll_seconds=0,
                    sleep=instant,
                    **options,
                ),
                "render": backend or FakeBackend(),
                "checks": HttpChecks(prober=_origins_serving(serves)),
            },
            authorise=allowed,
        )
    finally:
        await client.aclose()


class TestACloudRelease:
    async def test_the_candidate_goes_whole_on_c2s_commit_and_both_origins_are_verified(
        self, pool, project
    ) -> None:
        github = FakeGithub()
        deployment = await _release(pool, project)
        assert await _run(pool, deployment, github) == "succeeded"

        [tree] = github.asked("POST", "/git/trees")
        # No base: the tree is exactly the files the candidate hashed.
        assert "base_tree" not in tree
        assert {entry["path"] for entry in tree["tree"]} == set(CODE) | set(TESTS) | set(LAYER)
        [commit] = github.asked("POST", "/git/commits")
        assert commit["parents"] == [C2_COMMIT] and f"Deployment {deployment}." in commit["message"]
        assert github.asked("PATCH", "/git/refs/heads/main") == [
            {"sha": NEW_COMMIT, "force": False}
        ]

        # Tested and built before anything moved traffic, then deployed (review item C4-8).
        [tested, deployed] = github.asked("POST", "/dispatches")
        inputs = {
            "ref": NEW_COMMIT,
            "candidate_hash": CANDIDATE,
            "backend_origin": BACKEND,
            "frontend_origin": FRONTEND,
        }
        assert tested["inputs"] == {"stage": "test", **inputs}
        assert deployed["inputs"] == {"stage": "deploy", **inputs}
        async with pool.connection() as conn:
            row = await store.get_deployment(conn, deployment)
        assert row["verified"] and row["fingerprint"]["commitSha"] == NEW_COMMIT

    async def test_a_version_an_accepted_fix_wrote_is_released_with_the_fix(
        self, pool, project
    ) -> None:
        """Never pushed, it is released on the patched version's commit with its own
        files whole, so production runs the fix the fingerprint names."""
        github = FakeGithub()
        deployment = await _release_of_a_fix(pool, project)

        assert await _run(pool, deployment, github, serves=FIXED_CANDIDATE) == "succeeded"

        [tree] = github.asked("POST", "/git/trees")
        committed = {entry["path"]: entry["content"] for entry in tree["tree"]}
        assert committed["apps/api/src/app.ts"] == FIXED["apps/api/src/app.ts"]
        [commit] = github.asked("POST", "/git/commits")
        assert commit["parents"] == [C2_COMMIT]
        dispatches = github.asked("POST", "/dispatches")
        assert [dispatch["inputs"]["candidate_hash"] for dispatch in dispatches] == [
            FIXED_CANDIDATE,
            FIXED_CANDIDATE,
        ]

    async def test_every_secret_arrives_sealed_and_opens_to_its_value(self, pool, project) -> None:
        github = FakeGithub()
        await _run(pool, await _release(pool, project), github)
        sealed = {
            path.rsplit("/", 1)[1]: body["encrypted_value"]
            for method, path, body in github.requests
            if method == "PUT" and "/actions/secrets/" in path
        }
        # No Render credential: the platform deploys the backend through Render's API.
        assert {name: github.opened(value) for name, value in sealed.items()} == {
            "VERCEL_TOKEN": VALUES["vercel"],
            "VERCEL_ORG_ID": "team_1",
            "VERCEL_PROJECT_ID": "prj_1",
        }
        in_the_clear = json.dumps([body for _, _, body in github.requests])
        assert all(value not in in_the_clear for value in VALUES.values())

    async def test_the_backend_is_deployed_from_the_layer_commit_before_the_dispatch(
        self, pool, project
    ) -> None:
        backend = FakeBackend()
        deployment = await _release(pool, project)
        assert await _run(pool, deployment, FakeGithub(), backend=backend) == "succeeded"
        assert backend.deployed == [NEW_COMMIT]
        async with pool.connection() as conn:
            steps = await store.deployment_steps(conn, deployment)
        assert [step["step_id"] for step in steps] == [
            "commit",
            "secrets",
            "test",
            "backend",
            "dispatch",
            "verify",
        ]


async def _said(pool, project_id: str) -> dict[str, str]:
    """What Activity recorded for the project, action to detail."""
    async with pool.connection() as conn, conn.cursor() as cur:
        await cur.execute(
            "SELECT action, detail FROM app.audit_events WHERE project_id = %s", (project_id,)
        )
        return {action: detail for action, detail in await cur.fetchall()}


class TestAReleaseIsTaggedWithItsNotes:
    """A release had no version in the repository, no tag and no notes: nothing
    there said which commit a deploy version was (review item C4-7)."""

    async def test_a_verified_release_is_tagged_at_its_commit_with_what_it_ships(
        self, pool, project
    ) -> None:
        github = FakeGithub()
        assert await _run(pool, await _release(pool, project), github) == "succeeded"

        [release] = github.releases
        assert (release["tag_name"], release["target_commitish"]) == ("release-v1", NEW_COMMIT)
        assert release["name"] == "Deploy version 1"
        assert release["body"].splitlines()[:2] == [
            "Deploy version 1.",
            f"Code version 1. Candidate {CANDIDATE[:12]}.",
        ]
        said = await _said(pool, project)
        assert said["Tagged the release"].startswith("release-v1 at ")
        assert "Code version 1." in said["Tagged the release"]

    async def test_a_tag_github_refuses_does_not_undo_a_verified_release(
        self, pool, project
    ) -> None:
        github = FakeGithub(releases_fail=True)

        assert await _run(pool, await _release(pool, project), github) == "succeeded"

        said = await _said(pool, project)
        assert "Could not tag the release" in said
        assert "Deploy version 1." in said["Could not tag the release"]


class TestTheReleaseShipsWhatStagingVerified:
    """C3 writes its tests beside the code, so staging built the candidate with
    them, and a release committed only C2's tree and C4's layer: the repository
    held no test the platform approved, and GitHub's run tested less than
    staging had. The tests are committed now, after the tree is held to the
    candidate's hash."""

    async def test_the_tests_testing_wrote_are_committed_with_the_code_and_the_layer(
        self, pool, project
    ) -> None:
        github = FakeGithub()
        deployment = await _release(pool, project)

        assert await _run(pool, deployment, github) == "succeeded"

        [tree] = github.asked("POST", "/git/trees")
        assert {entry["path"]: entry["content"] for entry in tree["tree"]} == {
            **CODE,
            **TESTS,
            **LAYER,
        }

    async def test_a_test_rewritten_after_staging_is_never_committed(self, pool, project) -> None:
        """A testing run writes its tests at the code version, so it can change
        them under a candidate waiting at the review."""
        deployment = await _release(pool, project)
        async with pool.connection() as conn:
            await store.put_code_files(
                conn,
                project,
                version=1,
                stage_id="test-generation",
                files={path: "// written again\n" for path in TESTS},
            )
        github = FakeGithub()

        assert await _run(pool, deployment, github) == "compensated"

        assert github.asked("POST", "/git/commits") == []
        async with pool.connection() as conn:
            row = await store.get_deployment(conn, deployment)
        assert f"not to candidate {CANDIDATE[:12]}" in row["cause"]
        assert "files nobody verified" in row["cause"]


class TestTheDispatch:
    """GitHub answered the first live cloud release's dispatch 204 with no body, and the
    release stopped at a workflow that had succeeded: on the API version the adapter
    pins, GitHub names the run a dispatch started only when asked, and the fake had
    always named it."""

    async def test_it_asks_github_to_name_the_run_it_started(self, pool, project) -> None:
        github = FakeGithub()
        assert await _run(pool, await _release(pool, project), github) == "succeeded"
        dispatches = github.asked("POST", "/dispatches")
        assert [dispatch["return_run_details"] for dispatch in dispatches] == [True, True]
        assert github.listings == [], "a run GitHub named needs no looking for"
        # A release runs the workflow it just committed, on the branch; only a
        # rollback goes to a tag.
        assert [dispatch["ref"] for dispatch in dispatches] == ["main", "main"]
        assert github.tags == {}

    async def test_a_204_is_followed_to_the_run_the_dispatch_started(self, pool, project) -> None:
        github = FakeGithub(names_the_run=False)
        deployment = await _release(pool, project)
        assert await _run(pool, deployment, github, run_appears_timeout=1) == "succeeded"
        assert github.listings[0] == {
            "event": "workflow_dispatch",
            "branch": "main",
            "per_page": "10",
        }
        runs = "/repos/presenter/tracker/actions/runs/"
        followed = {path.removeprefix(runs) for m, path, _ in github.requests if runs in path}
        assert followed == {"7"}, "not the earlier run on the same head, nor another head's"

    async def test_githubs_own_clock_says_which_run_is_new(self, pool, project) -> None:
        # By this machine's clock, ten minutes ahead of GitHub's, the new run looks old.
        github = FakeGithub(names_the_run=False, clock=timedelta(minutes=-10))
        deployment = await _release(pool, project)
        assert await _run(pool, deployment, github, run_appears_timeout=1) == "succeeded"

    async def test_a_run_that_never_appears_waits_for_a_person(self, pool, project) -> None:
        github = FakeGithub(names_the_run=False, vanishing="deploy")
        deployment = await _release(pool, project)
        result = await _run(pool, deployment, github, run_appears_timeout=0.05)
        assert result == "awaiting-rollback-approval"
        async with pool.connection() as conn:
            row = await store.get_deployment(conn, deployment)
        assert "no run of it appeared" in row["cause"]


class TestWhatGithubEnforces:
    async def test_a_private_free_repository_uses_repository_secrets_and_no_environment(
        self, pool, project
    ) -> None:
        github = FakeGithub(private=True, plan="free")
        await _run(pool, await _release(pool, project), github)
        assert github.asked("PUT", "/environments/production") == []
        assert github.asked("POST", "/pending_deployments") == []

    async def test_a_private_repository_on_a_paid_plan_keeps_its_secrets_in_the_repository(
        self, pool, project
    ) -> None:
        """GitHub has environments there but no reviewers, and the workflow names no
        environment, so secrets put in one would be read by nothing."""
        github = FakeGithub(private=True, plan="pro")
        await _run(pool, await _release(pool, project), github)
        assert github.asked("PUT", "/environments/production") == []
        assert any("/actions/secrets/" in path for _, path, _ in github.requests)

    async def test_a_public_repository_mirrors_the_platforms_decision_in_githubs_rule(
        self, pool, project
    ) -> None:
        github = FakeGithub(private=False)
        await _run(pool, await _release(pool, project), github)
        assert github.asked("PUT", "/environments/production") == [
            {"reviewers": [{"type": "User", "id": 42}]}
        ]
        assert any("/environments/production/secrets/" in path for _, path, _ in github.requests)
        assert github.asked("POST", "/pending_deployments") == [
            {
                "environment_ids": [9],
                "state": "approved",
                "comment": "Approved at the platform's deployment review by presenter.",
            }
        ]


class TestWhatStopsIt:
    async def test_a_branch_that_moved_on_is_not_committed_on(self, pool, project) -> None:
        github = FakeGithub(
            head="9" * 40,
            commits={
                "9" * 40: {
                    "tree": {"sha": "tree-other"},
                    "message": "Somebody's own change",
                    "parents": [{"sha": C2_COMMIT}],
                }
            },
        )
        deployment = await _release(pool, project)
        assert await _run(pool, deployment, github) == "compensated"
        assert github.asked("POST", "/git/commits") == []
        async with pool.connection() as conn:
            row = await store.get_deployment(conn, deployment)
        assert "moved on" in row["cause"] and "nobody verified" in row["cause"]

    async def test_a_commit_that_fails_its_tests_never_reaches_render(self, pool, project) -> None:
        """The backend went live before the workflow tested the commit, so a failing
        test needed a rollback a person decides (review item C4-8)."""
        github, backend = FakeGithub(failing_stage="test"), FakeBackend()
        deployment = await _release(pool, project)

        assert await _run(pool, deployment, github, backend=backend) == "compensated"

        assert backend.deployed == [], "Render was never asked"
        assert github.stages == ["test"], "the deploy stage was never dispatched"
        async with pool.connection() as conn:
            row = await store.get_deployment(conn, deployment)
        assert row["cause"].startswith(
            "test failed: the deploy workflow's test stage ended failure"
        )

    async def test_a_workflow_that_fails_after_traffic_moved_waits_for_a_person(
        self, pool, project
    ) -> None:
        github = FakeGithub(failing_stage="deploy")
        deployment = await _release(pool, project)
        assert await _run(pool, deployment, github) == "awaiting-rollback-approval"
        assert [m for m, path, _ in github.requests if m == "DELETE"] == []
        async with pool.connection() as conn:
            row = await store.get_deployment(conn, deployment)
        assert "ended failure" in row["cause"] and "actions/runs/7" in row["cause"]


async def _finished_release(pool, project_id: str, key: str) -> str:
    """An earlier release of this project, finished, whose layer the branch may sit on."""
    async with pool.connection() as conn:
        row, _ = await store.create_deployment(
            conn,
            project_id=project_id,
            deploy_version=1,
            kind="release",
            target="cloud",
            plan_id=f"{project_id}-deploy-v1",
            candidate_hash=CANDIDATE,
            idempotency_key=key,
            authorised={"kind": "gate", "by": "presenter", "gateId": "g-0", "goAhead": True},
            requested_by="presenter",
        )
        await store.finish_deployment(conn, row["id"], state="succeeded", verified=True)
    return str(row["id"])


def _layer(deployment_id: str, parent: str) -> dict:
    """A commit as the commit step makes it: C2's tree plus a layer, naming its deployment."""
    return {
        "tree": {"sha": "tree-layer"},
        "message": (
            f"Deployment layer for deploy version 1\n\nCandidate {CANDIDATE}.\n"
            f"Deployment {deployment_id}."
        ),
        "parents": [{"sha": parent}],
    }


LAYER_COMMIT, HAND_COMMIT = "3" * 40, "4" * 40


class TestALaterRelease:
    """A code version's first cloud release moves the branch to its layer commit, and the
    next release found the branch moved and refused it, so a code version could reach the
    cloud once. A later release now builds on the platform's own layers, and on nothing else."""

    async def test_it_builds_on_an_earlier_layer_and_still_ships_c2s_tree(
        self, pool, project
    ) -> None:
        earlier = await _finished_release(pool, project, f"{project}-earlier")
        github = FakeGithub(head=LAYER_COMMIT, commits={LAYER_COMMIT: _layer(earlier, C2_COMMIT)})
        deployment = await _release(pool, project)

        assert await _run(pool, deployment, github) == "succeeded"
        [tree] = github.asked("POST", "/git/trees")
        # The candidate's files whole, so nothing of the earlier layer's lingers.
        assert "base_tree" not in tree
        assert {entry["path"] for entry in tree["tree"]} == set(CODE) | set(TESTS) | set(LAYER)
        [commit] = github.asked("POST", "/git/commits")
        assert commit["parents"] == [LAYER_COMMIT]

    async def test_a_commit_nobody_on_the_platform_made_is_refused_after_a_layer(
        self, pool, project
    ) -> None:
        earlier = await _finished_release(pool, project, f"{project}-earlier")
        github = FakeGithub(
            head=HAND_COMMIT,
            commits={
                LAYER_COMMIT: _layer(earlier, C2_COMMIT),
                HAND_COMMIT: {
                    "tree": {"sha": "tree-hand"},
                    "message": "Fix a typo by hand",
                    "parents": [{"sha": LAYER_COMMIT}],
                },
            },
        )
        deployment = await _release(pool, project)

        assert await _run(pool, deployment, github) == "compensated"
        assert github.asked("POST", "/git/commits") == []
        async with pool.connection() as conn:
            row = await store.get_deployment(conn, deployment)
        assert HAND_COMMIT[:12] in row["cause"] and "nobody verified" in row["cause"]

    async def test_a_commit_landing_the_verified_tree_is_the_code_it_was_built_from(
        self, pool, project
    ) -> None:
        """An approved version lands on the default branch by a commit of its own
        when the branch had moved on since the version was pushed: exactly the
        version's tree, on top of an earlier release's layer."""
        earlier = await _finished_release(pool, project, f"{project}-earlier")
        landing = "6" * 40
        github = FakeGithub(
            head=landing,
            commits={
                landing: {
                    "tree": {"sha": "tree-0"},
                    "message": "Code version 2, approved",
                    "parents": [{"sha": LAYER_COMMIT}],
                },
                LAYER_COMMIT: _layer(earlier, "7" * 40),
            },
        )
        deployment = await _release(pool, project)

        assert await _run(pool, deployment, github) == "succeeded"
        [commit] = github.asked("POST", "/git/commits")
        assert commit["parents"] == [landing]

    async def test_a_layer_naming_another_projects_deployment_is_not_trusted(
        self, pool, project
    ) -> None:
        stranger = "5d6b1f0e-8c1a-4c2e-9f55-0a1b2c3d4e5f"
        github = FakeGithub(head=LAYER_COMMIT, commits={LAYER_COMMIT: _layer(stranger, C2_COMMIT)})
        deployment = await _release(pool, project)

        assert await _run(pool, deployment, github) == "compensated"
        assert github.asked("POST", "/git/commits") == []


class TestACloudRollback:
    @pytest.mark.parametrize("tagged_before", [False, True])
    async def test_the_verified_commit_is_redeployed_and_its_fingerprint_checked(
        self, pool, project, tagged_before
    ) -> None:
        from sdlc_contracts import RestoreStep, RollbackPlan, VerificationCheck, VerifiedRelease

        verified_hash, verified_commit = "a" * 64, "3" * 40
        # The verified release's own tag: deploy version 1, at its commit.
        tag = "verified-v1-3333333"
        async with pool.connection() as conn:
            verified, _ = await store.create_deployment(
                conn,
                project_id=project,
                deploy_version=1,
                kind="release",
                target="cloud",
                plan_id="an-earlier-plan",
                candidate_hash=verified_hash,
                idempotency_key=f"{project}-earlier",
                authorised={"kind": "gate", "by": "presenter", "gateId": "g-0"},
                requested_by="presenter",
            )
            await store.finish_deployment(
                conn,
                verified["id"],
                state="succeeded",
                verified=True,
                fingerprint={"candidateHash": verified_hash, "commitSha": verified_commit},
            )
            failed, _ = await store.create_deployment(
                conn,
                project_id=project,
                deploy_version=2,
                kind="release",
                target="cloud",
                plan_id="the-failed-plan",
                candidate_hash=CANDIDATE,
                idempotency_key=f"{project}-failed",
                authorised={"kind": "gate", "by": "presenter", "gateId": "g-1"},
                requested_by="presenter",
            )
            await store.finish_deployment(
                conn, failed["id"], state="awaiting-rollback-approval", cause="smoke failed"
            )
            plan = RollbackPlan(
                version=2,
                generated_at=NOW,
                candidate_hash=CANDIDATE,
                restore_target=VerifiedRelease(
                    deployment_id=str(verified["id"]),
                    deploy_version=1,
                    candidate_hash=verified_hash,
                    target="cloud",
                    commit_sha=verified_commit,
                    verified_at=NOW,
                ),
                restorable=True,
                steps=[
                    RestoreStep(
                        id="restore-backend",
                        label="Redeploy the backend",
                        provider="render",
                        action="deploy the verified commit on Render",
                        moves_traffic=True,
                    ),
                    RestoreStep(
                        id="redeploy-frontend",
                        label="Redeploy the frontend",
                        provider="github",
                        action="dispatch deploy.yml with the verified commit",
                        moves_traffic=True,
                    ),
                ],
                checks=[
                    VerificationCheck(id="fp", kind="fingerprint", role="frontend", expect="a")
                ],
            )
            await store.put_artefact(
                conn,
                project_id=project,
                kind="rollback-plan",
                version=2,
                body=plan.model_dump(by_alias=True, mode="json"),
            )
            for kind, version, body in (
                (
                    "code-repository",
                    1,
                    CodeRepository(
                        version=1,
                        repository=RepositoryPointer(
                            owner="presenter",
                            name="tracker",
                            default_branch="main",
                            commit_sha=C2_COMMIT,
                            url="https://github.com/presenter/tracker",
                        ),
                    ),
                ),
            ):
                await store.put_artefact(
                    conn,
                    project_id=project,
                    kind=kind,
                    version=version,
                    body=body.model_dump(by_alias=True, mode="json"),
                )
            rollback, _ = await store.create_deployment(
                conn,
                project_id=project,
                deploy_version=1,
                kind="rollback",
                target="cloud",
                plan_id=f"{project}-rollback-v2",
                candidate_hash=verified_hash,
                idempotency_key=f"{project}-rollback",
                authorised={
                    "kind": "rollback",
                    "by": "presenter",
                    "deploymentId": str(failed["id"]),
                    "fromVersion": 2,
                },
                requested_by="presenter",
                restores=verified["id"],
            )
        github = FakeGithub(tags={tag: verified_commit} if tagged_before else None)
        backend = FakeBackend()
        assert (
            await _run(pool, rollback["id"], github, serves=verified_hash, backend=backend)
            == "succeeded"
        )
        assert backend.deployed == [verified_commit]
        [dispatch] = github.asked("POST", "/dispatches")
        # On the verified commit's own tag, so the workflow that runs is the one
        # that release shipped. On the branch, the newer release's workflow ran
        # the older code against the newer smoke list (review item C4-4).
        assert dispatch["ref"] == tag
        assert github.tags == {tag: verified_commit}
        assert github.asked("POST", "/git/refs") == [
            {"ref": f"refs/tags/{tag}", "sha": verified_commit}
        ]
        assert (dispatch["inputs"]["ref"], dispatch["inputs"]["candidate_hash"]) == (
            verified_commit,
            verified_hash,
        )
        assert dispatch["inputs"]["stage"] == "deploy", "a verified commit is not tested again"
        assert github.asked("POST", "/git/commits") == [], "a rollback commits nothing"
        assert github.releases == [], "and is not a release to tag"
        async with pool.connection() as conn:
            assert (await store.get_deployment(conn, failed["id"]))["state"] == "rolled-back"


@pytest.mark.cloud
async def test_a_real_repository_says_what_github_can_enforce() -> None:
    """Read only, and only on request: `-m cloud`, with C4_CLOUD_TEST_REPO=owner/name
    and GITHUB_TOKEN set. It changes nothing on GitHub."""
    import os

    from orchestrator.probes import repository_protection

    target = os.environ.get("C4_CLOUD_TEST_REPO", "")
    token = os.environ.get("GITHUB_TOKEN", "")
    if "/" not in target or not token:
        pytest.skip("set C4_CLOUD_TEST_REPO=owner/name and GITHUB_TOKEN to run it")
    owner, name = target.split("/", 1)
    protection, reason = await repository_protection(token, owner, name)
    assert protection in {"configured", "unavailable-plan", "unavailable-private-repo"} and reason
