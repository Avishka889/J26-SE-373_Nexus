"""How the orchestrator reaches Component 4.

The same seam the other three have: one protocol, an in process implementation
and an HTTP one, chosen by configuration, with contract types crossing the
boundary either way. Files travel in the request rather than as a workspace
path, because the orchestrator prunes its workspaces and a service on another
host could not follow a path anyway.

Two words cross this seam that the component raises. `NotBuilt` is a stage that
does not exist yet: it fails the stage, because a skip would say "nothing to do"
when the truth is "nothing done yet". `NotApplicable` is a stage with nothing to
do on this target, such as staging without a Docker daemon: it becomes
`StageNotApplicable`, which the graph records as a skip. C3's client turned its
not-built error into a skip; this one keeps the two apart.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx
from sdlc_contracts import (
    ApiContract,
    ArchitectureGraph,
    ChangelogReport,
    DependencyUpdates,
    DeployPlan,
    FeedbackReport,
    ImpactReport,
    ManifestRow,
    MonitoringReport,
    PipelineConfig,
    ReleaseCandidate,
    RiskReport,
    RollbackPlan,
    VerifiedRelease,
)

from .c1 import StageOutcome
from .c3 import StageNotApplicable
from .thinking import Levelled, thinking_sent

#: A staging build installs, tests and boots a candidate in a container, which on
#: a cold cache is minutes; the other stages are seconds to a minute.
STAGE_TIMEOUT_SECONDS = 1200.0


@dataclass(frozen=True)
class UpdatesOutcome:
    """What detection produced: the report, and the release note texts it read.

    The texts are stored among the deployment files, because the changelog check
    has to run against exactly the text the model was shown.
    """

    report: DependencyUpdates
    texts: dict[str, str]
    summary: str
    notes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PipelineOutcome:
    """What pipeline generation produced: the validated config, the plan, the files."""

    config: PipelineConfig
    plan: DeployPlan | None
    files: dict[str, str]
    summary: str
    notes: dict[str, Any] = field(default_factory=dict)


class C4Client(Protocol):
    """The stage calls Component 4 answers.

    Per stage, for C1's reason: each is a stage a reader watches move, and a
    crash should cost the stage that was running rather than the run.
    """

    #: What produced the artefacts, for the record on a run.
    model: str

    async def detect_updates(
        self,
        files: dict[str, str],
        *,
        target: str,
        version: int,
        code_version: int,
        test_version: int,
        packages: list[str] | None = None,
        github_token: str | None = None,
    ) -> UpdatesOutcome: ...

    async def analyse_changelogs(
        self, updates: DependencyUpdates, notes: dict[str, str], *, version: int
    ) -> StageOutcome[ChangelogReport]: ...

    async def analyse_impact(
        self,
        files: dict[str, str],
        updates: DependencyUpdates,
        changelog: ChangelogReport | None,
        *,
        graph: ArchitectureGraph | None,
        contract: ApiContract | None,
        manifest: list[ManifestRow],
        version: int,
        code_version: int,
        design_version: int | None,
    ) -> StageOutcome[ImpactReport]: ...

    async def assess_risk(
        self,
        updates: DependencyUpdates,
        changelog: ChangelogReport | None,
        impact: ImpactReport | None,
        *,
        version: int,
    ) -> StageOutcome[RiskReport]: ...

    async def generate_pipeline(
        self,
        files: dict[str, str],
        updates: DependencyUpdates,
        risk: RiskReport,
        *,
        stack_id: str,
        contract: ApiContract | None,
        release_target: str,
        included: list[str],
        settings: dict[str, Any],
        version: int,
        code_version: int,
    ) -> PipelineOutcome: ...

    async def verify_candidate(
        self,
        files: dict[str, str],
        layer: dict[str, str],
        *,
        candidate_hash: str,
        included: list[str],
        excluded: list[dict[str, str]],
        version: int,
        code_version: int,
        updates: DependencyUpdates | None = None,
        settings: dict[str, Any] | None = None,
    ) -> StageOutcome[ReleaseCandidate]: ...

    async def plan_rollback(
        self,
        candidate: ReleaseCandidate,
        risk: RiskReport,
        previous: VerifiedRelease | None,
        *,
        release_target: str,
        version: int,
        database: bool = False,
    ) -> StageOutcome[RollbackPlan]: ...

    async def summarise_feedback(
        self,
        monitoring: MonitoringReport,
        risk: RiskReport | None,
        impact: ImpactReport | None,
        *,
        project_id: str,
        deploy_version: int,
        fault_injected: str | None = None,
    ) -> StageOutcome[FeedbackReport]: ...

    def targets(self) -> list[dict[str, str]]: ...


def _outcome[T](answer: Any) -> StageOutcome[T]:
    return StageOutcome(artefact=answer.artefact, summary=answer.summary, notes=answer.notes)


class InProcessC4:
    """The component, imported and called directly."""

    def __init__(self, model: str, *, cache_dir: str | None = None, thinking: str = "off") -> None:
        try:
            from c4.agents import settings_for
            from c4.service import C4
        except ModuleNotFoundError as exc:
            if (exc.name or "").split(".")[0] != "c4":
                raise
            raise RuntimeError(
                "C4_MODE is 'inprocess' but the component is not installed. "
                "Install the sdlc-c4 package, or set C4_MODE=http and C4_BASE_URL."
            ) from exc
        # One component per thinking level, as C1's client keeps them (3B).
        self._levels = Levelled(
            lambda level: C4(model, cache_dir=cache_dir, thinking=level), thinking, opens=False
        )
        self._settings_for = settings_for
        self.model = model
        #: The configured level, which a run uses where its account chose none.
        self.level = thinking
        # What every agent's request says about thinking, as C1's client reads it.
        self.thinking = self.thinking_for(thinking)

    @property
    def _component(self) -> Any:
        """The component at the configured level."""
        return self._levels.configured

    def thinking_for(self, level: str) -> str:
        """What this component's requests say about thinking at a level, as a run records it."""
        return thinking_sent(self._settings_for(self.model, thinking=level))

    @staticmethod
    @asynccontextmanager
    async def _translating() -> AsyncIterator[None]:
        """Turn "nothing to do here" into the seam's word for it, and only that."""
        from c4.service import NotApplicable

        try:
            yield
        except NotApplicable as skip:
            raise StageNotApplicable(skip.reason) from skip

    async def detect_updates(
        self,
        files: dict[str, str],
        *,
        target: str,
        version: int,
        code_version: int,
        test_version: int,
        packages: list[str] | None = None,
        github_token: str | None = None,
    ) -> UpdatesOutcome:
        async with self._translating():
            answer = await (await self._levels.current()).detect_updates(
                files,
                target=target,
                version=version,
                code_version=code_version,
                test_version=test_version,
                packages=packages,
                github_token=github_token,
            )
        texts = dict(answer.notes.pop("texts", {}))
        return UpdatesOutcome(
            report=answer.artefact, texts=texts, summary=answer.summary, notes=answer.notes
        )

    async def analyse_changelogs(
        self, updates: DependencyUpdates, notes: dict[str, str], *, version: int
    ) -> StageOutcome[ChangelogReport]:
        async with self._translating():
            answer = await (await self._levels.current()).analyse_changelogs(
                updates, notes, version=version
            )
        return _outcome(answer)

    async def analyse_impact(
        self,
        files: dict[str, str],
        updates: DependencyUpdates,
        changelog: ChangelogReport | None,
        *,
        graph: ArchitectureGraph | None,
        contract: ApiContract | None,
        manifest: list[ManifestRow],
        version: int,
        code_version: int,
        design_version: int | None,
    ) -> StageOutcome[ImpactReport]:
        async with self._translating():
            answer = await (await self._levels.current()).analyse_impact(
                files,
                updates,
                changelog,
                graph=graph,
                contract=contract,
                manifest=manifest,
                version=version,
                code_version=code_version,
                design_version=design_version,
            )
        return _outcome(answer)

    async def assess_risk(
        self,
        updates: DependencyUpdates,
        changelog: ChangelogReport | None,
        impact: ImpactReport | None,
        *,
        version: int,
    ) -> StageOutcome[RiskReport]:
        async with self._translating():
            answer = await (await self._levels.current()).assess_risk(
                updates, changelog, impact, version=version
            )
        return _outcome(answer)

    async def generate_pipeline(
        self,
        files: dict[str, str],
        updates: DependencyUpdates,
        risk: RiskReport,
        *,
        stack_id: str,
        contract: ApiContract | None,
        release_target: str,
        included: list[str],
        settings: dict[str, Any],
        version: int,
        code_version: int,
    ) -> PipelineOutcome:
        async with self._translating():
            answer = await (await self._levels.current()).generate_pipeline(
                files,
                updates,
                risk,
                stack_id=stack_id,
                contract=contract,
                release_target=release_target,
                included=included,
                settings=settings,
                version=version,
                code_version=code_version,
            )
        plan = answer.notes.pop("plan", None)
        layer = dict(answer.notes.pop("files", {}))
        return PipelineOutcome(
            config=answer.artefact,
            plan=DeployPlan.model_validate(plan) if isinstance(plan, dict) else plan,
            files=layer,
            summary=answer.summary,
            notes=answer.notes,
        )

    async def verify_candidate(
        self,
        files: dict[str, str],
        layer: dict[str, str],
        *,
        candidate_hash: str,
        included: list[str],
        excluded: list[dict[str, str]],
        version: int,
        code_version: int,
        updates: DependencyUpdates | None = None,
        settings: dict[str, Any] | None = None,
    ) -> StageOutcome[ReleaseCandidate]:
        async with self._translating():
            answer = await (await self._levels.current()).verify_candidate(
                files,
                layer,
                candidate_hash=candidate_hash,
                included=included,
                excluded=excluded,
                version=version,
                code_version=code_version,
                updates=updates,
                settings=settings,
            )
        return _outcome(answer)

    async def plan_rollback(
        self,
        candidate: ReleaseCandidate,
        risk: RiskReport,
        previous: VerifiedRelease | None,
        *,
        release_target: str,
        version: int,
        database: bool = False,
    ) -> StageOutcome[RollbackPlan]:
        async with self._translating():
            answer = await (await self._levels.current()).plan_rollback(
                candidate,
                risk,
                previous,
                release_target=release_target,
                version=version,
                database=database,
            )
        return _outcome(answer)

    async def summarise_feedback(
        self,
        monitoring: MonitoringReport,
        risk: RiskReport | None,
        impact: ImpactReport | None,
        *,
        project_id: str,
        deploy_version: int,
        fault_injected: str | None = None,
    ) -> StageOutcome[FeedbackReport]:
        async with self._translating():
            answer = await (await self._levels.current()).summarise_feedback(
                monitoring,
                risk,
                impact,
                project_id=project_id,
                deploy_version=deploy_version,
                fault_injected=fault_injected,
            )
        return _outcome(answer)

    def targets(self) -> list[dict[str, str]]:
        return self._component.targets()


