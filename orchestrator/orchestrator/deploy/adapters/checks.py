"""The checks a deploy plan runs itself: what an address serves, asked over HTTP.

A check passes only when the address serves the expected candidate's
fingerprint, its page answers with HTML, and every smoke request answers with
JSON, the same rules staging applied: the generated backend answers any request
that accepts a page with its index.html, so a status alone proves nothing. The
expected candidate is the release's own, or for a rollback the verified
release's; "restored" means that hash is served again (NFR6).

`check` asks the container `start` started, before any traffic moves; `verify`
asks the release port after the switch, and its answer is what makes the
deployment verified.
"""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import httpx

from ...saga.executor import StepContext, StepFailed, StepResult

BOOT_WITHIN_SECONDS = 60

#: How long one request may take before it counts as unanswered.
PROBE_TIMEOUT_SECONDS = 10.0


class Prober(Protocol):
    """Asks a URL with headers: the status (None when nothing answered), the content
    type and the body. `timeout` is how long the answer may take."""

    def __call__(
        self, url: str, headers: dict[str, str], *, timeout: float = ...
    ) -> Awaitable[tuple[int | None, str, str]]: ...


async def probe(
    url: str, headers: dict[str, str], *, timeout: float = PROBE_TIMEOUT_SECONDS
) -> tuple[int | None, str, str]:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            answer = await client.get(url, headers=headers)
    except httpx.HTTPError as error:
        return None, "", f"{type(error).__name__}: {error}"
    return answer.status_code, answer.headers.get("content-type", ""), answer.text[:2000]


def _address(ctx: StepContext) -> str:
    """The address the step before this one left: the started container or the release port."""
    wanted = ("start", "start-verified") if ctx.step.id == "check" else ("switch", "switch-back")
    for step_id in wanted:
        address = (ctx.earlier.get(step_id) or {}).get("address")
        if address:
            return address
    raise StepFailed(f"no step before {ctx.step.id} left an address to check")


def _expected(ctx: StepContext) -> tuple[str, list[str], dict[str, Any]]:
    if ctx.deployment["kind"] == "rollback":
        if ctx.previous is None:
            raise StepFailed("a rollback has no verified release to expect")
        release = ctx.previous
        restored = ctx.candidate
        return (
            release.candidate_hash,
            [check.path for check in restored.smoke if check.path != "/"] if restored else [],
            {
                "candidateHash": release.candidate_hash,
                "imageDigest": release.image_digest,
                "lockfileSha256": release.lockfile_sha256,
            },
        )
    candidate = ctx.candidate
    if candidate is None:
        raise StepFailed("there is no candidate to expect")
    return (
        candidate.candidate_hash,
        [check.path for check in candidate.smoke if check.path != "/"],
        {
            "candidateHash": candidate.candidate_hash,
            "imageDigest": candidate.image_digest,
            "lockfileSha256": candidate.lockfile_sha256,
        },
    )


class HttpChecks:
    def __init__(
        self,
        *,
        prober: Prober = probe,
        boot_within: float = BOOT_WITHIN_SECONDS,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._probe = prober
        self._boot_within = boot_within
        self._sleep = sleep

    async def execute(self, ctx: StepContext) -> StepResult:
        dispatched = next(
            (
                ctx.earlier[step_id]
                for step_id in ("dispatch", "redeploy-frontend")
                if step_id in ctx.earlier
            ),
            None,
        )
        if dispatched is not None:
            return await self._cloud(ctx, dispatched)
        address = _address(ctx)
        base = f"http://{address}"
        expected, paths, fingerprint = _expected(ctx)
        began = time.monotonic()
        status, body = None, ""
        while time.monotonic() - began < self._boot_within:
            status, _, body = await self._probe(
                f"{base}/release.json", {"Accept": "application/json"}
            )
            if status == 200:
                break
            await self._sleep(1)
        if status != 200:
            raise StepFailed(f"{base}/release.json did not answer within {self._boot_within:.0f}s")
        try:
            served = str(json.loads(body).get("candidateHash") or "")
        except (json.JSONDecodeError, AttributeError):
            served = ""
        if served != expected:
            raise StepFailed(
                f"{base} serves candidate {served[:12] or 'nothing'}, not {expected[:12]}"
            )
        answers = []
        for path, kind in [("/", "text/html"), *((path, "application/json") for path in paths)]:
            status, content_type, _ = await self._probe(f"{base}{path}", {"Accept": kind})
            ok = status is not None and 200 <= status < 300 and content_type.startswith(kind)
            answers.append(f"{path} {status} {content_type or 'no content type'}")
            if not ok:
                raise StepFailed(f"{base}{path} answered {status} {content_type}, not {kind}")
        return StepResult(
            resource={
                "checked": address,
                "verified": ctx.step.id != "check",
                "fingerprint": fingerprint,
                "url": base,
            },
            log=f"{base} serves {expected[:12]}; " + "; ".join(answers),
        )

    async def compensate(self, ctx: StepContext) -> None:
        """A check creates nothing, so there is nothing to undo."""

    async def find_existing(self, ctx: StepContext) -> dict[str, Any] | None:
        """A check is asked again rather than adopted."""
        return None

    async def _serves(self, base: str, expected: str, smoke: list[tuple[str, str]]) -> list[str]:
        """One origin: its fingerprint, then each request of the kind it must answer with."""
        began = time.monotonic()
        status, body = None, ""
        while time.monotonic() - began < self._boot_within:
            status, _, body = await self._probe(
                f"{base}/release.json", {"Accept": "application/json"}
            )
            if status == 200:
                break
            await self._sleep(1)
        if status != 200:
            raise StepFailed(f"{base}/release.json did not answer within {self._boot_within:.0f}s")
        try:
            served = str(json.loads(body).get("candidateHash") or "")
        except (json.JSONDecodeError, AttributeError):
            served = ""
        if served != expected:
            raise StepFailed(
                f"{base} serves candidate {served[:12] or 'nothing'}, not {expected[:12]}"
            )
        answers = []
        for path, kind in smoke:
            status, content_type, _ = await self._probe(f"{base}{path}", {"Accept": kind})
            ok = status is not None and 200 <= status < 300 and content_type.startswith(kind)
            answers.append(f"{path} {status}")
            if not ok:
                raise StepFailed(f"{base}{path} answered {status} {content_type}, not {kind}")
        return answers

    async def _cloud(self, ctx: StepContext, dispatched: dict[str, Any]) -> StepResult:
        """Both origins, as the generated verify-release workflow checks them."""
        origins = dispatched.get("origins") or {}
        backend, frontend = origins.get("backend"), origins.get("frontend")
        if not backend or not frontend:
            raise StepFailed("the dispatch recorded no origins to check")
        expected, paths, fingerprint = _expected(ctx)
        page = [("/", "text/html")]
        on_backend = await self._serves(
            backend, expected, page + [(path, "application/json") for path in paths]
        )
        on_frontend = await self._serves(
            frontend, expected, page + [(f"/api{path}", "application/json") for path in paths]
        )
        return StepResult(
            resource={
                "checked": [backend, frontend],
                "verified": True,
                "fingerprint": {**fingerprint, "commitSha": dispatched.get("ref")},
                "url": frontend,
            },
            log=f"both origins serve {expected[:12]}; "
            + "; ".join(on_backend + [f"frontend {answer}" for answer in on_frontend]),
        )
