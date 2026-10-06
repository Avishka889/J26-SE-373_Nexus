# ruff: noqa: F811 - `client` is the deployment routes' fixture, imported to be used by name
"""Monitoring: a bounded window over a release, recorded, classified, and flagged, never acted on.

A verified release is written to the deployment tables with a candidate whose
smoke checks name `/tasks`, and a scripted prober stands in for the release, so
each claim is about the monitor and not about a network: every probe is kept,
the report names its source and window, a release found down waits for a
person's rollback decision (FR20), and nothing else moves. A fake clock stands
in for a host that takes a minute to wake, so no test waits for one.
"""

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from orchestrator.db import store
from orchestrator.deploy.monitor import watch
from orchestrator.deploy.supervisor import MonitorSupervisor
from sdlc_contracts import BuildStepReport, MonitoringReport, ReleaseCandidate, SmokeCheck

from .conftest import needs_db
from .test_deployment_routes import _approved_tests, client  # noqa: F401

pytestmark = needs_db

NOW = datetime(2026, 9, 28, tzinfo=UTC)
VERIFIED, OTHER = "a" * 64, "b" * 64
BASE = "http://release.test"
BACKEND, FRONTEND = "https://tt-api.onrender.test", "https://tt.vercel.test"


async def instant(seconds: float) -> None:
    return None


