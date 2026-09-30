"""Component 4 as a service, one endpoint per stage.

Transport only, like C1's and C2's apps: every endpoint validates its input into
contract types, calls the one method, and answers with the artefact, the summary
and the notes. C3 never had one of these, so its http mode posted to routes
nothing served; this component's http mode is real from the first commit.

Two answers are not errors in the usual sense and say so by status: a stage not
built yet answers 501 with the phase it lands in, and a stage with nothing to do
on this target answers 409 with `notApplicable` and the reason, which the
orchestrator's client turns back into a skip.
"""

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sdlc_contracts import (
    ApiContract,
    ArchitectureGraph,
    ChangelogReport,
    DependencyUpdates,
    ImpactReport,
    ManifestRow,
    MonitoringReport,
    ReleaseCandidate,
    RiskReport,
    VerifiedRelease,
)
from sdlc_contracts.wire import WireModel

from .service import C4, NotApplicable, NotBuilt, StageAnswer

DEFAULT_MODEL = "deepseek:deepseek-flash"


class DetectIn(WireModel):
    files: dict[str, str]
    target: str = Field(min_length=1)
    version: int = Field(ge=1)
    code_version: int = Field(ge=1)
    test_version: int = Field(ge=1)
    packages: list[str] | None = None
    #: Decrypted by the orchestrator for the release notes lookup. It crosses
    #: this internal boundary and nothing else: never logged, never echoed.
    github_token: str | None = None


class ChangelogIn(WireModel):
    updates: DependencyUpdates
    notes: dict[str, str]
    version: int = Field(ge=1)


class ImpactIn(WireModel):
    files: dict[str, str]
    updates: DependencyUpdates
    changelog: ChangelogReport | None = None
    graph: ArchitectureGraph | None = None
    contract: ApiContract | None = None
    manifest: list[ManifestRow] = Field(default_factory=list)
    version: int = Field(ge=1)
    code_version: int = Field(ge=1)
    design_version: int | None = None


class RiskIn(WireModel):
    updates: DependencyUpdates
    changelog: ChangelogReport | None = None
    impact: ImpactReport | None = None
    version: int = Field(ge=1)


class PipelineIn(WireModel):
    files: dict[str, str]
    updates: DependencyUpdates
    risk: RiskReport
    stack_id: str = Field(min_length=1)
    contract: ApiContract | None = None
    release_target: str = Field(min_length=1)
    included: list[str] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)
    version: int = Field(ge=1)
    code_version: int = Field(ge=1)


class CandidateIn(WireModel):
    files: dict[str, str]
    layer: dict[str, str]
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    included: list[str] = Field(default_factory=list)
    excluded: list[dict[str, str]] = Field(default_factory=list)
    version: int = Field(ge=1)
    code_version: int = Field(ge=1)
    updates: DependencyUpdates | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class RollbackIn(WireModel):
    candidate: ReleaseCandidate
    risk: RiskReport
    previous: VerifiedRelease | None = None
    release_target: str = Field(min_length=1)
    version: int = Field(ge=1)
    #: The project has its own database where this release goes.
    database: bool = False


class FeedbackIn(WireModel):
    monitoring: MonitoringReport
    risk: RiskReport | None = None
    impact: ImpactReport | None = None
    project_id: str = Field(min_length=1)
    deploy_version: int = Field(ge=1)
    #: The controlled failure injected into the watched release, when one was.
    fault_injected: str | None = None


def _reply(answer: StageAnswer) -> dict[str, Any]:
    """The one response shape every stage answers with."""
    artefact = answer.artefact
    return {
        "artefact": artefact.model_dump(by_alias=True, mode="json")
        if hasattr(artefact, "model_dump")
        else artefact,
        "summary": answer.summary,
        "notes": answer.notes,
    }


