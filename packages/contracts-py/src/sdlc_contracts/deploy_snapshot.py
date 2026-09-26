"""The deployment phase snapshot: one payload the browser reads.

The same shape as the other three phases' snapshots, for the same reason: every
mutation answers with the whole phase, so the client never reconciles a partial
update against what it already had.

Three things about this phase make its snapshot different.

**Decisions sit beside the reports, never inside them.** A person approving,
rejecting or deferring an update is an overlay, laid beside the risk report in
`decisions`. The risk report is exactly what the rule produced, so the level a
reader sees is never one somebody edited.

**Execution outlives the run.** A release and a monitoring window are carried
out by the orchestrator after the gate, so their state comes from the deployment
ledger (`deployments`), newest first, including every failed attempt and its
cause (FR16). The release and monitoring stages mirror that ledger.

**What stops a release is said, by the server.** `blocking` holds the release
guards' refusals in words, computed where the guards run, so the browser never
decides by itself whether a release may go ahead.
"""

from typing import Literal

from pydantic import Field, computed_field, model_validator

from .changelog_report import ChangelogReport
from .dependency_update import DependencyUpdates
from .deploy_plan import DeployPlan, ProviderId, ReleaseTarget
from .deploy_rules import HealthState
from .feedback import FeedbackReport
from .ids import DEPLOY_STAGE_IDS, DeployStageId, UpdateId
from .impact_report import ImpactReport
from .model_use import StageModelUse
from .monitoring_report import MonitoringReport
from .pipeline_config import PipelineConfig
from .release_candidate import ReleaseCandidate
from .remediation_proposal import RiskLevel
from .risk_report import RiskReport
from .rollback_plan import RollbackPlan, VerifiedRelease
from .run_status import RunStatus
from .snapshot import GateState
from .wire import WireDatetime, WireModel

DeployStageStatus = Literal["pending", "generating", "complete", "failed", "skipped"]
DeployThreadKind = Literal["user_note", "answer", "stage_summary", "system"]
UpdateDecisionKind = Literal["approved", "rejected", "deferred"]
DeploymentKind = Literal["release", "rollback"]

#: A deployment's life. `compensated` is a failure before production moved,
#: cleaned up automatically. `awaiting-rollback-approval` is a failure after it
#: moved, which only a human may undo (FR20). `kept-unverified` is one of those
#: whose rollback a person declined: it serves, and nothing verified it.
DeploymentState = Literal[
    "pending",
    "running",
    "succeeded",
    "compensated",
    "failed",
    "awaiting-rollback-approval",
    "rolled-back",
    "kept-unverified",
]

StepState = Literal["pending", "running", "succeeded", "failed", "compensated", "skipped"]


class DeployStageState(WireModel):
    """One stage of the deployment phase, as the stepper renders it."""

    id: DeployStageId
    status: DeployStageStatus = "pending"
    #: The deploy version this stage ran at. Zero means never.
    generated_from_version: int = Field(default=0, ge=0)
    generated_at: WireDatetime | None = None
    summary: str | None = None
    error: str | None = None
    #: What answered this stage's current version, where it asked a model (0015).
    model_use: StageModelUse | None = None

    @model_validator(mode="after")
    def failure_says_why(self) -> "DeployStageState":
        if self.status == "failed" and not self.error:
            raise ValueError(f"stage {self.id} failed without saying why")
        if self.status != "failed" and self.error:
            raise ValueError(f"stage {self.id} is {self.status} but carries an error")
        return self

    @model_validator(mode="after")
    def a_skip_says_why_too(self) -> "DeployStageState":
        if self.status == "skipped" and not (self.summary or "").strip():
            raise ValueError(f"stage {self.id} was skipped without saying why")
        return self


class DeployThreadMessage(WireModel):
    id: str = Field(min_length=1)
    kind: DeployThreadKind
    stage_id: DeployStageId | None = None
    author: str = Field(min_length=1)
    content: str = Field(min_length=1)
    at: WireDatetime
    produced_version: int | None = None


