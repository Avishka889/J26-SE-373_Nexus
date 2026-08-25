"""Identity and vocabulary shared across every artefact.

The stage ids are the single canonical vocabulary: they are the contract schema
names, the run event stage keys, the C1 endpoint paths (minus the slash), and
the frontend's own stage ids, all at once. Anything that needs to name a stage
imports from here.
"""

from typing import Annotated, Literal, get_args

from pydantic import Field

DesignStageId = Literal[
    "requirements",
    "domain-model",
    "architecture-graph",
    "architecture-recommendation",
    "uml-diagrams",
    "wireframes",
    "sprint-plan",
    "design-review",
]

DESIGN_STAGE_IDS: tuple[DesignStageId, ...] = get_args(DesignStageId)

# Two stages have no endpoint by design. Domain Model is a projection over the
# architecture graph (actors and entities are graph nodes, so generating it
# separately would create a second copy to drift), and Design Review is the
# orchestrator's gate rather than something a component produces.
PROJECTED_STAGE_IDS: frozenset[str] = frozenset({"domain-model", "design-review"})

#: The stages a component service actually produces an artefact for.
ARTEFACT_STAGE_IDS: tuple[DesignStageId, ...] = tuple(
    stage for stage in DESIGN_STAGE_IDS if stage not in PROJECTED_STAGE_IDS
)

#: The stages a run makes progress on, which is what a reader watches.
#:
#: Wider than the artefacts by exactly one. Domain Model produces nothing of its
#: own, but it is a projection of the architecture graph, so it is being built
#: whenever the graph is: leaving it out made it sit grey and finished-looking
#: beside seven spinners, which reads as skipped rather than as waiting.
#:
#: Design Review stays out. It is the gate, and it genuinely has nothing to do
#: until every other stage is done, so showing it as generating would be a lie
#: about what the run is doing.
GENERATING_STAGE_IDS: tuple[DesignStageId, ...] = (*ARTEFACT_STAGE_IDS, "domain-model")

ArtefactKind = Literal[
    "requirements",
    "architecture-graph",
    "architecture-recommendation",
    "uml-diagrams",
    "wireframes",
    "sprint-plan",
]

ARTEFACT_KINDS: tuple[ArtefactKind, ...] = get_args(ArtefactKind)

# Ids are part of the contract, not decoration: every artefact element traces to
# a requirement id, so a malformed one breaks traceability rather than looking
# untidy. Constrained at the type so no generator can emit "REQ 1" or "r-1".
RequirementId = Annotated[str, Field(pattern=r"^R-\d+$")]
AssumptionId = Annotated[str, Field(pattern=r"^A-\d+$")]
QuestionId = Annotated[str, Field(pattern=r"^Q-\d+$")]
StoryId = Annotated[str, Field(pattern=r"^US-\d+$")]

#: Requirement ids an element was generated from. Empty is a validation failure
#: everywhere except the requirements artefact itself.
Traces = Annotated[list[RequirementId], Field(default_factory=list)]

# ------------------------------------------------------------------ C2 (code)
# The code phase's canonical vocabulary, kept apart from the design phase's on
# purpose: DesignStageId types the design snapshot and everything C1, so adding
# to it would silently change C1's progress arithmetic and stage validators.

CodeStageId = Literal[
    "sprint-scope",
    "tech-stack",
    "api-contract",
    "frontend-code",
    "backend-code",
    "contract-agreement",
    "build",
    "code-review",
]

CODE_STAGE_IDS: tuple[CodeStageId, ...] = get_args(CodeStageId)

#: Code Review is the gate, produced by nobody.
CODE_PROJECTED_STAGE_IDS: frozenset[str] = frozenset({"code-review"})

#: The stages the C2 component produces an artefact for. The repository push
#: happens inside `build`, so it is not a stage of its own; its result lives on
#: the code-repository artefact that stage writes.
CODE_ARTEFACT_STAGE_IDS: tuple[CodeStageId, ...] = tuple(
    stage for stage in CODE_STAGE_IDS if stage not in CODE_PROJECTED_STAGE_IDS
)

#: What a reader watches while a code run is in flight. Code Review stays out
#: for the same reason Design Review does: the gate has nothing to do until
#: everything else is done.
CODE_GENERATING_STAGE_IDS: tuple[CodeStageId, ...] = CODE_ARTEFACT_STAGE_IDS

CodeArtefactKind = Literal[
    "sprint-scope",
    "tech-stack",
    "api-contract",
    "contract-agreement",
    "code-repository",
]

CODE_ARTEFACT_KINDS: tuple[CodeArtefactKind, ...] = get_args(CodeArtefactKind)

#: Human choices on the code axis, stored as overlays like C1's edits: the
#: machine's output stays untouched and the decision carries who and when.
CodeOverlayKind = Literal[
    "story_scope",
    "stack_selection",
    "contract_arm_choice",
    "contract_item_decision",
]

CODE_OVERLAY_KINDS: tuple[CodeOverlayKind, ...] = get_args(CodeOverlayKind)


# ------------------------------------------------------------ the testing axis

#: The stages of Testing and Security, in the order a run walks them.
#:
#: Generation and execution are separate because one costs model calls and the
#: other does not, and a reader who wants the tests again should not have to pay
#: for both. Execution and quality are separate because mutation testing is
#: minutes where a test run is seconds: reporting a green suite while mutants
#: are still being killed is honest, and holding the green back until they are
#: is not.
#:
#: Self healing sits between them and the security work because it is about the
#: run that just happened: it reads the failures execution produced and the diff
#: between this code version and the one the tests were written against.
TestStageId = Literal[
    "test-generation",
    "test-run",
    "test-quality",
    "self-healing",
    "security-scan",
    "remediation",
    "test-review",
]

