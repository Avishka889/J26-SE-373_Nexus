"""Checkpoint 3: a security fix proposed, approved, applied and re-verified.

The one loop in this platform that crosses a component boundary. C3 finds the
weakness and proposes a patch; a person accepts it; the orchestrator applies it
as a new code version, because C3 does not write source and a component that
both found the weakness and edited the code to close it could mark its own
homework; and C3 re-verifies by comparing the numbers before and after.

Three properties are held here, and each is a way the loop could look like it
worked while doing nothing.

  1. A fix reaches the code because a person decided it should. A proposal that
     was never accepted is refused, and so is one whose patch no longer fits
     the file it was written against.
  2. The result is an ordinary code version. Rolling back means going back to
     the version before it, not reversing an edit nobody recorded.
  3. Re-verification is subtraction, and a pair of passes measured differently
     is refused rather than subtracted.
"""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.graph.runner import RunSupervisor
from orchestrator.main import create_app, lifespan_for_tests
from sdlc_contracts import (
    CODE_GENERATING_STAGE_IDS,
    CodeRepository,
    ManifestRow,
    RepositoryPointer,
)

from orchestrator import crypto

from .conftest import needs_db
from .test_deployment_routes import _newer_code

pytestmark = needs_db

VULNERABLE = """package com.example;

public class Accounts {
    public static String findByName(Connection db, String name) throws SQLException {
        Statement statement = db.createStatement();
        return statement.executeQuery("select * from users where name = '" + name + "'");
    }
}
"""

PATH = "apps/api/src/Accounts.java"


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, lifespan_factory=lifespan_for_tests)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            created: list[str] = []
            c.created_projects = created  # type: ignore[attr-defined]
            try:
                yield c
            finally:
                async with app.state.pool.connection() as conn:
                    for project_id in created:
                        await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)


async def _advance(client: httpx.AsyncClient, run_id) -> None:
    supervisor: RunSupervisor = client.app.state.supervisor  # type: ignore[attr-defined]
    await supervisor.advance(uuid.UUID(str(run_id)))


def _patched() -> str:
    return VULNERABLE.replace(
        'return statement.executeQuery("select * from users where name = \'" + name + "\'");',
        'return safeQuery(db, "select * from users where name = ?", name);',
    )


def _proposal(*, path: str = PATH, diff: str | None = None) -> dict:
    from c3.remediate.patch import unified

    return {
        "id": "fix-CWE-89",
        "findingId": "CWE-89:accounts:6",
        "cwe": "CWE-89",
        "generatedAt": datetime.now(UTC).isoformat(),
        "summary": "use a parameterised query",
        "patch": [{"path": path, "diff": diff or unified(path, VULNERABLE, _patched())}],
        "risk": {
            "level": "low",
            "statement": "Low risk: the patch changes 2 lines in 1 file.",
            "facts": [
                {"label": "files changed", "value": 1},
                {"label": "lines changed", "value": 2},
            ],
        },
        "affectedEndpoints": [],
        "affectedTests": [],
        "state": "proposed",
        "decidedBy": "",
        "decisionNote": "",
    }


async def _through_code(
    client: httpx.AsyncClient, *, planted: str = VULNERABLE, others: dict[str, str] | None = None
) -> tuple[str, int]:
    """A project with an approved code version carrying the vulnerable file, and `others`."""
    created = await client.post("/projects", json={"name": "Records", "description": ""})
    project_id = created.json()["id"]
    client.created_projects.append(project_id)  # type: ignore[attr-defined]
    await client.patch(
        f"/projects/{project_id}", json={"requirementText": "Someone creates a record."}
    )
    runs = (await client.get("/runs", params={"project": project_id})).json()
    await _advance(client, runs[0]["id"])
    await client.post(
        f"/projects/{project_id}/design/decision", json={"kind": "approved", "by": "you"}
    )
    await _advance(client, runs[0]["id"])

    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        design_version = await store.current_version(conn, project_id)
        code_version = await store.next_code_version(conn, project_id)
        await store.seed_code_stages(conn, project_id)
        await store.set_stages(
            conn, project_id, list(CODE_GENERATING_STAGE_IDS), status="generating"
        )
        code_run = await store.create_run(
            conn,
            project_id=project_id,
            requirements_version=code_version,
            component="c2",
            source_version=design_version,
        )
    await _advance(client, code_run["id"])

    # The weakness the proposal is about, in the code version under test. Planted
    # while the version waits at its review: an approved version's code is
    # settled, and the store refuses to rewrite it.
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        version = await store.current_code_version(conn, project_id)
        files = await store.code_files(conn, project_id, version=version)
        await store.put_code_files(
            conn,
            project_id,
            version=version,
            stage_id="backend-code",
            files={**files, PATH: planted, **(others or {})},
        )
    await client.post(
        f"/projects/{project_id}/code/decision", json={"kind": "approved", "by": "you"}
    )
    await _advance(client, code_run["id"])
    return project_id, version


async def _with_proposal(
    client: httpx.AsyncClient,
    proposal: dict | None = None,
    *,
    planted: str = VULNERABLE,
    others: dict[str, str] | None = None,
) -> tuple[str, int]:
    """A proposal written against the vulnerable file. `planted` is the file the
    approved code really carries, so a test can make the patch no longer fit
    without rewriting an approved version, which the store refuses. `others`
    are further files it carries, for a proposal that patches more than one."""
    project_id, code_version = await _through_code(client, planted=planted, others=others)
    await client.post(f"/projects/{project_id}/testing/run")
    runs = (await client.get("/runs", params={"project": project_id})).json()
    await _advance(client, runs[0]["id"])

    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        version = await store.current_test_version(conn, project_id)
        await store.put_artefact(
            conn,
            project_id=project_id,
            kind="remediation-proposal",
            version=version,
            body={
                "version": version,
                "generatedAt": datetime.now(UTC).isoformat(),
                # The target kind, which is what the run writes here and what
                # the apply path reads to decide whether this platform owns the
                # thing being patched. A fixture saying "apps/api" passed for
                # months and then hid a refusal that only fires on a sample.
                "target": "generated",
                "proposals": [proposal or _proposal()],
            },
        )
    return project_id, code_version


