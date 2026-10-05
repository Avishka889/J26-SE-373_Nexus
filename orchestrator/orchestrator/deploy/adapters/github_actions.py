"""The cloud release target: GitHub runs the generated deploy workflow; the orchestrator drives it.

The orchestrator decides and records; GitHub Actions tests the commit and
deploys the frontend, holding only what that needs (a Vercel token and ids),
never a Render credential: the backend is deployed by the orchestrator itself,
through Render's API (the `render` adapter), between the test and the
dispatch. Four steps are GitHub's; the check after them is the orchestrator's
own. The Vercel project and addresses are the project's own, made by the
platform (`deploy/provision.py`).

- **commit**: the candidate's whole file set committed as one tree: every
  file of its code version, the tests testing wrote beside it included, and
  C4's deployment layer, so the release is exactly the candidate staging
  verified, which is checked by hashing them before anything is sent. Its
  parent is the branch head, which is the version's commit (or the one it
  patched, for a version an accepted fix wrote) on a code version's first
  release and an earlier release's layer after that. Anything else between
  them (a commit this platform did not make for this project) is refused:
  committing on it would release code nobody verified. The tree was C2's
  commit's with the tests and the layer added, until 2026-10-05: a version an
  applied fix wrote carried the patched version's commit, so production ran
  the code without the fix while every fingerprint named the fixed candidate.
- **secrets**: each deploy secret sealed with a libsodium sealed box to the key
  GitHub publishes (repository or environment), so the value leaves the
  orchestrator only encrypted, and only to GitHub. Where GitHub has required
  reviewers (the workflow then names `production`), the secrets go to that
  environment, created with the project's owner as its reviewer, so GitHub's
  own rule mirrors the platform's decision; everywhere else they are the
  repository's, which is what a workflow naming no environment reads.
- **test**: `deploy.yml` dispatched at its test stage with the commit, the
  candidate hash and both origins, and its run followed to the end: it tests
  the commit and builds its frontend, before anything moves traffic. The
  backend went live first until review item C4-8, so a failing test needed a
  rollback; now it stops the release, and the secrets are undone.
- **dispatch**: `deploy.yml` dispatched again at its deploy stage, which deploys
  the frontend and verifies both. Where GitHub has reviewers, the job waiting
  on `production` is approved with the platform's decision as the comment. It
  moves traffic, as the backend step before it did. A rollback's
  `redeploy-frontend` is this stage too: its commit was tested when it shipped.

Every call carries the token only in its header, and every message that could
carry an upstream error is redacted.
"""

import asyncio
import base64
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

import httpx
from nacl.public import PublicKey, SealedBox
from psycopg_pool import AsyncConnectionPool
from sdlc_contracts import RepositoryPointer
from sdlc_contracts.deploy_rules import candidate_hash, fingerprint_file

from ...crypto import decrypt, redacted
from ...db import store
from ...probes.github import GITHUB_API, repository_protection
from ...saga.executor import StepContext, StepFailed, StepResult
from ..provision import cloud_resources_of

WORKFLOW = "deploy.yml"
ENVIRONMENT = "production"
RUN_TIMEOUT_SECONDS = 45 * 60
POLL_SECONDS = 10.0
#: How long the run a dispatch answered 204 started may take to be listed.
RUN_APPEARS_SECONDS = 120.0
#: How long before GitHub's answer to a dispatch the run it started may say it was created.
RUN_CREATED_LEEWAY_SECONDS = 60
#: How far back from the branch head a release looks for C2's commit, through
#: layers earlier releases committed. Far more releases than one code version sees.
LAYER_WALK = 50
#: The last line of every layer commit's message, naming the deployment that made it.
_DEPLOYMENT_LINE = re.compile(r"^Deployment ([0-9a-f-]{36})\.$", re.MULTILINE)


def _deployment_named(message: str) -> uuid.UUID | None:
    """The deployment a layer commit's message names, or None for any other commit."""
    found = _DEPLOYMENT_LINE.search(message)
    if found is None:
        return None
    try:
        return uuid.UUID(found.group(1))
    except ValueError:
        return None


