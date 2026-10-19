"""The push over a mock transport: real sequence, real bodies, no network.

The recorder plays GitHub and keeps every request, so the tests assert what
was actually sent: the order of calls, inline tree content, the commit
parentage, and that the token never leaks through an error path.
"""

import json

import httpx
import pytest
from c2.repo.github import NO_CONNECTION, GitHubPushError, land, push_monorepo, redact
from sdlc_contracts import RepositoryPointer

TOKEN = "ghp_secret_a1b2c3"


class Recorder:
    """Answers like GitHub, remembers like a test double."""

    def __init__(
        self,
        *,
        existing_repo: bool = False,
        broken_step: str | None = None,
        branch_exists: bool = False,
        main_tip: str = "base111",
        main_moved: bool = False,
        open_pulls: list[dict] | None = None,
        pulls_refused: bool = False,
    ):
        self.requests: list[httpx.Request] = []
        self.existing_repo = existing_repo
        self.broken_step = broken_step
        self.branch_exists = branch_exists
        self.main_tip = main_tip
        #: The default branch moved on since the version was pushed, so moving
        #: it to the version is not a fast-forward.
        self.main_moved = main_moved
        #: Pull requests already open on the repository, as GitHub lists them.
        self.open_pulls = open_pulls or []
        self.pulls_refused = pulls_refused

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = f"{request.method} {request.url.path}"
        if self.broken_step and self.broken_step in key:
            # A hostile error body that echoes the caller's header back.
            return httpx.Response(500, json={"message": f"boom {TOKEN}"})
        if key == "POST /repos/vinozhan/shopflow/pulls":
            if self.pulls_refused:
                return httpx.Response(403, json={"message": "Resource not accessible"})
            return httpx.Response(
                201,
                json={"number": 7, "html_url": "https://github.com/vinozhan/shopflow/pull/7"},
            )
        if key == "GET /repos/vinozhan/shopflow/pulls":
            return httpx.Response(200, json=self.open_pulls)
        if request.method == "PATCH" and "/pulls/" in request.url.path:
            return httpx.Response(200, json={"state": "closed"})
        if key == "POST /user/repos":
            if self.existing_repo:
                return httpx.Response(422, json={"message": "name already exists"})
            return httpx.Response(201, json=self._repository())
        if key == "GET /user":
            return httpx.Response(200, json={"login": "vinozhan"})
        if key == "GET /repos/vinozhan/shopflow":
            return httpx.Response(200, json=self._repository())
        if key == "GET /repos/vinozhan/shopflow/git/ref/heads/main":
            return httpx.Response(200, json={"object": {"sha": self.main_tip}})
        if key == "GET /repos/vinozhan/shopflow/git/commits/commit333":
            return httpx.Response(200, json={"sha": "commit333", "tree": {"sha": "tree222"}})
        if key == "POST /repos/vinozhan/shopflow/git/refs":
            if self.branch_exists:
                return httpx.Response(422, json={"message": "Reference already exists"})
            return httpx.Response(201, json={"ref": json.loads(request.content)["ref"]})
        if key == "PATCH /repos/vinozhan/shopflow/git/refs/heads/code/v2":
            return httpx.Response(200, json={"object": {"sha": "commit333"}})
        if key == "POST /repos/vinozhan/shopflow/git/trees":
            return httpx.Response(201, json={"sha": "tree222"})
        if key == "POST /repos/vinozhan/shopflow/git/commits":
            # A commit on a branch that moved on is a landing commit of its own.
            parents = json.loads(request.content)["parents"]
            return httpx.Response(
                201, json={"sha": "landing555" if parents == ["layer444"] else "commit333"}
            )
        if key == "PATCH /repos/vinozhan/shopflow/git/refs/heads/main":
            sha = json.loads(request.content)["sha"]
            if self.main_moved and sha == "commit333":
                return httpx.Response(422, json={"message": "Update is not a fast forward"})
            return httpx.Response(200, json={"object": {"sha": sha}})
        return httpx.Response(404, json={"message": f"unexpected call {key}"})

    @staticmethod
    def _repository() -> dict:
        return {
            "name": "shopflow",
            "owner": {"login": "vinozhan"},
            "default_branch": "main",
            "html_url": "https://github.com/vinozhan/shopflow",
        }