class Clock:
    """Monotonic seconds that move only when a scripted answer takes time."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


class Release:
    """A scripted release: which rounds answer, which candidate it serves, how long
    its first answer takes, and the timeout each request was given."""

    def __init__(
        self,
        *,
        failing: set[int] = frozenset(),
        serves: str = VERIFIED,
        clock: Clock | None = None,
        first_answer_seconds: float = 0.0,
    ) -> None:
        self.failing, self.serves = failing, serves
        self.clock, self.first_answer_seconds = clock, first_answer_seconds
        self.round = -1
        self.asked: list[str] = []
        self.timeouts: list[float | None] = []
        #: Called after each request with how many were asked, to change the world mid window.
        self.after = None
        #: Set to hold every answer until it is released.
        self.held: asyncio.Event | None = None

    async def __call__(
        self, url: str, headers: dict[str, str], *, timeout: float | None = None
    ) -> tuple[int | None, str, str]:
        path = url.removeprefix(BASE)
        if self.held is not None:
            await self.held.wait()
        if not self.asked and self.clock is not None:
            self.clock.now += self.first_answer_seconds
        self.asked.append(path)
        self.timeouts.append(timeout)
        if self.after is not None:
            await self.after(len(self.asked))
        if path == "/release.json":
            self.round += 1
        if self.round in self.failing:
            return None, "", "connection refused"
        if path == "/release.json":
            return 200, "application/json", f'{{"candidateHash": "{self.serves}"}}'
        if path == "/":
            return 200, "text/html", "<!doctype html>"
        return 200, "application/json", "[]"


class Origins:
    """A cloud release's two origins, as Vercel and Render answer them: the frontend
    sends `/api` on to the backend and answers any other path with its page."""

    def __init__(self, *, backend_serves: str = VERIFIED, frontend_serves: str = VERIFIED):
        self.serves = {BACKEND: backend_serves, FRONTEND: frontend_serves}
        self.asked: list[str] = []

    async def __call__(
        self, url: str, headers: dict[str, str], *, timeout: float | None = None
    ) -> tuple[int | None, str, str]:
        self.asked.append(url)
        origin = BACKEND if url.startswith(BACKEND) else FRONTEND
        path = url.removeprefix(origin)
        if path == "/release.json":
            return 200, "application/json", f'{{"candidateHash": "{self.serves[origin]}"}}'
        if path.startswith("/api/") or (origin == BACKEND and path != "/"):
            return 200, "application/json", "[]"
        return 200, "text/html", "<!doctype html>"


async def _verified_release(
    client, *, url: str | None = BASE, cloud: bool = False
) -> tuple[str, uuid.UUID]:
    project_id = await _approved_tests(client)
    async with client.app.state.pool.connection() as conn:
        row, _ = await store.create_deployment(
            conn,
            project_id=project_id,
            deploy_version=1,
            kind="release",
            target="cloud" if cloud else "local",
            plan_id=f"{project_id}-deploy-v1",
            candidate_hash=VERIFIED,
            idempotency_key=f"{project_id}-release-1",
            authorised={"kind": "gate", "by": "you", "gateId": "g-1"},
            requested_by="you",
        )
        await store.finish_deployment(
            conn,
            row["id"],
            state="succeeded",
            verified=True,
            fingerprint={"candidateHash": VERIFIED},
            url=FRONTEND if cloud else url,
        )
        if cloud:
            # What the dispatch step records, and the release's verification read.
            await store.ensure_step(
                conn,
                row["id"],
                seq=3,
                step_id="dispatch",
                provider="github",
                idempotency_key=f"{project_id}-dispatch",
                moves_traffic=True,
            )
            await store.update_step(
                conn,
                row["id"],
                3,
                state="succeeded",
                resource={"run": 7, "origins": {"backend": BACKEND, "frontend": FRONTEND}},
            )
        candidate = ReleaseCandidate(
            version=1,
            generated_at=NOW,
            code_version=1,
            candidate_hash=VERIFIED,
            image="sdlc-c4-monitored:v1",
            image_digest="sha256:" + "d" * 64,
            toolchain="docker",
            isolation="a container on loopback",
            steps=[
                BuildStepReport(name=name, command=name, outcome="passed", duration_seconds=0.1)
                for name in ("candidate", "lockfile", "install", "test", "image", "boot")
            ],
            smoke=[
                SmokeCheck(path="/", status_code=200, ok=True),
                SmokeCheck(path="/tasks", status_code=200, ok=True),
            ],
            fingerprint=VERIFIED,
        )
        await store.put_artefact(
            conn,
            project_id=project_id,
            kind="release-candidate",
            version=1,
            body=candidate.model_dump(by_alias=True, mode="json"),
        )
    return project_id, row["id"]


async def _after(client, project_id: str, deployment_id) -> tuple[dict, list[dict], list[dict]]:
    async with client.app.state.pool.connection() as conn:
        row = await store.get_deployment(conn, deployment_id)
        ledger = await store.list_deployments(conn, project_id, limit=50)
        thread = await store.thread(conn, project_id)
    return row, ledger, thread


class TestAWindow:
    async def test_a_release_serving_its_fingerprint_is_healthy(self, client) -> None:
        project_id, deployment_id = await _verified_release(client)
        release = Release()

        report = await watch(
            client.app.state.pool,
            deployment_id,
            rounds=3,
            interval=2,
            prober=release,
            sleep=instant,
        )

        assert report.current_state == "healthy" and report.fingerprint_matches is True
        # Asked just after it was released: no idle spell, and no request waited for a wake.
        assert report.idle_from == "released" and report.idle_seconds < 60
        assert release.timeouts == [None] * 9
        # The release's fingerprint, its page, and the candidate's own smoke GET.
        assert release.asked == ["/release.json", "/", "/tasks"] * 3
        assert "3 rounds 2s apart" in report.source
        row, ledger, _ = await _after(client, project_id, deployment_id)
        assert row["state"] == "succeeded" and len(ledger) == 1
        async with client.app.state.pool.connection() as conn:
            stored = await store.artefacts_at(
                conn, project_id, version=1, kinds=("monitoring-report",)
            )
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT count(*) FROM app.health_samples WHERE deployment_id = %s",
                    (deployment_id,),
                )
                (samples,) = await cur.fetchone()
        assert samples == 9
        kept = MonitoringReport.model_validate(stored["monitoring-report"]["body"])
        assert kept.current_state == "healthy"

    async def test_a_release_that_stops_answering_waits_for_a_person(self, client) -> None:
        project_id, deployment_id = await _verified_release(client)

        report = await watch(
            client.app.state.pool,
            deployment_id,
            rounds=3,
            interval=1,
            prober=Release(failing={0, 1, 2}),
            sleep=instant,
        )

        assert report.current_state == "down"
        row, ledger, thread = await _after(client, project_id, deployment_id)
        assert row["state"] == "awaiting-rollback-approval"
        assert row["cause"].startswith("monitoring found it down")
        # Flagged, and nothing more: no rollback was written, let alone started (FR20).
        assert [entry["kind"] for entry in ledger] == ["release"]
        assert "A rollback waits for your decision" in thread[-1]["content"]
        # Said in Activity too, which heard only the conversation's copy (review item X-7).
        entries = (await client.get("/activity", params={"project": project_id})).json()
        found = next(entry for entry in entries if entry["title"].startswith("Monitoring"))
        assert found["title"] == "Monitoring found the release down"
        assert found["category"] == "deployment" and found["outcome"] == "failed"
        assert "A rollback waits for your decision" in found["description"]

    async def test_another_candidate_answering_well_is_down(self, client) -> None:
        project_id, deployment_id = await _verified_release(client)

        report = await watch(
            client.app.state.pool,
            deployment_id,
            rounds=3,
            interval=1,
            prober=Release(serves=OTHER),
            sleep=instant,
        )

        assert report.current_state == "down" and report.fingerprint_matches is False
        row, _, _ = await _after(client, project_id, deployment_id)
        assert row["state"] == "awaiting-rollback-approval"

    async def test_a_failed_round_is_degraded_and_flags_nothing(self, client) -> None:
        project_id, deployment_id = await _verified_release(client)

        report = await watch(
            client.app.state.pool,
            deployment_id,
            rounds=4,
            interval=1,
            prober=Release(failing={1}),
            sleep=instant,
        )

        assert report.current_state == "degraded"
        assert [event.kind for event in report.events] == ["degraded"]
        row, _, thread = await _after(client, project_id, deployment_id)
        assert row["state"] == "succeeded"
        assert "degraded" in thread[-1]["content"]
        entries = (await client.get("/activity", params={"project": project_id})).json()
        found = next(entry for entry in entries if entry["title"].startswith("Monitoring"))
        assert found["title"] == "Monitoring found the release degraded"
        assert found["category"] == "deployment" and found["outcome"] == "info"

    async def test_a_slow_fingerprint_after_the_first_request_is_not_the_application(
        self, client
    ) -> None:
        """Two slow answers from the platform's own release.json called Book
        Tracker degraded while every request of the application answered in
        time. The first request still counts: it is the one that finds the
        host awake or asleep."""
        _, deployment_id = await _verified_release(client)
        clock = Clock()

        class SlowFingerprint(Release):
            async def __call__(self, url, headers, *, timeout=None):
                if url.endswith("/release.json") and self.asked:
                    clock.now += 2.6
                return await super().__call__(url, headers, timeout=timeout)

        report = await watch(
            client.app.state.pool,
            deployment_id,
            rounds=4,
            interval=1,
            prober=SlowFingerprint(clock=clock),
            sleep=instant,
            clock=clock,
        )

        assert report.current_state == "healthy", report.states[-1].evidence
        fingerprint = next(one for one in report.probes if one.probe.endswith("/release.json"))
        # Kept and shown all the same.
        assert fingerprint.p95_ms is not None and fingerprint.p95_ms > 2000
        assert "the fingerprint's time counts only as the first request" in report.source

    async def test_a_release_with_no_address_is_not_watched(self, client) -> None:
        _, deployment_id = await _verified_release(client, url=None)
        try:
            await watch(client.app.state.pool, deployment_id, prober=Release(), sleep=instant)
        except ValueError as refused:
            assert "no released address" in str(refused)
        else:
            raise AssertionError("a release with no address was watched")


async def _last_asked(client, deployment_id, minutes: float) -> None:
    """A probe on record from `minutes` ago, as the last thing that asked the release."""
    async with client.app.state.pool.connection() as conn:
        await store.add_health_sample(
            conn,
            deployment_id=deployment_id,
            project_id=(await store.get_deployment(conn, deployment_id))["project_id"],
            probe="GET /release.json",
            status_code=200,
            latency_ms=40.0,
            ok=True,
            observed_fingerprint=VERIFIED,
        )
        await conn.execute(
            "UPDATE app.health_samples SET at = now() - make_interval(secs => %s) "
            "WHERE deployment_id = %s",
            (minutes * 60, deployment_id),
        )


class TestACloudRelease:
    """The first live cloud window called a healthy release down: it asked the frontend's
    address for the candidate's smoke paths without `/api`, Vercel answered each with the
    page, and every round failed. A window now asks both origins as verification does."""

    async def test_both_origins_are_asked_as_verification_asks_them(self, client) -> None:
        project_id, deployment_id = await _verified_release(client, cloud=True)
        origins = Origins()

        report = await watch(
            client.app.state.pool,
            deployment_id,
            rounds=3,
            interval=2,
            prober=origins,
            sleep=instant,
        )

        assert report.current_state == "healthy" and report.fingerprint_matches is True
        # The backend first, so a free host asleep is woken by the request given the time.
        assert (
            origins.asked
            == [
                f"{BACKEND}/release.json",
                f"{BACKEND}/",
                f"{BACKEND}/tasks",
                f"{FRONTEND}/release.json",
                f"{FRONTEND}/",
                f"{FRONTEND}/api/tasks",
            ]
            * 3
        )
        assert report.urls == [BACKEND, FRONTEND]
        row, _, _ = await _after(client, project_id, deployment_id)
        assert row["state"] == "succeeded"

    @pytest.mark.parametrize(
        ("backend", "frontend"), [(OTHER, VERIFIED), (VERIFIED, OTHER)], ids=["backend", "frontend"]
    )
    async def test_either_origin_serving_another_candidate_is_down(
        self, client, backend: str, frontend: str
    ) -> None:
        project_id, deployment_id = await _verified_release(client, cloud=True)
        origins = Origins(backend_serves=backend, frontend_serves=frontend)

        report = await watch(
            client.app.state.pool,
            deployment_id,
            rounds=3,
            interval=2,
            prober=origins,
            sleep=instant,
        )

        assert report.current_state == "down" and report.fingerprint_matches is False
        assert f"serves candidate {OTHER[:12]}" in report.states[-1].evidence
        row, _, _ = await _after(client, project_id, deployment_id)
        assert row["state"] == "awaiting-rollback-approval"


class TestIdleTime:
    async def test_a_minute_long_first_answer_after_an_idle_spell_is_a_wake(self, client) -> None:
        _, deployment_id = await _verified_release(client)
        await _last_asked(client, deployment_id, minutes=20)
        clock = Clock()
        release = Release(clock=clock, first_answer_seconds=60)

        report = await watch(
            client.app.state.pool,
            deployment_id,
            rounds=3,
            interval=1,
            prober=release,
            sleep=instant,
            clock=clock,
        )

        assert report.current_state == "cold-start", report.states[-1].evidence
        assert report.idle_from == "last-sample" and 1190 < report.idle_seconds < 1300
        # Only the request that wakes the host waits as long as a wake may take.
        assert release.timeouts[0] == 90.0 and set(release.timeouts[1:]) == {None}
        assert "to wake the host" in report.source

    async def test_the_same_slow_answer_without_an_idle_spell_is_degraded(self, client) -> None:
        _, deployment_id = await _verified_release(client)
        await _last_asked(client, deployment_id, minutes=1)
        clock = Clock()
        release = Release(clock=clock, first_answer_seconds=60)

        report = await watch(
            client.app.state.pool,
            deployment_id,
            rounds=3,
            interval=1,
            prober=release,
            sleep=instant,
            clock=clock,
        )

        assert report.current_state == "degraded"
        assert set(release.timeouts) == {None}

    async def test_with_no_probe_on_record_idle_counts_from_the_release(self, client) -> None:
        _, deployment_id = await _verified_release(client)
        async with client.app.state.pool.connection() as conn:
            await conn.execute(
                "UPDATE app.deployments SET finished_at = now() - interval '30 minutes' "
                "WHERE id = %s",
                (deployment_id,),
            )

        report = await watch(
            client.app.state.pool,
            deployment_id,
            rounds=3,
            interval=1,
            prober=Release(),
            sleep=instant,
        )

        assert report.idle_from == "released" and 1790 < report.idle_seconds < 1900


async def _another(client, project_id: str, version: int, *, state: str) -> uuid.UUID:
    """A later deployment on the same project and target, left in `state`."""
    async with client.app.state.pool.connection() as conn:
        row, _ = await store.create_deployment(
            conn,
            project_id=project_id,
            deploy_version=version,
            kind="release",
            target="local",
            plan_id=f"{project_id}-deploy-v{version}",
            candidate_hash=OTHER,
            idempotency_key=f"{project_id}-release-{version}",
            authorised={"kind": "gate", "by": "you", "gateId": f"g-{version}"},
            requested_by="you",
        )
        if state != "pending":
            await store.finish_deployment(
                conn,
                row["id"],
                state=state,
                verified=state == "succeeded",
                fingerprint={"candidateHash": OTHER},
                url=BASE if state == "succeeded" else None,
                cause=None if state == "succeeded" else "the check failed before traffic moved",
            )
    return row["id"]


def _supervisor(client, release: "Release") -> MonitorSupervisor:
    return MonitorSupervisor(
        pool=client.app.state.pool, rounds=3, interval=1, prober=release, sleep=instant
    )


class TestTheSupervisor:
    async def test_a_verified_release_is_watched_once(self, client) -> None:
        project_id, deployment_id = await _verified_release(client)
        monitor = _supervisor(client, Release())

        opened = await monitor.sweep()
        await monitor.wait()

        assert deployment_id in opened
        async with client.app.state.pool.connection() as conn:
            stored = await store.artefacts_at(
                conn, project_id, version=1, kinds=("monitoring-report",)
            )
        assert stored["monitoring-report"]["body"]["currentState"] == "healthy"
        # Its window left samples after it finished, so it is not watched again.
        assert deployment_id not in await monitor.sweep()

    async def test_a_replaced_release_is_never_watched(self, client) -> None:
        project_id, deployment_id = await _verified_release(client)
        await _another(client, project_id, 2, state="pending")

        assert deployment_id not in await _supervisor(client, Release()).sweep()
        try:
            await watch(client.app.state.pool, deployment_id, prober=Release(), sleep=instant)
        except ValueError as refused:
            assert "has been replaced" in str(refused)
        else:
            raise AssertionError("a replaced release was watched")

    async def test_a_release_that_failed_before_traffic_moved_replaces_nothing(
        self, client
    ) -> None:
        project_id, deployment_id = await _verified_release(client)
        await _another(client, project_id, 2, state="failed")

        assert deployment_id in await _supervisor(client, Release()).sweep()
        async with client.app.state.pool.connection() as conn:
            serving = await store.serving_release(conn, project_id, "local")
        assert serving is not None and serving["id"] == deployment_id

    async def test_an_old_release_waits_to_be_asked(self, client) -> None:
        _, deployment_id = await _verified_release(client)
        async with client.app.state.pool.connection() as conn:
            await conn.execute(
                "UPDATE app.deployments SET finished_at = now() - interval '2 hours' WHERE id = %s",
                (deployment_id,),
            )

        assert deployment_id not in await _supervisor(client, Release()).sweep()

    async def test_a_release_begun_mid_window_ends_it_and_flags_nothing(self, client) -> None:
        project_id, deployment_id = await _verified_release(client)
        release = Release(failing={1, 2, 3, 4})

        async def a_release_begins(asked: int) -> None:
            if asked == 3:  # the end of the first round
                await _another(client, project_id, 2, state="pending")

        release.after = a_release_begins

        report = await watch(
            client.app.state.pool,
            deployment_id,
            rounds=5,
            interval=1,
            prober=release,
            sleep=instant,
        )

        # One round, then the window ended; the rounds that would have failed were never asked.
        assert release.asked == ["/release.json", "/", "/tasks"]
        assert report.current_state == "unknown"
        assert "ended after 1 of 5 rounds" in report.states[-1].evidence
        row, _, _ = await _after(client, project_id, deployment_id)
        assert row["state"] == "succeeded"

    async def test_a_release_begun_in_the_last_round_is_not_blamed(self, client) -> None:
        project_id, deployment_id = await _verified_release(client)
        release = Release(failing={0, 1, 2})

        async def a_release_begins(asked: int) -> None:
            if asked == 9:  # the last request of the last round
                await _another(client, project_id, 2, state="pending")

        release.after = a_release_begins

        report = await watch(
            client.app.state.pool,
            deployment_id,
            rounds=3,
            interval=1,
            prober=release,
            sleep=instant,
        )

        assert report.current_state == "unknown" and not report.events
        row, _, thread = await _after(client, project_id, deployment_id)
        assert row["state"] == "succeeded"
        assert not any(message["content"].startswith("Monitoring found") for message in thread)

    async def test_the_flag_itself_refuses_a_replaced_release(self, client) -> None:
        project_id, deployment_id = await _verified_release(client)
        await _another(client, project_id, 2, state="pending")

        async with client.app.state.pool.connection() as conn:
            flagged = await store.flag_for_rollback(conn, deployment_id, "found down")

        assert flagged is False


class TestTheWindowRoute:
    async def test_there_is_nothing_to_watch_before_a_verified_release(self, client) -> None:
        project_id = await _approved_tests(client)
        answer = await client.post(
            f"/projects/{project_id}/deployment/monitoring/window",
            json={"rounds": 3, "interval": 1},
        )
        assert answer.status_code == 409
        assert "nothing verified serves" in answer.text

    async def test_a_person_opens_a_window_on_what_serves_now(self, client) -> None:
        project_id, deployment_id = await _verified_release(client)
        release = Release()
        release.held = asyncio.Event()
        client.app.state.monitor = _supervisor(client, release)

        opened = await client.post(
            f"/projects/{project_id}/deployment/monitoring/window",
            json={"rounds": 3, "interval": 1},
        )
        again = await client.post(
            f"/projects/{project_id}/deployment/monitoring/window",
            json={"rounds": 3, "interval": 1},
        )
        release.held.set()
        await client.app.state.monitor.wait()

        assert opened.status_code == 200, opened.text
        assert again.status_code == 409 and "being watched already" in again.text
        async with client.app.state.pool.connection() as conn:
            stored = await store.artefacts_at(
                conn, project_id, version=1, kinds=("monitoring-report",)
            )
        assert stored["monitoring-report"]["body"]["deploymentId"] == str(deployment_id)

    async def test_the_snapshot_says_which_release_a_window_watches_now(self, client) -> None:
        """What the live walkthrough met. The orchestrator opens a window on release,
        the snapshot did not say so, and the page offered to open a second one, which
        the server refused, while it showed an earlier window's report as current."""
        project_id, deployment_id = await _verified_release(client)
        release = Release()
        release.held = asyncio.Event()
        client.app.state.monitor = _supervisor(client, release)

        opened = await client.post(
            f"/projects/{project_id}/deployment/monitoring/window",
            json={"rounds": 3, "interval": 1},
        )
        during = (await client.get(f"/projects/{project_id}/deployment")).json()
        release.held.set()
        await client.app.state.monitor.wait()
        after = (await client.get(f"/projects/{project_id}/deployment")).json()

        assert opened.status_code == 200, opened.text
        assert opened.json()["watching"] == str(deployment_id)
        assert during["watching"] == str(deployment_id)
        assert after["watching"] is None

    async def test_a_verified_release_waiting_for_its_window_is_working(self, client) -> None:
        """The monitor opens a window within its next poll; until then the snapshot says
        so, or the page stops reading and never shows the window or its report."""
        project_id, _ = await _verified_release(client)
        before = (await client.get(f"/projects/{project_id}/deployment")).json()
        monitor = _supervisor(client, Release())

        await monitor.sweep()
        await monitor.wait()

        after = (await client.get(f"/projects/{project_id}/deployment")).json()
        assert before["stages"]["monitoring"]["status"] == "generating"
        assert after["stages"]["monitoring"]["status"] == "pending"
        assert after["monitoring"]["currentState"] == "healthy"

    async def test_the_newest_window_is_the_one_shown_after_a_rollback(self, client) -> None:
        """What the live walkthrough met. A rollback restored deploy version 2, and the
        window on it wrote its report at version 2, later than the version 3 report
        that found 3 down. The snapshot took the highest version for the newest, and
        kept showing a release that no longer served, down, as the latest word."""
        project_id, deployment_id = await _verified_release(client)
        await watch(
            client.app.state.pool,
            deployment_id,
            rounds=1,
            interval=1,
            prober=Release(),
            sleep=instant,
        )
        async with client.app.state.pool.connection() as conn:
            found = await store.artefacts_at(
                conn, project_id, version=1, kinds=("monitoring-report",)
            )
            # The same shape at a higher version, written first: the release a
            # rollback replaced, watched before the rollback.
            later = {**found["monitoring-report"]["body"], "version": 5}
            await store.put_artefact(
                conn, project_id=project_id, kind="monitoring-report", version=5, body=later
            )
        await watch(
            client.app.state.pool,
            deployment_id,
            rounds=1,
            interval=1,
            prober=Release(),
            sleep=instant,
        )

        snapshot = (await client.get(f"/projects/{project_id}/deployment")).json()

        assert snapshot["monitoring"]["version"] == 1

    async def test_a_window_is_bounded(self, client) -> None:
        project_id = await _approved_tests(client)
        answer = await client.post(
            f"/projects/{project_id}/deployment/monitoring/window",
            json={"rounds": 1000, "interval": 1},
        )
        assert answer.status_code == 422


