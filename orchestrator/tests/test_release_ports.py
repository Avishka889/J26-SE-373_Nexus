"""Each project's local release on a port of its own.

Every project's release bound one port. A container from one project, up for
six days, held it, so a new project's first local release failed at its switch,
a traffic step, and then waited on a rollback with nothing to restore. A
monitoring window on one project could read another project's fingerprint, and
deleting a project left its containers behind.

Docker is answered here by a stand-in that keeps a list of containers and
answers the few commands the local target asks, so what is under test is which
port is chosen and what is removed; the real adapter against real Docker is in
`test_local_release.py`.
"""

import re
from datetime import UTC, datetime

import pytest
from orchestrator.deploy.adapters.local_docker import LocalDocker, remove_project
from orchestrator.saga.executor import StepContext, StepFailed
from sdlc_contracts import BuildStepReport, DeployStep, ReleaseCandidate, VerifiedRelease

NOW = datetime(2026, 10, 5, tzinfo=UTC)
BASE = 18080


class FakeDocker:
    """The docker commands the local target asks, answered from a list of containers."""

    def __init__(self, *, refusals: int = 0, refusal: str = "") -> None:
        self.containers: list[dict] = []
        self.asked: list[list[str]] = []
        #: How many runs Docker refuses before it starts one, and with what.
        self.refusals = refusals
        self.refusal = refusal or (
            "docker: Error response from daemon: ports are not available: exposing port TCP "
            "127.0.0.1:{port} -> 127.0.0.1:0: /forwards/expose returned unexpected status: 500"
        )

    def add(
        self,
        *,
        project: str = "",
        port: int | None = None,
        labelled: bool = True,
        running: bool = True,
        role: str = "release",
        lane: str = "release",
    ) -> str:
        labels = {}
        if project:
            labels = {"sdlc.c4.project": project, "sdlc.c4.lane": lane, "sdlc.c4.role": role}
            if port is not None and labelled:
                labels["sdlc.c4.port"] = str(port)
        container = f"c{len(self.containers) + 1:011d}"
        self.containers.append(
            {
                "id": container,
                "labels": labels,
                "running": running,
                "ports": [port] if port is not None else [],
            }
        )
        return container

    def removed(self) -> list[str]:
        return [args[-1] for args in self.asked if args[:2] == ["rm", "-f"]]

    async def __call__(self, args: list[str]) -> tuple[int, str]:
        self.asked.append(args)
        if args[0] == "image":
            return 0, '{"3001/tcp":{}}'
        if args[0] == "inspect":
            return 0, "sha256:" + "0" * 64
        if args[0] == "rm":
            self.containers = [one for one in self.containers if one["id"] != args[-1]]
            return 0, args[-1]
        if args[0] == "port":
            [one] = [one for one in self.containers if one["id"] == args[1]]
            return 0, f"127.0.0.1:{one['ports'][0]}"
        if args[0] == "run":
            return self._run(args[1:])
        if args[0] == "ps":
            return 0, self._ps(args[1:])
        raise AssertionError(f"not a command the local target asks: {args}")

    def _run(self, args: list[str]) -> tuple[int, str]:
        labels = dict(
            args[index + 1].split("=", 1) for index, one in enumerate(args) if one == "--label"
        )
        published = args[args.index("-p") + 1]
        port = int(published.split(":")[1]) if published.split(":")[1] else 49152
        if any(one["running"] and port in one["ports"] for one in self.containers):
            return 125, f"Bind for 127.0.0.1:{port} failed: port is already allocated"
        if self.refusals:
            # As Docker does: the container is created, its id printed, and the
            # start refused after it.
            self.refusals -= 1
            created = f"{len(self.containers) + 200:064x}"
            self.containers.append({"id": created, "labels": labels, "running": False, "ports": []})
            return 125, created + "\n" + self.refusal.format(port=port)
        container = f"c{len(self.containers) + 100:011d}"
        self.containers.append(
            {"id": container, "labels": labels, "running": True, "ports": [port]}
        )
        return 0, container

    def _ps(self, args: list[str]) -> str:
        every = "-a" in args or "-aq" in args
        quiet = "-q" in args or "-aq" in args
        filters = [args[index + 1] for index, one in enumerate(args) if one == "--filter"]
        form = args[args.index("--format") + 1] if "--format" in args else ""
        found = []
        for one in self.containers:
            if not (every or one["running"]):
                continue
            keep = True
            for wanted in filters:
                kind, _, value = wanted.partition("=")
                if kind == "label":
                    key, _, expected = value.partition("=")
                    keep = keep and one["labels"].get(key) == expected
                elif kind == "publish":
                    keep = keep and one["running"] and int(value) in one["ports"]
            if keep:
                found.append(one)
        if quiet:
            return "\n".join(one["id"] for one in found)
        return "\n".join(self._format(form, one) for one in found)

    @staticmethod
    def _format(form: str, one: dict) -> str:
        text = form.replace("{{.ID}}", one["id"]).replace(
            "{{.Ports}}",
            ", ".join(f"127.0.0.1:{port}->3001/tcp" for port in one["ports"])
            if one["running"]
            else "",
        )
        return re.sub(
            r'\{\{\.Label "([^"]+)"\}\}', lambda match: one["labels"].get(match.group(1), ""), text
        )