async def _tests_approved(client: httpx.AsyncClient, project_id: str) -> None:
    """The test review approves the run waiting at it: its code is what may ship."""
    decided = await client.post(
        f"/projects/{project_id}/testing/decision",
        json={"kind": "approved", "by": "you", "note": "the finding is fixed next"},
    )
    assert decided.status_code == 200, decided.text
    runs = (await client.get("/runs", params={"project": project_id})).json()
    await _advance(client, runs[0]["id"])


class TestAFixOverNewerCodeShipsWithIt:
    """Applying a fix patches the newest code version. With the next sprint's code
    written and not yet tested, a fix reaches production only together with it,
    once its tests are approved: a fix to the released build alone is not
    offered, so code versions stay one line. Nothing said so (review item C4-13);
    the snapshot, and so the page, and the record say it now."""

    async def test_the_snapshot_says_where_a_fix_goes_and_what_may_ship(self, client) -> None:
        project_id, code_version = await _with_proposal(client)
        await _tests_approved(client, project_id)
        newer = await _newer_code(client, project_id, tested=False, sprint=2)

        snapshot = (await client.get(f"/projects/{project_id}/testing")).json()

        assert snapshot["fixShipsWith"] == {
            "codeVersion": newer,
            "sprint": 2,
            "releasableCodeVersion": code_version,
            "releasableSprint": 1,
        }

    async def test_with_nothing_newer_a_fix_ships_on_its_own(self, client) -> None:
        project_id, _ = await _with_proposal(client)
        await _tests_approved(client, project_id)

        snapshot = (await client.get(f"/projects/{project_id}/testing")).json()

        assert snapshot["fixShipsWith"] is None

    async def test_applying_one_says_so_in_the_record(self, client) -> None:
        project_id, code_version = await _with_proposal(client)
        await _tests_approved(client, project_id)
        newer = await _newer_code(client, project_id, tested=False, sprint=2)
        await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/decision",
            json={"decision": "accepted", "by": "you"},
        )

        applied = await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/apply", json={"by": "you"}
        )

        assert applied.status_code == 200, applied.text
        trail = (await client.get("/audit", params={"project": project_id})).json()
        entry = next(e for e in trail if e["action"] == "Applied a security fix")
        assert (
            f"It ships with sprint 2, once code version {newer + 1}'s tests are approved; code "
            f"version {code_version}, the newest with approved tests, does not get it on its own."
        ) in entry["detail"]


async def _two_proposals(client: httpx.AsyncClient) -> tuple[str, int]:
    """The SQL injection fix, and a second fix to the page beside it, both accepted."""
    project_id, code_version = await _with_proposal(client, others={PAGE_PATH: PAGE})
    second = {
        **_fix_of((PAGE_PATH, PAGE, PAGE.replace("return null", "return undefined"))),
        "id": "fix-CWE-79",
        "findingId": "CWE-79:page:1",
        "cwe": "CWE-79",
    }
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        version = await store.current_test_version(conn, project_id)
        found = await store.artefacts_at(
            conn, project_id, version=version, kinds=("remediation-proposal",)
        )
        body = dict(found["remediation-proposal"]["body"])
        body["proposals"] = [*body["proposals"], second]
        await store.put_artefact(
            conn, project_id=project_id, kind="remediation-proposal", version=version, body=body
        )
    for fix in ("fix-CWE-89", "fix-CWE-79"):
        decided = await client.post(
            f"/projects/{project_id}/testing/remediation/{fix}/decision",
            json={"decision": "accepted", "by": "you"},
        )
        assert decided.status_code == 200, decided.text
    return project_id, code_version


class TestOneFixAtATime:
    """Two fixes applied before re-testing left the first impossible to re-verify:
    every apply patched the newest code, testing only runs on the newest code, and
    re-verification needs a run at exactly the fix's version (review item C3-9)."""

    async def test_a_second_fix_waits_until_the_first_ones_version_is_tested(self, client) -> None:
        project_id, code_version = await _two_proposals(client)
        first = await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/apply", json={"by": "you"}
        )
        assert first.status_code == 200, first.text

        refused = await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-79/apply", json={"by": "you"}
        )

        assert refused.status_code == 409
        assert (
            f"fix-CWE-89 is applied as code version {code_version + 1}, which no testing run "
            "has measured yet"
        ) in refused.text
        assert f"run the tests on code version {code_version + 1} first" in refused.text
        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            assert await store.current_code_version(conn, project_id) == code_version + 1

    async def test_once_its_version_is_tested_the_next_fix_goes_on(self, client) -> None:
        project_id, code_version = await _two_proposals(client)
        await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/apply", json={"by": "you"}
        )
        started = await client.post(f"/projects/{project_id}/testing/run")
        assert started.status_code == 200, started.text
        runs = (await client.get("/runs", params={"project": project_id})).json()
        await _advance(client, runs[0]["id"])
        # The new run's scan proposes the page's fix again, at its own version.
        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            version = await store.current_test_version(conn, project_id)
            earlier = await store.artefacts_at(
                conn, project_id, version=version - 1, kinds=("remediation-proposal",)
            )
            second = next(
                one
                for one in earlier["remediation-proposal"]["body"]["proposals"]
                if one["id"] == "fix-CWE-79"
            )
            await store.put_artefact(
                conn,
                project_id=project_id,
                kind="remediation-proposal",
                version=version,
                body={
                    "version": version,
                    "generatedAt": datetime.now(UTC).isoformat(),
                    "target": "generated",
                    "proposals": [second],
                },
            )
        await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-79/decision",
            json={"decision": "accepted", "by": "you"},
        )

        applied = await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-79/apply", json={"by": "you"}
        )

        assert applied.status_code == 200, applied.text
        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            assert await store.current_code_version(conn, project_id) == code_version + 2

    async def test_a_fix_newer_code_has_passed_holds_nothing_up(self, client) -> None:
        # The code phase can write a newer version over a fix nobody tested, and
        # testing runs only on the newest code, so that version can never be
        # measured now: waiting for it would refuse every fix after it for good.
        project_id, _ = await _two_proposals(client)
        await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/apply", json={"by": "you"}
        )
        newer = await _newer_code(client, project_id, tested=False)

        applied = await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-79/apply", json={"by": "you"}
        )

        assert applied.status_code == 200, applied.text
        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            assert await store.current_code_version(conn, project_id) == newer + 1

    async def test_a_fix_applied_twice_is_told_it_is_applied(self, client) -> None:
        # Its patch met the code it had already written, and the refusal blamed
        # the file for changing after the fix was proposed.
        project_id, code_version = await _two_proposals(client)
        url = f"/projects/{project_id}/testing/remediation/fix-CWE-89/apply"
        await client.post(url, json={"by": "you"})

        again = await client.post(url, json={"by": "you"})

        assert again.status_code == 409
        assert f"this fix is already applied, as code version {code_version + 1}" in again.text


