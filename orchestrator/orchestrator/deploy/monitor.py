"""Monitoring: a bounded window of probes against the live release, and what it concludes.

Opened after a release, or on request, and never left running: a free host
probed forever never sleeps and spends its month of hours on being watched.
Each round asks the release's `/release.json` (its fingerprint), its page, and
every GET the candidate was smoke tested with, the same requests and rules as
staging and verification; a cloud release on both of its origins, as its
verification asked them. A fingerprint's answer time is kept and shown, and it
counts toward the window's state only as the window's first request: after
that it is the platform's own file answering, not the application. Every answer is kept (`health_samples`), and the
window is classified by `health-rule/1` into one state with its evidence.

**It flags; it never rolls back.** A release found `down` becomes
`awaiting-rollback-approval`, with the evidence as its cause, and the thread
says a person's decision is waiting. A release found `degraded` still serves
the verified candidate (a different one is `down`), so it is reported and not
flagged; the rollback route accepts it all the same. Either way the rollback is
a person's decision (FR20).

**Idle time.** A free host sleeps when nothing asks it anything, and its first
answer after that is a wake, not an outage. How long the release had gone
unasked is read from the record: its last probe, or when it was released. After
an idle spell the window's first request is given the wake allowance
(`cold_start_first_ms`) to answer, and the rule may call a slow or failed first
round a cold start. Traffic from anyone else is not seen, so this is an upper
bound on the host's own idle time; for the generated projects the platform is
the only client.

The report names its source and window, as every number on the platform must.
"""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from psycopg_pool import AsyncConnectionPool
from sdlc_contracts import (
    DeploymentEvent,
    HealthState,
    HealthThresholds,
    MonitoringReport,
    ProbeSummary,
    ReleaseCandidate,
    StateInterval,
    classify_window,
)

from ..db import store
from .adapters.checks import Prober, probe


async def _idle(
    conn, row: dict
) -> tuple[float | None, Literal["last-sample", "released", "given"] | None]:
    """Seconds since this platform last asked the release anything, and from what."""
    now = datetime.now(UTC)
    last = await store.last_health_sample_at(conn, row["id"])
    if last is not None:
        return max(0.0, (now - last).total_seconds()), "last-sample"
    if row.get("finished_at") is not None:
        return max(0.0, (now - row["finished_at"]).total_seconds()), "released"
    return None, None


#: What a round heard: every probe answered as it must, the slowest answer in ms,
#: and the candidate hash `/release.json` named (on two origins, the one that is
#: not the expected candidate, when either is not).
Round = tuple[bool, float | None, str | None]


@dataclass
class Observed:
    """What one window asked and heard, before anything is concluded from it."""

    rounds: list[Round]
    #: Per request path: answers, samples, latencies of the answers, last error.
    summaries: dict[str, dict[str, Any]]
    started: datetime
    ended: datetime
    #: Whatever ended the window before its last round, when something did.
    stopped_by: Any = None


def requests_for(
    candidate: ReleaseCandidate | None, origins: dict[str, str] | None = None
) -> list[tuple[str, str]]:
    """The fingerprint, the page, and every GET the candidate was smoke tested with.

    Paths are asked of the release's one address. A cloud release is asked on
    both of its origins, by full address, as its verification asked them: the
    backend with the smoke paths as they are, then the frontend, whose rewrite
    sends `/api` on to the backend and answers any other path with its page (the
    first live cloud window asked the frontend for `/calculations` and called a
    healthy release down). The backend goes first, so a free host asleep is woken
    by the request given the time to wake.
    """
    smoke = [check.path for check in (candidate.smoke if candidate else []) if check.path != "/"]
    if not origins:
        return [("/release.json", "application/json"), ("/", "text/html")] + [
            (path, "application/json") for path in smoke
        ]
    backend, frontend = origins["backend"].rstrip("/"), origins["frontend"].rstrip("/")
    return (
        [(f"{backend}/release.json", "application/json"), (f"{backend}/", "text/html")]
        + [(f"{backend}{path}", "application/json") for path in smoke]
        + [(f"{frontend}/release.json", "application/json"), (f"{frontend}/", "text/html")]
        + [(f"{frontend}/api{path}", "application/json") for path in smoke]
    )


