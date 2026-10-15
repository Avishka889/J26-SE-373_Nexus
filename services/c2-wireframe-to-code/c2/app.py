"""Component 2 as a service, one endpoint per stage.

Transport only, exactly like C1's app: every endpoint validates its input
into contract types, calls the one method, and returns the artefact, the
summary and the notes. The two code stages return the generated files and
their manifest instead of a single artefact, because files are what they
produce; the snapshot never carries bodies, but this internal boundary does,
since the orchestrator has to store what was generated.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from pydantic import Field
from sdlc_contracts import (
    ApiContract,
    ArchitectureGraph,
    ArchitectureRecommendation,
    EarlierPage,
    ParsedRequirement,
    RepositoryPointer,
    SprintPlan,
    SprintScope,
    WireframesArtefact,
)
from sdlc_contracts.wire import WireModel

from .codegen.manifest import FileSet
from .service import C2, Arm, StageResult

DEFAULT_MODEL = "google:gemini-2.5-pro"


class ScopeIn(WireModel):
    sprint: SprintPlan
    wireframes: WireframesArtefact


class StackIn(WireModel):
    graph: ArchitectureGraph
    recommendation: ArchitectureRecommendation | None = None


class ContractIn(WireModel):
    version: int = Field(ge=1)
    graph: ArchitectureGraph
    wireframes: WireframesArtefact
    scope: SprintScope
    arm: Arm = "rule"
    #: The acceptance criteria of the stories in the build, read for field rules.
    criteria: list[str] = Field(default_factory=list)


class FrontendIn(WireModel):
    project_name: str = Field(min_length=1)
    contract: ApiContract
    wireframes: WireframesArtefact
    scope: SprintScope
    design_version: int = Field(ge=1)
    arm: str = "rule"
    fill: bool = False
    #: What the design's requirements say, which the page writer reads.
    requirements: list[ParsedRequirement] = Field(default_factory=list)
    #: What the previous generation made of each page, kept while unchanged.
    earlier: list[EarlierPage] = Field(default_factory=list)


class BackendIn(WireModel):
    contract: ApiContract
    #: The contract arm the run chose, recorded per manifest row.
    arm: str = "rule"
    fill: bool = False


class AgreementIn(WireModel):
    contract: ApiContract
    sources: dict[str, str]


class BuildIn(WireModel):
    sources: dict[str, str]


class PushIn(WireModel):
    files: dict[str, str]
    name: str = Field(min_length=1)
    #: The decrypted token, or None when the owner has no connection. It
    #: crosses this internal boundary and nothing else: never logged, never
    #: echoed back.
    token: str | None = None
    message: str = Field(min_length=1)
    #: The version's own branch; None moves the default branch, as before.
    branch: str | None = None


class LandIn(WireModel):
    pointer: RepositoryPointer
    token: str | None = None
    message: str = Field(min_length=1)


def _reply(result: StageResult[Any]) -> dict[str, Any]:
    """The one response shape every artefact stage answers with."""
    return {
        "artefact": result.artefact.model_dump(by_alias=True, mode="json"),
        "summary": result.summary,
        "notes": result.notes,
    }


def _files_reply(result: StageResult[FileSet], arm: str) -> dict[str, Any]:
    """The code stages: file bodies for storage, manifest rows for the record."""
    return {
        "files": {generated.path: generated.content for generated in result.artefact.files},
        "manifest": [
            row.model_dump(by_alias=True, mode="json") for row in result.artefact.manifest(arm)
        ],
        "summary": result.summary,
        "notes": result.notes,
    }


def create_app(component: C2 | None = None) -> FastAPI:
    """The service. A component can be passed in, which is how tests drive it."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.c2 = component or C2(
            os.environ.get("C2_MODEL", DEFAULT_MODEL),
            # The same switch the orchestrator reads, off unless configured.
            thinking=os.environ.get("C2_THINKING", "").strip() or "off",
        )
        yield

    app = FastAPI(title="Component 2: Wireframe to Code", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/stages/sprint-scope")
    async def sprint_scope(body: ScopeIn) -> dict[str, Any]:
        return _reply(await app.state.c2.derive_scope(body.sprint, body.wireframes))

    @app.post("/stages/tech-stack")
    async def tech_stack(body: StackIn) -> dict[str, Any]:
        return _reply(await app.state.c2.propose_stack(body.graph, body.recommendation))

    @app.post("/stages/api-contract")
    async def api_contract(body: ContractIn) -> dict[str, Any]:
        return _reply(
            await app.state.c2.infer_contract(
                body.version,
                body.graph,
                body.wireframes,
                body.scope,
                arm=body.arm,
                criteria=body.criteria,
            )
        )

    @app.post("/stages/frontend-code")
    async def frontend_code(body: FrontendIn) -> dict[str, Any]:
        result = await app.state.c2.generate_frontend(
            body.project_name,
            body.contract,
            body.wireframes,
            body.scope,
            design_version=body.design_version,
            arm=body.arm,
            fill=body.fill,
            requirements=body.requirements,
            earlier=body.earlier,
        )
        return _files_reply(result, body.arm)

    @app.post("/stages/backend-code")
    async def backend_code(body: BackendIn) -> dict[str, Any]:
        result = await app.state.c2.generate_backend(body.contract, fill=body.fill)
        return _files_reply(result, body.arm)

    @app.post("/stages/contract-agreement")
    async def contract_agreement(body: AgreementIn) -> dict[str, Any]:
        return _reply(await app.state.c2.check_agreement(body.contract, body.sources))

    @app.post("/stages/build")
    async def build(body: BuildIn) -> dict[str, Any]:
        return _reply(await app.state.c2.build(body.sources))

    # Not under /stages: the push is part of the build stage's work, separated
    # because it needs the connection's token and the build does not.
    @app.post("/push")
    async def push(body: PushIn) -> dict[str, Any]:
        result = await app.state.c2.push(
            body.files, name=body.name, token=body.token, message=body.message, branch=body.branch
        )
        return {
            "pointer": (
                result.pointer.model_dump(by_alias=True, mode="json") if result.pointer else None
            ),
            "reason": result.reason,
        }

    @app.post("/land")
    async def land_version(body: LandIn) -> dict[str, Any]:
        result = await app.state.c2.land(body.pointer, token=body.token, message=body.message)
        return {"commitSha": result.commit_sha, "how": result.how, "reason": result.reason}

    return app
