"""The impact stage over the stub graph: one index, the files that use what changed, their components.

The project is the task list application the stub Semantic Architecture Graph
describes, written here so that two files use the removed `del` and the rest do
not. The stage is checked for what it maps and why, for what it refuses to map,
and for building its index exactly once however many updates it looks at.
"""

import json
from pathlib import Path

import httpx
import pytest
from c4.impact import stage
from c4.impact.sag import map_to_graph, map_to_modules
from c4.intake.fetch import Fetcher
from c4.service import C4
from sdlc_contracts import (
    ApiContract,
    ArchitectureGraph,
    ChangelogReport,
    DependencyUpdate,
    DependencyUpdates,
    ImpactReport,
    ManifestRow,
    update_id_for,
    update_key,
)

HERE = Path(__file__).resolve().parent / "fixtures" / "sag"
GRAPH = ArchitectureGraph.model_validate(json.loads((HERE / "graph.json").read_text()))
CONTRACT = ApiContract.model_validate(json.loads((HERE / "contract.json").read_text()))
MANIFEST = [
    ManifestRow.model_validate(row) for row in json.loads((HERE / "manifest.json").read_text())
]

FILES = {
    "apps/api/src/routes/task-lists.ts": (
        'import { Router } from "express";\n'
        "export function taskListsRouter() {\n"
        "  const router = Router();\n"
        '  router.del("/:id", (req, res) => res.sendStatus(204));\n'
        "  return router;\n"
        "}\n"
    ),
    "apps/api/src/routes/tasks.ts": (
        'import { Router } from "express";\n'
        "export const tasks = Router();\n"
        'tasks.get("/", (req, res) => res.json([]));\n'
    ),
    "apps/api/src/models/Task.ts": "export interface Task { id: string; title: string }\n",
    "apps/api/src/server.ts": (
        'import express from "express";\n'
        "const app = express();\n"
        'app.del("/all", (req, res) => res.sendStatus(204));\n'
    ),
    "apps/web/src/screens/TaskListScreen.tsx": "export const TaskListScreen = () => null;\n",
    "apps/api/package.json": json.dumps({"scripts": {"test": "vitest run"}}),
}


def _update(package: str, ecosystem: str = "npm", old: str = "1.0.0", new: str = "2.0.0"):
    key = update_key(ecosystem, package, old, new)
    return DependencyUpdate(
        id=update_id_for(key),
        key=key,
        ecosystem=ecosystem,  # type: ignore[arg-type]
        package=package,
        manifest_path="pom.xml" if ecosystem == "maven" else "apps/api/package.json",
        scope="compile" if ecosystem == "maven" else "prod",
        declared=old,
        from_version=old,
        to_version=new,
        candidate="latest",
        change="major",
    )


EXPRESS = _update("express", old="4.21.2", new="5.1.0")
ZOD = _update("zod")
VITEST = _update("vitest")


def _updates(*updates: DependencyUpdate) -> DependencyUpdates:
    return DependencyUpdates(
        version=1,
        generated_at="2026-09-27T00:00:00Z",
        code_version=1,
        test_version=1,
        target="generated",
        updates=list(updates),
    )


def _claiming(update: DependencyUpdate, kind: str, symbols: list[str]) -> ChangelogReport:
    """A changelog report with one verified claim for one update."""
    return ChangelogReport.model_validate(
        {
            "version": 1,
            "generatedAt": "2026-09-27T00:00:00Z",
            "modelId": "deepseek:deepseek-flash",
            "promptId": "changelog-extract/1",
            "promptSha256": "0" * 64,
            "perUpdate": [
                {
                    "updateId": update.id,
                    "notesFound": True,
                    "claims": [
                        {
                            "id": f"{update.id}-c1",
                            "kind": kind,
                            "symbols": symbols,
                            "quote": f"Removed {' and '.join(symbols)}.",
                            "sourceUrl": "https://example/releases",
                            "version": update.to_version,
                        }
                    ],
                    "vote": {
                        "signal": "changelog",
                        "level": "high",
                        "ruleId": "changelog-rule/1",
                        "rationale": "written by code",
                    },
                    "model": {
                        "modelId": "deepseek:deepseek-flash",
                        "promptId": "changelog-extract/1",
                        "promptSha256": "0" * 64,
                        "outcome": "answered",
                    },
                }
            ],
        }
    )


def _registry() -> httpx.MockTransport:
    """Every package is known and none has a tarball, so no declaration diff can run."""

    def answer(request: httpx.Request) -> httpx.Response:
        name = request.url.path.lstrip("/")
        return httpx.Response(
            200,
            json={"name": name, "dist-tags": {"latest": "2.0.0"}, "versions": {"2.0.0": {}}},
        )

    return httpx.MockTransport(answer)


