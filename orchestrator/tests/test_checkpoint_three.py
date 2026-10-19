"""Checkpoint 3, walked on the local target, on real containers.

The plan's walk, in order, through the orchestrator's own routes, graph, guards,
saga, monitor and scenarios; only the component is a stand in. Its analysis is
the canned one, and its candidates are real: each deploy version gets its own
candidate hash and a small image that serves it, and its rollback plans are
written by C4's own builder. The steps:

1. the baseline release, reviewed, because a first release always is;
2. a Low update, released without a review under the policy a person set;
3. a Medium update, held at the review until a person approves it;
4. a High update, reviewed, with its rollback prepared to the release before;
5. a controlled failure injected (`stop-container`);
6. monitoring finding the release down, and a rollback waiting on a person;
7. that person approving the rollback (here, the test, in their place);
8. the guard reporting restored because the verified fingerprint is served again.

Marked `docker`: it builds four small images and runs them in its own lane on a
free port, and removes everything it made.
"""

import hashlib
import json
import socket
import subprocess
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from orchestrator.clients.c1 import StageOutcome
from orchestrator.clients.c4 import PipelineOutcome
from orchestrator.clients.canned_c4 import CannedC4
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.deploy import scenarios
from orchestrator.deploy.adapters.checks import HttpChecks
from orchestrator.deploy.adapters.local_docker import LocalDocker, docker
from orchestrator.deploy.monitor import watch
from orchestrator.main import create_app, lifespan_for_tests
from orchestrator.saga.executor import run_deployment
from orchestrator.saga.runner import authorise_release
from sdlc_contracts import (
    BuildStepReport,
    DeployPlan,
    DeployStep,
    DeployTarget,
    EnvironmentProtection,
    ExcludedUpdate,
    ReleaseCandidate,
    RollbackPolicy,
    SmokeCheck,
)

from .conftest import needs_db
from .test_deployment_spine import _start_deploy_run, _tested
from .test_local_release import NODE, SERVER
from .test_testing_spine import _advance

pytestmark = needs_db

LANE = "test-walk"
PERSON = "the presenter"


def _docker_answers() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, check=False).returncode == 0
    except FileNotFoundError:
        return False


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class WalkC4(CannedC4):
    """The canned analysis, with candidates that are real and differ per version."""

    def __init__(self, tmp: Path) -> None:
        super().__init__()
        self.tmp = tmp

    @staticmethod
    def hash_for(version: int) -> str:
        return hashlib.sha256(f"walk-candidate-v{version}".encode()).hexdigest()

    async def generate_pipeline(self, files, updates, risk, *, version, **kwargs):
        canned = await super().generate_pipeline(files, updates, risk, version=version, **kwargs)
        digest = self.hash_for(version)
        plan = DeployPlan(
            plan_id=f"walk-v{version}",
            project_id="walk",
            generated_by="walk",
            generated_at=datetime.now(UTC),
            deploy_version=version,
            stack="mern",
            target="local",
            candidate_hash=digest,
            targets=[DeployTarget(role="app", provider="local-docker", resource="the image")],
            steps=[
                DeployStep(id="start", label="Start", provider="local-docker", compensation="stop"),
                DeployStep(id="check", label="Check", depends_on="start"),
                DeployStep(
                    id="switch",
                    label="Switch",
                    provider="local-docker",
                    depends_on="check",
                    compensation="restore the verified release, once a person approves",
                    moves_traffic=True,
                ),
                DeployStep(id="verify", label="Verify", depends_on="switch"),
            ],
            rollback=RollbackPolicy(note="application only"),
            environment_protection=EnvironmentProtection(github="not-applicable"),
        )
        return PipelineOutcome(
            config=canned.config.model_copy(update={"candidate_hash": digest}),
            plan=plan,
            files=canned.files,
            summary=canned.summary,
            notes={},
        )

    def _image(self, version: int, candidate_hash: str) -> tuple[str, str]:
        context = self.tmp / f"v{version}"
        context.mkdir(exist_ok=True)
        (context / "server.mjs").write_text(SERVER)
        (context / "release.json").write_text(json.dumps({"candidateHash": candidate_hash}))
        (context / "Dockerfile").write_text(
            f"FROM {NODE}\nWORKDIR /app\nCOPY server.mjs release.json /app/\n"
            'EXPOSE 3001\nUSER 1000:1000\nCMD ["node", "server.mjs"]\n'
        )
        tag = f"sdlc-c4-walk:v{version}"
        subprocess.run(
            ["docker", "build", "-q", "--label", f"sdlc.c4.lane={LANE}", "-t", tag, str(context)],
            check=True,
            capture_output=True,
        )
        digest = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", tag],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        return tag, digest

    async def verify_candidate(
        self, files, layer, *, candidate_hash, included, excluded, version, code_version, **_
    ):
        self._called("staging-verification")
        tag, digest = self._image(version, candidate_hash)
        candidate = ReleaseCandidate(
            version=version,
            generated_at=datetime.now(UTC),
            code_version=code_version,
            candidate_hash=candidate_hash,
            included=included,
            excluded=[ExcludedUpdate.model_validate(item) for item in excluded],
            image=tag,
            image_digest=digest,
            toolchain="docker, a small image that serves the candidate's fingerprint",
            isolation="a container on loopback",
            steps=[
                BuildStepReport(name=name, command=name, outcome="passed", duration_seconds=0.1)
                for name in ("candidate", "lockfile", "install", "test", "image", "boot")
            ],
            smoke=[
                SmokeCheck(path="/", status_code=200, ok=True),
                SmokeCheck(path="/tasks", status_code=200, ok=True),
            ],
            fingerprint=candidate_hash,
        )
        return StageOutcome(artefact=candidate, summary="verified", notes={})

    async def plan_rollback(
        self, candidate, risk, previous, *, release_target, version, database=False
    ):
        from c4.rollback.plan import plan

        self._called("rollback-planning")
        prepared = plan(
            candidate,
            risk,
            previous,
            release_target=release_target,
            version=version,
            database=database,
        )
        return StageOutcome(artefact=prepared, summary="planned", notes={})