class TestAFixReachesTheCodeBecauseAPersonDecided:
    async def test_a_proposal_nobody_accepted_is_not_applied(self, client) -> None:
        project_id, _ = await _with_proposal(client)

        answer = await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/apply",
            json={"by": "you"},
        )

        assert answer.status_code == 409
        assert "has not been accepted" in answer.text

    async def test_an_accepted_proposal_is_applied(self, client) -> None:
        project_id, code_version = await _with_proposal(client)
        await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/decision",
            json={"decision": "accepted", "by": "you"},
        )

        answer = await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/apply",
            json={"by": "you"},
        )

        assert answer.status_code == 200, answer.text
        async with client.app.state.pool.connection() as conn:
            after = await store.current_code_version(conn, project_id)
            files = await store.code_files(conn, project_id, version=after)
        assert after == code_version + 1, "the fix is an ordinary new code version"
        assert "safeQuery" in files[PATH]
        assert "executeQuery" not in files[PATH]

    async def test_a_proposal_that_does_not_exist_is_not_found(self, client) -> None:
        project_id, _ = await _with_proposal(client)

        answer = await client.post(
            f"/projects/{project_id}/testing/remediation/invented/apply", json={"by": "you"}
        )

        assert answer.status_code == 404, answer.text


class TestAPatchThatNoLongerFitsIsRefused:
    async def test_the_file_moving_underneath_refuses_the_apply(self, client) -> None:
        """A proposal is made against one code version and applied against
        whatever is current. Forcing it would write unreviewed code into the
        one place where being wrong is worst."""
        project_id, _ = await _with_proposal(
            client, planted=VULNERABLE.replace("Statement statement", "Statement stmt")
        )
        await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/decision",
            json={"decision": "accepted", "by": "you"},
        )

        answer = await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/apply",
            json={"by": "you"},
        )

        assert answer.status_code == 409
        assert "has to be proposed again" in answer.text

    async def test_the_code_version_is_not_allocated_when_the_patch_is_refused(
        self, client
    ) -> None:
        """A refused apply must leave no trace. A version number burned on a
        patch that did not land is a gap a reader will try to explain."""
        project_id, code_version = await _with_proposal(client, planted="totally different\n")
        await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/decision",
            json={"decision": "accepted", "by": "you"},
        )

        await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/apply", json={"by": "you"}
        )

        async with client.app.state.pool.connection() as conn:
            assert await store.current_code_version(conn, project_id) == code_version

    async def test_a_patch_naming_a_file_the_version_lacks_is_refused(self, client) -> None:
        project_id, _ = await _with_proposal(client, _proposal(path="apps/api/src/Absent.java"))
        await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/decision",
            json={"decision": "accepted", "by": "you"},
        )

        answer = await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/apply", json={"by": "you"}
        )

        assert answer.status_code == 409
        assert "does not contain" in answer.text


POINTER = RepositoryPointer(
    owner="presenter",
    name="records",
    default_branch="main",
    commit_sha="c" * 40,
    url="https://github.com/presenter/records",
)


class TestAFixVersionIsAVersionOfItsOwn:
    """Applying a fix copied every artefact forward, the repository pointer and
    the build report too. So the fix version was never pushed, Push refused it
    as pushed already, and a cloud release built on the commit without the fix
    while every fingerprint named the fixed candidate."""

    async def _applied(self, client, connect=None) -> tuple[str, int]:
        project_id, code_version = await _with_proposal(client)
        await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/decision",
            json={"decision": "accepted", "by": "you"},
        )
        if connect is not None:
            connect()
        answer = await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/apply", json={"by": "you"}
        )
        assert answer.status_code == 200, answer.text
        return project_id, code_version + 1

    @staticmethod
    async def _repository(client, project_id: str, version: int) -> CodeRepository:
        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            found = await store.artefacts_at(
                conn, project_id, version=version, kinds=("code-repository",)
            )
        return CodeRepository.model_validate(found["code-repository"]["body"])

    async def test_without_github_it_says_it_was_neither_built_nor_pushed(self, client) -> None:
        project_id, fixed = await self._applied(client)

        repository = await self._repository(client, project_id, fixed)

        assert repository.repository is None, "no pointer to a commit without the fix"
        assert repository.build is None, "the build was of the files it patched"
        assert repository.not_pushed_reason is not None
        assert "applying an accepted security fix over code version" in (
            repository.not_pushed_reason
        )
        assert "there is no working GitHub connection" in repository.not_pushed_reason

    async def test_with_github_it_is_pushed_to_its_own_branch_and_lands(
        self, client, monkeypatch
    ) -> None:
        """Approved through the version it patched, so it lands as an approval does."""
        canned = client.app.state.clients["c2"]  # type: ignore[attr-defined]

        async def sealed(conn, key):
            return b"sealed"

        def connect() -> None:
            # GitHub connected once the fix is accepted, so the one push and
            # the one landing are the fix version's.
            canned.pushes_to = POINTER
            monkeypatch.setattr(store, "get_secret", sealed)
            monkeypatch.setattr(crypto, "decrypt", lambda key, ciphertext: "a-token")

        project_id, fixed = await self._applied(client, connect)

        repository = await self._repository(client, project_id, fixed)
        assert repository.repository is not None
        assert repository.repository.branch == f"code/v{fixed}"
        assert repository.not_pushed_reason is None
        assert canned.landed == [POINTER.commit_sha]
        assert PATH in canned.pushed_paths[-1]
        assert not any("__tests__" in path for path in canned.pushed_paths[-1]), (
            "a push leaves the tests out, as it does for every version"
        )
        entries = (await client.get("/audit", params={"project": project_id})).json()
        [applied] = [row for row in entries if row["action"] == "Applied a security fix"]
        assert (
            f"Pushed to {POINTER.url}, branch code/v{fixed}. main now carries it."
            in (applied["detail"])
        )

    async def test_its_tests_stay_filed_as_the_tests(self, client) -> None:
        project_id, fixed = await self._applied(client)

        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            before = await store.code_files(
                conn, project_id, version=fixed - 1, stage_id=store.TEST_FILE_STAGE
            )
            after = await store.code_files(
                conn, project_id, version=fixed, stage_id=store.TEST_FILE_STAGE
            )

        assert before and after == before


