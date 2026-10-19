# ruff: noqa: F811 - `pool` and `project` are the saga tests' fixtures, used by name
"""The local release target, and the ledger that records every attempt.

The checks are shown refusing what they exist to refuse, with the network
scripted. Then, marked `docker`, two small images that each serve their own
fingerprint are released in turn through the real adapter, in a lane and on a
port of their own: the release port serves the first, then the second, whose
switch replaced the first's container.
"""

import json
import socket
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.db import store
from orchestrator.deploy.adapters.checks import HttpChecks
from orchestrator.deploy.adapters.local_docker import LocalDocker, docker
from orchestrator.saga.executor import StepContext, StepFailed, run_deployment
from sdlc_contracts import (
    BuildStepReport,
    DeployPlan,
    DeployStep,
    DeployTarget,
    EnvironmentProtection,
    ReleaseCandidate,
    RollbackPolicy,
    SmokeCheck,
)

from .conftest import needs_db
from .test_saga import pool, project  # noqa: F401

NOW = datetime(2026, 9, 28, tzinfo=UTC)
NODE = (
    "node:22-bookworm-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c"
)
LANE = "test-release"


def _candidate(digest: str, image: str = "sdlc-c4-test:v1") -> ReleaseCandidate:
    return ReleaseCandidate(
        version=1,
        generated_at=NOW,
        code_version=1,
        candidate_hash=digest,
        image=image,
        image_digest="sha256:" + "e" * 64,
        toolchain="scripted",
        isolation="scripted",
        steps=[BuildStepReport(name="image", command="docker build .", outcome="passed")],
        smoke=[SmokeCheck(path="/", ok=True), SmokeCheck(path="/tasks", ok=True)],
        fingerprint=digest,
    )


def _ctx(step_id: str, candidate: ReleaseCandidate, earlier: dict) -> StepContext:
    step = DeployStep(id=step_id, label=step_id)
    return StepContext(
        deployment={"id": "d", "kind": "release", "project_id": "p"},
        plan=None,  # type: ignore[arg-type]
        step=step,
        seq=0,
        key="k",
        candidate=candidate,
        previous=None,
        earlier=earlier,
    )


def _serving(hash_: str, *, tasks_type: str = "application/json"):
    async def prober(url: str, headers: dict[str, str]):
        if url.endswith("/release.json"):
            return 200, "application/json", json.dumps({"candidateHash": hash_})
        if url.endswith("/tasks"):
            return 200, tasks_type, "[]"
        return 200, "text/html; charset=utf-8", "<!doctype html>"

    return prober


class TestTheChecks:
    async def test_the_expected_fingerprint_and_the_right_kinds_pass(self) -> None:
        checks = HttpChecks(prober=_serving("a" * 64))
        result = await checks.execute(
            _ctx("verify", _candidate("a" * 64), {"switch": {"address": "127.0.0.1:18080"}})
        )
        assert result.resource["verified"] and result.resource["url"] == "http://127.0.0.1:18080"
        assert result.resource["fingerprint"]["candidateHash"] == "a" * 64

    async def test_another_candidates_fingerprint_is_refused(self) -> None:
        checks = HttpChecks(prober=_serving("b" * 64))
        with pytest.raises(StepFailed, match=r"serves candidate bbbbbbbbbbbb, not aaaaaaaaaaaa"):
            await checks.execute(
                _ctx("check", _candidate("a" * 64), {"start": {"address": "127.0.0.1:1"}})
            )

    async def test_a_page_answering_a_json_smoke_request_is_refused(self) -> None:
        checks = HttpChecks(prober=_serving("a" * 64, tasks_type="text/html"))
        with pytest.raises(StepFailed, match="not application/json"):
            await checks.execute(
                _ctx("check", _candidate("a" * 64), {"start": {"address": "127.0.0.1:1"}})
            )

    async def test_an_address_that_never_answers_is_refused_in_time(self) -> None:
        async def silent(url, headers):
            return None, "", "connection refused"

        async def instant(seconds):
            return None

        checks = HttpChecks(prober=silent, boot_within=0.05, sleep=instant)
        with pytest.raises(StepFailed, match="did not answer within"):
            await checks.execute(
                _ctx("check", _candidate("a" * 64), {"start": {"address": "127.0.0.1:1"}})
            )


