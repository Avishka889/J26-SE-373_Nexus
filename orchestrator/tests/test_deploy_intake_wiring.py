"""The real C4 stages, driven through the orchestrator's in process client.

The spine test uses a canned component. This one uses the real one for the
stages that are built, with its registries answered from recorded shapes, its
lockfile pin stubbed and its model scripted, and proves the chain from the
registry to the code:

- detection runs on the code version the approved tests measured, and what it
  found lands on the deploy axis with the baseline lockfile and the release
  notes stored as deployment files;
- the changelog stage reads those stored notes back, byte for byte, and
  verifies the model's claim against them;
- the impact stage takes the claim's symbol to the stored code and finds, and
  reads back, the line that uses it;
- the risk stage combines the three votes by the rule;
- pipeline generation reads the project's layout, reports a project no template
  fits as unsupported (FR14), and for the platform's own generated app stores
  the configuration, the plan and the layer, each file under the stage that
  wrote it;
- staging verification builds exactly that stored candidate, with Docker
  scripted here, and records the fingerprint the container served.
"""

import json
from collections.abc import AsyncIterator
from pathlib import Path

import c4
import httpx
import pytest
from c4.eval.loaders.clients import read_client
from c4.harness.staging import Ran
from c4.intake.lockfile import Pin
from c4.pipeline.candidate import Resolution
from c4.pipeline.validate import validate
from c4.service import C4
from orchestrator.api.deps import DEV_OWNER_ID
from orchestrator.clients.c4 import InProcessC4
from orchestrator.clients.thinking import Levelled
from orchestrator.config import Settings
from orchestrator.db import store
from orchestrator.main import create_app, lifespan_for_tests
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sdlc_contracts import (
    BaselinePin,
    ChangelogReport,
    DependencyUpdates,
    DeployPlan,
    ImpactReport,
    PipelineConfig,
    ReleaseCandidate,
    RiskReport,
)

from .conftest import needs_db
from .test_deployment_spine import _start_deploy_run, _tested
from .test_testing_spine import _advance

pytestmark = needs_db

MANIFESTS = {
    "package.json": json.dumps({"name": "generated-app", "workspaces": ["apps/*"]}),
    "apps/api/package.json": json.dumps(
        {"name": "@app/api", "dependencies": {"express": "^4.21.2"}}, indent=2
    ),
    "apps/api/src/app.ts": (
        'import express from "express";\n'
        "export const app = express();\n"
        'app.del("/items/:id", (req, res) => res.sendStatus(204));\n'
    ),
}

PIN = Pin(
    record=BaselinePin(
        lockfile_path="package-lock.json",
        lockfile_sha256="b" * 64,
        packages=60,
        direct=1,
        resolved_by="npm 10.9.2 install --package-lock-only --ignore-scripts",
    ),
    text='{"lockfileVersion": 3}',
    resolved={"apps/api": {"express": "4.21.2"}},
)


RELEASES = [
    {"tag_name": "v5.1.0", "body": "- Added support for `res.links()` with several `rel` values."},
    {"tag_name": "v5.0.0", "body": "- Removed `app.del()`; use `app.delete()` instead."},
    {"tag_name": "4.21.2", "body": "- Fixed a crash in the router."},
]

REMOVAL = {
    "kind": "removal",
    "symbols": ["app.del"],
    "quote": "Removed `app.del()`; use `app.delete()` instead.",
    "version": "5.0.0",
}


