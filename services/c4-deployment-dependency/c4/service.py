"""Component 4 as the orchestrator sees it: one method per stage.

Every method takes contracts and plain data and returns a `StageAnswer`, and
none of them reaches a cloud provider, a database or the orchestrator: the
component analyses and generates, and the orchestrator executes. Files arrive in
the request rather than as a workspace path, because the orchestrator prunes its
workspaces and because an HTTP client on another host could not follow a path.

A stage that is not built yet raises `NotBuilt`, naming the phase it lands in,
rather than returning something empty that a reader could take for a result.
A stage that does not apply to this target raises `NotApplicable` with the
reason, which the orchestrator records as a skip: not a failure and not a
completion.
"""

from collections import Counter
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

import httpx
from pydantic_ai.models import Model
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

from .model_use import reports_model_use


class NotBuilt(RuntimeError):
    """A stage that has not been implemented yet, saying which and when.

    Deliberately not a quiet empty result. The reader is told the stage did not
    run, and a run that reaches it fails at that stage with the reason on it.
    """

    def __init__(self, stage: str, phase: str) -> None:
        super().__init__(
            f"{stage} is not built yet: it lands in {phase}. "
            "Nothing was run and nothing was measured."
        )
        self.stage = stage
        self.phase = phase


class NotApplicable(RuntimeError):
    """A stage that has nothing to do on this target, and says why.

    Separate from `NotBuilt` on purpose. C3's client turns its not-built error
    into a skip; here a stage that is not built fails, because a skip would read
    as "nothing to do" when the truth is "nothing done yet".
    """

    def __init__(self, stage: str, reason: str) -> None:
        super().__init__(reason)
        self.stage = stage
        self.reason = reason


class StageAnswer:
    """What a stage produced, in the shape the client passes back.

    The orchestrator has its own type for this and the component does not
    import it: the two sides agree on attribute names and nothing else.
    """

    def __init__(self, artefact: Any, summary: str, notes: dict[str, Any]) -> None:
        self.artefact = artefact
        self.summary = summary
        self.notes = notes