def _ctx(project: str, *, previous: VerifiedRelease | None = None) -> StepContext:
    candidate = ReleaseCandidate(
        version=1,
        generated_at=NOW,
        code_version=1,
        candidate_hash="a" * 64,
        image="app:v1",
        image_digest="sha256:" + "e" * 64,
        toolchain="scripted",
        isolation="scripted",
        steps=[BuildStepReport(name="image", command="docker build .", outcome="passed")],
        fingerprint="a" * 64,
    )
    return StepContext(
        deployment={"id": f"d-{project}", "kind": "release", "project_id": project},
        plan=None,  # type: ignore[arg-type]
        step=DeployStep(id="switch", label="Switch", moves_traffic=True, compensation="restore"),
        seq=2,
        key="k",
        candidate=candidate,
        previous=previous,
    )


def _verified_at(url: str) -> VerifiedRelease:
    return VerifiedRelease(
        deployment_id="d-earlier",
        deploy_version=1,
        candidate_hash="b" * 64,
        target="local",
        image_digest="sha256:" + "b" * 64,
        url=url,
        verified_at=NOW,
    )


def _target(fake: FakeDocker, *, free=lambda port: True, waited: list | None = None) -> LocalDocker:
    async def wait(seconds: float) -> None:
        if waited is not None:
            waited.append(seconds)

    return LocalDocker(release_port=BASE, run=fake, free=free, sleep=wait)


class TestAFirstRelease:
    async def test_it_takes_the_first_port_no_other_project_holds(self) -> None:
        fake = FakeDocker()
        theirs = fake.add(project="p-other", port=BASE)

        switched = await _target(fake).execute(_ctx("p-new"))

        assert switched.resource["address"] == f"127.0.0.1:{BASE + 1}"
        assert "sdlc.c4.port=18081" in switched.command
        assert theirs not in fake.removed(), "another project's release is not this one's"

    async def test_a_port_another_project_claims_is_not_taken_while_its_release_is_stopped(
        self,
    ) -> None:
        """A release a fault stopped is still that project's, and so is its port."""
        fake = FakeDocker()
        fake.add(project="p-other", port=BASE, running=False)

        switched = await _target(fake).execute(_ctx("p-new"))

        assert switched.resource["address"] == f"127.0.0.1:{BASE + 1}"

    async def test_a_port_held_outside_any_project_is_skipped(self) -> None:
        """A container nothing labels, or a process outside Docker, holds it."""
        fake = FakeDocker()
        fake.add(port=BASE)

        switched = await _target(fake, free=lambda port: port != BASE + 1).execute(_ctx("p-new"))

        assert switched.resource["address"] == f"127.0.0.1:{BASE + 2}"