def _registry() -> httpx.MockTransport:
    express = {
        "name": "express",
        "dist-tags": {"latest": "5.1.0"},
        "time": {"4.21.2": "2024-12-05T00:00:00Z", "5.1.0": "2025-03-31T00:00:00Z"},
        "versions": {"4.21.2": {}, "5.1.0": {}},
        "repository": {"type": "git", "url": "git+https://github.com/expressjs/express.git"},
    }

    def answer(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://registry.npmjs.org/express":
            return httpx.Response(200, json=express)
        if request.url.path == "/repos/expressjs/express/releases":
            return httpx.Response(200, json=RELEASES if request.url.params["page"] == "1" else [])
        return httpx.Response(404)

    return httpx.MockTransport(answer)


def _model() -> FunctionModel:
    def respond(_: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[
                ToolCallPart(
                    info.output_tools[0].name, {"claims": [REMOVAL], "stated_level": "medium"}
                )
            ]
        )

    return FunctionModel(respond)


class ScriptedDocker:
    """Builds succeed, and the container serves the fingerprint its build context
    held, as a real one would; the component's own tests build for real."""

    def __init__(self) -> None:
        self.release = ""

    def run(self, argv: list[str], timeout: float) -> Ran:
        if argv[:2] == ["docker", "build"] and "--target" not in argv:
            self.release = (Path(argv[-1]) / "apps/web/public/release.json").read_text()
        if argv[:2] == ["docker", "port"]:
            return Ran(0, "127.0.0.1:61000\n", 0.1)
        if argv[:3] == ["docker", "image", "inspect"]:
            return Ran(0, "sha256:" + "e" * 64, 0.1)
        return Ran(0, "c0ffee\n" if argv[:2] == ["docker", "run"] else "ok", 1.0)

    def probe(self, url: str, headers: dict[str, str], timeout: float):
        if url.endswith("/release.json"):
            return 200, "application/json", self.release
        kind = headers.get("Accept", "application/json")
        return 200, kind, "[]" if kind == "application/json" else "<!doctype html>"


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, lifespan_factory=lifespan_for_tests)
    docker = ScriptedDocker()
    real = InProcessC4("deepseek:deepseek-flash")
    scripted = C4(
        "deepseek:deepseek-flash",
        http=httpx.AsyncClient(transport=_registry()),
        pinner=lambda files: PIN,
        agent_model=_model(),
        # The candidate's lockfile is the baseline with nothing applied, and the
        # files are checked by everything that needs no Docker; npm and the
        # linters have their own tests in the component.
        resolver=lambda files, updates: Resolution(
            lockfile=files["package-lock.json"], resolved_by="scripted"
        ),
        validator=lambda files: validate(files, docker_reason="not run in the wiring test"),
        runner=docker.run,
        prober=docker.probe,
    )
    # The client keeps one component per thinking level (3B); this one answers
    # at every level, so a run asks the scripted parts whatever its level.
    real._levels = Levelled(lambda level: scripted, real.level, opens=False)
    app.state.c4 = real
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


async def test_the_real_intake_and_changelog_stages_run_on_the_tested_code(client) -> None:
    project_id, code_version, test_version = await _tested(client)
    async with client.app.state.pool.connection() as conn:
        await store.put_code_files(
            conn, project_id, version=code_version, stage_id="backend-code", files=MANIFESTS
        )
    run, deploy_version = await _start_deploy_run(client, project_id, test_version)

    await _advance(client, run["id"])

    async with client.app.state.pool.connection() as conn:
        at = await store.artefacts_at(
            conn,
            project_id,
            version=deploy_version,
            kinds=(
                "dependency-updates",
                "changelog-report",
                "impact-report",
                "risk-report",
                "pipeline-config",
            ),
        )
        stored = await store.deploy_files(
            conn, project_id, version=deploy_version, stage_id="dependency-updates"
        )
        stages = {row["stage_id"]: row for row in await store.stage_states(conn, project_id)}
    report = DependencyUpdates.model_validate(at["dependency-updates"]["body"])
    assert report.code_version == code_version and report.test_version == test_version
    assert [(u.package, u.from_version, u.to_version) for u in report.updates] == [
        ("express", "4.21.2", "5.1.0")
    ]
    assert stored["package-lock.json"] == PIN.text
    assert stages["dependency-updates"]["status"] == "complete"

    # The notes went into the store and came back out as the same bytes: the
    # changelog stage refuses to show a model any text whose hash has moved.
    [ref] = report.updates[0].notes
    assert ref.path in stored and ref.version == "5.1.0"
    changelog = ChangelogReport.model_validate(at["changelog-report"]["body"])
    [analysis] = changelog.per_update
    assert stages["changelog-analysis"]["status"] == "complete"
    assert analysis.windows == ["5.0.0", "5.1.0"]
    assert [(c.kind, c.version) for c in analysis.claims] == [("removal", "5.0.0")]
    assert analysis.vote.level == "high"
    assert analysis.model is not None and analysis.model.stated_level == "medium"

    # The impact stage takes the claim's symbol to the code: the removed `del`
    # is used at app.ts line 3, read back from the stored file.
    impact = ImpactReport.model_validate(at["impact-report"]["body"])
    [usage] = impact.per_update
    assert stages["impact-analysis"]["status"] == "complete"
    assert usage.vote.level == "high"
    assert [(r.symbol, r.span.path, r.span.start_line) for r in usage.references] == [
        ("app.del", "apps/api/src/app.ts", 3)
    ]
    assert [f.path for f in impact.affected_files] == ["apps/api/src/app.ts"]
    assert impact.extraction.files_indexed >= 1

    # The risk stage combines the three: a major by number, a verified removal,
    # and the code's own use of it all say High, so no advisory is needed.
    risk = RiskReport.model_validate(at["risk-report"]["body"])
    [assessed] = risk.assessments
    assert stages["risk-assessment"]["status"] == "complete"
    assert [vote.level for vote in assessed.votes] == ["high", "high", "high"]
    assert assessed.arbitration.final == "high" and not assessed.arbitration.advisory
    assert assessed.affected_files == ["apps/api/src/app.ts"]

    # An API with no start script and no frontend is a layout no template was
    # written for: the stack is reported unsupported with the reason, nothing
    # is generated (FR14), and there is no candidate for staging to build.
    config = PipelineConfig.model_validate(at["pipeline-config"]["body"])
    assert stages["pipeline-generation"]["status"] == "complete"
    assert not config.stack.supported and config.files == []
    assert "layout could not be read" in config.stack.reason
    assert stages["staging-verification"]["status"] == "skipped"