TEST_STAGE_IDS: tuple[TestStageId, ...] = get_args(TestStageId)

#: Test Review is the gate, produced by nobody.
TEST_PROJECTED_STAGE_IDS: frozenset[str] = frozenset({"test-review"})

TEST_ARTEFACT_STAGE_IDS: tuple[TestStageId, ...] = tuple(
    stage for stage in TEST_STAGE_IDS if stage not in TEST_PROJECTED_STAGE_IDS
)

#: What a reader watches while a testing run is in flight.
TEST_GENERATING_STAGE_IDS: tuple[TestStageId, ...] = TEST_ARTEFACT_STAGE_IDS

#: `validation-report` is the C3 to C4 seam and keeps the name C4 already reads.
#: `heal-report` is separate from `test-report` rather than a field on it,
#: because a heal is a decision about a test and the two have different
#: lifetimes: a test report is replaced by the next run, and a refusal is
#: evidence that has to survive it.
TestArtefactKind = Literal[
    "test-report",
    "heal-report",
    "validation-report",
    "remediation-proposal",
]

TEST_ARTEFACT_KINDS: tuple[TestArtefactKind, ...] = get_args(TestArtefactKind)

#: Human choices on the testing axis. The honesty guard decides mechanically
#: whether a repair may be accepted; these are what a person decides afterwards,
#: and they are stored as overlays so the machine's own output stays untouched
#: and every decision carries who made it and when.
TestOverlayKind = Literal[
    "target_selection",
    "finding_decision",
    "heal_decision",
    "remediation_decision",
    # The only one of these a machine writes. It sits with the human decisions
    # because it belongs to the same proposal on the same version axis, and
    # because the artefact it concerns was sealed by the run that produced it:
    # a measurement taken two runs later cannot go back inside it.
    "remediation_reverification",
]

TEST_OVERLAY_KINDS: tuple[TestOverlayKind, ...] = get_args(TestOverlayKind)


# ------------------------------------------------------------- the deploy axis

#: The stages of Deployment, in the order a run walks them.
#:
#: The release notes are read before the code is searched because the claims a
#: model verifies name the symbols the search looks for, and both come before
#: the risk assessment because it combines their votes. The pipeline and the
#: staging build come after the risk is fixed, so nothing observed while
#: building a candidate can leak back into the level it was built on.
#:
#: The last two are not the graph's. A release and a monitoring window outlive
#: any one run: the orchestrator's saga runner and monitor execute them after
#: the gate, which is why a failed run must not be able to reset them.
DeployStageId = Literal[
    "dependency-updates",
    "changelog-analysis",
    "impact-analysis",
    "risk-assessment",
    "pipeline-generation",
    "staging-verification",
    "rollback-planning",
    "deployment-review",
    "release",
    "monitoring",
]

DEPLOY_STAGE_IDS: tuple[DeployStageId, ...] = get_args(DeployStageId)

#: Deployment Review is the gate, produced by nobody.
DEPLOY_PROJECTED_STAGE_IDS: frozenset[str] = frozenset({"deployment-review"})

#: Executed by the orchestrator after the gate, never by a graph node.
DEPLOY_RUNNER_STAGE_IDS: tuple[DeployStageId, ...] = ("release", "monitoring")

DEPLOY_ARTEFACT_STAGE_IDS: tuple[DeployStageId, ...] = tuple(
    stage
    for stage in DEPLOY_STAGE_IDS
    if stage not in DEPLOY_PROJECTED_STAGE_IDS and stage not in DEPLOY_RUNNER_STAGE_IDS
)

#: What a reader watches while a deployment run is in flight.
DEPLOY_GENERATING_STAGE_IDS: tuple[DeployStageId, ...] = DEPLOY_ARTEFACT_STAGE_IDS

#: One kind per stage that writes something, plus the two the runner writes.
#: `deploy-plan` and `feedback` keep the names their drafts already had.
DeployArtefactKind = Literal[
    "dependency-updates",
    "changelog-report",
    "impact-report",
    "risk-report",
    "pipeline-config",
    "deploy-plan",
    "release-candidate",
    "rollback-plan",
    "monitoring-report",
    "feedback",
]

DEPLOY_ARTEFACT_KINDS: tuple[DeployArtefactKind, ...] = get_args(DeployArtefactKind)

#: What the deployment gate freezes once it approves a version. The monitoring
#: report and the feedback derived from it are written after the approval by
#: design, so freezing them would forbid the thing they exist to record.
DEPLOY_GATED_ARTEFACT_KINDS: tuple[DeployArtefactKind, ...] = tuple(
    kind for kind in DEPLOY_ARTEFACT_KINDS if kind not in ("monitoring-report", "feedback")
)

#: Human choices on the deploy axis, stored as overlays so the reports stay as
#: the analysis produced them. A decision about an update sits beside the risk
#: report and never inside it: a level a person could edit would stop being the
#: rule's level.
DeployOverlayKind = Literal[
    "update_decision",
    "update_scope",
    "release_target",
    "release_policy",
    "rollback_decision",
    "feedback_decision",
]

DEPLOY_OVERLAY_KINDS: tuple[DeployOverlayKind, ...] = get_args(DeployOverlayKind)

#: One dependency update, named by a hash of what it is.
#:
#: The readable name (`npm:@vitejs/plugin-react@4.3.0->5.0.1`) travels beside it
#: as the update's key. The id is not the key itself because a scoped npm name
#: holds a slash and every decision route puts the id in a path. Hashing the key
#: rather than numbering updates keeps a decision about the same update
#: attached to it across deploy versions.
UpdateId = Annotated[str, Field(pattern=r"^u-[0-9a-f]{12}$")]