def _answered_at(answer: httpx.Response) -> datetime:
    """When GitHub answered, by its own clock; by this machine's if it did not say."""
    try:
        return parsedate_to_datetime(answer.headers["date"])
    except (KeyError, TypeError, ValueError):
        return datetime.now(UTC)


def seal(public_key: str, value: str) -> str:
    """A libsodium sealed box to GitHub's public key, base64 encoded, as GitHub asks."""
    box = SealedBox(PublicKey(base64.b64decode(public_key)))
    return base64.b64encode(box.encrypt(value.encode("utf-8"))).decode("ascii")


@dataclass(frozen=True)
class Cloud:
    """Everything a cloud step needs, read from the store for the deployment."""

    token: str
    repository: RepositoryPointer
    layer: dict[str, str]
    #: Every file of the candidate's code version, the tests testing wrote beside
    #: it included: what a release commits, whole. Empty for a rollback, which
    #: commits nothing.
    code: dict[str, str]
    #: What the release's files hash to, for the commit to hold against the
    #: candidate; None for a rollback.
    tree_hash: str | None
    secrets: dict[str, str]
    backend_origin: str
    frontend_origin: str
    owner_login: str


class GithubActions:
    def __init__(
        self,
        *,
        pool: AsyncConnectionPool,
        secret_key: str,
        client: httpx.AsyncClient | None = None,
        poll_seconds: float = POLL_SECONDS,
        run_timeout: float = RUN_TIMEOUT_SECONDS,
        run_appears_timeout: float = RUN_APPEARS_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._pool = pool
        self._secret_key = secret_key
        self._client = client
        self._poll = poll_seconds
        self._timeout = run_timeout
        self._run_appears = run_appears_timeout
        self._sleep = sleep

    # -------------------------------------------------------------- context

    async def _cloud(self, ctx: StepContext) -> Cloud:
        row = ctx.deployment
        project_id = row["project_id"]
        async with self._pool.connection() as conn:
            project = await store.project_without_owner_check(conn, project_id)
            if project is None:
                raise StepFailed("the project no longer exists")
            owner = project["owner_id"]
            # The candidate's code version names the commit a release is built on;
            # a rollback redeploys a recorded commit and needs only the repository,
            # which is the same whichever version pushed it.
            code_version = (
                ctx.candidate.code_version
                if ctx.candidate is not None
                else await store.current_code_version(conn, project_id)
            )
            # Its own push, or for a version an accepted fix wrote and nobody has
            # pushed yet, the version it patched: the repository is the same,
            # and the release commits the files whole either way.
            pointer_body, _ = await store.repository_field_through_patches(
                conn, project_id, code_version, "repository"
            )
            layer = await store.deploy_files(
                conn,
                project_id,
                version=row["deploy_version"],
                stage_id="pipeline-generation",
            )
            code_files: dict[str, str] = {}
            tree_hash: str | None = None
            if ctx.candidate is not None:
                # The version's files with C3's tests beside them, as staging built
                # the candidate. Without the tests the repository held no test the
                # platform approved, and GitHub's run tested less than staging.
                code_files = await store.code_files(conn, project_id, version=code_version)
                tree_hash = candidate_hash(
                    {**code_files, **layer}, fingerprint=fingerprint_file(layer) or ""
                )
            body = await store.settings_body(conn, owner)
            made = await cloud_resources_of(conn, project_id, owner)

            async def secret(provider: str) -> str:
                ciphertext = await store.get_secret(conn, f"{owner}:{provider}")
                if ciphertext is None:
                    raise StepFailed(f"there is no {provider} connection to deploy with")
                return decrypt(self._secret_key, ciphertext)

            token = await secret("github")
            vercel_token = await secret("vercel")
        pointer = RepositoryPointer.model_validate(pointer_body) if pointer_body else None
        if pointer is None:
            raise StepFailed(f"code version {code_version} was never pushed to a repository")
        if made is None:
            raise StepFailed(
                "this project has no Vercel project or Render service yet: an analysis with the "
                "cloud target makes them"
            )
        connections = body.get("connections") or {}
        github_meta = (connections.get("github") or {}).get("probe") or {}
        return Cloud(
            token=token,
            repository=pointer,
            layer=layer,
            code=code_files,
            tree_hash=tree_hash,
            secrets={
                "VERCEL_TOKEN": vercel_token,
                "VERCEL_ORG_ID": made.vercel.org_id,
                "VERCEL_PROJECT_ID": made.vercel.project_id,
            },
            backend_origin=made.render.origin.rstrip("/"),
            frontend_origin=made.vercel.origin.rstrip("/"),
            owner_login=str(github_meta.get("login") or pointer.owner),
        )

    async def _call(
        self, cloud: Cloud, method: str, path: str, *, json: Any = None, ok=(200, 201, 204)
    ) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {cloud.token}",
            "Accept": "application/vnd.github+json",
            # The version the whole platform pins. Moving to 2026-03-10 means the
            # dispatch drops `return_run_details`, which that version removed.
            "X-GitHub-Api-Version": "2022-11-28",
        }
        owns = self._client is None
        http = self._client or httpx.AsyncClient(timeout=30)
        try:
            answer = await http.request(method, f"{GITHUB_API}{path}", headers=headers, json=json)
        except httpx.HTTPError as error:
            raise StepFailed(
                redacted(f"GitHub could not be reached: {error}", cloud.token)
            ) from error
        finally:
            if owns:
                await http.aclose()
        if answer.status_code not in ok:
            message = redacted(answer.text[:300], cloud.token, *cloud.secrets.values())
            raise StepFailed(f"GitHub answered {answer.status_code} to {method} {path}: {message}")
        return answer

    def _repo(self, cloud: Cloud) -> str:
        return f"/repos/{cloud.repository.owner}/{cloud.repository.name}"

    # ---------------------------------------------------------------- steps

    async def execute(self, ctx: StepContext) -> StepResult:
        cloud = await self._cloud(ctx)
        if ctx.step.id == "commit":
            return await self._commit(ctx, cloud)
        if ctx.step.id == "secrets":
            return await self._secrets(cloud)
        if ctx.step.id == "test":
            return await self._dispatch(ctx, cloud, stage="test")
        if ctx.step.id in ("dispatch", "redeploy-frontend"):
            return await self._dispatch(ctx, cloud, stage="deploy")
        raise StepFailed(f"the cloud target has no step called {ctx.step.id}")

    async def publish(self, ctx: StepContext, *, commit: str, notes: str) -> dict[str, str]:
        """Tag a verified release's commit, with its notes, as a GitHub release.

        `release-v<deploy version>`, so the repository says which commit a deploy
        version is. 422 is GitHub saying the tag is already there.
        """
        cloud = await self._cloud(ctx)
        tag = f"release-v{ctx.deployment['deploy_version']}"
        answer = await self._call(
            cloud,
            "POST",
            f"{self._repo(cloud)}/releases",
            json={
                "tag_name": tag,
                "target_commitish": commit,
                "name": f"Deploy version {ctx.deployment['deploy_version']}",
                "body": notes,
            },
            ok=(201, 422),
        )
        url = answer.json().get("html_url", "") if answer.status_code == 201 else ""
        return {"tag": tag, "url": url or "already tagged"}

    async def _layers_only_since(self, ctx: StepContext, cloud: Cloud, head: str) -> None:
        """Refuse unless every commit between C2's and the head is this project's own layer.

        The first release of a code version finds the branch at C2's commit, or at
        the commit that landed it there with exactly its tree. A later one finds it
        at the layer an earlier release committed on top, and may build on that,
        because those commits hold only files this platform generated. A commit
        anyone else made in between is code nobody verified, and is refused.
        """
        repo, branch = self._repo(cloud), cloud.repository.default_branch
        base, sha = cloud.repository.commit_sha, head
        code_tree: str | None = None
        for _ in range(LAYER_WALK):
            if sha == base:
                return
            commit = (await self._call(cloud, "GET", f"{repo}/git/commits/{sha}")).json()
            # An approved version lands on the default branch by a commit of its
            # own when the branch had moved on since the version was pushed:
            # exactly the version's tree, so exactly the code staging verified.
            if code_tree is None:
                code_tree = (await self._call(cloud, "GET", f"{repo}/git/commits/{base}")).json()[
                    "tree"
                ]["sha"]
            if (commit.get("tree") or {}).get("sha") == code_tree:
                return
            parents = [parent["sha"] for parent in commit.get("parents") or []]
            ours = False
            named = _deployment_named(commit.get("message") or "")
            if named is not None and len(parents) == 1:
                async with self._pool.connection() as conn:
                    row = await store.get_deployment(conn, named)
                ours = row is not None and row["project_id"] == ctx.deployment["project_id"]
            if not ours:
                raise StepFailed(
                    f"{branch} is at {head[:12]}, and {sha[:12]} on the way back to "
                    f"{base[:12]}, the commit this candidate was built from, is not a deployment "
                    "layer this platform committed for this project; the repository moved on "
                    "since, and committing on it would release code nobody verified"
                )
            sha = parents[0]
        raise StepFailed(
            f"{branch} is more than {LAYER_WALK} commits past {base[:12]}, the commit this "
            "candidate was built from; the repository moved on since, and committing on it "
            "would release code nobody verified"
        )

    async def _commit(self, ctx: StepContext, cloud: Cloud) -> StepResult:
        repo, branch = self._repo(cloud), cloud.repository.default_branch
        if ctx.candidate is not None and cloud.tree_hash != ctx.candidate.candidate_hash:
            # Tests are written beside the code at its version, so a testing run
            # after staging can change them under a candidate that is waiting.
            raise StepFailed(
                f"the files this release would commit hash to {str(cloud.tree_hash)[:12]}, not "
                f"to candidate {ctx.candidate.candidate_hash[:12]}, which staging verified: "
                "something changed since, so committing now would ship files nobody verified. "
                "Analyse again to build a candidate from what is there now"
            )
        committed = {**cloud.code, **cloud.layer}
        head = (await self._call(cloud, "GET", f"{repo}/git/ref/heads/{branch}")).json()
        parent = head["object"]["sha"]
        await self._layers_only_since(ctx, cloud, parent)
        # The whole tree, with no base: the release is exactly the files the
        # candidate hashed, so neither a commit without them nor an earlier
        # layer's files can linger in it.
        tree = (
            await self._call(
                cloud,
                "POST",
                f"{repo}/git/trees",
                json={
                    "tree": [
                        {"path": path, "mode": "100644", "type": "blob", "content": content}
                        for path, content in sorted(committed.items())
                    ],
                },
            )
        ).json()
        message = (
            f"Deployment layer for deploy version {ctx.deployment['deploy_version']}\n\n"
            f"Candidate {ctx.deployment['candidate_hash']}.\n"
            f"Deployment {ctx.deployment['id']}."
        )
        created = (
            await self._call(
                cloud,
                "POST",
                f"{repo}/git/commits",
                json={"message": message, "tree": tree["sha"], "parents": [parent]},
            )
        ).json()
        await self._call(
            cloud,
            "PATCH",
            f"{repo}/git/refs/heads/{branch}",
            json={"sha": created["sha"], "force": False},
        )
        return StepResult(
            resource={"commit": created["sha"], "branch": branch, "base": parent},
            log=(
                f"committed {len(cloud.code)} code and test files and {len(cloud.layer)} "
                f"deployment files on {parent[:12]} as {created['sha'][:12]}"
            ),
        )

    async def _secrets(self, cloud: Cloud) -> StepResult:
        repo = self._repo(cloud)
        protection, why = await repository_protection(
            cloud.token, cloud.repository.owner, cloud.repository.name, client=self._client
        )
        # Only where the workflow names `production`: that is where GitHub's reviewers
        # can hold the job, and a workflow naming no environment reads the repository's.
        environment = protection == "configured"
        if environment:
            body: dict[str, Any] = {}
            if protection == "configured":
                owner = (await self._call(cloud, "GET", f"/users/{cloud.owner_login}")).json()
                body = {"reviewers": [{"type": "User", "id": owner["id"]}]}
            await self._call(cloud, "PUT", f"{repo}/environments/{ENVIRONMENT}", json=body)
            base = f"{repo}/environments/{ENVIRONMENT}/secrets"
        else:
            base = f"{repo}/actions/secrets"
        key = (await self._call(cloud, "GET", f"{base}/public-key")).json()
        created: list[str] = []
        for name, value in cloud.secrets.items():
            answer = await self._call(
                cloud,
                "PUT",
                f"{base}/{name}",
                json={"encrypted_value": seal(key["key"], value), "key_id": key["key_id"]},
            )
            if answer.status_code == 201:
                created.append(name)
        return StepResult(
            resource={
                "scope": "environment" if environment else "repository",
                "protection": protection,
                "names": sorted(cloud.secrets),
                "created": created,
            },
            log=f"sealed {len(cloud.secrets)} secrets into the {base.rsplit('/', 1)[0]} ({why})",
        )

    async def _dispatch(self, ctx: StepContext, cloud: Cloud, *, stage: str) -> StepResult:
        repo = self._repo(cloud)
        if ctx.deployment["kind"] == "rollback":
            if ctx.previous is None or not ctx.previous.commit_sha:
                raise StepFailed("the verified release recorded no commit to redeploy")
            ref, candidate = ctx.previous.commit_sha, ctx.previous.candidate_hash
        else:
            commit = (ctx.earlier.get("commit") or {}).get("commit")
            if not commit:
                raise StepFailed("no commit was made to dispatch")
            ref, candidate = commit, ctx.deployment["candidate_hash"]
        protection = (ctx.earlier.get("secrets") or {}).get("protection")
        # Which workflow file runs is decided by the ref the dispatch names. A
        # release runs the one it just committed, on the branch. A rollback ran
        # the branch's too, the newer release's, so the older code was smoked
        # against the newer smoke list; it runs on the verified commit's own tag
        # now, which is that release's workflow (review item C4-4).
        on = cloud.repository.default_branch
        head_sha = ""
        if ctx.deployment["kind"] == "rollback" and ctx.previous is not None:
            on = f"verified-v{ctx.previous.deploy_version}-{ref[:7]}"
            # 422 is GitHub saying the tag is already there, from an earlier attempt.
            await self._call(
                cloud,
                "POST",
                f"{repo}/git/refs",
                json={"ref": f"refs/tags/{on}", "sha": ref},
                ok=(201, 422),
            )
            head_sha = ref
        else:
            head = (await self._call(cloud, "GET", f"{repo}/git/ref/heads/{on}")).json()
            head_sha = head["object"]["sha"]
        # On the API version this pins, GitHub names the run a dispatch started only
        # when asked (`return_run_details`, since 2026-02-19), and otherwise answers
        # 204 with no body, as the first live cloud release found. Should it answer
        # 204 all the same, the run is looked for among the workflow's runs.
        answer = await self._call(
            cloud,
            "POST",
            f"{repo}/actions/workflows/{WORKFLOW}/dispatches",
            json={
                "ref": on,
                "inputs": {
                    "stage": stage,
                    "ref": ref,
                    "candidate_hash": candidate,
                    "backend_origin": cloud.backend_origin,
                    "frontend_origin": cloud.frontend_origin,
                },
                "return_run_details": True,
            },
            ok=(200, 204),
        )
        if answer.status_code == 200:
            started = answer.json()
            run_id, url = started["workflow_run_id"], started.get("html_url", "")
        else:
            run_id, url = await self._run_started(cloud, head_sha, answer)
        began = time.monotonic()
        approved = False
        while time.monotonic() - began < self._timeout:
            run = (await self._call(cloud, "GET", f"{repo}/actions/runs/{run_id}")).json()
            if run.get("status") == "completed":
                if run.get("conclusion") != "success":
                    raise StepFailed(
                        f"the deploy workflow's {stage} stage ended {run.get('conclusion')}: {url}"
                    )
                return StepResult(
                    resource={
                        "run": run_id,
                        "url": url,
                        "ref": ref,
                        "origins": {
                            "backend": cloud.backend_origin,
                            "frontend": cloud.frontend_origin,
                        },
                        "approvedByPlatform": approved,
                    },
                    log=f"deploy.yml's {stage} stage, run {run_id}, succeeded: {url}",
                )
            # Only the deploy stage names `production`: the test stage waits on no one.
            if stage == "deploy" and protection == "configured" and not approved:
                pending = (
                    await self._call(
                        cloud, "GET", f"{repo}/actions/runs/{run_id}/pending_deployments"
                    )
                ).json()
                waiting = [
                    item["environment"]["id"]
                    for item in pending
                    if item.get("current_user_can_approve")
                ]
                if waiting:
                    authorised = ctx.deployment.get("authorised") or {}
                    await self._call(
                        cloud,
                        "POST",
                        f"{repo}/actions/runs/{run_id}/pending_deployments",
                        json={
                            "environment_ids": waiting,
                            "state": "approved",
                            "comment": (
                                "Approved at the platform's deployment review by "
                                f"{authorised.get('by') or 'the policy'}."
                            ),
                        },
                    )
                    approved = True
            await self._sleep(self._poll)
        raise StepFailed(
            f"the deploy workflow's {stage} stage did not finish within {self._timeout:.0f}s: {url}"
        )

    async def _run_started(
        self, cloud: Cloud, head: str, answer: httpx.Response
    ) -> tuple[int, str]:
        """The run a dispatch GitHub answered 204 started: the newest dispatched run of
        the workflow on the branch head it was given, created since GitHub answered.

        The time is GitHub's own, from its answer's `Date`, so this machine's clock,
        which may disagree with GitHub's, never decides which run is the new one.
        """
        since = _answered_at(answer) - timedelta(seconds=RUN_CREATED_LEEWAY_SECONDS)
        repo = self._repo(cloud)
        began = time.monotonic()
        while time.monotonic() - began < self._run_appears:
            listed = await self._call(
                cloud,
                "GET",
                f"{repo}/actions/workflows/{WORKFLOW}/runs?event=workflow_dispatch"
                f"&branch={cloud.repository.default_branch}&per_page=10",
            )
            started = [
                (created, run)
                for run in listed.json().get("workflow_runs") or []
                if run.get("head_sha") == head and run.get("created_at")
                for created in [datetime.fromisoformat(run["created_at"])]
                if created >= since
            ]
            if started:
                _, newest = max(started, key=lambda pair: pair[0])
                return int(newest["id"]), str(newest.get("html_url") or "")
            await self._sleep(self._poll)
        raise StepFailed(
            f"GitHub accepted the dispatch of {WORKFLOW}, and no run of it appeared within "
            f"{self._run_appears:.0f}s"
        )

    async def compensate(self, ctx: StepContext) -> None:
        """Only the secrets can be undone before traffic moves: the ones this release created."""
        if ctx.step.id != "secrets":
            return
        cloud = await self._cloud(ctx)
        resource = ctx.resource or {}
        repo = self._repo(cloud)
        base = (
            f"{repo}/environments/{ENVIRONMENT}/secrets"
            if resource.get("scope") == "environment"
            else f"{repo}/actions/secrets"
        )
        for name in resource.get("created") or []:
            await self._call(cloud, "DELETE", f"{base}/{name}", ok=(204, 404))

    async def find_existing(self, ctx: StepContext) -> dict[str, Any] | None:
        """A commit this deployment already made is found by its message; nothing else is adopted."""
        if ctx.step.id != "commit":
            return None
        cloud = await self._cloud(ctx)
        repo, branch = self._repo(cloud), cloud.repository.default_branch
        head = (await self._call(cloud, "GET", f"{repo}/git/ref/heads/{branch}")).json()
        sha = head["object"]["sha"]
        commit = (await self._call(cloud, "GET", f"{repo}/git/commits/{sha}")).json()
        if f"Deployment {ctx.deployment['id']}." in commit.get("message", ""):
            return {
                "commit": sha,
                "branch": branch,
                "base": (commit.get("parents") or [{}])[0].get("sha"),
            }
        return None
