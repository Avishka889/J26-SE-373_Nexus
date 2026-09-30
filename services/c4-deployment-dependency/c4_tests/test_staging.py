"""Staging verification: the candidate built from its own Dockerfile, booted, and asked what it is.

Docker is scripted in most of these, so each way a candidate can fail is shown
failing for its own reason and nothing else: files that are not the candidate,
an included update the lockfile does not carry, tests that fail in the build, a
container serving another fingerprint, and a smoke request the page fallback
answered with HTML. One test, marked `docker`, builds and boots the platform's
own generated app for real.
"""

import json
import subprocess
from datetime import UTC, datetime

import pytest
from c4.harness import staging
from c4.harness.container import DATABASE_IMAGE
from c4.harness.staging import Ran, verify
from c4.service import C4, NotApplicable

from .docker import needs_docker
from .test_pipeline_generation import SUPERTEST, TRACKER, _generate

NOW = datetime(2026, 9, 28, tzinfo=UTC)
GENERATED = _generate()
LAYER = GENERATED.layer
CANDIDATE = GENERATED.config.candidate_hash
IMAGE = "sdlc-c4-task-tracker:v2"

#: The tracker as code generated from 2026-10-01 is: its backend reads
#: MONGODB_URL. The tracker itself only declares the name in `.env.example`.
READS = {
    **TRACKER,
    "apps/api/src/app.ts": TRACKER["apps/api/src/app.ts"]
    + "\nexport const databaseUrl = process.env.MONGODB_URL;\n",
}
READING = _generate(READS)


class Docker:
    """A scripted Docker: every command is recorded, and the builds and the
    container answer as the test says."""

    def __init__(
        self,
        *,
        failing: str = "",
        serves: str = CANDIDATE,
        tasks_type="application/json",
        database_answers: bool = True,
        failing_output: str = "",
    ):
        self.failing = failing
        self.failing_output = failing_output
        self.serves = serves
        self.tasks_type = tasks_type
        self.database_answers = database_answers
        self.commands: list[list[str]] = []

    def run(self, argv: list[str], timeout: float) -> Ran:
        self.commands.append(argv)
        if argv[:2] == ["docker", "run"] and DATABASE_IMAGE in argv:
            return Ran(0, "db0\n", 1.5)
        if argv[:3] == ["docker", "exec", "db0"]:
            return Ran(0, "1\n", 0.2) if self.database_answers else Ran(1, "not yet", 0.2)
        if argv[:2] == ["docker", "build"]:
            target = argv[argv.index("--target") + 1] if "--target" in argv else "image"
            if target == self.failing:
                return Ran(
                    1, self.failing_output or f"the {target} stage failed: 2 tests failed", 12.0
                )
            return Ran(0, f"built {target}", 10.0)
        if argv[:3] == ["docker", "image", "inspect"]:
            return Ran(0, "sha256:" + "e" * 64 + "\n", 0.1)
        if argv[:2] == ["docker", "run"]:
            return Ran(0, "c0ffee\n", 0.5)
        if argv[:2] == ["docker", "port"]:
            return Ran(0, "127.0.0.1:61000\n", 0.1)
        return Ran(0, "", 0.1)

    def probe(self, url: str, headers: dict[str, str], timeout: float):
        path = url.removeprefix("http://127.0.0.1:61000")
        if path == "/release.json":
            return 200, "application/json", json.dumps({"candidateHash": self.serves})
        if path == "/":
            return 200, "text/html; charset=utf-8", "<!doctype html>"
        if path == "/tasks":
            return 200, self.tasks_type, "[]"
        return 404, "text/html", "not found"