SERVER = """import http from "node:http";
import fs from "node:fs";
const release = fs.readFileSync("/app/release.json");
http.createServer((req, res) => {
  const wantsPage = (req.headers.accept || "").includes("text/html");
  if (req.url === "/release.json") {
    res.writeHead(200, { "content-type": "application/json" });
    return res.end(release);
  }
  if (req.url === "/tasks" && !wantsPage) {
    res.writeHead(200, { "content-type": "application/json; charset=utf-8" });
    return res.end("[]");
  }
  res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
  res.end("<!doctype html><title>app</title>");
}).listen(3001, "0.0.0.0");
"""


def _image(tmp_path: Path, name: str, candidate_hash: str) -> str:
    context = tmp_path / name
    context.mkdir()
    (context / "server.mjs").write_text(SERVER)
    (context / "release.json").write_text(json.dumps({"candidateHash": candidate_hash}))
    (context / "Dockerfile").write_text(
        f"FROM {NODE}\nWORKDIR /app\nCOPY server.mjs release.json /app/\n"
        'EXPOSE 3001\nUSER 1000:1000\nCMD ["node", "server.mjs"]\n'
    )
    tag = f"sdlc-c4-test-release:{name}"
    subprocess.run(
        ["docker", "build", "-q", "--label", f"sdlc.c4.lane={LANE}", "-t", tag, str(context)],
        check=True,
        capture_output=True,
    )
    return subprocess.run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", tag],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _plan(project_id: str, version: int, candidate_hash: str) -> DeployPlan:
    return DeployPlan(
        plan_id=f"{project_id}-deploy-v{version}",
        project_id=project_id,
        generated_by="test",
        generated_at=NOW,
        deploy_version=version,
        stack="mern",
        target="local",
        candidate_hash=candidate_hash,
        targets=[DeployTarget(role="app", provider="local-docker", resource="the image")],
        steps=[
            DeployStep(id="start", label="Start", provider="local-docker", compensation="stop it"),
            DeployStep(id="check", label="Check", depends_on="start"),
            DeployStep(
                id="switch",
                label="Switch",
                provider="local-docker",
                depends_on="check",
                compensation="restore, once a person approves",
                moves_traffic=True,
            ),
            DeployStep(id="verify", label="Verify", depends_on="switch"),
        ],
        rollback=RollbackPolicy(note="application only"),
        environment_protection=EnvironmentProtection(github="not-applicable"),
    )


async def _release(db_pool, project_id: str, version: int, digest: str, candidate_hash: str, port):
    candidate = _candidate(candidate_hash).model_copy(update={"image_digest": digest})
    async with db_pool.connection() as conn:
        for kind, body in (
            ("deploy-plan", _plan(project_id, version, candidate_hash)),
            ("release-candidate", candidate),
        ):
            await store.put_artefact(
                conn,
                project_id=project_id,
                kind=kind,
                version=version,
                body=body.model_dump(by_alias=True, mode="json"),
            )
        row, _ = await store.create_deployment(
            conn,
            project_id=project_id,
            deploy_version=version,
            kind="release",
            target="local",
            plan_id=f"{project_id}-deploy-v{version}",
            candidate_hash=candidate_hash,
            idempotency_key=f"{project_id}-{version}",
            authorised={"kind": "gate", "by": "you", "gateId": f"g-{version}"},
            requested_by="you",
        )

    async def allowed(conn, row):
        return []

    state = await run_deployment(
        db_pool,
        row["id"],
        adapters={
            "local-docker": LocalDocker(release_port=port, lane=LANE),
            "checks": HttpChecks(),
        },
        authorise=allowed,
    )
    return state, row["id"]


