"""The backend on Render, deployed by the orchestrator through Render's API.

Render's API cannot create or read a deploy hook, so GitHub Actions could deploy
the backend only by holding the Render API key, which least privilege keeps in
the orchestrator. The platform deploys it here instead, as a step of its own,
before the workflow deploys the frontend that calls it:

- **backend** (a release) deploys the commit the `commit` step made;
  **restore-backend** (a rollback) deploys the recorded verified release's commit.
- The deploy is followed until Render says it is live, then until the backend
  serves the candidate's fingerprint at `/release.json`, so the frontend is
  never deployed against a backend that is not the approved one.
- A deploy that ends before going live (a failed build or pre-deploy, or one
  cancelled) moved no traffic: Render keeps the previous deploy serving. The
  step says so (`moved=False`), and the saga undoes the release as it undoes a
  step before traffic. Anything that fails after Render went live is a
  person's to undo (FR20).

The key travels only in a header, and every message that could echo it is
redacted.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from psycopg_pool import AsyncConnectionPool

from ...crypto import decrypt, redacted
from ...db import store
from ...probes.deploy_targets import RENDER_API
from ...saga.executor import StepContext, StepFailed, StepResult
from ..provision import cloud_resources_of

POLL_SECONDS = 10.0
#: A free service's Docker build of a generated app, with its tests, is minutes.
DEPLOY_TIMEOUT_SECONDS = 30 * 60
#: A free service asleep takes about a minute to wake; this allows for a slow one.
FINGERPRINT_TIMEOUT_SECONDS = 10 * 60
#: Ended before going live: the previous deploy still serves.
NEVER_LIVE = frozenset({"build_failed", "pre_deploy_failed", "canceled"})
#: Ended after Render began replacing the running deploy.
FAILED_LIVE = frozenset({"update_failed", "deactivated"})


class RenderDeploys:
    def __init__(
        self,
        *,
        pool: AsyncConnectionPool,
        secret_key: str,
        client: httpx.AsyncClient | None = None,
        poll_seconds: float = POLL_SECONDS,
        deploy_timeout: float = DEPLOY_TIMEOUT_SECONDS,
        fingerprint_timeout: float = FINGERPRINT_TIMEOUT_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._pool = pool
        self._secret_key = secret_key
        self._client = client
        self._poll = poll_seconds
        self._deploy_timeout = deploy_timeout
        self._fingerprint_timeout = fingerprint_timeout
        self._sleep = sleep

    async def _target(self, ctx: StepContext) -> tuple[str, str, str]:
        """The Render key, and the project's service and its address."""
        project_id = ctx.deployment["project_id"]
        async with self._pool.connection() as conn:
            project = await store.project_without_owner_check(conn, project_id)
            if project is None:
                raise StepFailed("the project no longer exists")
            owner = project["owner_id"]
            made = await cloud_resources_of(conn, project_id, owner)
            ciphertext = await store.get_secret(conn, f"{owner}:render")
        if made is None:
            raise StepFailed(
                "this project has no Render service yet: an analysis with the cloud target "
                "makes one"
            )
        if ciphertext is None:
            raise StepFailed("there is no render connection to deploy with")
        return decrypt(self._secret_key, ciphertext), made.render.service_id, made.render.origin

    async def _call(
        self, key: str, method: str, path: str, *, json: Any = None, ok=(200, 201)
    ) -> httpx.Response:
        owns = self._client is None
        http = self._client or httpx.AsyncClient(timeout=30)
        try:
            answer = await http.request(
                method,
                f"{RENDER_API}{path}",
                json=json,
                headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            )
        except httpx.HTTPError as error:
            raise StepFailed(redacted(f"Render could not be reached: {error}", key)) from error
        finally:
            if owns:
                await http.aclose()
        if answer.status_code not in ok:
            said = redacted(answer.text[:300], key)
            raise StepFailed(f"Render answered {answer.status_code} to {method} {path}: {said}")
        return answer

    async def _served(self, origin: str) -> str | None:
        owns = self._client is None
        http = self._client or httpx.AsyncClient(timeout=30)
        try:
            answer = await http.get(f"{origin}/release.json", headers={"Cache-Control": "no-cache"})
            if answer.status_code != 200:
                return None
            return str(answer.json().get("candidateHash") or "") or None
        except (httpx.HTTPError, ValueError):
            return None
        finally:
            if owns:
                await http.aclose()

    async def execute(self, ctx: StepContext) -> StepResult:
        if ctx.step.id == "backend":
            commit = (ctx.earlier.get("commit") or {}).get("commit")
            candidate = ctx.deployment["candidate_hash"]
            if not commit:
                raise StepFailed("no commit was made to deploy")
        elif ctx.step.id == "restore-backend":
            if ctx.previous is None or not ctx.previous.commit_sha:
                raise StepFailed("the verified release recorded no commit to redeploy")
            commit, candidate = ctx.previous.commit_sha, ctx.previous.candidate_hash
        else:
            raise StepFailed(f"the Render adapter has no step called {ctx.step.id}")

        key, service, origin = await self._target(ctx)
        started = await self._call(
            key, "POST", f"/services/{service}/deploys", json={"commitId": commit}
        )
        deploy = str(started.json()["id"])

        began, status = time.monotonic(), ""
        while time.monotonic() - began < self._deploy_timeout:
            answer = await self._call(key, "GET", f"/services/{service}/deploys/{deploy}")
            status = str(answer.json().get("status") or "")
            if status == "live":
                break
            if status in NEVER_LIVE:
                raise StepFailed(
                    f"Render's deploy {deploy} of {commit[:12]} ended {status} before it went "
                    "live, so the previous deploy still serves",
                    moved=False,
                )
            if status in FAILED_LIVE:
                raise StepFailed(f"Render's deploy {deploy} of {commit[:12]} ended {status}")
            await self._sleep(self._poll)
        else:
            raise StepFailed(
                f"Render's deploy {deploy} of {commit[:12]} was still {status or 'starting'} "
                f"after {self._deploy_timeout:.0f}s"
            )

        began = time.monotonic()
        while time.monotonic() - began < self._fingerprint_timeout:
            if await self._served(origin) == candidate:
                return StepResult(
                    resource={"service": service, "deploy": deploy, "commit": commit},
                    log=(
                        f"Render deploy {deploy} of {commit[:12]} is live, and {origin} serves "
                        f"candidate {candidate[:12]}"
                    ),
                    command=f"POST {RENDER_API}/services/{service}/deploys commitId={commit}",
                )
            await self._sleep(self._poll)
        raise StepFailed(
            f"Render says deploy {deploy} is live, but {origin} did not serve candidate "
            f"{candidate[:12]} within {self._fingerprint_timeout:.0f}s"
        )

    async def compensate(self, ctx: StepContext) -> None:
        """Nothing: a deploy that went live is a person's to undo (FR20)."""
        return None

    async def find_existing(self, ctx: StepContext) -> dict[str, Any] | None:
        """Nothing is adopted: deploying the same commit again is harmless, and followed."""
        return None
