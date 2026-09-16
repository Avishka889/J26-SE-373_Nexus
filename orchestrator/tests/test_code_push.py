# ruff: noqa: F811 - `client` is the code routes' fixture, imported to be used by name
"""Where generated code goes: each version to a branch of its own, the approved one on main.

Every version went to the default branch, unreviewed and failing ones included,
and without GitHub at build time the only way to the code was a whole new run.
GitHub is the canned C2 here, and the token is stood in for: this client acts as
the development identity, whose credentials a test must never write.
"""

import io
import zipfile

import pytest
from orchestrator.db import store
from orchestrator.graph import code_nodes
from sdlc_contracts import RepositoryPointer

from orchestrator import crypto

from .conftest import needs_db
from .test_code_routes import _advance_all, _generated, client  # noqa: F401

pytestmark = needs_db

POINTER = RepositoryPointer(
    owner="presenter",
    name="records",
    default_branch="main",
    commit_sha="c" * 40,
    url="https://github.com/presenter/records",
)


@pytest.fixture
def github(client):
    """The canned C2, answering pushes as GitHub would once connected."""
    canned = client.app.state.clients["c2"]
    canned.pushes_to = POINTER
    return canned


@pytest.fixture
def connected(github, monkeypatch):
    """A GitHub token, as far as the build and the landing can tell."""

    async def token(pool, project_id):
        return "a-token"

    monkeypatch.setattr(code_nodes, "_github_token", token)
    return github


async def _approve(client, project_id: str) -> None:
    decided = await client.post(
        f"/projects/{project_id}/code/decision", json={"kind": "approved", "note": "read it"}
    )
    assert decided.status_code == 200, decided.text
    await _advance_all(client, project_id)


async def _thread(client, project_id: str) -> list[str]:
    snapshot = (await client.get(f"/projects/{project_id}/code")).json()
    return [message["content"] for message in snapshot["thread"]]


class TestEachVersionOnItsOwnBranch:
    async def test_the_build_pushes_to_the_versions_branch_and_main_waits(
        self, client, connected
    ) -> None:
        _project_id, snapshot = await _generated(client)

        version = snapshot["codeVersion"]
        assert connected.pushed_branches == [f"code/v{version}"]
        assert snapshot["repository"]["repository"]["branch"] == f"code/v{version}"
        assert connected.landed == [], "nothing reaches main before its review"

    async def test_approving_lands_the_version_on_main(self, client, connected) -> None:
        project_id, snapshot = await _generated(client)

        await _approve(client, project_id)

        assert connected.landed == [POINTER.commit_sha]
        assert any(
            f"main now carries code version {snapshot['codeVersion']}" in line
            for line in await _thread(client, project_id)
        )

    async def test_a_landing_github_refuses_is_said_and_the_approval_stands(
        self, client, connected
    ) -> None:
        connected.land_refused = "GitHub PATCH answered 403: the token cannot write"
        project_id, _ = await _generated(client)

        await _approve(client, project_id)

        snapshot = (await client.get(f"/projects/{project_id}/code")).json()
        assert snapshot["gate"]["decision"]["kind"] == "approved"
        assert any("could not move" in line for line in await _thread(client, project_id))
        async with client.app.state.pool.connection() as conn:
            run = await store.latest_run(conn, project_id, component="c2")
        assert run["state"] == "done", "a landing GitHub refuses does not fail the run"


class TestGithubRefusingThePush:
    """A refusal raised at push time took the finished build with it: no build
    report was stored, and Push and Download were not offered."""

    REFUSAL = RuntimeError(
        "GitHub answered 403 to POST /git/trees: refusing to allow a token to create "
        "or update a workflow without the workflow scope"
    )

    async def test_the_build_is_kept_and_the_refusal_said(self, client, connected) -> None:
        connected.push_raises = self.REFUSAL

        _project_id, snapshot = await _generated(client)

        repository = snapshot["repository"]
        assert repository["build"] is not None, "the build report was kept"
        assert repository["repository"] is None
        assert repository["notPushedReason"].startswith("not pushed: GitHub answered 403")
        assert snapshot["stages"]["build"]["status"] == "complete"

    async def test_pushing_later_says_why_rather_than_failing(self, client, github) -> None:
        project_id, _ = await _generated(client)

        async def ciphertext(conn, key):
            return b"sealed"

        github.push_raises = self.REFUSAL
        with pytest.MonkeyPatch.context() as patched:
            patched.setattr(store, "get_secret", ciphertext)
            patched.setattr(crypto, "decrypt", lambda key, sealed: "a-token")
            answer = await client.post(f"/projects/{project_id}/code/push", json={})

        assert answer.status_code == 409
        assert "GitHub did not take the push: GitHub answered 403" in answer.text