@pytest.mark.docker
@needs_db
class TestTheRealLocalTarget:
    async def test_two_releases_in_turn_move_the_release_port(
        self,
        pool,
        project,
        tmp_path,
    ) -> None:
        port = _free_port()
        first, second = "a" * 64, "b" * 64
        try:
            image_a = _image(tmp_path, "a", first)
            image_b = _image(tmp_path, "b", second)
            state, one = await _release(pool, project, 1, image_a, first, port)
            async with pool.connection() as conn:
                released = await store.get_deployment(conn, one)
            # The cause says which step failed and in the provider's words, if one does.
            assert state == "succeeded", released["cause"]
            assert released["verified"] and released["url"] == f"http://127.0.0.1:{port}"
            assert released["fingerprint"]["imageDigest"] == image_a

            state, two = await _release(pool, project, 2, image_b, second, port)
            async with pool.connection() as conn:
                assert state == "succeeded", (await store.get_deployment(conn, two))["cause"]
            _, served = await docker(["ps", "-q", "--filter", f"label=sdlc.c4.lane={LANE}"])
            assert len(served.split()) == 1, "the first release's container was replaced"
            probe = await HttpChecks().execute(
                _ctx("verify", _candidate(second), {"switch": {"address": f"127.0.0.1:{port}"}})
            )
            assert probe.resource["verified"]
        finally:
            _, containers = await docker(["ps", "-aq", "--filter", f"label=sdlc.c4.lane={LANE}"])
            for container in containers.split():
                await docker(["rm", "-f", container])
            await docker(["rmi", "-f", "sdlc-c4-test-release:a", "sdlc-c4-test-release:b"])


@pytest.mark.docker
@needs_db
class TestTwoProjectsOnOneMachine:
    async def test_each_releases_on_its_own_port_and_both_keep_serving(
        self,
        pool,
        project,
        tmp_path,
    ) -> None:
        """Every project's release bound one port, so the project that took it
        first made every later project's first release fail at its switch."""
        port = _free_port()
        async with pool.connection() as conn:
            other = (await store.create_project(conn, name="Saga case two", owner_id=DEV_OWNER_ID))[
                "id"
            ]
        try:
            image_a = _image(tmp_path, "a", "a" * 64)
            image_b = _image(tmp_path, "b", "b" * 64)
            assert (await _release(pool, project, 1, image_a, "a" * 64, port))[0] == "succeeded"

            state, theirs = await _release(pool, other, 1, image_b, "b" * 64, port)

            async with pool.connection() as conn:
                released = await store.get_deployment(conn, theirs)
            assert state == "succeeded", released["cause"]
            assert released["url"] != f"http://127.0.0.1:{port}", "a port of its own"
            for address, served in (
                (f"127.0.0.1:{port}", "a" * 64),
                (released["url"].removeprefix("http://"), "b" * 64),
            ):
                probe = await HttpChecks().execute(
                    _ctx("verify", _candidate(served), {"switch": {"address": address}})
                )
                assert probe.resource["verified"], f"{address} still serves its own release"
        finally:
            _, containers = await docker(["ps", "-aq", "--filter", f"label=sdlc.c4.lane={LANE}"])
            for container in containers.split():
                await docker(["rm", "-f", container])
            await docker(["rmi", "-f", "sdlc-c4-test-release:a", "sdlc-c4-test-release:b"])
            async with pool.connection() as conn:
                await store.delete_project(conn, other, owner_id=DEV_OWNER_ID)