@pytest.fixture
async def walk(settings: Settings, tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    if not _docker_answers():
        pytest.skip("no Docker daemon answers")
    app = create_app(settings, lifespan_factory=lifespan_for_tests)
    app.state.c4 = WalkC4(tmp_path)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            client.app = app  # type: ignore[attr-defined]
            created: list[str] = []
            client.created_projects = created  # type: ignore[attr-defined]
            try:
                yield client
            finally:
                async with app.state.pool.connection() as conn:
                    from orchestrator.api.deps import DEV_OWNER_ID

                    for project_id in created:
                        await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)
                _, containers = await docker(
                    ["ps", "-aq", "--filter", f"label=sdlc.c4.lane={LANE}"]
                )
                for container in containers.split():
                    await docker(["rm", "-f", container])
                _, images = await docker(["images", "-q", "--filter", f"label=sdlc.c4.lane={LANE}"])
                for image in set(images.split()):
                    await docker(["rmi", "-f", image])


async def _run(client, project_id: str, test_version: int, packages: list[str]) -> tuple[dict, int]:
    await client.post(
        f"/projects/{project_id}/deployment/scope",
        json={"target": "generated", "packages": packages, "by": PERSON},
    )
    run, version = await _start_deploy_run(client, project_id, test_version)
    await _advance(client, run["id"])
    return run, version


async def _approve(client, project_id: str, run_id, note: str) -> None:
    snapshot = (await client.get(f"/projects/{project_id}/deployment")).json()
    for view in snapshot["decisions"]:
        if view["needsDecision"]:
            await client.post(
                f"/projects/{project_id}/deployment/updates/{view['updateId']}/decision",
                json={"decision": "approved", "by": PERSON, "note": note},
            )
    answer = await client.post(
        f"/projects/{project_id}/deployment/decision", json={"kind": "approved", "by": PERSON}
    )
    assert answer.status_code == 200, answer.text
    await _advance(client, run_id)


async def _carry_out(client, project_id: str, port: int) -> dict:
    """The saga runner's work, done here: the pending deployment, carried to its end."""
    pool = client.app.state.pool
    async with pool.connection() as conn:
        [pending] = [
            row
            for row in await store.list_deployments(conn, project_id, limit=50)
            if row["state"] == "pending"
        ]
    state = await run_deployment(
        pool,
        pending["id"],
        adapters={
            "local-docker": LocalDocker(release_port=port, lane=LANE),
            "checks": HttpChecks(),
        },
        authorise=authorise_release,
    )
    async with pool.connection() as conn:
        row = await store.get_deployment(conn, pending["id"])
    assert state == "succeeded" and row["verified"], row.get("cause")
    return row


async def _review_waits(client, project_id: str) -> bool:
    async with client.app.state.pool.connection() as conn:
        gate = await store.pending_gate(conn, project_id=project_id, kind="c4-deploy-review")
    return gate is not None