async def observe(
    base: str,
    requests: list[tuple[str, str]],
    *,
    rounds: int,
    interval: float,
    prober: Prober = probe,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
    wake_timeout: float | None = None,
    heard: Callable[..., Awaitable[None]] | None = None,
    before_round: Callable[[int], Awaitable[Any]] | None = None,
    expected: str | None = None,
) -> Observed:
    """Ask every request once a round, `interval` apart, and keep what was heard.

    A request is a path on `base`, or a full address. `wake_timeout`, when a
    wake is expected, is how long the window's first request may take. `heard`
    is told each answer as it arrives. `before_round` is asked before every
    round after the first; anything it returns other than None ends the window,
    and is kept as what stopped it. `expected`, when given, is the candidate a
    round must find everywhere it asks: any other one named is the round's.
    """
    started = datetime.now(UTC)
    summaries: dict[str, dict[str, Any]] = {
        path: {"ok": 0, "samples": 0, "ms": [], "error": ""} for path, _ in requests
    }
    window: list[Round] = []
    stopped_by: Any = None
    for index in range(rounds):
        if index and before_round is not None:
            stopped_by = await before_round(index)
            if stopped_by is not None:
                break
        round_ok, slowest, served = True, 0.0, None
        for position, (path, kind) in enumerate(requests):
            url = path if path.startswith(("http://", "https://")) else f"{base}{path}"
            began = clock()
            if wake_timeout is not None and index == 0 and position == 0:
                # The request that wakes a sleeping host waits as long as a wake may take.
                status, content_type, body = await prober(
                    url, {"Accept": kind}, timeout=wake_timeout
                )
            else:
                status, content_type, body = await prober(url, {"Accept": kind})
            elapsed = (clock() - began) * 1000
            ok = status is not None and 200 <= status < 300 and content_type.startswith(kind)
            fingerprint = None
            if path.endswith("/release.json") and ok:
                try:
                    fingerprint = str(json.loads(body).get("candidateHash") or "") or None
                except (json.JSONDecodeError, AttributeError):
                    fingerprint = None
            summary = summaries[path]
            summary["samples"] += 1
            summary["ok"] += int(ok)
            if ok:
                summary["ms"].append(elapsed)
            else:
                summary["error"] = f"{status} {content_type}".strip() if status else body[:200]
            round_ok = round_ok and ok
            # The fingerprint says which release answered, and how fast is the
            # platform's own file, not the application: two slow answers from
            # Vercel's copy of it called Book Tracker degraded. Only the
            # window's first request counts its time, because that request is
            # the one that finds the host awake or asleep.
            if (index == 0 and position == 0) or not path.endswith("/release.json"):
                slowest = max(slowest, elapsed)
            if fingerprint is not None and (served is None or served == expected):
                served = fingerprint
            if heard is not None:
                await heard(
                    path=path,
                    status=status,
                    elapsed=elapsed,
                    ok=ok,
                    fingerprint=fingerprint,
                    error=None if ok else summary["error"],
                )
        window.append((round_ok, slowest if round_ok else None, served))
        if index < rounds - 1:
            await sleep(interval)
    return Observed(window, summaries, started, datetime.now(UTC), stopped_by)


def conclude(
    rounds: list[Round],
    *,
    expected: str,
    idle_seconds: float | None,
    thresholds: HealthThresholds | None = None,
) -> tuple[HealthState, str]:
    """`health-rule/1` over a window, at the thresholds every report records."""
    thresholds = thresholds or HealthThresholds()
    return classify_window(
        rounds,
        expected=expected,
        min_samples=thresholds.min_samples,
        degraded_p95_ms=thresholds.degraded_p95_ms,
        cold_start_first_ms=thresholds.cold_start_first_ms,
        idle_seconds=idle_seconds,
        cold_start_idle_seconds=thresholds.cold_start_idle_seconds,
    )


def _percentile(values: list[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, min(len(ordered) - 1, round(share * len(ordered)) - 1))]