class HttpC4:
    """The component, over the wire.

    Every response is validated into its contract type on arrival, so a service
    answering the wrong shape is caught at the boundary it crossed. A 409 that
    says `notApplicable` comes back as the same skip the in process client
    raises; a 501 is a stage the service has not built, and fails like one.
    """

    def __init__(self, base_url: str, *, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self.model = f"whatever {self._base_url} is running"
        self._client = client

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        client = self._client or httpx.AsyncClient(timeout=STAGE_TIMEOUT_SECONDS)
        try:
            response = await client.post(f"{self._base_url}{path}", json=body)
        finally:
            if self._client is None:
                await client.aclose()
        if response.status_code == 409 and response.json().get("notApplicable"):
            raise StageNotApplicable(str(response.json().get("detail", "")))
        if response.status_code == 501:
            raise RuntimeError(str(response.json().get("detail", "not built")))
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _dump(value: Any) -> Any:
        return (
            value.model_dump(by_alias=True, mode="json") if hasattr(value, "model_dump") else value
        )

    async def detect_updates(
        self,
        files: dict[str, str],
        *,
        target: str,
        version: int,
        code_version: int,
        test_version: int,
        packages: list[str] | None = None,
        github_token: str | None = None,
    ) -> UpdatesOutcome:
        payload = await self._post(
            "/stages/dependency-updates",
            {
                "files": files,
                "target": target,
                "version": version,
                "codeVersion": code_version,
                "testVersion": test_version,
                "packages": packages,
                "githubToken": github_token,
            },
        )
        notes = dict(payload.get("notes") or {})
        texts = dict(notes.pop("texts", {}))
        return UpdatesOutcome(
            report=DependencyUpdates.model_validate(payload["artefact"]),
            texts=texts,
            summary=payload["summary"],
            notes=notes,
        )

    async def analyse_changelogs(
        self, updates: DependencyUpdates, notes: dict[str, str], *, version: int
    ) -> StageOutcome[ChangelogReport]:
        payload = await self._post(
            "/stages/changelog-analysis",
            {"updates": self._dump(updates), "notes": notes, "version": version},
        )
        return StageOutcome(
            artefact=ChangelogReport.model_validate(payload["artefact"]),
            summary=payload["summary"],
            notes=payload.get("notes") or {},
        )

    async def analyse_impact(
        self,
        files: dict[str, str],
        updates: DependencyUpdates,
        changelog: ChangelogReport | None,
        *,
        graph: ArchitectureGraph | None,
        contract: ApiContract | None,
        manifest: list[ManifestRow],
        version: int,
        code_version: int,
        design_version: int | None,
    ) -> StageOutcome[ImpactReport]:
        payload = await self._post(
            "/stages/impact-analysis",
            {
                "files": files,
                "updates": self._dump(updates),
                "changelog": self._dump(changelog),
                "graph": self._dump(graph),
                "contract": self._dump(contract),
                "manifest": [self._dump(row) for row in manifest],
                "version": version,
                "codeVersion": code_version,
                "designVersion": design_version,
            },
        )
        return StageOutcome(
            artefact=ImpactReport.model_validate(payload["artefact"]),
            summary=payload["summary"],
            notes=payload.get("notes") or {},
        )

    async def assess_risk(
        self,
        updates: DependencyUpdates,
        changelog: ChangelogReport | None,
        impact: ImpactReport | None,
        *,
        version: int,
    ) -> StageOutcome[RiskReport]:
        payload = await self._post(
            "/stages/risk-assessment",
            {
                "updates": self._dump(updates),
                "changelog": self._dump(changelog),
                "impact": self._dump(impact),
                "version": version,
            },
        )
        return StageOutcome(
            artefact=RiskReport.model_validate(payload["artefact"]),
            summary=payload["summary"],
            notes=payload.get("notes") or {},
        )

    async def generate_pipeline(
        self,
        files: dict[str, str],
        updates: DependencyUpdates,
        risk: RiskReport,
        *,
        stack_id: str,
        contract: ApiContract | None,
        release_target: str,
        included: list[str],
        settings: dict[str, Any],
        version: int,
        code_version: int,
    ) -> PipelineOutcome:
        payload = await self._post(
            "/stages/pipeline-generation",
            {
                "files": files,
                "updates": self._dump(updates),
                "risk": self._dump(risk),
                "stackId": stack_id,
                "contract": self._dump(contract),
                "releaseTarget": release_target,
                "included": included,
                "settings": settings,
                "version": version,
                "codeVersion": code_version,
            },
        )
        notes = dict(payload.get("notes") or {})
        plan = notes.pop("plan", None)
        layer = dict(notes.pop("files", {}))
        return PipelineOutcome(
            config=PipelineConfig.model_validate(payload["artefact"]),
            plan=DeployPlan.model_validate(plan) if plan else None,
            files=layer,
            summary=payload["summary"],
            notes=notes,
        )

    async def verify_candidate(
        self,
        files: dict[str, str],
        layer: dict[str, str],
        *,
        candidate_hash: str,
        included: list[str],
        excluded: list[dict[str, str]],
        version: int,
        code_version: int,
        updates: DependencyUpdates | None = None,
        settings: dict[str, Any] | None = None,
    ) -> StageOutcome[ReleaseCandidate]:
        payload = await self._post(
            "/stages/staging-verification",
            {
                "files": files,
                "layer": layer,
                "candidateHash": candidate_hash,
                "included": included,
                "excluded": excluded,
                "version": version,
                "codeVersion": code_version,
                "updates": self._dump(updates),
                "settings": settings or {},
            },
        )
        return StageOutcome(
            artefact=ReleaseCandidate.model_validate(payload["artefact"]),
            summary=payload["summary"],
            notes=payload.get("notes") or {},
        )

    async def plan_rollback(
        self,
        candidate: ReleaseCandidate,
        risk: RiskReport,
        previous: VerifiedRelease | None,
        *,
        release_target: str,
        version: int,
        database: bool = False,
    ) -> StageOutcome[RollbackPlan]:
        payload = await self._post(
            "/stages/rollback-planning",
            {
                "candidate": self._dump(candidate),
                "risk": self._dump(risk),
                "previous": self._dump(previous),
                "releaseTarget": release_target,
                "version": version,
                "database": database,
            },
        )
        return StageOutcome(
            artefact=RollbackPlan.model_validate(payload["artefact"]),
            summary=payload["summary"],
            notes=payload.get("notes") or {},
        )

    async def summarise_feedback(
        self,
        monitoring: MonitoringReport,
        risk: RiskReport | None,
        impact: ImpactReport | None,
        *,
        project_id: str,
        deploy_version: int,
        fault_injected: str | None = None,
    ) -> StageOutcome[FeedbackReport]:
        payload = await self._post(
            "/stages/feedback",
            {
                "monitoring": self._dump(monitoring),
                "risk": self._dump(risk),
                "impact": self._dump(impact),
                "projectId": project_id,
                "deployVersion": deploy_version,
                "faultInjected": fault_injected,
            },
        )
        return StageOutcome(
            artefact=FeedbackReport.model_validate(payload["artefact"]),
            summary=payload["summary"],
            notes=payload.get("notes") or {},
        )

    def targets(self) -> list[dict[str, str]]:
        return [{"id": "generated", "label": "The generated application", "note": ""}]


def make_c4_client(
    mode: str,
    *,
    model: str,
    base_url: str,
    cache_dir: str | None = None,
    thinking: str = "off",
) -> C4Client:
    if mode == "http":
        return HttpC4(base_url)
    return InProcessC4(model, cache_dir=cache_dir, thinking=thinking)
