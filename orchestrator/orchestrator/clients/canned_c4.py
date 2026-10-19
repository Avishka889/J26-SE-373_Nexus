"""Component 4, answered from constants, for the spine tests.

The deployment spine tests are about the deploy version axis, the stage table,
the gate and where each artefact lands, and none of that is more true for having
fetched release notes or built a container. So every stage answers here from
constants, with one rule: every artefact is one the real contracts accept. The
risk report's levels come from `deploy_rules` exactly as the component's will,
so a canned report that disagreed with the rule would be refused the same way a
real one would.

Three updates, chosen so the report carries every shape a reader meets: a major
update whose removed symbol the project uses (high, and all three signals
agree), a minor update the notes call a fix and the project does not touch
(medium by the version number alone, so the signals disagree and the report must
say so), and a patch with nothing known to have changed (low, one signal
abstaining).
"""

from dataclasses import dataclass, field
from typing import Any

from sdlc_contracts import (
    ARBITRATION_RULE,
    CHANGELOG_RULE,
    SEMVER_RULE,
    STRATEGY_RULE,
    USAGE_RULE,
    AffectedComponent,
    AffectedFile,
    ApiContract,
    Arbitration,
    ArchitecturalLayout,
    ArchitectureGraph,
    BuildStepReport,
    ChangedSymbol,
    ChangelogAnalysis,
    ChangelogClaim,
    ChangelogReport,
    CloudResources,
    ComponentLink,
    DependencyUpdate,
    DependencyUpdates,
    DeployPlan,
    DeployStep,
    DeployTarget,
    EnvironmentProtection,
    EvidenceRef,
    EvidenceSpan,
    ExcludedUpdate,
    ExtractionRecord,
    FeedbackItem,
    FeedbackReport,
    FileValidation,
    ImpactReport,
    Latency,
    ManifestRow,
    ModelCall,
    MonitoringReport,
    PipelineConfig,
    PipelineFile,
    ReleaseCandidate,
    RenderService,
    RestoreStep,
    RiskReport,
    RollbackPlan,
    RollbackPolicy,
    SignalVote,
    SmokeCheck,
    StackSupport,
    Strategy,
    UpdateAssessment,
    UpdateImpact,
    UpdateRollback,
    UsageReference,
    VercelProject,
    VerificationCheck,
    VerifiedRelease,
    safety_first,
    semver_level,
    strategy_for,
    update_id_for,
    update_key,
)

from ..db.store import now as store_now
from .c1 import StageOutcome
from .c4 import PipelineOutcome, UpdatesOutcome
from .canned import canned_thinking
from .thinking import RUN_THINKING

SHA = "0" * 64
CANDIDATE = "c" * 64
PREVIOUS = "b" * 64
UPDATES = (
    ("express", "4.21.2", "5.1.0", "major"),
    ("zod", "3.23.8", "3.24.1", "minor"),
    ("vite", "6.0.1", "6.0.3", "patch"),
)
#: The canned votes: SemVer is the rule's, the other two are chosen per update.
VOTES = {
    "express": ("high", "high"),
    "zod": ("low", "low"),
    "vite": ("low", None),
}


def _id(package: str, low: str, high: str) -> str:
    return update_id_for(update_key("npm", package, low, high))


def _vote(signal: str, level: str | None, evidence: list[str]) -> SignalVote:
    rule = {"semver": SEMVER_RULE, "changelog": CHANGELOG_RULE, "usage": USAGE_RULE}[signal]
    return SignalVote(
        signal=signal,
        level=level,
        abstained_reason="" if level else "nothing known to have changed",
        rule_id=rule,
        rationale=f"canned {signal} vote",
        evidence_ids=evidence if level else [],
    )