class TestTheLoopIsAudited:
    async def test_applying_records_which_version_carries_the_fix(self, client) -> None:
        """Rolling back means going back to the version before it, so the
        version that carries it has to be on the record."""
        project_id, code_version = await _with_proposal(client)
        await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/decision",
            json={"decision": "accepted", "by": "you"},
        )
        await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/apply", json={"by": "you"}
        )

        entries = (await client.get("/audit", params={"project": project_id})).json()
        applied = [row for row in entries if row["action"] == "Applied a security fix"]

        assert applied, "the apply is audited"
        assert f"code version {code_version + 1}" in applied[0]["target"]
        assert "CWE-89" in applied[0]["target"]

    async def test_the_overlay_carries_the_version_that_was_applied(self, client) -> None:
        project_id, code_version = await _with_proposal(client)
        await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/decision",
            json={"decision": "accepted", "by": "you"},
        )
        await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/apply", json={"by": "you"}
        )

        async with client.app.state.pool.connection() as conn:
            rows = await store.overlays(conn, project_id)
        decision = next(row for row in rows if row["kind"] == "remediation_decision")

        assert decision["value"]["appliedCodeVersion"] == code_version + 1

    async def test_the_testing_phase_sees_the_code_move_on(self, client) -> None:
        """The fix is a new code version, so the tests now describe a version
        that is no longer current and the phase says so."""
        project_id, _ = await _with_proposal(client)
        await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/decision",
            json={"decision": "accepted", "by": "you"},
        )
        applied = await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/apply", json={"by": "you"}
        )

        assert applied.json()["codeMovedOn"] is True, (
            "a fix that changed the code leaves the previous testing run describing an "
            "older version, and the phase has to say so rather than let a green report "
            "stand over code it never saw"
        )


def _finding(index: int) -> dict:
    # The first is the one the proposal answers, at the line its patch replaces.
    line = 6 + index
    return {
        "id": f"CWE-89:accounts:{line}",
        "cwe": "CWE-89",
        "title": "Query built by string concatenation",
        "origin": "scanner",
        "raisedBy": ["scanner"],
        "evidence": {"path": PATH, "startLine": line, "endLine": line, "snippet": "executeQuery("},
        "factors": {
            "attackVector": "N",
            "attackComplexity": "L",
            "privilegesRequired": "N",
            "userInteraction": "N",
            "scope": "U",
            "confidentiality": "H",
            "integrity": "H",
            "availability": "H",
        },
        "status": "open",
        "confidence": 0.9,
        "confidenceSource": "scanner-rule",
    }


def _validation(version: int, *, findings: int, arms: int = 1, files: int = 12) -> dict:
    """A scan result with a chosen number of open findings.

    Written by the test rather than measured, because the canned component
    finds nothing and this is about the subtraction, not about the scanner.
    """
    return {
        "version": version,
        "generatedAt": datetime.now(UTC).isoformat(),
        "target": "the generated app",
        "findings": [_finding(index) for index in range(findings)],
        "detectorRuns": [
            {
                "arm": arm,
                "modelId": "canned",
                "startedAt": datetime.now(UTC).isoformat(),
                "durationSeconds": 0.01,
                "offline": True,
                "filesScanned": files,
            }
            for arm in ("scanner", "llm", "trained")[:arms]
        ],
        "tests": {"run": 1, "passed": 0, "failed": 1, "skipped": 0, "lineCoverage": 80.0},
    }


async def _put_validation(client: httpx.AsyncClient, project_id: str, version: int, **kw) -> None:
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        await store.put_artefact(
            conn,
            project_id=project_id,
            kind="validation-report",
            version=version,
            body=_validation(version, **kw),
        )


async def _applied_fix(
    client: httpx.AsyncClient,
    proposal: dict | None = None,
    *,
    others: dict[str, str] | None = None,
) -> tuple[str, int, int]:
    """A project whose accepted fix has been applied. Returns ids and versions."""
    project_id, code_version = await _with_proposal(client, proposal, others=others)
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        test_version = await store.current_test_version(conn, project_id)
    await _put_validation(client, project_id, test_version, findings=1)
    await client.post(
        f"/projects/{project_id}/testing/remediation/fix-CWE-89/decision",
        json={"decision": "accepted", "by": "you"},
    )
    applied = await client.post(
        f"/projects/{project_id}/testing/remediation/fix-CWE-89/apply", json={"by": "you"}
    )
    assert applied.status_code == 200, applied.text
    return project_id, code_version, test_version