def _client(recorder: Recorder) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(recorder.handler))


FILES = {"README.md": "# ShopFlow\n", "apps/api/src/app.ts": "export const app = 1;\n"}


class TestTheHappyPath:
    async def test_one_tree_one_commit_one_ref_update_in_order(self) -> None:
        recorder = Recorder()
        async with _client(recorder) as client:
            result = await push_monorepo(
                FILES, name="shopflow", token=TOKEN, client=client, message="Generate v1"
            )
        calls = [f"{r.method} {r.url.path}" for r in recorder.requests]
        assert calls == [
            "POST /user/repos",
            "GET /repos/vinozhan/shopflow/git/ref/heads/main",
            "POST /repos/vinozhan/shopflow/git/trees",
            "POST /repos/vinozhan/shopflow/git/commits",
            "PATCH /repos/vinozhan/shopflow/git/refs/heads/main",
        ]
        assert result.pointer is not None and result.reason is None
        assert result.pointer.owner == "vinozhan"
        assert result.pointer.commit_sha == "commit333"
        assert result.pointer.url == "https://github.com/vinozhan/shopflow"

    async def test_the_tree_carries_every_file_inline(self) -> None:
        recorder = Recorder()
        async with _client(recorder) as client:
            await push_monorepo(FILES, name="shopflow", token=TOKEN, client=client, message="m")
        tree_request = next(r for r in recorder.requests if r.url.path.endswith("/git/trees"))
        body = json.loads(tree_request.content)
        assert {entry["path"] for entry in body["tree"]} == set(FILES)
        assert all(entry["type"] == "blob" and entry["mode"] == "100644" for entry in body["tree"])
        assert all("content" in entry and "sha" not in entry for entry in body["tree"])

    async def test_the_commit_sits_on_the_branch_tip(self) -> None:
        recorder = Recorder()
        async with _client(recorder) as client:
            await push_monorepo(
                FILES, name="shopflow", token=TOKEN, client=client, message="Generate v1"
            )
        commit_request = next(r for r in recorder.requests if r.url.path.endswith("/git/commits"))
        body = json.loads(commit_request.content)
        assert body == {"message": "Generate v1", "tree": "tree222", "parents": ["base111"]}

    async def test_the_calls_authenticate_the_documented_way(self) -> None:
        recorder = Recorder()
        async with _client(recorder) as client:
            await push_monorepo(FILES, name="shopflow", token=TOKEN, client=client, message="m")
        for request in recorder.requests:
            assert request.headers["Authorization"] == f"Bearer {TOKEN}"
            assert request.headers["X-GitHub-Api-Version"] == "2022-11-28"


class TestTheSecondPush:
    async def test_an_existing_repository_is_found_and_reused(self) -> None:
        recorder = Recorder(existing_repo=True)
        async with _client(recorder) as client:
            result = await push_monorepo(
                FILES, name="shopflow", token=TOKEN, client=client, message="Generate v2"
            )
        calls = [f"{r.method} {r.url.path}" for r in recorder.requests]
        assert calls[:3] == ["POST /user/repos", "GET /user", "GET /repos/vinozhan/shopflow"]
        assert result.pointer is not None
        assert result.pointer.commit_sha == "commit333"


