"""Detection end to end, on the generated monorepo, answered from recorded shapes.

What this proves is FR1 to FR3 as a reader meets them: the updates a project
could take, each with its version change, its notes and where its source lives;
and every dependency that could not be analysed, each with a reason a developer
can act on. Nothing is dropped, and nothing that could not be read raises.
"""

import json

import httpx
from c4.intake.detect import detect
from c4.intake.fetch import Fetcher
from c4.intake.lockfile import Pin, PinFailed
from c4.service import C4
from sdlc_contracts import BaselinePin, DependencyUpdates

ROOT = json.dumps(
    {"name": "generated-app", "private": True, "workspaces": ["apps/*", "packages/*"]}
)
API = json.dumps(
    {
        "name": "@app/api",
        "dependencies": {"@app/contract": "*", "express": "^4.21.2", "zod": "^3.23.8"},
        "devDependencies": {"vitest": "^2.1.0"},
    },
    indent=2,
)
FILES = {
    "package.json": ROOT,
    "apps/api/package.json": API,
    "packages/contract/package.json": json.dumps({"name": "@app/contract"}),
}

PIN = Pin(
    record=BaselinePin(
        lockfile_path="package-lock.json",
        lockfile_sha256="a" * 64,
        packages=40,
        direct=3,
        resolved_by="npm 10.9.2 install --package-lock-only --ignore-scripts",
    ),
    text='{"lockfileVersion": 3}',
    resolved={"apps/api": {"express": "4.21.2", "zod": "3.23.8", "vitest": "2.1.9"}},
)


def _pinned(files: dict[str, str]) -> Pin:
    return PIN


def _unpinnable(files: dict[str, str]) -> Pin:
    raise PinFailed("npm could not resolve the tree: ETARGET no matching version")


def _package(
    name: str, versions: dict[str, str], latest: str, repository: str | None = None
) -> dict:
    document = {
        "name": name,
        "dist-tags": {"latest": latest},
        "time": versions,
        "versions": {
            v: {"dist": {"tarball": f"https://registry.npmjs.org/{name}/-/{name}-{v}.tgz"}}
            for v in versions
        },
    }
    if repository:
        document["repository"] = {"url": f"git+https://github.com/{repository}.git"}
    return document


EXPRESS = _package(
    "express",
    {
        "4.21.2": "2024-12-05T00:00:00Z",
        "4.21.3": "2025-01-01T00:00:00Z",
        "5.1.0": "2025-03-31T00:00:00Z",
    },
    "5.1.0",
    repository="expressjs/express",
)
ZOD = _package("zod", {"3.24.1": "2025-01-01T00:00:00Z"}, "3.24.1")

RELEASES = [
    {"tag_name": "v5.1.0", "body": "- Added `res.links` overloads."},
    {"tag_name": "v5.0.0", "body": "- Removed `app.del`, use `app.delete` instead."},
    {"tag_name": "v4.21.3", "body": "- Fixed a header being sent twice."},
]