async def _run_again(client: httpx.AsyncClient, project_id: str) -> int:
    """Decide the open testing gate, then test the patched code version."""
    await client.post(
        f"/projects/{project_id}/testing/decision",
        json={"kind": "approved", "by": "you", "note": "one fix applied, re-testing"},
    )
    runs = (await client.get("/runs", params={"project": project_id})).json()
    await _advance(client, runs[0]["id"])

    started = await client.post(f"/projects/{project_id}/testing/run")
    assert started.status_code == 200, started.text
    runs = (await client.get("/runs", params={"project": project_id})).json()
    await _advance(client, runs[0]["id"])
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        return await store.current_test_version(conn, project_id)


class TestAReviewTheFixMovedPast:
    """Applying an accepted fix before the test review was decided moved the code
    on, and the review was then of code no longer current. The page did not offer
    to decide it, and running the tests again was refused while it waited, so
    there was nothing left to press."""

    async def test_running_the_tests_again_closes_it_and_tests_the_fix(self, client) -> None:
        project_id, code_version, _ = await _applied_fix(client)
        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            patched = await store.current_code_version(conn, project_id)
            waiting = await store.pending_gate(conn, project_id=project_id, kind="c3-test-review")
        assert patched > code_version and waiting is not None

        started = await client.post(f"/projects/{project_id}/testing/run")

        assert started.status_code == 200, started.text
        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            closed = await store.get_run(conn, waiting["run_id"])
            history = await store.gate_history(conn, project_id, kind="c3-test-review")
            fresh = await store.latest_run(conn, project_id)
        assert closed is not None and closed["state"] == "superseded"
        assert history[-1]["decision"] == "changes"
        assert f"the code is at version {patched} now" in history[-1]["note"]
        assert fresh is not None and fresh["component"] == "c3"
        assert fresh["source_version"] == patched

    async def test_requesting_changes_there_is_refused_and_says_what_to_do(self, client) -> None:
        """Changes would test the older code again: running the tests is the way on."""
        project_id, _, _ = await _applied_fix(client)

        refused = await client.post(
            f"/projects/{project_id}/testing/decision",
            json={"kind": "changes", "by": "you", "note": "test the fix"},
        )

        assert refused.status_code == 409
        assert "would test the older code again" in refused.text
        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            still = await store.pending_gate(conn, project_id=project_id, kind="c3-test-review")
        assert still is not None, "a refused change closed the review"