class TestTheHonestOutcomes:
    async def test_no_connection_is_a_reason_and_zero_requests(self) -> None:
        recorder = Recorder()
        async with _client(recorder) as client:
            result = await push_monorepo(
                FILES, name="shopflow", token=None, client=client, message="m"
            )
        assert result.pointer is None
        assert result.reason == NO_CONNECTION
        assert recorder.requests == []

    async def test_an_error_body_echoing_the_token_is_redacted(self) -> None:
        recorder = Recorder(broken_step="git/trees")
        async with _client(recorder) as client:
            with pytest.raises(GitHubPushError) as caught:
                await push_monorepo(FILES, name="shopflow", token=TOKEN, client=client, message="m")
        text = str(caught.value)
        assert TOKEN not in text
        assert "[redacted]" in text
        assert "500" in text

    def test_redact_survives_an_empty_token(self) -> None:
        assert redact("message", "") == "message"


POINTER = RepositoryPointer(
    owner="vinozhan",
    name="shopflow",
    default_branch="main",
    commit_sha="commit333",
    url="https://github.com/vinozhan/shopflow",
    branch="code/v2",
)


def _calls(recorder: Recorder) -> list[str]:
    return [f"{r.method} {r.url.path}" for r in recorder.requests]


class TestAVersionOnItsOwnBranch:
    """Every version landed on main, unreviewed and failing ones included:
    Task Tracker's main received version 3 with its typecheck failing."""

    async def test_it_goes_to_its_branch_and_the_default_branch_stays(self) -> None:
        recorder = Recorder()
        async with _client(recorder) as client:
            result = await push_monorepo(
                FILES, name="shopflow", token=TOKEN, client=client, message="m", branch="code/v2"
            )
        assert _calls(recorder)[:5] == [
            "POST /user/repos",
            "GET /repos/vinozhan/shopflow/git/ref/heads/main",
            "POST /repos/vinozhan/shopflow/git/trees",
            "POST /repos/vinozhan/shopflow/git/commits",
            "POST /repos/vinozhan/shopflow/git/refs",
        ]
        created = json.loads(recorder.requests[4].content)
        assert created == {"ref": "refs/heads/code/v2", "sha": "commit333"}
        assert result.pointer is not None
        assert (result.pointer.branch, result.pointer.default_branch) == ("code/v2", "main")

    async def test_a_second_push_of_a_version_replaces_its_branch(self) -> None:
        recorder = Recorder(branch_exists=True)
        async with _client(recorder) as client:
            await push_monorepo(
                FILES, name="shopflow", token=TOKEN, client=client, message="m", branch="code/v2"
            )
        moved = next(r for r in recorder.requests if r.method == "PATCH")
        assert f"{moved.method} {moved.url.path}" == (
            "PATCH /repos/vinozhan/shopflow/git/refs/heads/code/v2"
        )
        assert json.loads(moved.content) == {"sha": "commit333", "force": True}