async def _rollback(db_pool, project_id: str, failed_id, verified_row, image: str, port):
    """A person's approved rollback of `failed_id` to `verified_row`, carried out for real."""
    from sdlc_contracts import RestoreStep, RollbackPlan, VerificationCheck, VerifiedRelease

    plan = RollbackPlan(
        version=2,
        generated_at=NOW,
        candidate_hash="b" * 64,
        restore_target=VerifiedRelease(
            deployment_id=str(verified_row["id"]),
            deploy_version=1,
            candidate_hash=verified_row["candidate_hash"],
            target="local",
            image_digest=image,
            verified_at=NOW,
        ),
        restorable=True,
        steps=[
            RestoreStep(
                id="start-verified", label="Start", provider="local-docker", action="start it"
            ),
            RestoreStep(
                id="switch-back",
                label="Switch back",
                provider="local-docker",
                action="move the port",
                moves_traffic=True,
            ),
        ],
        checks=[VerificationCheck(id="fp", kind="fingerprint", role="app", expect="a" * 64)],
    )
    async with db_pool.connection() as conn:
        await store.put_artefact(
            conn,
            project_id=project_id,
            kind="rollback-plan",
            version=2,
            body=plan.model_dump(by_alias=True, mode="json"),
        )
        await store.finish_deployment(
            conn,
            verified_row["id"],
            state="succeeded",
            verified=True,
            fingerprint={"candidateHash": verified_row["candidate_hash"], "imageDigest": image},
        )
        row, _ = await store.create_deployment(
            conn,
            project_id=project_id,
            deploy_version=1,
            kind="rollback",
            target="local",
            plan_id=f"{project_id}-rollback-v2",
            candidate_hash=verified_row["candidate_hash"],
            idempotency_key=f"{project_id}-rollback",
            authorised={
                "kind": "rollback",
                "by": "you",
                "deploymentId": str(failed_id),
                "fromVersion": 2,
            },
            requested_by="you",
            restores=verified_row["id"],
        )

    async def allowed(conn, row):
        return []

    return await run_deployment(
        db_pool,
        row["id"],
        adapters={
            "local-docker": LocalDocker(release_port=port, lane=LANE),
            "checks": HttpChecks(),
        },
        authorise=allowed,
    )


@pytest.mark.docker
@needs_db
class TestTheRealRollback:
    async def _two_releases(self, pool, project, tmp_path, port):
        image_a = _image(tmp_path, "a", "a" * 64)
        image_b = _image(tmp_path, "b", "b" * 64)
        assert (await _release(pool, project, 1, image_a, "a" * 64, port))[0] == "succeeded"
        state, failed = await _release(pool, project, 2, image_b, "b" * 64, port)
        assert state == "succeeded"
        async with pool.connection() as conn:
            [verified_row] = [
                row
                for row in await store.list_deployments(conn, project)
                if row["deploy_version"] == 1
            ]
        return image_a, image_b, failed, verified_row

    async def _clean(self):
        _, containers = await docker(["ps", "-aq", "--filter", f"label=sdlc.c4.lane={LANE}"])
        for container in containers.split():
            await docker(["rm", "-f", container])
        await docker(["rmi", "-f", "sdlc-c4-test-release:a", "sdlc-c4-test-release:b"])

    async def test_an_approved_rollback_serves_the_verified_release_again(
        self,
        pool,
        project,
        tmp_path,
    ) -> None:
        port = _free_port()
        try:
            image_a, _, failed, verified_row = await self._two_releases(
                pool, project, tmp_path, port
            )
            assert await _rollback(pool, project, failed, verified_row, image_a, port) == (
                "succeeded"
            )
            probe = await HttpChecks().execute(
                _ctx("verify", _candidate("a" * 64), {"switch": {"address": f"127.0.0.1:{port}"}})
            )
            assert probe.resource["verified"]
            async with pool.connection() as conn:
                assert (await store.get_deployment(conn, failed))["state"] == "rolled-back"
        finally:
            await self._clean()

    async def test_a_rollback_that_starts_the_wrong_image_is_not_reported_restored(
        self,
        pool,
        project,
        tmp_path,
    ) -> None:
        """The record says the verified release's image is B's: the switch succeeds, the
        container runs, and what it serves is B. Restored means A is served again."""
        port = _free_port()
        try:
            _, image_b, failed, verified_row = await self._two_releases(
                pool, project, tmp_path, port
            )
            state = await _rollback(pool, project, failed, verified_row, image_b, port)
            assert state == "awaiting-rollback-approval"
            async with pool.connection() as conn:
                assert (await store.get_deployment(conn, failed))["state"] != "rolled-back"
        finally:
            await self._clean()
