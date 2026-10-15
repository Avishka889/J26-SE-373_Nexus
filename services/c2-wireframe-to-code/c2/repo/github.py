"""The GitHub push: one tree, one commit, one ref update.

The REST calls a classic PAT with the `repo` scope can make, and nothing
else: create the repository (or find it again on a second push), read the
branch tip, post one tree with every file's content inline, post one commit
on that tip, move the branch. No git binary, no clone, no per blob calls.

Two honesty rules live here. A missing connection is a recorded outcome
("not pushed: ..."), never an invented URL. And the token never appears in
an error or a log: every failure message passes through redact() first,
because GitHub error bodies and request dumps can echo headers back.
"""

import logging
from dataclasses import dataclass

import httpx
from sdlc_contracts import RepositoryPointer

log = logging.getLogger(__name__)

API = "https://api.github.com"
NO_CONNECTION = "not pushed: the project owner has no GitHub connection"


class GitHubPushError(RuntimeError):
    """A push step failed; the message is already redacted."""


@dataclass(frozen=True)
class PushResult:
    """Exactly one side is set: the pointer, or the reason there is none."""

    pointer: RepositoryPointer | None = None
    reason: str | None = None


@dataclass(frozen=True)
class LandResult:
    """Where the default branch went: the commit it now carries and how, or why not."""

    commit_sha: str | None = None
    #: "fast-forward", "landing commit", or "already there".
    how: str = ""
    reason: str | None = None


def redact(text: str, token: str) -> str:
    return text.replace(token, "[redacted]") if token else text


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def _call(
    client: httpx.AsyncClient,
    token: str,
    method: str,
    path: str,
    *,
    json: dict | None = None,
    accept_statuses: tuple[int, ...] = (),
) -> httpx.Response:
    try:
        response = await client.request(method, f"{API}{path}", headers=_headers(token), json=json)
    except httpx.HTTPError as error:
        raise GitHubPushError(
            redact(f"GitHub {method} {path} did not answer: {error}", token)
        ) from None
    if response.is_success or response.status_code in accept_statuses:
        return response
    raise GitHubPushError(
        redact(
            f"GitHub {method} {path} answered {response.status_code}: {response.text[:300]}",
            token,
        )
    )


async def _create_or_find_repository(client: httpx.AsyncClient, token: str, name: str) -> dict:
    """Create the repository, or find it again when this is a second push."""
    created = await _call(
        client,
        token,
        "POST",
        "/user/repos",
        json={"name": name, "private": True, "auto_init": True},
        accept_statuses=(422,),
    )
    if created.status_code != 422:
        return created.json()
    # 422 is "name already exists on this account": a regeneration pushing
    # again. Resolve the login and fetch the existing repository.
    user = await _call(client, token, "GET", "/user")
    login = user.json()["login"]
    existing = await _call(client, token, "GET", f"/repos/{login}/{name}")
    return existing.json()


async def push_monorepo(
    files: dict[str, str],
    *,
    name: str,
    token: str | None,
    client: httpx.AsyncClient,
    message: str,
    branch: str | None = None,
) -> PushResult:
    """Push the whole file set as one commit; the tree is the full snapshot.

    With `branch`, the commit goes to a branch of its own, on the default
    branch's tip, and the default branch does not move: it carries a version
    once the code review approves it (`land`). Without, the default branch
    moves, as every push did before: unreviewed and failing versions included.
    """
    if not token:
        return PushResult(reason=NO_CONNECTION)

    repository = await _create_or_find_repository(client, token, name)
    owner = repository["owner"]["login"]
    repo_name = repository["name"]
    default_branch = repository["default_branch"]
    base = f"/repos/{owner}/{repo_name}"

    tip = await _call(client, token, "GET", f"{base}/git/ref/heads/{default_branch}")
    parent_sha = tip.json()["object"]["sha"]

    tree = await _call(
        client,
        token,
        "POST",
        f"{base}/git/trees",
        json={
            "tree": [
                {"path": path, "mode": "100644", "type": "blob", "content": content}
                for path, content in sorted(files.items())
            ]
        },
    )
    commit = await _call(
        client,
        token,
        "POST",
        f"{base}/git/commits",
        json={"message": message, "tree": tree.json()["sha"], "parents": [parent_sha]},
    )
    commit_sha = commit.json()["sha"]
    if branch:
        await _set_branch(client, token, base, branch, commit_sha)
    else:
        await _call(
            client,
            token,
            "PATCH",
            f"{base}/git/refs/heads/{default_branch}",
            json={"sha": commit_sha, "force": False},
        )

    log.info("pushed %s files to %s/%s@%s", len(files), owner, repo_name, branch or default_branch)
    return PushResult(
        pointer=RepositoryPointer(
            provider="github",
            owner=owner,
            name=repo_name,
            default_branch=default_branch,
            commit_sha=commit_sha,
            url=repository["html_url"],
            branch=branch or "",
        )
    )


async def _set_branch(
    client: httpx.AsyncClient, token: str, base: str, branch: str, sha: str
) -> None:
    """Point a version's own branch at its commit, creating it the first time.

    Forced on a second push of the same version: the branch holds that one
    version, and pushing it again replaces it.
    """
    created = await _call(
        client,
        token,
        "POST",
        f"{base}/git/refs",
        json={"ref": f"refs/heads/{branch}", "sha": sha},
        accept_statuses=(422,),
    )
    if created.status_code == 422:
        await _call(
            client,
            token,
            "PATCH",
            f"{base}/git/refs/heads/{branch}",
            json={"sha": sha, "force": True},
        )


async def land(
    pointer: RepositoryPointer,
    *,
    token: str | None,
    client: httpx.AsyncClient,
    message: str,
) -> LandResult:
    """Move the default branch to an approved version, rewriting nothing on it.

    A fast-forward when the default branch has not moved since the version was
    pushed on its tip. When it has (a release committed its layer on top in
    between), a commit carrying exactly the version's tree on the branch's tip:
    the branch holds the approved code either way, and a release reads a commit
    with the verified tree as the code it was built from.
    """
    if not token:
        return LandResult(reason=NO_CONNECTION)
    base = f"/repos/{pointer.owner}/{pointer.name}"
    branch = pointer.default_branch
    tip = (await _call(client, token, "GET", f"{base}/git/ref/heads/{branch}")).json()
    tip_sha = tip["object"]["sha"]
    if tip_sha == pointer.commit_sha:
        return LandResult(commit_sha=tip_sha, how="already there")
    moved = await _call(
        client,
        token,
        "PATCH",
        f"{base}/git/refs/heads/{branch}",
        json={"sha": pointer.commit_sha, "force": False},
        accept_statuses=(422,),
    )
    if moved.status_code != 422:
        return LandResult(commit_sha=pointer.commit_sha, how="fast-forward")
    # Not a fast-forward: the branch moved on after the version was pushed.
    code = (await _call(client, token, "GET", f"{base}/git/commits/{pointer.commit_sha}")).json()
    commit = (
        await _call(
            client,
            token,
            "POST",
            f"{base}/git/commits",
            json={"message": message, "tree": code["tree"]["sha"], "parents": [tip_sha]},
        )
    ).json()
    await _call(
        client,
        token,
        "PATCH",
        f"{base}/git/refs/heads/{branch}",
        json={"sha": commit["sha"], "force": False},
    )
    return LandResult(commit_sha=commit["sha"], how="landing commit")