#: A test step as Docker prints it: the API's two failures, npm naming the
#: workspace, the web workspace's passing run, and Docker's closing error block,
#: which repeats the last lines printed. What failed is far above the last
#: 2,000 characters.
_WEB_RUN = "".join(
    f"#14 4.{index:03d}  \u2713 src/components/Panel{index}.test.tsx (3 tests) 41ms\n"
    for index in range(40)
)
VITEST_FAILURE = (
    '#0 building with "default" instance using docker driver\n'
    "#14 [test 1/1] RUN npm test --workspaces --if-present\n"
    "#14 0.874 > @app/api@0.0.0 test\n"
    "#14 0.874 > vitest run\n"
    "#14 3.012  \u276f test/tasks.test.ts (15 tests | 2 failed) 210ms\n"
    "#14 3.100 \u23af\u23af\u23af\u23af\u23af\u23af\u23af Failed Tests 2 \u23af\u23af\u23af\u23af\u23af\u23af\u23af\n"
    "#14 3.100  FAIL  test/tasks.test.ts > tasks > rejects a task without a title\n"
    "#14 3.100 AssertionError: expected 201 to be 400 // Object.is equality\n"
    "#14 3.100  \u276f test/tasks.test.ts:24:29\n"
    "#14 3.100  FAIL  test/tasks.test.ts > tasks > lists tasks newest first\n"
    "#14 3.100 AssertionError: expected [ \u2026(2) ] to deeply equal [ \u2026(2) ]\n"
    "#14 3.101  Test Files  1 failed (1)\n"
    "#14 3.101       Tests  2 failed | 13 passed (15)\n"
    "#14 3.200 npm error workspace @app/api@0.0.0\n"
    "#14 3.200 npm error command sh -c vitest run\n"
    "#14 3.300 > @app/web@0.0.0 test\n"
    + _WEB_RUN
    + '#14 ERROR: process "/bin/sh -c npm test --workspaces --if-present" did not complete successfully: exit code: 1\n'
    "------\n"
    " > [test 1/1] RUN npm test --workspaces --if-present:\n"
    "5.401       Tests  12 passed (12)\n"
    "------\n"
    'ERROR: failed to solve: process "/bin/sh -c npm test --workspaces --if-present" did not complete successfully: exit code: 1\n'
)


def _verify(docker: Docker, *, files=TRACKER, layer=LAYER, candidate=CANDIDATE, included=(), **kw):
    return verify(
        files,
        layer,
        candidate=candidate,
        included=list(included),
        excluded=[],
        image=IMAGE,
        version=2,
        code_version=3,
        runner=docker.run,
        prober=docker.probe,
        now=NOW,
        sleep=lambda seconds: None,
        **kw,
    )


def _outcomes(candidate) -> dict[str, str]:
    return {step.name: step.outcome for step in candidate.steps}


class TestAVerifiedCandidate:
    def test_every_step_passes_and_the_fingerprint_is_the_candidates(self) -> None:
        docker = Docker()
        candidate = _verify(docker)
        assert _outcomes(candidate) == {
            name: "passed" for name in ("candidate", "lockfile", "install", "test", "image", "boot")
        }
        assert candidate.fingerprint == CANDIDATE and candidate.image_digest == "sha256:" + "e" * 64
        assert [(check.path, check.ok) for check in candidate.smoke] == [
            ("/", True),
            ("/tasks", True),
        ]
        assert candidate.verified

    def test_the_container_is_removed_and_the_intermediate_stages_leave_no_image(self) -> None:
        docker = Docker()
        _verify(docker)
        assert ["docker", "rm", "-f", "c0ffee"] in docker.commands
        builds = [argv for argv in docker.commands if argv[:2] == ["docker", "build"]]
        assert all("type=cacheonly" in argv for argv in builds[:2])
        assert builds[2][:5] == ["docker", "build", "--label", "sdlc.c4.lane=staging", "-t"]