class UpdateDecisionView(WireModel):
    """What a person decided about one update, and whether a decision is owed."""

    update_id: UpdateId
    decision: UpdateDecisionKind | None = None
    by: str | None = None
    at: WireDatetime | None = None
    note: str | None = None
    #: The level the update had when it was decided. A decision taken at a
    #: lower level does not count once the level rises.
    level_at_decision: RiskLevel | None = None
    needs_decision: bool
    needs_review_note: bool


class FeedbackDecisionView(WireModel):
    """What a person did with one feedback item (M5)."""

    item_id: str = Field(min_length=1)
    #: `sent` became a design change note for C1's next run; `dismissed` did not.
    decision: Literal["sent", "dismissed"]
    by: str = Field(min_length=1)
    at: WireDatetime
    note: str | None = None
    #: The deploy version whose feedback report held the item.
    deploy_version: int = Field(ge=1)
    #: For a sent item, the design version its change note opened.
    design_version: int | None = Field(default=None, ge=1)


class DeploymentStepView(WireModel):
    """One step of one deployment, in the shape the shared console reads."""

    seq: int = Field(ge=0)
    step_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    provider: ProviderId | None = None
    state: StepState
    moves_traffic: bool = False
    attempt: int = Field(default=0, ge=0)
    command: str = ""
    log_tail: str = ""
    error: str = ""
    started_at: WireDatetime | None = None
    finished_at: WireDatetime | None = None


class DeploymentView(WireModel):
    """One attempt to release or roll back, whatever came of it (FR16)."""

    id: str = Field(min_length=1)
    kind: DeploymentKind
    target: ReleaseTarget
    state: DeploymentState
    candidate_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    deploy_version: int = Field(ge=1)
    verified: bool = False
    #: Why it failed, in the provider's words where it gave any.
    cause: str = ""
    #: The controlled failure scenario injected into it, when one was.
    fault_injected: str = ""
    requested_by: str = Field(min_length=1)
    #: Who authorised it: a gate decision, the standing policy, or a rollback
    #: decision, named.
    authorised_by: str = ""
    #: For a rollback, the deployment it returned to.
    restores: str | None = None
    url: str | None = None
    created_at: WireDatetime
    finished_at: WireDatetime | None = None
    steps: list[DeploymentStepView] = Field(default_factory=list)


class VercelProject(WireModel):
    """The Vercel project the platform created for a project's frontend."""

    project_id: str = Field(min_length=1)
    #: The account or team that owns it, which the Vercel CLI reads as its org id.
    org_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    #: The production domain the platform claimed for it, before any deployment.
    origin: str = Field(pattern=r"^https://[a-z0-9.-]+$")


class RenderService(WireModel):
    """The Render web service the platform created for a project's backend."""

    service_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    origin: str = Field(pattern=r"^https://[a-z0-9.-]+$")
    #: The Render workspace it belongs to.
    owner_id: str = Field(min_length=1)
    dashboard_url: str = ""


class AtlasDatabase(WireModel):
    """The project's own database on the account's Atlas cluster, and who may use it.

    The password is not here: the platform keeps it encrypted with its secrets,
    and it reaches only Atlas and the Render service, inside MONGODB_URL.
    """

    cluster: str = Field(min_length=1)
    #: The cluster's public host, from its SRV connection string.
    host: str = Field(min_length=1)
    database: str = Field(min_length=1)
    #: A database user whose one role is reading and writing `database`.
    username: str = Field(min_length=1)
    #: The Render service MONGODB_URL was set on.
    service_id: str = Field(min_length=1)


class CloudResources(WireModel):
    """What the platform created for a project's cloud releases.

    Made on the project's first analysis with the cloud target, from the tokens
    the account keeps in Settings, and reused after that. Kept per project, so
    every project releases to its own.
    """

    vercel: VercelProject
    render: RenderService
    #: None when the account keeps no Atlas connection: the app keeps its
    #: records in memory, and a restart or a release empties them.
    database: AtlasDatabase | None = None
    created_at: WireDatetime


class Blocker(WireModel):
    """One reason a release may not go ahead, from the server's guards."""

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    update_id: UpdateId | None = None