TRACKER = read_client(
    Path(c4.__file__).resolve().parents[1] / "studies" / "clients" / "task-tracker"
)


async def test_the_generated_app_gets_its_pipeline_stored_by_stage(client) -> None:
    project_id, code_version, test_version = await _tested(client)
    async with client.app.state.pool.connection() as conn:
        await store.put_code_files(
            conn, project_id, version=code_version, stage_id="backend-code", files=TRACKER
        )
    run, deploy_version = await _start_deploy_run(client, project_id, test_version)

    await _advance(client, run["id"])

    async with client.app.state.pool.connection() as conn:
        at = await store.artefacts_at(
            conn,
            project_id,
            version=deploy_version,
            kinds=("pipeline-config", "deploy-plan", "release-candidate"),
        )
        layer = await store.deploy_files(
            conn, project_id, version=deploy_version, stage_id="pipeline-generation"
        )
        pinned = await store.deploy_files(
            conn, project_id, version=deploy_version, stage_id="dependency-updates"
        )
        stages = {row["stage_id"]: row for row in await store.stage_states(conn, project_id)}
    config = PipelineConfig.model_validate(at["pipeline-config"]["body"])
    assert stages["pipeline-generation"]["status"] == "complete"
    assert config.stack.supported and config.stack.layout is not None
    assert config.stack.layout.kind == "one-process"
    assert {f.path for f in config.files} >= {"Dockerfile", "render.yaml", "vercel.json"}

    # The plan names this project and the release target the settings default to.
    plan = DeployPlan.model_validate(at["deploy-plan"]["body"])
    assert plan.project_id == project_id and plan.target == "local"
    assert plan.candidate_hash == config.candidate_hash

    # Each stage keeps its own lockfile at the same path: the baseline detection
    # pinned, and the candidate's.
    assert pinned["package-lock.json"] == PIN.text
    assert "package-lock.json" in layer and "Dockerfile" in layer

    # The files route serves the layer by default, and the fingerprint in it is
    # the candidate's hash.
    answer = await client.get(
        f"/projects/{project_id}/deployment/files/apps/web/public/release.json"
    )
    assert answer.status_code == 200
    assert json.loads(answer.json()["content"])["candidateHash"] == config.candidate_hash
    baseline = await client.get(
        f"/projects/{project_id}/deployment/files/package-lock.json",
        params={"stage": "dependency-updates"},
    )
    assert baseline.json()["content"] == PIN.text

    # Staging built exactly the stored candidate: its files hash to the candidate
    # hash, and the container served that hash back.
    candidate = ReleaseCandidate.model_validate(at["release-candidate"]["body"])
    assert stages["staging-verification"]["status"] == "complete"
    assert candidate.candidate_hash == config.candidate_hash == candidate.fingerprint
    assert candidate.image == f"sdlc-c4-{project_id.replace('_', '-')}:v{deploy_version}"
    assert candidate.verified