class TestARebuildThatChangesThePushOutcome:
    """A rebuild set the side of the push it learned and never cleared the
    other: a pointer beside a not pushed reason is a record its own contract
    refuses, and the Code page could not load."""

    async def _rebuilt(self, client, project_id: str) -> dict:
        retried = await client.post(f"/projects/{project_id}/code/stages/build/retry")
        assert retried.status_code == 200, retried.text
        await _advance_all(client, project_id)
        answer = await client.get(f"/projects/{project_id}/code")
        assert answer.status_code == 200, answer.text
        build = answer.json()["stages"]["build"]
        assert build["status"] == "complete", build["error"]
        return answer.json()["repository"]

    async def test_pushed_on_the_rebuild_says_nothing_of_not_pushed(
        self, client, github, monkeypatch
    ) -> None:
        github.pushes_to = None
        project_id, snapshot = await _generated(client)
        assert snapshot["repository"]["notPushedReason"]
        github.pushes_to = POINTER

        async def token(pool, project_id):
            return "a-token"

        monkeypatch.setattr(code_nodes, "_github_token", token)

        repository = await self._rebuilt(client, project_id)

        assert repository["repository"]["branch"] == f"code/v{snapshot['codeVersion']}"
        assert repository["notPushedReason"] is None

    async def test_refused_on_the_rebuild_it_stays_where_it_was_pushed(
        self, client, connected
    ) -> None:
        project_id, snapshot = await _generated(client)
        connected.push_raises = RuntimeError("GitHub answered 502 to POST /git/trees")

        repository = await self._rebuilt(client, project_id)

        assert repository["repository"]["branch"] == f"code/v{snapshot['codeVersion']}"
        assert repository["notPushedReason"] is None


class TestPushingAVersionLater:
    """Built without GitHub, a version had no way to a repository but a new run."""

    @pytest.fixture
    def token_now(self, monkeypatch):
        async def ciphertext(conn, key):
            return b"sealed"

        monkeypatch.setattr(store, "get_secret", ciphertext)
        monkeypatch.setattr(crypto, "decrypt", lambda key, sealed: "a-token")

    async def test_an_approved_version_is_pushed_once_and_lands(
        self, client, github, token_now
    ) -> None:
        github.pushes_to = None
        project_id, snapshot = await _generated(client)
        assert snapshot["repository"]["repository"] is None
        await _approve(client, project_id)
        github.pushes_to = POINTER

        pushed = await client.post(f"/projects/{project_id}/code/push", json={})

        assert pushed.status_code == 200, pushed.text
        repository = pushed.json()["repository"]
        assert repository["repository"]["branch"] == f"code/v{snapshot['codeVersion']}"
        assert repository["notPushedReason"] is None
        assert github.landed == [POINTER.commit_sha]
        again = await client.post(f"/projects/{project_id}/code/push", json={})
        assert again.status_code == 409 and "already" in again.text

    async def test_without_a_connection_it_says_where_to_make_one(self, client) -> None:
        project_id, _ = await _generated(client)

        answer = await client.post(f"/projects/{project_id}/code/push", json={})

        assert answer.status_code == 409 and "connect GitHub in Settings" in answer.text


class TestTheArchive:
    async def test_a_version_downloads_as_its_generated_files(self, client) -> None:
        project_id, snapshot = await _generated(client)

        answer = await client.get(f"/projects/{project_id}/code/archive")

        assert answer.status_code == 200, answer.text
        assert answer.headers["content-type"] == "application/zip"
        assert "attachment" in answer.headers["content-disposition"]
        names = set(zipfile.ZipFile(io.BytesIO(answer.content)).namelist())
        generated = {row["path"] for row in snapshot["repository"]["manifest"]}
        assert names and names <= generated
