"""The impact stage reads the graph the code was built from, not the newest one.

C4 maps affected files to Semantic Architecture Graph components. The graph it
maps against has to be the one behind the code being deployed: the design that
code version was generated from, two hops back through the testing run and the
code run. A design that moved on since describes components this code does not
have, and a mapping against it would name components that do not exist in the
release, or miss ones that do.
"""

from collections.abc import AsyncIterator

import httpx
import pytest
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.clients.canned_c4 import CannedC4
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.main import create_app, lifespan_for_tests

from .conftest import needs_db
from .test_deployment_spine import _start_deploy_run, _tested
from .test_testing_spine import _advance

pytestmark = needs_db


class RecordingC4(CannedC4):
    """The canned component, remembering which graph the impact stage was handed."""

    seen: dict

    async def analyse_impact(self, files, updates, changelog, **kwargs):
        graph = kwargs["graph"]
        self.seen = {
            "design_version": kwargs["design_version"],
            "node_ids": {node.id for node in graph.nodes} if graph else set(),
        }
        return await super().analyse_impact(files, updates, changelog, **kwargs)


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, lifespan_factory=lifespan_for_tests)
    app.state.c4 = RecordingC4()
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            c.app = app  # type: ignore[attr-defined]
            created: list[str] = []
            c.created_projects = created  # type: ignore[attr-defined]
            try:
                yield c
            finally:
                async with app.state.pool.connection() as conn:
                    for project_id in created:
                        await store.delete_project(conn, project_id, owner_id=DEV_OWNER_ID)


async def test_the_impact_stage_reads_the_graph_behind_the_code(client) -> None:
    project_id, code_version, test_version = await _tested(client)
    async with client.app.state.pool.connection() as conn:
        design = await store.design_version_for_code(conn, project_id, code_version)
        behind = await store.artefacts_at(
            conn, project_id, version=design, kinds=("architecture-graph",)
        )
        # A newer design, with a component the deployed code knows nothing about.
        newer = dict(behind["architecture-graph"]["body"])
        newer["nodes"] = [
            *newer["nodes"],
            {
                "id": "e-invoice",
                "kind": "entity",
                "label": "Invoice",
                "position": {"x": 0, "y": 0},
                "traces": [],
            },
        ]
        await store.put_artefact(
            conn,
            project_id=project_id,
            kind="architecture-graph",
            version=design + 1,
            body=newer,
        )
    run, _ = await _start_deploy_run(client, project_id, test_version)

    await _advance(client, run["id"])

    seen = client.app.state.c4.seen
    assert seen["design_version"] == design
    assert seen["node_ids"], "the stage was handed no graph at all"
    assert "e-invoice" not in seen["node_ids"], "the stage read a design newer than the code"
