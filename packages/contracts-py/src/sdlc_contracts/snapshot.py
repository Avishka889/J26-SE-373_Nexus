"""The design snapshot: a view model, not a cross service seam.

Each artefact is stored and validated separately, and C2 consumes the
architecture graph alone. This bundles all of them plus run, gate, stage and
thread state into the one payload the browser reads, because every mutation
answers with a whole snapshot and that is what keeps the client simple.

Two fields the wire deliberately does not carry:

- "outdated" per stage. The client computes it as
  `generatedFromVersion < requirementsVersion`, so the two can never disagree.
- progress. Derived from stage statuses and the gate decision, for the same
  reason.
"""

from typing import Literal

from pydantic import Field, model_validator

from .architecture import ArchitectureRecommendation
from .ids import DESIGN_STAGE_IDS, DesignStageId, QuestionId, Traces
from .model_use import StageModelUse
from .requirements import Assumption, ClarifyingQuestion, ParsedRequirement
from .run_status import RunStatus
from .sag import ArchitectureGraph
from .sprint import SprintPlan
from .uml import UmlArtefact
from .wire import WireDatetime, WireModel
from .wireframes import WireframesArtefact

StageStatus = Literal["pending", "generating", "complete", "failed"]
ThreadMessageKind = Literal["user_note", "answer", "stage_summary", "system"]
GateDecisionKind = Literal["approved", "changes"]


class StageState(WireModel):
    id: DesignStageId
    status: StageStatus = "pending"
    #: The requirements version this stage was generated from. Zero means never.
    generated_from_version: int = Field(default=0, ge=0)
    generated_at: WireDatetime | None = None
    #: The one line posted into the thread when the stage finished.
    summary: str | None = None
    #: Plain words, set only when the status is failed.
    error: str | None = None
    #: What answered this stage's current version, where it asked a model (0015).
    model_use: StageModelUse | None = None

    @model_validator(mode="after")
    def failure_says_why(self) -> "StageState":
        if self.status == "failed" and not self.error:
            raise ValueError(f"stage {self.id} failed without saying why")
        if self.status != "failed" and self.error:
            raise ValueError(f"stage {self.id} is {self.status} but carries an error")
        return self


class GateDecision(WireModel):
    kind: GateDecisionKind
    at: WireDatetime
    by: str = Field(min_length=1)
    #: The requirements version this decision covers, and nothing later. When
    #: the requirements move on, the decision goes to history and the phase asks
    #: again.
    version: int = Field(ge=1)
    note: str | None = None

    @model_validator(mode="after")
    def changes_come_with_a_reason(self) -> "GateDecision":
        if self.kind == "changes" and not self.note:
            raise ValueError("requesting changes without saying what to change is not a decision")
        return self


class GateState(WireModel):
    decision: GateDecision | None = None
    history: list[GateDecision] = Field(default_factory=list)


class ConsistencyFinding(WireModel):
    """Something two artefacts disagree about, for the reader at the gate.

    Separate from `ValidationFinding`, which is carried on a single node and says
    that one thing could not be confirmed. This is about the design as a whole:
    a must-have with no story, a diagram naming a node the graph no longer has.
    Neither can be seen from inside the artefact it concerns, and both are read
    at the moment somebody decides whether to approve.

    Derived at read time and never stored. It is a statement about the current
    set of artefacts, so a stored copy would go stale exactly when it mattered:
    the moment one of them is regenerated.
    """

    rule_id: str = Field(min_length=1)
    #: `error` means the design has a defect worth fixing before approving.
    #: `warning` means worth knowing. Neither blocks the gate: approving is a
    #: human decision, and a check that refused would be the tool overruling the
    #: person it exists to inform.
    severity: Literal["error", "warning"]
    #: Written for the person deciding, in plain words.
    reason: str = Field(min_length=1)
    #: The requirements this concerns, so it links somewhere useful.
    traces: Traces
    #: Where to go and fix it, which is rarely the page this is read on.
    stage_id: DesignStageId | None = None


class AskedQuestion(WireModel):
    """The question an answer in the conversation answers, as the design asked it."""

    id: QuestionId
    question: str = Field(min_length=1)
    traces: Traces
    #: When the design asked it: when the requirements version it belongs to was written.
    asked_at: WireDatetime


class DesignThreadMessage(WireModel):
    id: str = Field(min_length=1)
    kind: ThreadMessageKind
    stage_id: DesignStageId | None = None
    author: str = Field(min_length=1)
    content: str = Field(min_length=1)
    at: WireDatetime
    #: The requirements version this message opened, for the note that caused one.
    #: Null on everything else, which is most messages. Recorded rather than
    #: inferred from position: the reader needs to see which change produced which
    #: version, and counting user messages down the transcript gets that wrong the
    #: moment an answer or a correction sits between two change notes.
    produced_version: int | None = None
    #: On an answer, the question it answers, from the version it was asked in, so
    #: the conversation keeps the question with its answer: an answered question
    #: is no longer open, and its words alone said nothing of what they answered.
    #: Null on every other message, and on an answer no record pairs with.
    question: AskedQuestion | None = None


class DesignSnapshot(WireModel):
    project_id: str = Field(min_length=1)
    #: The product being designed, which the wireframe player uses as the first
    #: breadcrumb rather than a name baked into a fixture.
    app_name: str = Field(min_length=1)
    requirements_version: int = Field(ge=0)
    stages: dict[DesignStageId, StageState]
    requirements: list[ParsedRequirement] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    questions: list[ClarifyingQuestion] = Field(default_factory=list)
    graph: ArchitectureGraph
    architecture: ArchitectureRecommendation | None = None
    uml: UmlArtefact
    wireframes: WireframesArtefact
    sprint: SprintPlan | None = None
    gate: GateState
    #: The phase's newest full run, so a run that stopped short of the review
    #: says so here rather than only in the audit log. None before any ran.
    run: RunStatus | None = None
    thread: list[DesignThreadMessage] = Field(default_factory=list)
    #: Change notes waiting, oldest first: they arrived while a run was in
    #: flight or a review was pending, and they apply, as one new version, when
    #: the review is decided. Shown so approving never regenerates unannounced.
    queued_changes: list[str] = Field(default_factory=list)
    #: The run is paused after Requirements Analysis on the questions it asked,
    #: and the rest of the design waits until the reader continues with the
    #: answers or with the assumptions.
    questions_pending: bool = False
    #: Where the artefacts disagree with each other. Derived at read time
    #: from the whole set, never stored, because it stops being true the
    #: moment one of them is regenerated.
    consistency: list[ConsistencyFinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def every_stage_is_present(self) -> "DesignSnapshot":
        """The client indexes `stages[id]` for all eight with no null guard, so
        a missing key is a crash rather than a blank."""
        missing = [stage for stage in DESIGN_STAGE_IDS if stage not in self.stages]
        if missing:
            raise ValueError(f"snapshot is missing stages: {', '.join(missing)}")
        return self