class TestReVerificationIsSubtraction:
    """The last quarter of the loop: the fix is in, so did it work?

    Answered by comparing two runs rather than by asking the model that
    proposed the fix, which is the same rule the healing guard follows one
    stage earlier. C3 does the arithmetic and may refuse it; the orchestrator
    stores what comes back and nothing else.
    """

    async def test_a_fix_nobody_applied_has_nothing_to_compare(self, client) -> None:
        project_id, _ = await _with_proposal(client)

        answer = await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/reverify",
            json={"by": "you"},
        )

        assert answer.status_code == 409
        assert "has not been applied" in answer.text

    async def test_the_patched_version_can_be_tested_without_a_second_approval(
        self, client
    ) -> None:
        """The reader approved the build and then approved this patch over it.
        Refusing to test the result would end the loop at the apply, because
        the patched version has no code gate of its own and nothing opens one."""
        project_id, _, _ = await _applied_fix(client)
        await client.post(
            f"/projects/{project_id}/testing/decision",
            json={"kind": "approved", "by": "you", "note": "one fix applied"},
        )
        runs = (await client.get("/runs", params={"project": project_id})).json()
        await _advance(client, runs[0]["id"])

        started = await client.post(f"/projects/{project_id}/testing/run")

        assert started.status_code == 200, started.text

    async def test_re_verifying_before_anything_tested_the_patch_asks_for_a_run(
        self, client
    ) -> None:
        """Comparing the proposing run against itself would be subtracting a
        number from itself, and it would read as a fix that changed nothing."""
        project_id, code_version, _ = await _applied_fix(client)

        answer = await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/reverify",
            json={"by": "you"},
        )

        assert answer.status_code == 409, answer.text
        assert f"code version {code_version + 1}" in answer.text

    async def test_a_second_run_lets_the_numbers_be_subtracted(self, client) -> None:
        project_id, _, _ = await _applied_fix(client)
        after_version = await _run_again(client, project_id)
        await _put_validation(client, project_id, after_version, findings=0)

        answer = await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/reverify",
            json={"by": "you"},
        )

        assert answer.status_code == 200, answer.text
        proposal = answer.json()["remediation"]["proposals"][0]
        assert proposal["reverification"]["findingsClosed"] == 1
        assert proposal["reverification"]["worsened"] is False
        assert proposal["reverification"]["findingId"] == "CWE-89:accounts:6"
        assert proposal["reverification"]["findingClosed"] is True
        assert proposal["state"] == "verified"

    async def test_a_fix_whose_finding_is_still_raised_is_not_verified(self, client) -> None:
        # The totals did not move, which read as verified while the after scan
        # still raised the very finding the fix was for (review item C3-7). The
        # fix adds an import, so the query is line 7 after it: a new id.
        from c3.remediate.patch import unified

        moved = _patched().replace(
            "package com.example;\n", "package com.example;\nimport java.sql.Connection;\n"
        )
        project_id, _, _ = await _applied_fix(
            client, _proposal(diff=unified(PATH, VULNERABLE, moved))
        )
        after_version = await _run_again(client, project_id)
        body = _validation(after_version, findings=0)
        first = _finding(0)
        body["findings"] = [
            {
                **first,
                "id": "CWE-89:accounts:7",
                "evidence": {**first["evidence"], "startLine": 7, "endLine": 7},
            }
        ]
        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            await store.put_artefact(
                conn,
                project_id=project_id,
                kind="validation-report",
                version=after_version,
                body=body,
            )

        answer = await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/reverify",
            json={"by": "you"},
        )

        assert answer.status_code == 200, answer.text
        proposal = answer.json()["remediation"]["proposals"][0]
        assert proposal["reverification"]["worsened"] is False
        assert proposal["reverification"]["stillRaisedAs"] == ["CWE-89:accounts:7"]
        assert proposal["reverification"]["verified"] is False
        assert proposal["state"] == "applied", "its finding is still raised"
        entry = next(
            one for one in answer.json()["audit"] if one["action"] == "Re-verified a security fix"
        )
        assert "the finding it was for is still raised, as CWE-89:accounts:7" in entry["detail"]

    async def test_a_comparison_that_never_looked_for_the_finding_verifies_nothing(
        self, client
    ) -> None:
        # Recorded before the finding was looked for: totals only.
        project_id, _, test_version = await _applied_fix(client)
        totals = {"openFindings": 1, "testsPassed": 3, "testsFailed": 0}
        async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
            await store.put_overlay(
                conn,
                project_id=project_id,
                version=test_version,
                kind="remediation_reverification",
                target_id="fix-CWE-89",
                value={"before": totals, "after": {**totals, "openFindings": 0}},
                by="you",
            )

        body = (await client.get(f"/projects/{project_id}/testing")).json()

        proposal = body["remediation"]["proposals"][0]
        assert proposal["reverification"]["findingsClosed"] == 1
        assert proposal["state"] == "applied", "a total says nothing about this finding"

    async def test_a_fix_that_broke_a_test_is_not_called_verified(self, client) -> None:
        """`worsened` is computed from the two snapshots, so "verified" cannot
        be recorded over numbers that say otherwise."""
        project_id, _, _ = await _applied_fix(client)
        after_version = await _run_again(client, project_id)
        await _put_validation(client, project_id, after_version, findings=0)
        async with client.app.state.pool.connection() as conn:
            found = await store.artefacts_at(
                conn, project_id, version=after_version, kinds=("test-report",)
            )
            broken = found["test-report"]["body"]
            broken["suites"][0]["cases"].append(
                {
                    "id": "c9",
                    "name": "a person sees the history",
                    "outcome": "failed",
                    "message": "the patch broke this",
                }
            )
            await store.put_artefact(
                conn,
                project_id=project_id,
                kind="test-report",
                version=after_version,
                body=broken,
            )

        answer = await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/reverify",
            json={"by": "you"},
        )

        assert answer.status_code == 200, answer.text
        proposal = answer.json()["remediation"]["proposals"][0]
        assert proposal["reverification"]["testsBroken"] == 1
        assert proposal["reverification"]["worsened"] is True
        assert proposal["state"] == "applied", "a fix that broke a test is not verified"

    async def test_a_comparison_c3_refuses_is_recorded_and_not_stored(self, client) -> None:
        """The refusal is the result. Storing a subtraction C3 would not make
        is how a fix that did nothing comes to look like a fix that worked."""
        project_id, _, _ = await _applied_fix(client)
        after_version = await _run_again(client, project_id)
        await _put_validation(client, project_id, after_version, findings=0, arms=3)

        class Refusing:
            async def reverify(self, *args, **kwargs):
                from orchestrator.clients.c3 import StageOutcome

                return StageOutcome(
                    artefact=None,
                    summary="the two passes cannot be compared: the arms differ",
                    notes={"comparable": False},
                )

        client.app.state.clients["c3"] = Refusing()
        answer = await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/reverify",
            json={"by": "you"},
        )

        # Refused, and said so in the answer: a 200 that changed nothing left a
        # reader with the conversation closed seeing nothing happen.
        assert answer.status_code == 409, answer.text
        assert "cannot be compared" in answer.json()["error"]
        body = (await client.get(f"/projects/{project_id}/testing")).json()
        assert body["remediation"]["proposals"][0]["reverification"] is None
        # The record of the refusal outlives the refused request.
        assert any("cannot be compared" in message["content"] for message in body["thread"])
        assert any(
            entry["action"] == "Re-verification refused" and "cannot be compared" in entry["detail"]
            for entry in body["audit"]
        )
        async with client.app.state.pool.connection() as conn:
            rows = await store.overlays(conn, project_id)
        assert not [row for row in rows if row["kind"] == "remediation_reverification"]


class TestTheSnapshotSaysWhatHappenedToAProposal:
    async def test_an_accepted_fix_stops_awaiting_a_decision(self, client) -> None:
        """Without this the page keeps asking for a decision that was made,
        because the artefact is what C3 proposed and cannot know what came
        after it."""
        project_id, _ = await _with_proposal(client)

        answer = await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/decision",
            json={"decision": "accepted", "by": "you"},
        )

        body = answer.json()
        assert body["remediation"]["awaitingDecision"] == 0
        assert body["remediation"]["proposals"][0]["state"] == "accepted"
        # The signed-in account decided, whatever the request said.
        assert body["remediation"]["proposals"][0]["decidedBy"] == "Local development"

    async def test_an_applied_fix_names_the_version_that_carries_it(self, client) -> None:
        project_id, code_version, _ = await _applied_fix(client)

        body = (await client.get(f"/projects/{project_id}/testing")).json()

        proposal = body["remediation"]["proposals"][0]
        assert proposal["state"] == "applied"
        assert proposal["appliedCodeVersion"] == code_version + 1

    async def test_a_dismissed_finding_leaves_the_open_count(self, client) -> None:
        """The reader's judgement counts, and the report stays as the arms
        produced it: precision computed over an edited report measures the
        editing."""
        project_id, _ = await _with_proposal(client)
        async with client.app.state.pool.connection() as conn:
            version = await store.current_test_version(conn, project_id)
        await _put_validation(client, project_id, version, findings=2)

        answer = await client.post(
            f"/projects/{project_id}/testing/findings/CWE-89:accounts:6/decision",
            json={"decision": "dismissed", "by": "you", "note": "reachable only from tests"},
        )

        body = answer.json()
        assert body["openFindings"] == 1, "one of the two was dismissed"
        async with client.app.state.pool.connection() as conn:
            found = await store.artefacts_at(
                conn, project_id, version=version, kinds=("validation-report",)
            )
        stored = found["validation-report"]["body"]["findings"]
        assert [one["status"] for one in stored] == ["open", "open"], "the artefact is untouched"