class TestEachFailureIsAnOutcome:
    def test_files_that_are_not_the_candidate_stop_before_anything_is_built(self) -> None:
        changed = {**LAYER, "Dockerfile": LAYER["Dockerfile"] + "# edited after review\n"}
        docker = Docker()
        candidate = _verify(docker, layer=changed)
        assert _outcomes(candidate)["candidate"] == "failed"
        assert "not the candidate" in candidate.steps[0].log_tail
        assert not any(argv[:2] == ["docker", "build"] for argv in docker.commands)
        assert not candidate.verified

    def test_an_included_update_the_lockfile_does_not_carry_is_found(self) -> None:
        candidate = _verify(Docker(), included=[SUPERTEST])
        [lockfile] = [step for step in candidate.steps if step.name == "lockfile"]
        assert lockfile.outcome == "failed"
        assert "supertest is at 7.2.2 in apps/api, not the included 7.3.0" in lockfile.log_tail
        assert candidate.included == [SUPERTEST.id] and not candidate.verified

    def test_an_included_update_nobody_can_name_is_not_dropped_from_the_record(self) -> None:
        candidate = _verify(Docker(), unmatched=("u-000000000000",))
        assert candidate.included == ["u-000000000000"]
        assert "not among the run's updates" in candidate.steps[1].log_tail

    def test_tests_that_fail_in_the_build_leave_no_image_and_nothing_booted(self) -> None:
        docker = Docker(failing="test")
        candidate = _verify(docker)
        outcomes = _outcomes(candidate)
        assert (outcomes["install"], outcomes["test"]) == ("passed", "failed")
        assert (outcomes["image"], outcomes["boot"]) == ("not-run", "not-run")
        assert "2 tests failed" in candidate.steps[3].log_tail
        assert candidate.image_digest is None and not candidate.verified
        assert not any(argv[:2] == ["docker", "run"] for argv in docker.commands)

    def test_a_failed_test_step_keeps_which_tests_failed(self) -> None:
        """Only the last 2,000 characters were kept, which were the next
        workspace's passing run and Docker's error block: the review said the
        test step failed and could not say which tests, or why."""
        assert len(VITEST_FAILURE) > 3000
        candidate = _verify(Docker(failing="test", failing_output=VITEST_FAILURE))

        kept = candidate.steps[3].log_tail
        assert kept.startswith("What failed:")
        assert "FAIL  test/tasks.test.ts > tasks > rejects a task without a title" in kept
        assert "AssertionError: expected 201 to be 400 // Object.is equality" in kept
        assert "FAIL  test/tasks.test.ts > tasks > lists tasks newest first" in kept
        assert "npm error workspace @app/api@0.0.0" in kept
        # BuildKit's step and time prefixes are not part of what was printed.
        assert "#14 3.100" not in kept.split("The last of the output:")[0]
        # And the tail is still there, as it was.
        assert kept.endswith(VITEST_FAILURE[-2000:].rstrip())

    def test_a_step_that_passed_keeps_only_its_tail(self) -> None:
        candidate = _verify(Docker())
        assert all(not step.log_tail.startswith("What failed:") for step in candidate.steps)

    def test_a_container_serving_another_fingerprint_is_not_this_candidate(self) -> None:
        candidate = _verify(Docker(serves="f" * 64))
        assert all(step.outcome == "passed" for step in candidate.steps)
        assert candidate.fingerprint == "f" * 64 and not candidate.verified

    def test_a_smoke_request_answered_with_the_page_is_not_an_answer(self) -> None:
        """The generated backend answers any request that accepts a page with its
        index.html; staging asks for JSON, so an endpoint that is not there fails."""
        candidate = _verify(Docker(tasks_type="text/html; charset=utf-8"))
        [tasks] = [check for check in candidate.smoke if check.path == "/tasks"]
        assert not tasks.ok and "where application/json was asked for" in tasks.detail
        assert not candidate.verified


class TestTheDatabaseBesideIt:
    """Code that reads MONGODB_URL is verified the way a release with a database runs it."""

    def _verify(self, docker: Docker):
        return _verify(
            docker, files=READS, layer=READING.layer, candidate=READING.config.candidate_hash
        )

    def test_code_that_reads_the_database_boots_beside_one_on_a_private_network(self) -> None:
        docker = Docker(serves=READING.config.candidate_hash)
        candidate = self._verify(docker)

        assert [step.name for step in candidate.steps][-2:] == ["database", "boot"]
        assert all(step.outcome == "passed" for step in candidate.steps)
        assert candidate.verified
        [network_made] = [a for a in docker.commands if a[:3] == ["docker", "network", "create"]]
        network = network_made[-1]
        [database] = [a for a in docker.commands if DATABASE_IMAGE in a]
        assert database[database.index("--network") + 1] == network
        assert "--network-alias" in database and "database" in database
        [app] = [a for a in docker.commands if a[:2] == ["docker", "run"] and IMAGE in a]
        assert app[app.index("--network") + 1] == network
        assert app[app.index("-e") + 1] == "MONGODB_URL=mongodb://database:27017/staging"
        # Everything it made is gone afterwards, the database with its records.
        assert ["docker", "rm", "-f", "db0"] in docker.commands
        assert docker.commands[-1] == ["docker", "network", "rm", network]
        assert "throwaway MongoDB" in candidate.isolation

    def test_code_that_only_declares_the_variable_gets_no_database(self) -> None:
        docker = Docker()
        candidate = _verify(docker)

        assert "database" not in _outcomes(candidate)
        assert not any(DATABASE_IMAGE in a or "network" in a for a in docker.commands)
        assert "MongoDB" not in candidate.isolation

    def test_a_database_that_never_answers_leaves_the_candidate_unverified(
        self, monkeypatch
    ) -> None:
        monkeypatch.setattr(staging, "BOOT_WITHIN_SECONDS", 0)
        docker = Docker(serves=READING.config.candidate_hash, database_answers=False)
        candidate = self._verify(docker)

        outcomes = _outcomes(candidate)
        assert (outcomes["database"], outcomes["boot"]) == ("failed", "not-run")
        assert "did not answer a ping" in candidate.steps[-2].log_tail
        assert not candidate.verified
        assert not any(a[:2] == ["docker", "run"] and IMAGE in a for a in docker.commands)
        assert ["docker", "rm", "-f", "db0"] in docker.commands
        assert docker.commands[-1][:3] == ["docker", "network", "rm"]