SIX_HOURS, SEVEN_DAYS = 6 * 3600, 7 * 86400


async def _aged(client, deployment_id, *, finished_hours: float, asked_hours: float) -> None:
    """A release that finished and was last asked this many hours ago."""
    await _last_asked(client, deployment_id, asked_hours * 60)
    async with client.app.state.pool.connection() as conn:
        await conn.execute(
            "UPDATE app.deployments SET finished_at = now() - make_interval(hours => %s) "
            "WHERE id = %s",
            (finished_hours, deployment_id),
        )


def _again(client, release: "Release", **how) -> MonitorSupervisor:
    return MonitorSupervisor(
        pool=client.app.state.pool,
        rounds=3,
        interval=1,
        prober=release,
        sleep=instant,
        **{"every_seconds": SIX_HOURS, "for_seconds": SEVEN_DAYS, **how},
    )


class TestWatchingWhatServesAgain:
    """Monitoring was one window per release, in its first hour. A release that
    went down the next day was never looked at again (review item C4-10)."""

    async def test_what_still_serves_is_watched_again_once_its_last_look_is_old(
        self, client
    ) -> None:
        project_id, deployment_id = await _verified_release(client)
        await _aged(client, deployment_id, finished_hours=8, asked_hours=7)

        assert deployment_id not in await _supervisor(client, Release()).sweep(), "not asked to"
        monitor = _again(client, Release())
        opened = await monitor.sweep()
        await monitor.wait()

        assert deployment_id in opened
        # Its window left a look that is new, so it waits for the next one.
        assert deployment_id not in await monitor.sweep()
        # And it said nothing: nothing was wrong, and a line every six hours is noise.
        async with client.app.state.pool.connection() as conn:
            thread = await store.thread(conn, project_id)
        assert not [one for one in thread if one["content"].startswith("Watching deploy version")]

    async def test_one_looked_at_lately_waits(self, client) -> None:
        _, deployment_id = await _verified_release(client)
        await _aged(client, deployment_id, finished_hours=8, asked_hours=1)

        assert deployment_id not in await _again(client, Release()).sweep()

    async def test_past_its_days_it_waits_to_be_asked(self, client) -> None:
        _, deployment_id = await _verified_release(client)
        await _aged(client, deployment_id, finished_hours=8 * 24, asked_hours=7)

        assert deployment_id not in await _again(client, Release()).sweep()

    async def test_a_cloud_release_is_watched_again_only_when_that_is_switched_on(
        self, client
    ) -> None:
        _, deployment_id = await _verified_release(client, cloud=True)
        await _aged(client, deployment_id, finished_hours=8, asked_hours=7)

        assert deployment_id not in await _again(client, Release()).sweep()
        assert deployment_id in await _again(client, Release(), cloud=True).sweep()

    async def test_a_restored_release_found_down_says_nobody_can_roll_it_back(self, client) -> None:
        project_id, _ = await _verified_release(client)
        async with client.app.state.pool.connection() as conn:
            restored, _ = await store.create_deployment(
                conn,
                project_id=project_id,
                deploy_version=1,
                kind="rollback",
                target="local",
                plan_id=f"{project_id}-rollback-v2",
                candidate_hash=VERIFIED,
                idempotency_key=f"{project_id}-rollback",
                authorised={"kind": "rollback", "by": "you", "fromVersion": 2},
                requested_by="you",
            )
            await store.finish_deployment(
                conn,
                restored["id"],
                state="succeeded",
                verified=True,
                fingerprint={"candidateHash": VERIFIED},
                url=BASE,
            )

        report = await watch(
            client.app.state.pool,
            restored["id"],
            rounds=3,
            interval=1,
            prober=Release(failing={0, 1, 2}),
            sleep=instant,
        )

        assert report.current_state == "down"
        row, _, thread = await _after(client, project_id, restored["id"])
        assert row["state"] == "succeeded", "a restore is not flagged for a rollback"
        assert thread[-1]["content"].endswith(
            "It is itself a restore, so there is no rollback to offer: it needs a person."
        )