@dataclass
class CannedC4:
    model: str = "canned (no model)"
    thinking: str | None = None
    #: The configured level, which a run uses where its account chose none.
    level: str = "off"
    #: The level each call came at, in order (None outside a run).
    levels: list[str | None] = field(default_factory=list)
    #: The stage names asked for, in order.
    calls: list[str] = field(default_factory=list)
    #: Stage names that should raise instead, for testing failure handling.
    fails: set[str] = field(default_factory=set)
    #: A generated pipeline one of whose validators failed, for the G7 guard.
    invalid_pipeline: bool = False
    #: Whether the staging build proves the candidate.
    verified: bool = True
    #: The settings each pipeline generation was given, in order.
    pipeline_settings: list[dict[str, Any]] = field(default_factory=list)
    #: The projects cloud resources were asked for, which is not a stage.
    provisioned: list[str] = field(default_factory=list)
    #: What each rollback plan was told about the release's database, in order.
    rollback_database: list[bool] = field(default_factory=list)

    def _called(self, name: str) -> None:
        self.calls.append(name)
        # The level the run asked this call at, so a test can see it arrive.
        self.levels.append(RUN_THINKING.get())
        if name in self.fails:
            raise RuntimeError(f"the {name} stage was told to fail")

    def thinking_for(self, level: str) -> str | None:
        """What a real component's record would say at a level; silent if this one is."""
        return canned_thinking(self.thinking, level)

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
        self._called("dependency-updates")
        updates = [
            DependencyUpdate(
                id=_id(package, low, high),
                key=update_key("npm", package, low, high),
                ecosystem="npm",
                package=package,
                manifest_path="apps/api/package.json",
                scope="prod",
                declared=f"^{low}",
                from_version=low,
                to_version=high,
                candidate="latest",
                change=change,
            )
            for package, low, high, change in UPDATES
            if packages is None or package in packages
        ]
        report = DependencyUpdates(
            version=version,
            generated_at=store_now(),
            code_version=code_version,
            test_version=test_version,
            target=target,
            updates=updates,
        )
        texts = {"notes/express/5.0.0.md": "## 5.0.0\n- Removed `app.del`, use `app.delete`.\n"}
        return UpdatesOutcome(report=report, texts=texts, summary="3 updates found", notes={})

    async def analyse_changelogs(
        self, updates: DependencyUpdates, notes: dict[str, str], *, version: int
    ) -> StageOutcome[ChangelogReport]:
        self._called("changelog-analysis")
        call = ModelCall(
            model_id=self.model,
            prompt_id="changelog-extract/1",
            prompt_sha256=SHA,
            outcome="answered",
        )
        analyses = []
        for update in updates.updates:
            claims = []
            if update.package == "express":
                claims = [
                    ChangelogClaim(
                        id="c1",
                        kind="removal",
                        symbols=["app.del"],
                        quote="Removed `app.del`, use `app.delete`.",
                        source_url="https://github.com/expressjs/express/releases/tag/v5.0.0",
                        version="5.0.0",
                    )
                ]
            elif update.package == "zod":
                claims = [
                    ChangelogClaim(
                        id="c2",
                        kind="fix",
                        quote="Fixed a crash in string parsing.",
                        source_url="https://github.com/colinhacks/zod/releases/tag/v3.24.1",
                        version="3.24.1",
                    )
                ]
            level = VOTES[update.package][0]
            analyses.append(
                ChangelogAnalysis(
                    update_id=update.id,
                    windows=[update.to_version],
                    notes_found=True,
                    claims=claims,
                    vote=_vote("changelog", level, [f"claim:{c.id}" for c in claims] or ["notes"]),
                    model=call,
                )
            )
        report = ChangelogReport(
            version=version,
            generated_at=store_now(),
            model_id=self.model,
            prompt_id="changelog-extract/1",
            prompt_sha256=SHA,
            per_update=analyses,
        )
        return StageOutcome(artefact=report, summary="2 claims verified", notes={})

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
        self._called("impact-analysis")
        express = _id("express", "4.21.2", "5.1.0")
        zod = _id("zod", "3.23.8", "3.24.1")
        vite = _id("vite", "6.0.1", "6.0.3")
        reference = UsageReference(
            symbol="app.del",
            symbol_kind="removed",
            match="member",
            span=EvidenceSpan(
                path="apps/api/src/app.ts", start_line=4, end_line=4, snippet="app.del('/x', h)"
            ),
        )
        report = ImpactReport(
            version=version,
            generated_at=store_now(),
            code_version=code_version,
            design_version=design_version,
            extraction=ExtractionRecord(
                extraction_id="canned", parser="canned", files_indexed=len(files), seconds=0.0
            ),
            changed_symbols=[
                ChangedSymbol(
                    update_id=express,
                    symbol="app.del",
                    kind="removed",
                    source="changelog",
                    tool="claim:c1",
                ),
                ChangedSymbol(
                    update_id=zod,
                    symbol="z.string",
                    kind="touched",
                    source="changelog",
                    tool="claim:c2",
                ),
            ],
            per_update=[
                UpdateImpact(
                    update_id=express,
                    imports_package=True,
                    references=[reference],
                    api_diff="unavailable",
                    api_diff_reason="canned",
                    vote=_vote("usage", "high", ["ref:1"]),
                ),
                UpdateImpact(
                    update_id=zod,
                    imports_package=True,
                    unreferenced=["z.string"],
                    api_diff="unavailable",
                    api_diff_reason="canned",
                    vote=_vote("usage", "low", ["component:none"]),
                ),
                UpdateImpact(
                    update_id=vite,
                    imports_package=False,
                    used_by_scripts=True,
                    api_diff="unavailable",
                    api_diff_reason="canned",
                    vote=_vote("usage", None, []),
                ),
            ],
            affected_files=[
                AffectedFile(
                    path="apps/api/src/app.ts",
                    update_ids=[express],
                    reference_count=1,
                    implements=["Record"],
                )
            ],
            affected_components=[
                AffectedComponent(
                    node_id="e-record",
                    label="Record",
                    kind="entity",
                    update_ids=[express],
                    files=["apps/api/src/app.ts"],
                    links=[
                        ComponentLink(
                            via="manifest-entity",
                            path="apps/api/src/app.ts",
                            detail="the manifest says it implements Record",
                        )
                    ],
                    traces=["R-1"],
                )
            ],
        )
        return StageOutcome(artefact=report, summary="1 file, 1 component", notes={})

    async def assess_risk(
        self,
        updates: DependencyUpdates,
        changelog: ChangelogReport | None,
        impact: ImpactReport | None,
        *,
        version: int,
    ) -> StageOutcome[RiskReport]:
        self._called("risk-assessment")
        assessments = []
        for update in updates.updates:
            changelog_level, usage_level = VOTES[update.package]
            votes = {
                "semver": semver_level(update.change),
                "changelog": changelog_level,
                "usage": usage_level,
            }
            final, decided_by = safety_first(votes)
            cast = {level for level in votes.values() if level is not None}
            assessments.append(
                UpdateAssessment(
                    update_id=update.id,
                    key=update.key,
                    package=update.package,
                    ecosystem=update.ecosystem,
                    from_version=update.from_version,
                    to_version=update.to_version,
                    change=update.change,
                    votes=[_vote(signal, level, ["version"]) for signal, level in votes.items()],
                    arbitration=Arbitration(
                        rule_id=ARBITRATION_RULE,
                        final=final,
                        decided_by=list(decided_by),
                        advisory=(
                            "The signals disagree; the most cautious level was taken."
                            if len(cast) != 1
                            else ""
                        ),
                    ),
                    strategy=Strategy(
                        rule_id=STRATEGY_RULE,
                        deploy=strategy_for(final),
                        manual_review_required=final == "high",
                        rollback_required=final == "high",
                    ),
                    evidence=[EvidenceRef(id="version", kind="version", summary=update.key)],
                    latency=Latency(
                        changelog_seconds=0.1, usage_seconds=0.1, arbitration_seconds=0.0
                    ),
                )
            )
        report = RiskReport(version=version, generated_at=store_now(), assessments=assessments)
        return StageOutcome(artefact=report, summary="1 high, 1 medium, 1 low", notes={})

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
        self._called("pipeline-generation")
        self.pipeline_settings.append(dict(settings))
        if stack_id != "mern":
            # As the real component answers (FR14): reported, and nothing generated.
            unsupported = PipelineConfig(
                version=version,
                generated_at=store_now(),
                code_version=code_version,
                candidate_hash=CANDIDATE,
                stack=StackSupport(
                    stack_id=stack_id,
                    supported=False,
                    reason=f"validated templates exist for mern only; {stack_id} is reported",
                ),
                kubernetes="skipped",
                kubernetes_reason="the stack is unsupported, so nothing was generated",
            )
            return PipelineOutcome(
                config=unsupported,
                plan=None,
                files={},
                summary=f"{stack_id} is not supported",
                notes={},
            )
        layer = {"Dockerfile": "FROM node:22-bookworm-slim\n", "vercel.json": "{}\n"}
        config = PipelineConfig(
            version=version,
            generated_at=store_now(),
            code_version=code_version,
            candidate_hash=CANDIDATE,
            stack=StackSupport(
                stack_id=stack_id,
                supported=True,
                layout=ArchitecturalLayout(
                    kind="one-process",
                    frontend_dir="apps/web",
                    backend_dir="apps/api",
                    serves_frontend_from_backend=True,
                    evidence=["canned"],
                ),
            ),
            files=[
                PipelineFile(
                    path=path,
                    purpose="container" if path == "Dockerfile" else "hosting",
                    sha256=SHA,
                    bytes=len(content),
                    template_id=f"canned/{path}@1",
                    validations=[
                        FileValidation(
                            validator="hadolint",
                            tool="canned",
                            outcome="failed",
                            findings=["DL3008 pin versions in apt-get install"],
                        )
                        if self.invalid_pipeline and path == "Dockerfile"
                        else FileValidation(
                            validator="json-schema", tool="canned", outcome="passed"
                        )
                    ],
                )
                for path, content in layer.items()
            ],
            kubernetes="skipped",
            kubernetes_reason="canned",
        )
        plan = DeployPlan(
            plan_id=f"plan-{version}",
            project_id="canned",
            generated_by=self.model,
            generated_at=store_now(),
            deploy_version=version,
            stack="mern",
            target="local",
            candidate_hash=CANDIDATE,
            targets=[DeployTarget(role="app", provider="local-docker", resource="container")],
            steps=[
                DeployStep(id="image", label="Load the image", provider="local-docker"),
                DeployStep(
                    id="switch",
                    label="Point production at the candidate",
                    provider="local-docker",
                    depends_on="image",
                    compensation="point production back",
                    moves_traffic=True,
                ),
            ],
            rollback=RollbackPolicy(note="application only"),
            environment_protection=EnvironmentProtection(github="not-applicable"),
        )
        if release_target == "cloud":
            # As the real component plans it: the target chosen when the run began,
            # with the steps the cloud adapter carries out.
            plan = plan.model_copy(
                update={
                    "target": "cloud",
                    "targets": [
                        DeployTarget(role="backend", provider="render", resource="web service"),
                        DeployTarget(role="frontend", provider="vercel", resource="project"),
                    ],
                    "steps": [
                        DeployStep(id="commit", label="Commit the layer", provider="github"),
                        DeployStep(
                            id="secrets",
                            label="Store the deploy secrets",
                            provider="github",
                            depends_on="commit",
                            compensation="delete the secrets this release created",
                        ),
                        DeployStep(
                            id="backend",
                            label="Deploy the backend on Render",
                            provider="render",
                            depends_on="secrets",
                            compensation="redeploy the verified release, once a person approves",
                            moves_traffic=True,
                        ),
                        DeployStep(
                            id="dispatch",
                            label="Dispatch deploy.yml",
                            provider="github",
                            depends_on="backend",
                            compensation="redeploy the verified release, once a person approves",
                            moves_traffic=True,
                        ),
                        DeployStep(id="verify", label="Verify", depends_on="dispatch"),
                    ],
                    "environment_protection": EnvironmentProtection(
                        github="unavailable-private-repo"
                    ),
                }
            )
        return PipelineOutcome(
            config=config, plan=plan, files=layer, summary="2 files, all valid", notes={}
        )

    async def provision_cloud(self, project_id: str) -> CloudResources:
        """What the platform would make for a cloud release, answered without Vercel or Render."""
        self.provisioned.append(project_id)
        slug = project_id.lower().replace("_", "-")
        return CloudResources(
            vercel=VercelProject(
                project_id="prj_canned",
                org_id="team_canned",
                name=slug,
                origin=f"https://{slug}.vercel.app",
            ),
            render=RenderService(
                service_id="srv-canned",
                name=f"{slug}-api",
                origin=f"https://{slug}-api.onrender.com",
                owner_id="tea-canned",
            ),
            created_at=store_now(),
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
        self._called("staging-verification")
        candidate = ReleaseCandidate(
            version=version,
            generated_at=store_now(),
            code_version=code_version,
            candidate_hash=candidate_hash,
            included=included,
            excluded=[ExcludedUpdate.model_validate(item) for item in excluded],
            image_digest="sha256:" + "d" * 64 if self.verified else None,
            toolchain="canned",
            isolation="canned",
            steps=[
                BuildStepReport(
                    name="test",
                    command="npm test",
                    outcome="passed" if self.verified else "failed",
                    duration_seconds=1.0,
                )
            ],
            smoke=[SmokeCheck(path="/records", status_code=200, ok=True)],
            fingerprint=candidate_hash if self.verified else None,
        )
        return StageOutcome(
            artefact=candidate,
            summary="verified" if self.verified else "the candidate did not verify",
            notes={},
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
        self._called("rollback-planning")
        self.rollback_database.append(database)
        restorable = previous is not None
        updates = [
            UpdateRollback(
                update_id=item.update_id,
                level=item.arbitration.final,
                status=(
                    ("prepared" if restorable else "unavailable")
                    if item.arbitration.final == "high"
                    else "not-required"
                ),
                reason="" if restorable else "this is the project's first release",
            )
            for item in risk.assessments
        ]
        plan = RollbackPlan(
            version=version,
            generated_at=store_now(),
            candidate_hash=candidate.candidate_hash,
            restore_target=previous,
            restorable=restorable,
            unrestorable_reason="" if restorable else "this is the project's first release",
            steps=(
                [
                    RestoreStep(
                        id="start",
                        label="Start the verified image",
                        provider="local-docker",
                        action="run the image by digest",
                        moves_traffic=True,
                    )
                ]
                if restorable
                else []
            ),
            checks=(
                [VerificationCheck(id="fp", kind="fingerprint", role="app", expect=PREVIOUS)]
                if restorable
                else []
            ),
            updates=updates,
        )
        return StageOutcome(artefact=plan, summary="rollback planned", notes={})

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
        """One item for a window that found something wrong, none for one that did not.

        Input dependent on purpose, as the canned C1 is: a double that suggested the
        same thing whatever it was shown could not prove that what a window found
        is what reaches C1's next run.
        """
        self._called("feedback")
        state = monitoring.current_state
        items = []
        if state in ("down", "degraded", "cold-start"):
            observed = monitoring.states[-1].evidence if monitoring.states else state
            items.append(
                FeedbackItem(
                    id=f"fb-canned-{state}",
                    kind="runtime",
                    source="monitoring",
                    summary=f"Deploy version {deploy_version} was {state}.",
                    evidence=(
                        f"In a controlled failure (`{fault_injected}`): " if fault_injected else ""
                    )
                    + observed,
                    evidence_ref=f"monitoring-report@{monitoring.version}#{state}",
                    suggested_requirement=(
                        f"The application shall not be {state} after deploy version "
                        f"{deploy_version} is released."
                    ),
                    traces=[],
                )
            )
        report = FeedbackReport(
            report_id=f"feedback-{project_id}-v{deploy_version}",
            project_id=project_id,
            generated_at=store_now(),
            deploy_version=deploy_version,
            source_reports=[f"monitoring-report@{monitoring.version}"],
            items=items,
        )
        return StageOutcome(artefact=report, summary=f"{len(items)} item(s)", notes={})

    def targets(self) -> list[dict[str, str]]:
        return [{"id": "generated", "label": "The generated application", "note": "canned"}]
