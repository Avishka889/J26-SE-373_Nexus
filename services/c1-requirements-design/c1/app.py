"""Component 1 as a service, one endpoint per stage.

The other side of the boundary the orchestrator's HTTP client talks to. It exists
so that running C1 in its own process is a configuration change rather than a
rewrite, and so the split appears in compose and in the architecture diagram as
something that works rather than something that is claimed.

There is deliberately nothing here but transport. Every endpoint validates its
input into contract types, calls the one method, and returns the artefact, the
summary and the notes. No stage logic, no storage, no idea what a run is: an
endpoint that started making decisions would be a second implementation of the
component drifting against the first.

The agents are built once at startup for the same reason they are in process:
each holds a connection to the provider.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from pydantic import Field
from sdlc_contracts import ArchitectureGraph, ParsedRequirement
from sdlc_contracts.wire import WireModel

from .service import C1, StageResult

DEFAULT_MODEL = "anthropic:claude-sonnet-5"


class RequirementsIn(WireModel):
    text: str = Field(min_length=1)


class GraphIn(WireModel):
    requirements: list[ParsedRequirement]
    text: str = ""


class RecommendationIn(WireModel):
    requirements: list[ParsedRequirement]
    graph: ArchitectureGraph


class UmlIn(WireModel):
    graph: ArchitectureGraph


class WireframesIn(WireModel):
    graph: ArchitectureGraph
    requirement_ids: list[str] = Field(default_factory=list)
    version: str = "v1"
    #: What each requirement says, which the drawer reads beside the graph.
    requirements: list[ParsedRequirement] = Field(default_factory=list)


class SprintIn(WireModel):
    requirements: list[ParsedRequirement]
    graph: ArchitectureGraph


class NamingIn(WireModel):
    text: str


def _reply(result: StageResult[Any]) -> dict[str, Any]:
    """The one response shape every stage answers with."""
    return {
        "artefact": result.artefact.model_dump(by_alias=True, mode="json"),
        "summary": result.summary,
        "notes": result.notes,
    }


def create_app(component: C1 | None = None) -> FastAPI:
    """The service. A component can be passed in, which is how tests drive it."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Built once, because every agent holds a provider connection.
        app.state.c1 = component or C1(
            os.environ.get("C1_MODEL", DEFAULT_MODEL),
            # The same switch the orchestrator reads, off unless configured.
            thinking=os.environ.get("C1_THINKING", "").strip() or "off",
        )
        yield

    app = FastAPI(title="Component 1: Requirements and Design", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/stages/requirements")
    async def requirements(body: RequirementsIn) -> dict[str, Any]:
        return _reply(await app.state.c1.parse_requirements(body.text))

    @app.post("/stages/graph")
    async def graph(body: GraphIn) -> dict[str, Any]:
        return _reply(await app.state.c1.build_graph(body.requirements, text=body.text))

    @app.post("/stages/recommendation")
    async def recommendation(body: RecommendationIn) -> dict[str, Any]:
        return _reply(await app.state.c1.recommend(body.requirements, body.graph))

    @app.post("/stages/uml")
    async def uml(body: UmlIn) -> dict[str, Any]:
        return _reply(await app.state.c1.write_uml(body.graph))

    @app.post("/stages/wireframes")
    async def wireframes(body: WireframesIn) -> dict[str, Any]:
        return _reply(
            await app.state.c1.draw_wireframes(
                body.graph,
                requirement_ids=body.requirement_ids,
                version=body.version,
                requirements=body.requirements,
            )
        )

    @app.post("/stages/sprint")
    async def sprint(body: SprintIn) -> dict[str, Any]:
        return _reply(await app.state.c1.plan_sprint(body.requirements, body.graph))

    # Not under /stages: nothing is stored and no stage row moves. A reader does
    # wait on it, because the orchestrator calls this before the first stage of a
    # project's first run starts; it bounds the call at its end, and keeps the
    # provisional name when the bound is hit.
    @app.post("/naming")
    async def naming(body: NamingIn) -> dict[str, str]:
        return {"title": await app.state.c1.name_project(body.text)}

    return app