async def _levels(client, project_id: str) -> dict[str, str]:
    """Each update at the current deploy version, by package, at its final level."""
    risk = (await client.get(f"/projects/{project_id}/deployment")).json()["risk"]
    return {item["package"]: item["arbitration"]["final"] for item in risk["assessments"]}


async def _served(port: int) -> str:
    async with httpx.AsyncClient(timeout=10) as http:
        answer = await http.get(f"http://127.0.0.1:{port}/release.json")
    return answer.json()["candidateHash"]


@pytest.mark.docker
async def test_checkpoint_three_on_the_local_target(walk) -> None:
    client = walk
    port = _free_port()
    project_id, _, test_version = await _tested(client)
    pool = client.app.state.pool

    # 1. The baseline release: nothing to update, and reviewed, as a first release is.
    run, first = await _run(client, project_id, test_version, [])
    assert await _levels(client, project_id) == {}
    assert await _review_waits(client, project_id)
    await _approve(client, project_id, run["id"], "the baseline")
    baseline = await _carry_out(client, project_id, port)
    assert await _served(port) == WalkC4.hash_for(first)

    # 2. A Low update, released under the policy, with no review.
    await client.post(
        f"/projects/{project_id}/deployment/policy", json={"autoDeployLow": True, "by": PERSON}
    )
    _, low = await _run(client, project_id, test_version, ["vite"])
    assert await _levels(client, project_id) == {"vite": "low"}
    assert not await _review_waits(client, project_id)
    automatic = await _carry_out(client, project_id, port)
    assert automatic["authorised"]["kind"] == "policy"
    assert await _served(port) == WalkC4.hash_for(low)

    # 3. A Medium update, held at the review until a person approves it.
    run, medium = await _run(client, project_id, test_version, ["zod"])
    assert await _levels(client, project_id) == {"zod": "medium"}
    assert await _review_waits(client, project_id)
    snapshot = (await client.get(f"/projects/{project_id}/deployment")).json()
    assert {blocker["code"] for blocker in snapshot["blocking"]} == {"G1"}
    await _approve(client, project_id, run["id"], "reviewed the minor")
    held = await _carry_out(client, project_id, port)
    assert held["authorised"]["kind"] == "gate"

    # 4. A High update, reviewed, with its rollback prepared to the release before.
    run, high = await _run(client, project_id, test_version, ["express"])
    assert await _levels(client, project_id) == {"express": "high"}
    assert await _review_waits(client, project_id)
    snapshot = (await client.get(f"/projects/{project_id}/deployment")).json()
    assert snapshot["rollback"]["restorable"]
    assert snapshot["rollback"]["restoreTarget"]["candidateHash"] == WalkC4.hash_for(medium)
    await _approve(client, project_id, run["id"], "reviewed the major: the del routes moved")
    reviewed = await _carry_out(client, project_id, port)
    assert await _served(port) == WalkC4.hash_for(high)

    # 5. A controlled failure: the release container is stopped.
    await scenarios.inject(pool, project_id, "stop-container", lane=LANE)

    # 6. Monitoring finds it down, and a rollback waits on a person.
    async def instant(seconds):
        return None

    report = await watch(pool, reviewed["id"], rounds=3, interval=1, sleep=instant)
    assert report.current_state == "down"
    snapshot = (await client.get(f"/projects/{project_id}/deployment")).json()
    [flagged] = [view for view in snapshot["deployments"] if view["id"] == str(reviewed["id"])]
    assert flagged["state"] == "awaiting-rollback-approval"
    assert flagged["faultInjected"] == "stop-container"

    # 7. The person approves the rollback.
    decided = await client.post(
        f"/projects/{project_id}/deployment/deployments/{reviewed['id']}/rollback/decision",
        json={"decision": "approved", "by": PERSON, "note": "the release stopped answering"},
    )
    assert decided.status_code == 200, decided.text
    restored = await _carry_out(client, project_id, port)

    # 8. Restored: the verified release before it is what is served again.
    assert restored["kind"] == "rollback" and restored["restores"] == held["id"]
    assert await _served(port) == WalkC4.hash_for(medium)
    async with pool.connection() as conn:
        failed = await store.get_deployment(conn, reviewed["id"])
        ledger = await store.list_deployments(conn, project_id, limit=50)
    assert failed["state"] == "rolled-back" and failed["fault_injected"] == "stop-container"
    assert [(row["kind"], row["state"]) for row in reversed(ledger)] == [
        ("release", "succeeded"),
        ("release", "succeeded"),
        ("release", "succeeded"),
        ("release", "rolled-back"),
        ("rollback", "succeeded"),
    ]
    assert baseline["verified"] and automatic["verified"]