class TestTheStage:
    async def test_without_docker_the_stage_is_skipped_saying_why(self, monkeypatch) -> None:
        component = C4("deepseek:deepseek-flash")
        monkeypatch.setattr(component, "_docker_reason", lambda: "docker is not installed")
        with pytest.raises(NotApplicable, match="no Docker daemon to build the candidate in"):
            await component.verify_candidate(
                TRACKER,
                LAYER,
                candidate_hash=CANDIDATE,
                included=[],
                excluded=[],
                version=2,
                code_version=3,
            )

    async def test_the_component_answers_with_the_candidate_and_a_summary(self) -> None:
        docker = Docker()
        component = C4("deepseek:deepseek-flash", runner=docker.run, prober=docker.probe)
        answer = await component.verify_candidate(
            TRACKER,
            LAYER,
            candidate_hash=CANDIDATE,
            included=[],
            excluded=[],
            version=2,
            code_version=3,
            settings={"project_slug": "task-tracker"},
        )
        assert answer.artefact.verified and answer.artefact.image == IMAGE
        assert answer.summary.startswith(f"verified: {IMAGE} serves candidate {CANDIDATE[:12]}")


@pytest.mark.docker
@needs_docker
class TestTheRealCandidate:
    def test_the_generated_app_builds_boots_and_serves_its_fingerprint(self) -> None:
        candidate = verify(
            TRACKER,
            LAYER,
            candidate=CANDIDATE,
            included=[],
            excluded=[],
            image="sdlc-c4-test-staging:v2",
            version=2,
            code_version=3,
        )
        assert all(step.outcome == "passed" for step in candidate.steps), candidate.steps
        assert candidate.fingerprint == CANDIDATE
        assert [(check.path, check.ok) for check in candidate.smoke] == [
            ("/", True),
            ("/tasks", True),
        ]
        assert candidate.verified

    def test_code_that_reads_the_database_boots_beside_a_real_one(self) -> None:
        image = "sdlc-c4-test-staging:database"
        try:
            candidate = verify(
                READS,
                READING.layer,
                candidate=READING.config.candidate_hash,
                included=[],
                excluded=[],
                image=image,
                version=2,
                code_version=3,
            )
            assert all(step.outcome == "passed" for step in candidate.steps), candidate.steps
            assert [step.name for step in candidate.steps][-2:] == ["database", "boot"]
            assert candidate.verified
            left = subprocess.run(
                ["docker", "network", "ls", "-q", "--filter", "label=sdlc.c4.lane=staging"],
                capture_output=True,
                text=True,
                check=True,
            )
            assert left.stdout.strip() == "", "the private network outlived the checks"
            running = subprocess.run(
                ["docker", "ps", "-aq", "--filter", f"ancestor={DATABASE_IMAGE}"],
                capture_output=True,
                text=True,
                check=True,
            )
            assert running.stdout.strip() == "", "the database outlived the checks"
        finally:
            subprocess.run(["docker", "rmi", "-f", image], capture_output=True, check=False)