class TestAFixForSomethingThisPlatformDoesNotOwn:
    """A proposal against a checked in sample cannot be applied, and has to say
    so in those words.

    It used to reach the patcher, which correctly reported that the file it
    named is not in this code version, and sent a reader to look for a file
    that had moved when nothing had moved. The real reason is that applying
    writes a new code version of the generated application, and a sample is a
    fixture in the component's own repository.
    """

    async def test_it_is_refused_by_name(self, client) -> None:
        project_id, _ = await _with_proposal(client)
        async with client.app.state.pool.connection() as conn:
            version = await store.current_test_version(conn, project_id)
            found = await store.artefacts_at(
                conn, project_id, version=version, kinds=("remediation-proposal",)
            )
            body = found["remediation-proposal"]["body"]
            body["target"] = "sample"
            await store.put_artefact(
                conn,
                project_id=project_id,
                kind="remediation-proposal",
                version=version,
                body=body,
            )
        await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/decision",
            json={"decision": "accepted", "by": "you"},
        )

        answer = await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/apply", json={"by": "you"}
        )

        assert answer.status_code == 409
        assert "does not patch" in answer.text
        assert "checked in fixture" in answer.text
        assert "does not contain" not in answer.text, "not the patcher's answer about a file"

    async def test_a_fix_for_the_generated_application_still_applies(self, client) -> None:
        project_id, code_version = await _with_proposal(client)
        await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/decision",
            json={"decision": "accepted", "by": "you"},
        )

        answer = await client.post(
            f"/projects/{project_id}/testing/remediation/fix-CWE-89/apply", json={"by": "you"}
        )

        assert answer.status_code == 200, answer.text
        async with client.app.state.pool.connection() as conn:
            assert await store.current_code_version(conn, project_id) == code_version + 1


# ------------------------------------------------- a fix and the next generation

#: A second file a fix can patch, for a fix that changes more than one.
AUDIT_PATH = "apps/api/src/Audit.java"
AUDIT = """package com.example;

public class Audit {
    public static String line(String name) {
        return "user " + name;
    }
}
"""

#: The canned frontend's one page, for a fix that reaches into the frontend.
PAGE_PATH = "apps/web/src/pages/FlowListPage.tsx"
PAGE = "// screen: flow/list\nexport function FlowListPage() { return null; }\n"


def _fix_of(*changes: tuple[str, str, str]) -> dict:
    """A proposal whose patch makes each (path, before, after) change, in order."""
    from c3.remediate.patch import unified

    return {
        **_proposal(),
        "patch": [
            {"path": path, "diff": unified(path, before, after)} for path, before, after in changes
        ],
    }


async def _generate_again(client: httpx.AsyncClient, project_id: str, **body) -> int:
    """Generate the code again, walked to its review. Returns the version it wrote.

    On purpose, as the page confirms it: the version a fix wrote counts as
    approved when the version it patched was, so replacing it is asked about.
    """
    started = await client.post(
        f"/projects/{project_id}/code/generate", json={"supersede": True, **body}
    )
    assert started.status_code == 200, started.text
    runs = (await client.get("/runs", params={"project": project_id})).json()
    await _advance(client, runs[0]["id"])
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        return await store.current_code_version(conn, project_id)


async def _decide_code(client: httpx.AsyncClient, project_id: str, kind: str) -> int:
    """Decide the code review; "changes" walks the new version to its review. Returns it."""
    decided = await client.post(
        f"/projects/{project_id}/code/decision",
        json={"kind": kind, "by": "you", "note": "the fix did not carry"},
    )
    assert decided.status_code == 200, decided.text
    runs = (await client.get("/runs", params={"project": project_id})).json()
    await _advance(client, runs[0]["id"])
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        return await store.current_code_version(conn, project_id)


async def _code_at(
    client: httpx.AsyncClient, project_id: str, version: int
) -> tuple[dict[str, str], dict[str, ManifestRow]]:
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        files = await store.code_files(conn, project_id, version=version)
        found = await store.artefacts_at(
            conn, project_id, version=version, kinds=("code-repository",)
        )
    manifest = CodeRepository.model_validate(found["code-repository"]["body"]).manifest
    return files, {row.path: row for row in manifest}


async def _said_about(client: httpx.AsyncClient, project_id: str, version: int) -> list[str]:
    """What the conversation said about fixes not carried into this version."""
    async with client.app.state.pool.connection() as conn:  # type: ignore[attr-defined]
        rows = await store.thread(conn, project_id)
    return [
        row["content"]
        for row in rows
        if f"was not carried into code version {version}:" in row["content"]
    ]