def _registry(routes: dict[str, httpx.Response]) -> httpx.MockTransport:
    def answer(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        for prefix, response in routes.items():
            if url.startswith(prefix):
                return response
        return httpx.Response(404)

    return httpx.MockTransport(answer)


ROUTES = {
    "https://registry.npmjs.org/express": httpx.Response(200, json=EXPRESS),
    "https://registry.npmjs.org/zod": httpx.Response(200, json=ZOD),
    "https://api.github.com/repos/expressjs/express/releases": httpx.Response(200, json=RELEASES),
}


async def _detected(routes=ROUTES, pinner=_pinned, files=FILES):
    fetcher = Fetcher(httpx.AsyncClient(transport=_registry(routes)))
    return await detect(files, fetcher=fetcher, pinner=pinner), fetcher


class TestTheUpdatesAProjectCouldTake:
    async def test_both_candidates_are_offered_and_the_in_range_one_names_the_latest(self) -> None:
        detected, _ = await _detected()
        express = {
            (u.candidate, u.to_version): u for u in detected.updates if u.package == "express"
        }
        in_range = express[("in-range", "4.21.3")]
        latest = express[("latest", "5.1.0")]
        assert (in_range.change, in_range.superseded_by) == ("patch", "5.1.0")
        assert (latest.change, latest.superseded_by) == ("major", None)
        assert latest.from_version == "4.21.2", "the version starts from what the pin resolved"

    async def test_an_update_carries_its_notes_date_and_source(self) -> None:
        detected, _ = await _detected()
        latest = next(u for u in detected.updates if u.to_version == "5.1.0")
        assert latest.repository_url == "https://github.com/expressjs/express"
        assert latest.published_at is not None and latest.published_at.year == 2025
        assert [ref.source for ref in latest.notes] == ["github-release"]
        stored = detected.texts[latest.notes[0].path]
        assert "Removed `app.del`" in stored and "Fixed a header" in stored

    async def test_the_baseline_lockfile_is_kept_to_be_committed(self) -> None:
        detected, _ = await _detected()
        assert detected.baseline == PIN.record
        assert detected.texts["package-lock.json"] == PIN.text


class TestWhatCouldNotBeAnalysedIsSaid:
    async def test_every_rejection_has_a_reason_and_a_sentence(self) -> None:
        detected, _ = await _detected()
        reasons = {r.package: r.reason for r in detected.rejected}
        assert reasons == {
            "@app/contract": "not-a-registry-dependency",
            "zod": "version-not-found",
            "vitest": "package-not-found",
        }
        assert all(r.detail for r in detected.rejected)

    async def test_an_unreachable_registry_rejects_instead_of_aborting(self) -> None:
        routes = {**ROUTES, "https://registry.npmjs.org/express": httpx.Response(503)}
        detected, _ = await _detected(routes)
        express = next(r for r in detected.rejected if r.package == "express")
        assert express.reason == "registry-unreachable"

    async def test_an_unresolvable_tree_rejects_every_npm_dependency_and_says_why(self) -> None:
        detected, _ = await _detected(pinner=_unpinnable)
        unresolved = [r for r in detected.rejected if r.reason == "unresolvable-version"]
        assert {r.package for r in unresolved} == {"express", "zod", "vitest"}
        assert all("ETARGET" in r.detail for r in unresolved)
        assert detected.updates == []

    async def test_every_question_was_asked_once_and_recorded(self) -> None:
        _, fetcher = await _detected()
        asked = [q.url for q in fetcher.queries if q.registry == "npm"]
        assert len(asked) == len(set(asked))


class TestMaven:
    POM = """<project xmlns="http://maven.apache.org/POM/4.0.0">
  <dependencies>
    <dependency><groupId>org.apache.dubbo</groupId><artifactId>dubbo</artifactId><version>2.7.3</version></dependency>
    <dependency><groupId>org.example</groupId><artifactId>ranged</artifactId><version>[1.0,2.0)</version></dependency>
  </dependencies>
</project>"""

    async def test_a_maven_update_and_a_range_nobody_can_resolve(self) -> None:
        metadata = b"<metadata><versioning><release>2.7.21</release><versions><version>2.7.3</version><version>2.7.21</version></versions></versioning></metadata>"
        routes = {
            "https://repo1.maven.org/maven2/org/apache/dubbo/dubbo/maven-metadata.xml": httpx.Response(
                200, content=metadata
            )
        }
        detected, _ = await _detected(routes, files={"pom.xml": self.POM})
        (update,) = detected.updates
        assert (update.package, update.from_version, update.to_version, update.change) == (
            "org.apache.dubbo:dubbo",
            "2.7.3",
            "2.7.21",
            "patch",
        )
        (ranged,) = detected.rejected
        assert ranged.reason == "unresolvable-version"


class TestOneUpdateDeclaredTwice:
    """The generated projects declare TypeScript and Vitest in both apps.

    The pin hoists one version for both, so both declarations name the same
    move, and that is one update: assessed once, decided once, and saying where
    else it applies. Two copies would be two identical assessments, and the
    report refuses an update listed twice, which failed every real run on a
    generated project until this was found on the live walkthrough.
    """

    WEB = json.dumps({"name": "@app/web", "devDependencies": {"vitest": "^2.1.0"}}, indent=2)
    VITEST = _package(
        "vitest",
        {"2.1.9": "2024-12-01T00:00:00Z", "3.2.4": "2025-06-17T00:00:00Z"},
        "3.2.4",
    )

    async def _detected(self):
        files = {**FILES, "apps/web/package.json": self.WEB}
        pin = Pin(
            record=PIN.record,
            text=PIN.text,
            resolved={**PIN.resolved, "apps/web": {"vitest": "2.1.9"}},
        )
        routes = {
            **ROUTES,
            "https://registry.npmjs.org/vitest": httpx.Response(200, json=self.VITEST),
        }
        return await _detected(routes=routes, pinner=lambda files: pin, files=files)

    async def test_it_is_one_update_that_says_where_else_it_applies(self) -> None:
        detected, _ = await self._detected()
        vitest = [update for update in detected.updates if update.package == "vitest"]
        assert len(vitest) == 1
        assert vitest[0].manifest_path == "apps/api/package.json"
        assert vitest[0].also_declared_in == ["apps/web/package.json"]

    async def test_the_report_accepts_it(self) -> None:
        detected, fetcher = await self._detected()
        from datetime import UTC, datetime

        from c4.intake.detect import report

        updates = report(
            detected,
            fetcher,
            version=1,
            code_version=1,
            test_version=1,
            target="generated",
            generated_at=datetime.now(UTC),
        )
        assert sum(update.package == "vitest" for update in updates.updates) == 1


async def test_a_run_scoped_to_nothing_still_pins_the_whole_tree() -> None:
    """The candidate is built from the baseline lockfile, so a run that looks at no
    package still needs it. The first live cloud run, scoped to none, found no
    lockfile at pipeline generation because detection pinned only for the scope."""
    asked: list[dict[str, str]] = []

    def pinner(files: dict[str, str]) -> Pin:
        asked.append(files)
        return PIN

    detected, _ = await _detected(pinner=pinner, files=FILES)
    scoped = await detect(
        FILES,
        fetcher=Fetcher(httpx.AsyncClient(transport=_registry(ROUTES))),
        pinner=pinner,
        packages=["none"],
    )

    assert scoped.updates == [] and scoped.rejected == []
    assert scoped.baseline == PIN.record
    assert "package-lock.json" in scoped.texts
    assert len(asked) == 2, "pinned for the unscoped run and for the one scoped to nothing"
    assert detected.baseline == scoped.baseline


async def test_the_component_answers_with_a_report_the_contract_accepts() -> None:
    component = C4(
        "deepseek:deepseek-flash",
        http=httpx.AsyncClient(transport=_registry(ROUTES)),
        pinner=_pinned,
    )
    answer = await component.detect_updates(
        FILES, target="generated", version=1, code_version=2, test_version=3
    )
    report = DependencyUpdates.model_validate(answer.artefact.model_dump(by_alias=True))
    assert (report.version, report.code_version, report.test_version) == (1, 2, 3)
    assert len(report.updates) == 2 and report.rejected_count == 3
    assert report.queried, "the questions asked travel with the report"
    assert "package-lock.json" in answer.notes["texts"]
    assert "2 updates found" in answer.summary


class TestTheEventLoopKeepsRunning:
    """The pin is an npm install that can take minutes, and the loop is not C4's.

    In process, C4 runs on the orchestrator's event loop. Run there directly, the
    pin froze every route of the orchestrator for as long as npm took, which is
    how the live walkthrough found it: the deployment page stopped updating the
    moment a run started. A slow pinner beside a ticking coroutine shows the
    loop is free while the pin works.
    """

    async def test_a_slow_pin_does_not_hold_the_loop(self) -> None:
        import asyncio
        import time

        def slow(files: dict[str, str]) -> Pin:
            time.sleep(0.4)
            return PIN

        ticks = 0

        async def ticker() -> None:
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        running = asyncio.create_task(ticker())
        try:
            await _detected(pinner=slow)
        finally:
            running.cancel()
        assert ticks >= 10, f"the loop ticked {ticks} times while npm pinned"