async def _analyse(files, updates, changelog=None, **kwargs) -> ImpactReport:
    async with httpx.AsyncClient(transport=_registry()) as client:
        return await stage.analyse(
            files,
            updates,
            changelog,
            graph=kwargs.get("graph", GRAPH),
            contract=CONTRACT,
            manifest=MANIFEST,
            version=1,
            code_version=1,
            design_version=1,
            fetcher=Fetcher(client),
        )


class TestTheStage:
    async def test_the_files_that_use_what_changed_and_the_components_they_are(self) -> None:
        report = await _analyse(
            FILES, _updates(EXPRESS, ZOD), _claiming(EXPRESS, "removal", ["app.del"])
        )
        express, zod = report.per_update
        assert express.vote.level == "high"
        assert [(r.span.path, r.span.start_line) for r in express.references] == [
            ("apps/api/src/routes/task-lists.ts", 4),
            ("apps/api/src/server.ts", 3),
        ]
        # Nothing known changed in zod, and nothing imports it: no vote.
        assert zod.vote.level is None and zod.api_diff == "unavailable"
        assert [f.path for f in report.affected_files] == [
            "apps/api/src/routes/task-lists.ts",
            "apps/api/src/server.ts",
        ]
        [component] = report.affected_components
        assert (component.node_id, component.label, component.traces) == (
            "e-task-list",
            "TaskList",
            ["R-1"],
        )
        assert {link.via for link in component.links} == {"endpoint-entity"}
        assert "ep-list-task-lists (GET /task-lists) is a view of TaskList" in [
            link.detail for link in component.links
        ]
        [unmapped] = report.unmapped_files
        assert (unmapped.path, unmapped.reason) == (
            "apps/api/src/server.ts",
            "implements-nothing-mapped",
        )
        assert report.granularity == "graph-node"

    async def test_the_project_is_indexed_once_however_many_updates_there_are(
        self, monkeypatch
    ) -> None:
        """NFR2: one index per run, built here and handed on as the report."""
        builds: list[int] = []
        real = stage.build

        def counting(*args, **kwargs):
            builds.append(1)
            return real(*args, **kwargs)

        monkeypatch.setattr(stage, "build", counting)
        report = await _analyse(
            FILES, _updates(EXPRESS, ZOD, VITEST), _claiming(EXPRESS, "removal", ["app.del"])
        )
        assert len(builds) == 1
        assert report.extraction.files_indexed == 5

    async def test_indexing_does_not_hold_the_event_loop(self, monkeypatch) -> None:
        """In process, the loop is the orchestrator's. Indexing a large Maven
        project took up to 100 s in Epoch 4, and on the loop that would freeze
        every route while it worked."""
        import asyncio
        import time

        real = stage.build

        def slow(*args, **kwargs):
            time.sleep(0.4)
            return real(*args, **kwargs)

        monkeypatch.setattr(stage, "build", slow)
        ticks = 0

        async def ticker() -> None:
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        running = asyncio.create_task(ticker())
        try:
            await _analyse(FILES, _updates(VITEST))
        finally:
            running.cancel()
        assert ticks >= 10, f"the loop ticked {ticks} times while the index was built"

    async def test_a_tool_used_only_by_a_script_is_recorded_on_its_update(self) -> None:
        report = await _analyse(FILES, _updates(VITEST))
        assert report.per_update[0].used_by_scripts

    async def test_without_a_graph_every_affected_file_is_unmapped_and_says_so(self) -> None:
        report = await _analyse(
            FILES, _updates(EXPRESS), _claiming(EXPRESS, "removal", ["app.del"]), graph=None
        )
        assert report.affected_components == []
        assert {(u.path, u.reason) for u in report.unmapped_files} == {
            ("apps/api/src/routes/task-lists.ts", "graph-unavailable"),
            ("apps/api/src/server.ts", "graph-unavailable"),
        }

    async def test_the_component_answers_through_its_stage(self) -> None:
        component = C4("deepseek:deepseek-flash", http=httpx.AsyncClient(transport=_registry()))
        answer = await component.analyse_impact(
            FILES,
            _updates(EXPRESS),
            _claiming(EXPRESS, "removal", ["app.del"]),
            graph=GRAPH,
            contract=CONTRACT,
            manifest=MANIFEST,
            version=2,
            code_version=1,
            design_version=1,
        )
        assert isinstance(answer.artefact, ImpactReport) and answer.artefact.version == 2
        assert answer.summary == (
            "1 of 1 update used by the code, in 2 files; 1 component reached, 1 file unmapped"
        )
        assert answer.notes["files_indexed"] == 5 and answer.notes["references"] == 2