def create_app(component: C4 | None = None) -> FastAPI:
    """The service. A component can be passed in, which is how tests drive it."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.c4 = component or C4(
            os.environ.get("C4_MODEL", DEFAULT_MODEL),
            cache_dir=os.environ.get("C4_CACHE_DIR") or None,
            # The same switch the orchestrator reads, off unless configured.
            thinking=os.environ.get("C4_THINKING", "").strip() or "off",
        )
        yield

    app = FastAPI(title="Component 4: Deployment and Dependency Evolution", lifespan=lifespan)

    @app.exception_handler(NotBuilt)
    async def not_built(_: Request, error: NotBuilt) -> JSONResponse:
        return JSONResponse(
            status_code=501,
            content={"detail": str(error), "stage": error.stage, "phase": error.phase},
        )

    @app.exception_handler(NotApplicable)
    async def not_applicable(_: Request, error: NotApplicable) -> JSONResponse:
        return JSONResponse(
            status_code=409,
            content={"detail": error.reason, "stage": error.stage, "notApplicable": True},
        )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "model": app.state.c4.model}

    @app.get("/targets")
    async def targets() -> list[dict[str, str]]:
        return app.state.c4.targets()

    @app.post("/stages/dependency-updates")
    async def dependency_updates(body: DetectIn) -> dict[str, Any]:
        return _reply(
            await app.state.c4.detect_updates(
                body.files,
                target=body.target,
                version=body.version,
                code_version=body.code_version,
                test_version=body.test_version,
                packages=body.packages,
                github_token=body.github_token,
            )
        )

    @app.post("/stages/changelog-analysis")
    async def changelog_analysis(body: ChangelogIn) -> dict[str, Any]:
        return _reply(
            await app.state.c4.analyse_changelogs(body.updates, body.notes, version=body.version)
        )

    @app.post("/stages/impact-analysis")
    async def impact_analysis(body: ImpactIn) -> dict[str, Any]:
        return _reply(
            await app.state.c4.analyse_impact(
                body.files,
                body.updates,
                body.changelog,
                graph=body.graph,
                contract=body.contract,
                manifest=body.manifest,
                version=body.version,
                code_version=body.code_version,
                design_version=body.design_version,
            )
        )

    @app.post("/stages/risk-assessment")
    async def risk_assessment(body: RiskIn) -> dict[str, Any]:
        return _reply(
            await app.state.c4.assess_risk(
                body.updates, body.changelog, body.impact, version=body.version
            )
        )

    @app.post("/stages/pipeline-generation")
    async def pipeline_generation(body: PipelineIn) -> dict[str, Any]:
        return _reply(
            await app.state.c4.generate_pipeline(
                body.files,
                body.updates,
                body.risk,
                stack_id=body.stack_id,
                contract=body.contract,
                release_target=body.release_target,
                included=body.included,
                settings=body.settings,
                version=body.version,
                code_version=body.code_version,
            )
        )

    @app.post("/stages/staging-verification")
    async def staging_verification(body: CandidateIn) -> dict[str, Any]:
        return _reply(
            await app.state.c4.verify_candidate(
                body.files,
                body.layer,
                candidate_hash=body.candidate_hash,
                included=body.included,
                excluded=body.excluded,
                version=body.version,
                code_version=body.code_version,
                updates=body.updates,
                settings=body.settings,
            )
        )

    @app.post("/stages/rollback-planning")
    async def rollback_planning(body: RollbackIn) -> dict[str, Any]:
        return _reply(
            await app.state.c4.plan_rollback(
                body.candidate,
                body.risk,
                body.previous,
                release_target=body.release_target,
                version=body.version,
                database=body.database,
            )
        )

    @app.post("/stages/feedback")
    async def feedback(body: FeedbackIn) -> dict[str, Any]:
        return _reply(
            await app.state.c4.summarise_feedback(
                body.monitoring,
                body.risk,
                body.impact,
                project_id=body.project_id,
                deploy_version=body.deploy_version,
                fault_injected=body.fault_injected,
            )
        )

    return app