async def watch(
    pool: AsyncConnectionPool,
    deployment_id,
    *,
    rounds: int = 5,
    interval: float = 30.0,
    prober: Prober = probe,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
    idle_seconds: float | None = None,
) -> MonitoringReport:
    """One window over one release: probe, record, classify, report, and flag if down.

    `idle_seconds` is read from the record unless it is given, as a Table 7
    episode gives the idle spell it emulates.
    """
    async with pool.connection() as conn:
        row = await store.get_deployment(conn, deployment_id)
        if row is None or not row.get("url"):
            raise ValueError("there is no released address to watch")
        if await store.newer_deployment(conn, row) is not None:
            raise ValueError(
                f"deploy version {row['deploy_version']} has been replaced by a later "
                "deployment, so what its address serves is not its to answer for"
            )
        found = await store.artefacts_at(
            conn, row["project_id"], version=row["deploy_version"], kinds=("release-candidate",)
        )
        # A cloud release's two origins, as its dispatch recorded them for verification.
        origins: dict[str, str] | None = None
        if row["target"] == "cloud":
            for step in await store.deployment_steps(conn, row["id"]):
                origins = (step.get("resource") or {}).get("origins") or origins
            if not origins:
                raise ValueError("the cloud release recorded no origins to watch")
        idle_from: Literal["last-sample", "released", "given"] | None = "given"
        if idle_seconds is None:
            idle_seconds, idle_from = await _idle(conn, row)
    thresholds = HealthThresholds()
    waking = idle_seconds is not None and idle_seconds >= thresholds.cold_start_idle_seconds
    candidate = (
        ReleaseCandidate.model_validate(found["release-candidate"]["body"])
        if "release-candidate" in found
        else None
    )
    base = str(row["url"]).rstrip("/")
    expected = row["candidate_hash"]

    async def heard(**answer: Any) -> None:
        async with pool.connection() as conn:
            await store.add_health_sample(
                conn,
                deployment_id=row["id"],
                project_id=row["project_id"],
                probe=f"GET {answer['path']}",
                status_code=answer["status"],
                latency_ms=round(answer["elapsed"], 3),
                ok=answer["ok"],
                observed_fingerprint=answer["fingerprint"],
                error=answer["error"],
            )

    async def replaced(_: int) -> store.Row | None:
        # A release begun during the window changes what the address serves; the
        # window ends, rather than calling this release down for the new one.
        async with pool.connection() as conn:
            return await store.newer_deployment(conn, row)

    observed = await observe(
        base,
        requests_for(candidate, origins),
        rounds=rounds,
        interval=interval,
        prober=prober,
        sleep=sleep,
        clock=clock,
        wake_timeout=thresholds.cold_start_first_ms / 1000 if waking else None,
        heard=heard,
        before_round=replaced,
        expected=expected,
    )
    window, summaries, started = observed.rounds, observed.summaries, observed.started
    replaced_by: store.Row | None = observed.stopped_by
    ended = observed.ended
    if replaced_by is None:
        async with pool.connection() as conn:
            replaced_by = await store.newer_deployment(conn, row)
    if replaced_by is not None:
        state: HealthState = "unknown"
        evidence = (
            f"the window ended after {len(window)} of {rounds} rounds, when deploy version "
            f"{replaced_by['deploy_version']} began: what the address serves is no longer "
            "this release's to answer for"
        )
    else:
        state, evidence = conclude(
            window, expected=expected, idle_seconds=idle_seconds, thresholds=thresholds
        )
    events: list[DeploymentEvent] = []
    if state in ("down", "degraded"):
        events.append(
            DeploymentEvent(at=ended, kind=state, deployment_id=str(row["id"]), detail=evidence)
        )
    fingerprints = [served for _, _, served in window if served]
    report = MonitoringReport(
        version=row["deploy_version"],
        generated_at=ended,
        deployment_id=str(row["id"]),
        target=row["target"],
        urls=[origins["backend"], origins["frontend"]] if origins else [base],
        source=(
            f"orchestrator HTTP probes from this host, {len(window)} rounds {interval:g}s apart"
            + "; the fingerprint's time counts only as the first request"
            + (
                f" (of {rounds}; ended when deploy version {replaced_by['deploy_version']} began)"
                if replaced_by is not None
                else ""
            )
            + (
                f"; unasked for {idle_seconds:.0f}s, so the first request was given "
                f"{thresholds.cold_start_first_ms / 1000:g}s to wake the host"
                if waking
                else ""
            )
        ),
        window_start=started,
        window_end=ended,
        probe_interval_seconds=max(1, round(interval)),
        thresholds=thresholds,
        probes=[
            ProbeSummary(
                probe=f"GET {path}",
                samples=summary["samples"],
                ok=summary["ok"],
                p50_ms=_percentile(summary["ms"], 0.5),
                p95_ms=_percentile(summary["ms"], 0.95),
                last_error=summary["error"],
            )
            for path, summary in summaries.items()
        ],
        states=[
            StateInterval(
                state=state, start=started, end=ended, samples=len(window), evidence=evidence
            )
        ],
        current_state=state,
        expected_candidate_hash=expected,
        fingerprint_matches=(fingerprints[-1] == expected) if fingerprints else None,
        events=events,
        idle_seconds=round(idle_seconds, 1) if idle_seconds is not None else None,
        idle_from=idle_from if idle_seconds is not None else None,
    )
    async with pool.connection() as conn:
        await store.put_artefact(
            conn,
            project_id=row["project_id"],
            kind="monitoring-report",
            version=row["deploy_version"],
            body=report.model_dump(by_alias=True, mode="json"),
        )
        said = None
        if state == "down":
            flagged = await store.flag_for_rollback(
                conn, row["id"], f"monitoring found it down: {evidence}"
            )
            said = f"Monitoring found deploy version {row['deploy_version']} down: {evidence}." + (
                " A rollback waits for your decision."
                if flagged
                # A restore has nothing behind it to return to, and it said nothing.
                else " It is itself a restore, so there is no rollback to offer: it needs a person."
                if row["kind"] == "rollback"
                else ""
            )
        elif state == "degraded":
            said = (
                f"Monitoring found deploy version {row['deploy_version']} degraded: "
                f"{evidence}. It still serves the verified candidate, so nothing is "
                "flagged; rolling it back is yours to decide."
            )
        if said is not None:
            await store.post_thread_message(
                conn,
                row["project_id"],
                kind="system",
                author="platform",
                content=said,
                stage_id="monitoring",  # type: ignore[arg-type]
            )
            # In Activity too, which heard only the conversation's copy (review item X-7).
            await store.record(
                conn,
                actor="system",
                action=f"Monitoring found the release {state}",
                target=f"deploy version {row['deploy_version']}, {row['target']}",
                detail=said,
                project_id=row["project_id"],
                category="deployment",
            )
    return report