class TestAVersionOpensAPullRequest:
    """A version went to its branch and the review moved the default branch to
    it: nothing on GitHub showed the change as one to review (review item C2-8)."""

    async def _push(self, recorder: Recorder, **how):
        async with _client(recorder) as client:
            return await push_monorepo(
                FILES, name="shopflow", token=TOKEN, client=client, message="Code version 2", **how
            )

    async def test_its_branch_is_proposed_into_the_default_branch(self) -> None:
        recorder = Recorder()

        result = await self._push(recorder, branch="code/v2")

        opened = next(
            r for r in recorder.requests if r.url.path.endswith("/pulls") and r.method == "POST"
        )
        assert json.loads(opened.content) == {
            "title": "Code version 2",
            "head": "code/v2",
            "base": "main",
            "body": "Opened by the platform for the code review. Approving the review lands it.",
        }
        assert result.pointer is not None
        assert result.pointer.pull_request_number == 7
        assert result.pointer.pull_request_url == "https://github.com/vinozhan/shopflow/pull/7"

    async def test_an_earlier_version_s_open_pull_request_is_closed(self) -> None:
        recorder = Recorder(
            open_pulls=[
                {"number": 5, "head": {"ref": "code/v1"}},
                {"number": 6, "head": {"ref": "feature/by-a-person"}},
                {"number": 7, "head": {"ref": "code/v2"}},
            ]
        )

        await self._push(recorder, branch="code/v2")

        closed = [r for r in recorder.requests if r.method == "PATCH" and "/pulls/" in r.url.path]
        assert [r.url.path for r in closed] == ["/repos/vinozhan/shopflow/pulls/5"]
        assert json.loads(closed[0].content) == {"state": "closed"}

    async def test_a_push_to_the_default_branch_opens_none(self) -> None:
        recorder = Recorder()

        result = await self._push(recorder)

        assert not [r for r in recorder.requests if "/pulls" in r.url.path]
        assert result.pointer is not None and result.pointer.pull_request_number is None

    async def test_a_pull_request_github_refuses_does_not_undo_the_push(self) -> None:
        recorder = Recorder(pulls_refused=True)

        result = await self._push(recorder, branch="code/v2")

        assert result.pointer is not None and result.pointer.commit_sha == "commit333"
        assert result.pointer.pull_request_url == ""

    async def test_landing_by_a_commit_of_its_own_closes_the_pull_request(self) -> None:
        # A fast-forward makes the version's commit part of the default branch,
        # which GitHub marks merged by itself. A landing commit does not.
        proposed = POINTER.model_copy(update={"pull_request_number": 7})
        moved_on, forward = Recorder(main_tip="layer444", main_moved=True), Recorder()
        async with _client(moved_on) as client:
            await land(proposed, token=TOKEN, client=client, message="Land v2")
        async with _client(forward) as client:
            await land(proposed, token=TOKEN, client=client, message="Land v2")

        assert [r.url.path for r in moved_on.requests if "/pulls/" in r.url.path] == [
            "/repos/vinozhan/shopflow/pulls/7"
        ]
        assert not [r for r in forward.requests if "/pulls" in r.url.path]


class TestLandingAnApprovedVersion:
    async def test_the_default_branch_fast_forwards_to_it(self) -> None:
        recorder = Recorder()
        async with _client(recorder) as client:
            result = await land(POINTER, token=TOKEN, client=client, message="Land v2")
        assert (result.commit_sha, result.how) == ("commit333", "fast-forward")
        moved = recorder.requests[-1]
        assert json.loads(moved.content) == {"sha": "commit333", "force": False}

    async def test_a_branch_that_moved_on_gets_a_commit_with_the_same_tree(self) -> None:
        """A release committed its layer on main after the version was pushed,
        so moving main to the version would drop the layer: nothing is
        rewritten, and main gains a commit carrying exactly the version's tree."""
        recorder = Recorder(main_tip="layer444", main_moved=True)
        async with _client(recorder) as client:
            result = await land(POINTER, token=TOKEN, client=client, message="Land v2")
        assert (result.commit_sha, result.how) == ("landing555", "landing commit")
        commit = next(
            r for r in recorder.requests if f"{r.method} {r.url.path}".endswith("/git/commits")
        )
        assert json.loads(commit.content) == {
            "message": "Land v2",
            "tree": "tree222",
            "parents": ["layer444"],
        }
        assert all(
            json.loads(r.content).get("force") is False
            for r in recorder.requests
            if r.method == "PATCH"
        )

    async def test_a_version_already_there_moves_nothing(self) -> None:
        recorder = Recorder(main_tip="commit333")
        async with _client(recorder) as client:
            result = await land(POINTER, token=TOKEN, client=client, message="Land v2")
        assert result.how == "already there"
        assert not any(r.method == "PATCH" for r in recorder.requests)

    async def test_no_connection_lands_nothing(self) -> None:
        recorder = Recorder()
        async with _client(recorder) as client:
            result = await land(POINTER, token=None, client=client, message="Land v2")
        assert result.reason == NO_CONNECTION and recorder.requests == []