class C4:
    """The component, holding the model string every model call is made with.

    The HTTP client, the cache directory, the lockfile pinner and the model can
    be handed in, which is how the tests answer every registry from recorded
    shapes and every model call from a script, and never reach the network.
    """

    def __init__(
        self,
        model: str,
        *,
        http: httpx.AsyncClient | None = None,
        cache_dir: str | None = None,
        pinner: Callable[[dict[str, str]], Any] | None = None,
        agent_model: Model | None = None,
        roseau: Path | None = None,
        resolver: Callable[..., Any] | None = None,
        validator: Callable[..., Any] | None = None,
        runner: Callable[..., Any] | None = None,
        prober: Callable[..., Any] | None = None,
        thinking: str = "off",
    ) -> None:
        self._model = model
        #: How hard the stages ask the model to think (`agents.THINKING_LEVELS`).
        self.thinking = thinking
        self._http = http
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._pinner = pinner
        #: A scripted model for tests. The configured string is still the one
        #: every report records, so a test reads exactly what a run would.
        self._agent_model = agent_model
        #: Roseau's launcher, when not the installed one.
        self._roseau = roseau
        #: What applies the included updates to the baseline pin, and what
        #: checks the generated files; npm and the pinned linters when not given.
        self._resolver = resolver
        self._validator = validator
        #: What runs Docker and what asks the booted candidate, for staging;
        #: the real ones when not given.
        self._runner = runner
        self._prober = prober

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[httpx.AsyncClient]:
        if self._http is not None:
            yield self._http
            return
        async with httpx.AsyncClient(headers={"User-Agent": "sdlc-platform-c4"}) as client:
            yield client

    @property
    def model(self) -> str:
        return self._model

    @property
    def npm_cache(self) -> Path | None:
        """npm's cache, kept between runs in the service's cache directory.

        The baseline pin and the candidate's resolution both use it, so every
        pin after the first asks the registry only whether what it has is still
        current, rather than downloading it all again. With no cache directory,
        each npm run has a scratch cache of its own, as it always had.
        """
        return self._cache_dir / "npm" if self._cache_dir else None

    def targets(self) -> list[dict[str, str]]:
        """The repositories this component can analyse."""
        return [
            {
                "id": "generated",
                "label": "The generated application",
                "note": "The code version the test review approved.",
            }
        ]

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
    ) -> StageAnswer:
        """FR1 to FR3: the updates the registries offer, and what is known about each."""
        from .intake.cache import Cache
        from .intake.detect import detect, report
        from .intake.fetch import Fetcher
        from .intake.lockfile import pin

        if target != "generated":
            raise NotApplicable(
                "dependency-updates", f"the target {target} is not one this component analyses"
            )
        async with self._client() as client:
            fetcher = Fetcher(client, cache=Cache(self._cache_dir))
            detected = await detect(
                files,
                fetcher=fetcher,
                pinner=self._pinner or partial(pin, cache=self.npm_cache),
                packages=packages,
                token=github_token,
            )
        artefact = report(
            detected,
            fetcher,
            version=version,
            code_version=code_version,
            test_version=test_version,
            target=target,
            generated_at=datetime.now(UTC),
        )
        summary = (
            f"{len(artefact.updates)} update{'s' if len(artefact.updates) != 1 else ''} found, "
            f"{len(artefact.rejected)} could not be analysed, "
            f"{len(artefact.up_to_date)} already up to date"
        )
        return StageAnswer(
            artefact,
            summary,
            {"texts": detected.texts, "questions_asked": len(fetcher.queries)},
        )

    @reports_model_use
    async def analyse_changelogs(
        self,
        updates: DependencyUpdates,
        notes: dict[str, str],
        *,
        version: int,
    ) -> StageAnswer:
        """FR5: claims from the release notes, each quote checked against the notes.

        `notes` is what the detection stage stored, path to text; each update's
        notes are checked against the hashes recorded when they were fetched
        before the model is shown them.
        """
        from .risk.changelog import analyse

        report = await analyse(
            updates,
            notes,
            model=self._model,
            version=version,
            agent_model=self._agent_model,
            thinking=self.thinking,
        )
        asked = [item.model for item in report.per_update if item.model is not None]
        voted = sum(1 for item in report.per_update if item.vote.level is not None)
        count = len(report.per_update)
        summary = (
            f"{count} update{'s' if count != 1 else ''} read: "
            f"{report.claims_verified} claim{'s' if report.claims_verified != 1 else ''} "
            f"verified, {report.claims_refused} refused; {voted} voted and "
            f"{count - voted} abstained"
            + (", stopped at a rate limit" if report.stopped_on_rate_limit else "")
        )
        return StageAnswer(
            report,
            summary,
            {
                "model_calls": len(asked),
                "tokens_in": sum(call.prompt_tokens for call in asked),
                "tokens_out": sum(call.completion_tokens for call in asked),
                "refusal_rate": round(report.refusal_rate, 3),
                "stopped_on_rate_limit": report.stopped_on_rate_limit,
            },
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
    ) -> StageAnswer:
        """FR9 to FR11: the files that use what changed, and the components they are.

        The project is indexed once here, and nowhere else: the risk stage is
        given this stage's report, never the files (NFR2).
        """
        from .impact.stage import analyse
        from .intake.cache import Cache
        from .intake.fetch import Fetcher

        async with self._client() as client:
            report = await analyse(
                files,
                updates,
                changelog,
                graph=graph,
                contract=contract,
                manifest=manifest,
                version=version,
                code_version=code_version,
                design_version=design_version,
                fetcher=Fetcher(client, cache=Cache(self._cache_dir)),
                launcher=self._roseau,
                cache_dir=self._cache_dir,
            )
        used = sum(1 for impact in report.per_update if impact.references)
        count = len(report.per_update)
        summary = (
            f"{used} of {count} update{'s' if count != 1 else ''} used by the code, in "
            f"{len(report.affected_files)} file{'s' if len(report.affected_files) != 1 else ''}; "
            f"{len(report.affected_components)} component"
            f"{'s' if len(report.affected_components) != 1 else ''} reached, "
            f"{len(report.unmapped_files)} file{'s' if len(report.unmapped_files) != 1 else ''} "
            f"unmapped"
        )
        diffs = Counter(impact.api_diff for impact in report.per_update)
        return StageAnswer(
            report,
            summary,
            {
                "files_indexed": report.extraction.files_indexed,
                "index_seconds": report.extraction.seconds,
                "changed_symbols": len(report.changed_symbols),
                "references": sum(len(impact.references) for impact in report.per_update),
                "refused_references": report.refused_count,
                "api_diffs": ", ".join(f"{state} {n}" for state, n in sorted(diffs.items())),
                "granularity": report.granularity,
            },
        )

    @reports_model_use
    async def assess_risk(
        self,
        updates: DependencyUpdates,
        changelog: ChangelogReport | None,
        impact: ImpactReport | None,
        *,
        version: int,
    ) -> StageAnswer:
        """FR4 to FR8: three votes per update and the rule that combines them.

        Artefacts only, never files: the code was indexed once, in the impact
        stage, and this signature is what keeps it from being indexed twice.
        """
        from .risk.assess import report
        from .risk.explain import explain

        risk = await explain(
            report(updates, changelog, impact, version=version),
            model=self._model,
            agent_model=self._agent_model,
            thinking=self.thinking,
        )
        levels = risk.by_level
        count = len(risk.assessments)
        summary = (
            f"{count} update{'s' if count != 1 else ''} assessed: {levels['high']} High, "
            f"{levels['medium']} Medium, {levels['low']} Low; {risk.disagreements} where the "
            f"signals disagree"
        )
        return StageAnswer(
            risk,
            summary,
            {
                "disagreements": risk.disagreements,
                "over_budget": risk.over_budget,
                "evidence_incomplete": risk.evidence_incomplete,
                "explanations_from_model": sum(
                    1 for item in risk.assessments if item.explanation_source == "model"
                ),
                "explanations_refused": risk.explanations_refused,
            },
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
    ) -> StageAnswer:
        """FR12 to FR14: the pipeline and deployment configuration, validated.

        The files carry the baseline lockfile beside the code, and the settings
        say what the orchestrator knows that the files do not: the project, its
        origins once they exist, and what GitHub can enforce. The generated
        layer and the deploy plan travel in the notes, as the client expects.
        npm and the linters run in a worker thread, so the loop keeps serving.
        """
        import asyncio

        from .harness.staging import reads_database
        from .pipeline.candidate import resolve
        from .pipeline.generate import generate
        from .pipeline.plan import deploy_plan

        options: dict[str, Any] = {
            "resolver": self._resolver or partial(resolve, cache=self.npm_cache)
        }
        if self._validator is not None:
            options["validate"] = self._validator
        generated = await asyncio.to_thread(
            generate,
            files,
            updates,
            stack_id=stack_id,
            contract=contract,
            included=included,
            settings=settings,
            version=version,
            code_version=code_version,
            **options,
        )
        notes: dict[str, Any] = {**generated.notes, "files": generated.layer}
        if generated.config.stack.supported:
            plan = deploy_plan(
                generated,
                project_id=str(settings.get("project_id") or "unknown"),
                release_target=release_target,
                github_protection=settings.get("github_protection"),
                version=version,
                reads_database=reads_database(files),
            )
            notes["plan"] = plan.model_dump(by_alias=True, mode="json")
        return StageAnswer(generated.config, generated.summary, notes)

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
    ) -> StageAnswer:
        """The candidate installed, tested, built, booted and smoke tested in a container.

        A failed build is an outcome, recorded as a candidate that is not verified.
        No Docker daemon is a skip, saying so: there is then nothing staging can
        build, and nothing a release could start.
        """
        import asyncio

        from .harness.staging import verify
        from .pipeline.candidate import image_tag

        reason = self._docker_reason() if self._runner is None else None
        if reason:
            raise NotApplicable(
                "staging-verification", f"no Docker daemon to build the candidate in: {reason}"
            )
        known = {update.id: update for update in (updates.updates if updates else [])}
        chosen = [known[update_id] for update_id in included if update_id in known]
        unmatched = tuple(update_id for update_id in included if update_id not in known)
        slug = str((settings or {}).get("project_slug") or "app")
        options: dict[str, Any] = {}
        if self._runner is not None:
            options["runner"] = self._runner
        if self._prober is not None:
            options["prober"] = self._prober
        candidate = await asyncio.to_thread(
            verify,
            files,
            layer,
            candidate=candidate_hash,
            included=chosen,
            excluded=excluded,
            image=image_tag(slug, version),
            version=version,
            code_version=code_version,
            unmatched=unmatched,
            **options,
        )
        passed = sum(1 for step in candidate.steps if step.outcome == "passed")
        summary = (
            f"verified: {candidate.image} serves candidate {candidate.candidate_hash[:12]}, "
            f"{len(candidate.smoke)} smoke requests answered"
            if candidate.verified
            else f"not verified: {passed} of {len(candidate.steps)} steps passed"
            + next(
                (
                    f", stopped at {step.name}"
                    for step in candidate.steps
                    if step.outcome in ("failed", "timed-out")
                ),
                "",
            )
        )
        return StageAnswer(
            candidate,
            summary,
            {
                "verified": candidate.verified,
                "image": candidate.image,
                "digest": candidate.image_digest,
            },
        )

    def _docker_reason(self) -> str | None:
        from .harness.container import docker_unavailable

        return docker_unavailable()

    async def plan_rollback(
        self,
        candidate: ReleaseCandidate,
        risk: RiskReport,
        previous: VerifiedRelease | None,
        *,
        release_target: str,
        version: int,
        database: bool = False,
    ) -> StageAnswer:
        """FR19: where a restore would return to, and how that would be checked."""
        from .rollback.plan import plan

        prepared = plan(
            candidate,
            risk,
            previous,
            release_target=release_target,
            version=version,
            database=database,
        )
        summary = (
            f"restorable to deploy version {prepared.restore_target.deploy_version}, "
            f"candidate {prepared.restore_target.candidate_hash[:12]}"
            if prepared.restorable and prepared.restore_target
            else f"not restorable: {prepared.unrestorable_reason}"
        )
        if prepared.blocks:
            summary += f"; {len(prepared.blocks)} High update(s) without a prepared rollback"
        return StageAnswer(
            prepared,
            summary,
            {"restorable": prepared.restorable, "blocks": prepared.blocks},
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
    ) -> StageAnswer:
        """FR22: what the release taught, as requirements C1 can accept or reject."""
        from .feedback import FEEDBACK_RULE, derive

        report = derive(
            monitoring,
            risk,
            impact,
            project_id=project_id,
            deploy_version=deploy_version,
            fault_injected=fault_injected,
        )
        kinds = sorted({item.kind for item in report.items})
        summary = (
            f"{len(report.items)} suggestion(s) for requirements ({', '.join(kinds)})"
            if report.items
            else f"nothing to suggest: the window found the release {monitoring.current_state}"
        )
        return StageAnswer(report, summary, {"rule": FEEDBACK_RULE, "items": len(report.items)})