class DeploySnapshot(WireModel):
    """Everything the deployment workspace renders, in one read."""

    project_id: str = Field(min_length=1)
    #: This phase's own counter. Zero before the first run.
    deploy_version: int = Field(ge=0)
    test_version: int = Field(ge=0)
    #: The test version whose review approved the code this phase may deploy.
    approved_test_version: int = Field(ge=0)
    #: The code version those approved tests measured: what a run analyses and
    #: what may ship. Newer code waits for its own tests and holds nothing back.
    approved_tested_code_version: int = Field(default=0, ge=0)
    #: The newest code version written, tested or not.
    code_version: int = Field(ge=0)
    #: The code version this phase's artefacts were produced from.
    deployed_code_version: int = Field(ge=0)
    #: The test version this deploy version's analysis started from: the tests
    #: whose approval covers what it ships. Zero before a run.
    analysed_test_version: int = Field(default=0, ge=0)
    #: Which repository was analysed: `generated` or `sample:<name>`.
    target: str = "generated"
    #: The packages a run analyses, as chosen; empty for every dependency.
    scope_packages: list[str] = Field(default_factory=list)
    release_target: ReleaseTarget = "local"
    #: The standing policy a human set for low risk updates.
    auto_deploy_low: bool = False
    stages: dict[DeployStageId, DeployStageState]
    updates: DependencyUpdates | None = None
    changelog: ChangelogReport | None = None
    impact: ImpactReport | None = None
    risk: RiskReport | None = None
    pipeline: PipelineConfig | None = None
    plan: DeployPlan | None = None
    candidate: ReleaseCandidate | None = None
    rollback: RollbackPlan | None = None
    monitoring: MonitoringReport | None = None
    feedback: FeedbackReport | None = None
    decisions: list[UpdateDecisionView] = Field(default_factory=list)
    #: What a person did with each feedback item decided so far.
    feedback_decisions: list[FeedbackDecisionView] = Field(default_factory=list)
    #: The ledger, newest first: the newest ten attempts.
    deployments: list[DeploymentView] = Field(default_factory=list)
    #: How many attempts the ledger holds, so a page showing the newest ten can
    #: say there are more rather than call ten "every release".
    deployments_total: int = Field(default=0, ge=0)
    current_release: VerifiedRelease | None = None
    #: The deployment a monitoring window watches now, if any. A window runs in
    #: the orchestrator, opened on release or on request, and writes its report
    #: when it ends, so until then the report is an earlier window's.
    watching: str | None = None
    #: The Vercel project and Render service this project releases to, once the
    #: platform has created them; None before its first cloud analysis.
    cloud: CloudResources | None = None
    blocking: list[Blocker] = Field(default_factory=list)
    gate: GateState
    #: The phase's newest full run, so a run that stopped short of the review
    #: says so here rather than only in the audit log. None before any ran.
    run: RunStatus | None = None
    thread: list[DeployThreadMessage] = Field(default_factory=list)

    @model_validator(mode="after")
    def every_stage_is_present(self) -> "DeploySnapshot":
        """The client indexes `stages[id]` for all ten with no null guard."""
        missing = [stage for stage in DEPLOY_STAGE_IDS if stage not in self.stages]
        if missing:
            raise ValueError(f"snapshot is missing stages: {', '.join(missing)}")
        return self

    @computed_field
    @property
    def code_moved_on(self) -> bool:
        """Whether code newer than what this phase's artefacts describe has approved tests.

        Newer code without approved tests is not a move: what these artefacts
        describe is still what may ship.
        """
        return (
            self.deployed_code_version > 0
            and self.approved_tested_code_version > self.deployed_code_version
        )

    @computed_field
    @property
    def awaiting_decision(self) -> int:
        return sum(1 for item in self.decisions if item.needs_decision)

    @computed_field
    @property
    def rollback_pending(self) -> bool:
        """A release failed after it moved production, and only a human may undo it."""
        return any(item.state == "awaiting-rollback-approval" for item in self.deployments)

    @computed_field
    @property
    def live_state(self) -> HealthState:
        return self.monitoring.current_state if self.monitoring else "unknown"