class TestALaterRelease:
    async def test_it_keeps_its_own_port(self) -> None:
        fake = FakeDocker()
        fake.add(project="p-other", port=BASE)
        mine = fake.add(project="p-mine", port=BASE + 5)

        switched = await _target(fake).execute(_ctx("p-mine"))

        assert switched.resource["address"] == f"127.0.0.1:{BASE + 5}"
        assert fake.removed() == [mine], "its own release was replaced, and only that"

    async def test_with_its_container_gone_it_returns_to_where_it_was_verified(self) -> None:
        fake = FakeDocker()

        switched = await _target(fake).execute(
            _ctx("p-mine", previous=_verified_at(f"http://127.0.0.1:{BASE + 9}"))
        )

        assert switched.resource["address"] == f"127.0.0.1:{BASE + 9}"

    async def test_a_release_from_before_ports_were_labelled_keeps_its_port(self) -> None:
        """The release running on this machine since before each project had its
        own port carries no port label, and its project keeps that port."""
        fake = FakeDocker()
        legacy = fake.add(project="p-mine", port=BASE, labelled=False)

        switched = await _target(fake).execute(
            _ctx("p-mine", previous=_verified_at(f"http://127.0.0.1:{BASE}"))
        )

        assert switched.resource["address"] == f"127.0.0.1:{BASE}"
        assert fake.removed() == [legacy]

    async def test_its_recorded_port_held_by_another_project_moves_it_rather_than_fails(
        self,
    ) -> None:
        fake = FakeDocker()
        fake.add(project="p-other", port=BASE)

        switched = await _target(fake).execute(
            _ctx("p-mine", previous=_verified_at(f"http://127.0.0.1:{BASE}"))
        )

        assert switched.resource["address"] == f"127.0.0.1:{BASE + 1}"


class TestNoPortFree:
    async def test_the_switch_refuses_before_anything_moves(self) -> None:
        """Refused as having moved nothing, so the saga undoes the steps before it
        rather than waiting on a rollback with nothing to restore."""
        fake = FakeDocker()
        mine = fake.add(project="p-mine", port=BASE, running=False)

        with pytest.raises(StepFailed, match="no release port from 18080 to 18279") as refused:
            await _target(fake, free=lambda port: False).execute(_ctx("p-new"))

        assert refused.value.moved is False
        assert fake.removed() == [] and mine in [one["id"] for one in fake.containers]
        assert not any(args[0] == "run" for args in fake.asked)


class TestDockerNotReadyWithThePort:
    """Docker Desktop refused to expose a port nothing held ("/forwards/expose
    returned unexpected status: 500"), and a port the replaced release held can
    take a moment to come free. Either failed the switch, a traffic step, and
    left the release waiting on a rollback."""

    async def test_the_start_is_tried_again_and_the_refused_container_removed(self) -> None:
        fake, waited = FakeDocker(refusals=1), []

        switched = await _target(fake, waited=waited).execute(_ctx("p-new"))

        assert switched.resource["address"] == f"127.0.0.1:{BASE}"
        assert waited == [0.5]
        [refused] = [args[-1] for args in fake.asked if args[:2] == ["rm", "-f"]]
        assert len(refused) == 64, "the container the refused run created"
        assert [one["id"] for one in fake.containers] == [switched.resource["container"]]

    async def test_a_refusal_that_lasts_still_fails_in_docker_s_words(self) -> None:
        fake, waited = FakeDocker(refusals=9), []

        with pytest.raises(StepFailed, match="ports are not available"):
            await _target(fake, waited=waited).execute(_ctx("p-new"))

        assert waited == [0.5, 1.0, 2.0]
        assert sum(1 for args in fake.asked if args[0] == "run") == 4

    async def test_any_other_refusal_is_not_tried_again(self) -> None:
        fake, waited = FakeDocker(refusals=1, refusal="docker: No such image: app:v1"), []

        with pytest.raises(StepFailed, match="No such image"):
            await _target(fake, waited=waited).execute(_ctx("p-new"))

        assert waited == []


class TestADeletedProject:
    async def test_its_containers_go_with_it_and_no_other_project_s(self) -> None:
        fake = FakeDocker()
        release = fake.add(project="p-gone", port=BASE)
        check = fake.add(project="p-gone", role="check", running=False)
        theirs = fake.add(project="p-other", port=BASE + 1)

        removed = await remove_project("p-gone", run=fake)

        assert removed == 2
        assert sorted(fake.removed()) == sorted([release, check])
        assert theirs not in fake.removed()