class TestTheMapping:
    def test_a_name_that_is_only_close_to_a_nodes_is_never_mapped_to_it(self) -> None:
        """`Tasks` is not `Task`: resemblance is not a recorded link."""
        rows = [
            ManifestRow(path="a.ts", stage="backend-code", generator="rule", implements=["Tasks"])
        ]
        components, unmapped = map_to_graph(
            {"a.ts": {EXPRESS.id}}, graph=GRAPH, contract=CONTRACT, manifest=rows
        )
        assert components == []
        assert [(u.path, u.reason) for u in unmapped] == [("a.ts", "implements-nothing-mapped")]

    def test_an_endpoint_whose_entity_no_node_carries_is_unmapped_with_that_reason(self) -> None:
        contract = CONTRACT.model_copy(deep=True)
        contract.endpoints[0].response.entity = "Comment"  # type: ignore[union-attr]
        rows = [
            ManifestRow(
                path="a.ts",
                stage="backend-code",
                generator="rule",
                implements=[contract.endpoints[0].id],
            )
        ]
        _, unmapped = map_to_graph(
            {"a.ts": {EXPRESS.id}}, graph=GRAPH, contract=contract, manifest=rows
        )
        assert [(u.reason, u.detail) for u in unmapped] == [
            ("no-graph-node-matches", "no graph entity is named exactly Comment")
        ]

    def test_a_file_the_manifest_does_not_know_is_unmapped(self) -> None:
        _, unmapped = map_to_graph(
            {"scripts/seed.ts": {EXPRESS.id}}, graph=GRAPH, contract=CONTRACT, manifest=MANIFEST
        )
        assert [u.reason for u in unmapped] == ["not-in-manifest"]

    def test_a_project_without_a_graph_maps_to_the_maven_module_a_file_sits_under(self) -> None:
        files = {
            "pom.xml": "<project><artifactId>parent</artifactId></project>",
            "core/pom.xml": (
                "<project><parent><artifactId>parent</artifactId></parent>"
                "<artifactId>core</artifactId></project>"
            ),
            "core/src/main/java/com/x/A.java": "class A {}",
            "tools/B.java": "class B {}",
        }
        components, unmapped = map_to_modules(
            {"core/src/main/java/com/x/A.java": {EXPRESS.id}, "tools/B.java": {EXPRESS.id}},
            files,
        )
        [core] = [c for c in components if c.node_id == "module:core"]
        assert (core.label, core.kind, core.links[0].via) == ("core", "module", "build-module")
        # `tools/` has no pom.xml of its own, so the root module is where it sits.
        assert [c.node_id for c in components] == ["module:.", "module:core"]
        assert unmapped == []


@pytest.mark.parametrize("claimed", [["RpcContext.getServerContext"]])
async def test_a_maven_project_is_reported_by_module(monkeypatch, claimed) -> None:
    monkeypatch.setenv("C4_ROSEAU", "/nowhere/roseau")
    dubbo = _update("org.apache.dubbo:dubbo", "maven", "2.7.3", "2.7.21")
    files = {
        "pom.xml": "<project><artifactId>agent</artifactId></project>",
        "core/pom.xml": "<project><artifactId>agent-core</artifactId></project>",
        "core/src/main/java/com/x/Handler.java": (
            "package com.x;\n"
            "import com.alibaba.dubbo.rpc.RpcContext;\n"
            "class Handler { Object f() { return RpcContext.getContext().getServerContext(); } }\n"
        ),
    }
    report = await _analyse(
        files, _updates(dubbo), _claiming(dubbo, "removal", claimed), graph=None
    )
    assert report.granularity == "module"
    assert report.per_update[0].api_diff == "unavailable"
    assert report.per_update[0].vote.level == "high"
    [component] = report.affected_components
    assert (component.node_id, component.label) == ("module:core", "agent-core")


async def test_each_update_is_charged_its_diff_its_search_and_the_whole_index(
    monkeypatch,
) -> None:
    """NFR1's usage step, per update, on a clock the test controls: one tick for
    each API diff and one for each search, plus the one index build every
    update is charged in full. One diff at a time, so the ticks cannot
    interleave between two diffs in flight."""
    monkeypatch.setattr(stage, "DIFFS_AT_ONCE", 1)
    ticks = iter(float(n) for n in range(1000))
    async with httpx.AsyncClient(transport=_registry()) as client:
        report = await stage.analyse(
            FILES,
            _updates(EXPRESS, ZOD),
            _claiming(EXPRESS, "removal", ["app.del"]),
            graph=GRAPH,
            contract=CONTRACT,
            manifest=MANIFEST,
            version=1,
            code_version=1,
            design_version=1,
            fetcher=Fetcher(client),
            clock=lambda: next(ticks),
        )
    index_seconds = report.extraction.seconds
    for impact in report.per_update:
        assert impact.seconds == pytest.approx(2.0 + index_seconds, abs=0.002)