class TestAFixIsCarriedIntoCodeGeneratedAgain:
    """Generating again writes every file from the design, so the next version
    used to lose every fix applied since, and the weakness came back without a
    word. Each fix is now merged into the regenerated files three ways, as git
    cherry-picks a commit, and where it cannot be, the review is told."""

    async def test_a_fix_lands_in_the_file_generated_again(self, client) -> None:
        project_id, _, _ = await _applied_fix(client)
        async with client.app.state.pool.connection() as conn:
            fixed = await store.current_code_version(conn, project_id)
        client.app.state.c2.extra_api_files = {PATH: VULNERABLE}

        version = await _generate_again(client, project_id)

        files, rows = await _code_at(client, project_id, version)
        assert version > fixed
        assert files[PATH] == _patched(), "the regenerated file lost the fix"
        assert rows[PATH].carried_fixes == [fixed]
        entries = (await client.get("/audit", params={"project": project_id})).json()
        carried = [row for row in entries if row["action"] == "Carried a security fix"]
        assert (
            carried and f"code version {fixed} into code version {version}" in carried[0]["target"]
        )

    async def test_a_change_elsewhere_in_the_file_is_kept_beside_the_fix(self, client) -> None:
        project_id, _, _ = await _applied_fix(client)
        generated = VULNERABLE.replace("package com.example;", "package com.example.records;")
        client.app.state.c2.extra_api_files = {PATH: generated}

        version = await _generate_again(client, project_id)

        files, _ = await _code_at(client, project_id, version)
        assert files[PATH] == _patched().replace(
            "package com.example;", "package com.example.records;"
        )

    async def test_lines_generated_differently_are_kept_as_generated_and_said(self, client) -> None:
        project_id, _, _ = await _applied_fix(client)
        generated = VULNERABLE.replace("select * from users", "select id, name from users")
        client.app.state.c2.extra_api_files = {PATH: generated}

        version = await _generate_again(client, project_id)

        files, rows = await _code_at(client, project_id, version)
        assert files[PATH] == generated, "a fix was forced into lines it was not reviewed against"
        assert "<<<<<<<" not in files[PATH]
        assert rows[PATH].carried_fixes == []
        [said] = await _said_about(client, project_id, version)
        assert "changed the lines of apps/api/src/Accounts.java that the fix changed" in said
        assert "Approving this version without the fix lets it go" in said
        stages = (await client.get(f"/projects/{project_id}/code")).json()["stages"]
        assert "1 not carried" in stages["backend-code"]["summary"]

    async def test_a_file_no_longer_generated_is_said_rather_than_written(self, client) -> None:
        project_id, _, _ = await _applied_fix(client)

        version = await _generate_again(client, project_id)

        files, _ = await _code_at(client, project_id, version)
        assert PATH not in files
        [said] = await _said_about(client, project_id, version)
        assert "the code generated this time has no apps/api/src/Accounts.java" in said

    async def test_without_git_nothing_is_forced(self, client, monkeypatch) -> None:
        project_id, _, _ = await _applied_fix(client)
        client.app.state.c2.extra_api_files = {PATH: VULNERABLE}
        monkeypatch.setattr("orchestrator.carrying.GIT", "git-that-is-not-installed")

        version = await _generate_again(client, project_id)

        files, _ = await _code_at(client, project_id, version)
        assert files[PATH] == VULNERABLE
        [said] = await _said_about(client, project_id, version)
        assert "git is not installed where the orchestrator runs" in said

    async def test_a_fix_lands_in_all_of_its_files_or_in_none(self, client) -> None:
        """A half carried fix is worse than none, as a half applied one is."""
        fixed_audit = AUDIT.replace('"user " + name', '"user " + escape(name)')
        project_id, _, _ = await _applied_fix(
            client,
            _fix_of((PATH, VULNERABLE, _patched()), (AUDIT_PATH, AUDIT, fixed_audit)),
            others={AUDIT_PATH: AUDIT},
        )
        regenerated_audit = AUDIT.replace('"user " + name', '"member " + name')
        client.app.state.c2.extra_api_files = {PATH: VULNERABLE, AUDIT_PATH: regenerated_audit}

        version = await _generate_again(client, project_id)

        files, _ = await _code_at(client, project_id, version)
        assert files[PATH] == VULNERABLE, "the half that merged was carried on its own"
        assert files[AUDIT_PATH] == regenerated_audit
        [said] = await _said_about(client, project_id, version)
        assert "apps/api/src/Audit.java" in said

    async def test_a_fix_spanning_the_frontend_and_the_backend_is_not_carried(self, client) -> None:
        safe_page = PAGE.replace("return null;", "return safe(null);")
        project_id, _, _ = await _applied_fix(
            client, _fix_of((PATH, VULNERABLE, _patched()), (PAGE_PATH, PAGE, safe_page))
        )
        client.app.state.c2.extra_api_files = {PATH: VULNERABLE}

        version = await _generate_again(client, project_id)

        files, _ = await _code_at(client, project_id, version)
        assert files[PATH] == VULNERABLE and files[PAGE_PATH] == PAGE
        [said] = await _said_about(client, project_id, version)
        assert "which the Frontend Code stage writes" in said
        assert "half a fix" in said

    async def test_a_stage_retried_on_its_own_carries_the_fix_again(self, client) -> None:
        project_id, _, _ = await _applied_fix(client)
        client.app.state.c2.extra_api_files = {PATH: VULNERABLE}
        version = await _generate_again(client, project_id)

        retried = await client.post(f"/projects/{project_id}/code/stages/backend-code/retry")
        assert retried.status_code == 200, retried.text
        runs = (await client.get("/runs", params={"project": project_id})).json()
        await _advance(client, runs[0]["id"])

        files, rows = await _code_at(client, project_id, version)
        assert files[PATH] == _patched(), "the retried stage wrote the file without the fix"
        assert rows[PATH].carried_fixes

    async def test_requesting_changes_tries_the_fix_again(self, client) -> None:
        """The next generation may write the lines as they were, and the fix with them."""
        project_id, _, _ = await _applied_fix(client)
        client.app.state.c2.extra_api_files = {
            PATH: VULNERABLE.replace("select * from users", "select id, name from users")
        }
        await _generate_again(client, project_id)
        client.app.state.c2.extra_api_files = {PATH: VULNERABLE}

        version = await _decide_code(client, project_id, "changes")

        files, _ = await _code_at(client, project_id, version)
        assert files[PATH] == _patched()

    async def test_approving_a_version_without_the_fix_lets_it_go(self, client) -> None:
        """The review said the fix was not carried, and the reviewer approved the
        code without it, so the next generation does not bring it back."""
        project_id, _, _ = await _applied_fix(client)
        client.app.state.c2.extra_api_files = {
            PATH: VULNERABLE.replace("select * from users", "select id, name from users")
        }
        await _generate_again(client, project_id)
        await _decide_code(client, project_id, "approved")
        client.app.state.c2.extra_api_files = {PATH: VULNERABLE}

        version = await _generate_again(client, project_id, supersede=True)

        files, rows = await _code_at(client, project_id, version)
        assert files[PATH] == VULNERABLE, "a fix the reviewer let go came back"
        assert rows[PATH].carried_fixes == []
        assert await _said_about(client, project_id, version) == [], "it was reported again"
