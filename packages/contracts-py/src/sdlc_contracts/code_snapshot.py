"""The code phase snapshot: a view model, not a cross service seam.

The browser reads the code phase the way it reads the design phase: one
payload, every mutation answering with the whole of it. Stage states, the
gate, the artefacts by kind, the scope, the contract diff and the thread are
composed here; file bodies are deliberately absent, because the client polls
this every 1.2 seconds while anything is generating and a run writes tens of
source files. Bodies live behind their own route.

Two versions ride along and they are different axes: `codeVersion` is this
phase's own counter, `designVersion` is the upstream one, and
`generatedFromDesignVersion` is the upstream version the artefacts were read
from, so "the design moved on" is a derivable fact rather than a stored flag.
"""

from typing import Literal

from pydantic import Field, model_validator

from .api_contract import ApiContractArtefact, ContractDiff
from .code_repository import CodeRepository
from .contract_agreement import ContractAgreement
from .ids import CODE_STAGE_IDS, CodeStageId, StoryId
from .model_use import StageModelUse
from .requirements import RequirementPriority
from .run_status import RunStatus
from .snapshot import GateState
from .sprint_scope import SprintScope
from .tech_stack import TechStackArtefact
from .wire import WireDatetime, WireModel

CodeStageStatus = Literal["pending", "generating", "complete", "failed"]
CodeThreadKind = Literal["user_note", "answer", "stage_summary", "system"]


class CodeStageState(WireModel):
    id: CodeStageId
    status: CodeStageStatus = "pending"
    #: The code version this stage was generated at. Zero means never.
    generated_from_version: int = Field(default=0, ge=0)
    generated_at: WireDatetime | None = None
    summary: str | None = None
    error: str | None = None
    #: What answered this stage's current version, where it asked a model (0015).
    model_use: StageModelUse | None = None

    @model_validator(mode="after")
    def failure_says_why(self) -> "CodeStageState":
        if self.status == "failed" and not self.error:
            raise ValueError(f"stage {self.id} failed without saying why")
        if self.status != "failed" and self.error:
            raise ValueError(f"stage {self.id} is {self.status} but carries an error")
        return self


class CodeThreadMessage(WireModel):
    id: str = Field(min_length=1)
    kind: CodeThreadKind
    stage_id: CodeStageId | None = None
    author: str = Field(min_length=1)
    content: str = Field(min_length=1)
    at: WireDatetime
    #: The code version a change producing message opened. Null on the rest.
    produced_version: int | None = None


class NextSprintStory(WireModel):
    id: StoryId
    title: str = Field(min_length=1)
    points: int = Field(ge=0)
    priority: RequirementPriority


class NextSprint(WireModel):
    """What planning the next sprint would add to the build, shown before anyone asks.

    Divided as the sprint plan divides one: the stories out of the build in
    priority order, up to the velocity assumption, stopping at the first that
    does not fit. Empty when every story is in the build.
    """

    number: int = Field(ge=1)
    stories: list[NextSprintStory] = Field(default_factory=list)
    points: int = Field(ge=0)
    velocity: int = Field(gt=0)
    #: Where the velocity came from, said beside it as the sprint plan says it.
    velocity_basis: str = Field(min_length=1)

    @model_validator(mode="after")
    def points_are_the_stories(self) -> "NextSprint":
        total = sum(story.points for story in self.stories)
        if self.points != total:
            raise ValueError(f"points is {self.points} but the stories total {total}")
        return self


class CodeSnapshot(WireModel):
    project_id: str = Field(min_length=1)
    #: This phase's own version counter. Zero before the first run.
    code_version: int = Field(ge=0)
    #: The design axis, for the staleness fact.
    design_version: int = Field(ge=0)
    generated_from_design_version: int = Field(ge=0)
    #: Why code cannot be generated from the design now (it was never approved,
    #: it changed and waits on its review, or it is being regenerated); null
    #: when the current design version is approved and settled.
    design_blocker: str | None = None
    stages: dict[CodeStageId, CodeStageState]
    scope: SprintScope | None = None
    #: The sprint "Plan the next sprint" would add, from the current design
    #: version's sprint plan. Null before a scope exists or without a plan.
    next_sprint: NextSprint | None = None
    tech_stack: TechStackArtefact | None = None
    contract: ApiContractArtefact | None = None
    agreement: ContractAgreement | None = None
    repository: CodeRepository | None = None
    #: Between the two most recent contract versions. Null before version 2.
    diff: ContractDiff | None = None
    gate: GateState
    #: The approved version whose review covers this one, when an accepted
    #: security fix wrote it: such a version has no review of its own, and
    #: counts as approved when the version it patched was. Null for a version
    #: with a review of its own, decided or not.
    approved_through: int | None = None
    #: The phase's newest full run, so a run that stopped short of the review
    #: says so here rather than only in the audit log. None before any ran.
    run: RunStatus | None = None
    thread: list[CodeThreadMessage] = Field(default_factory=list)

    @model_validator(mode="after")
    def every_stage_is_present(self) -> "CodeSnapshot":
        """The client indexes `stages[id]` for all eight with no null guard."""
        missing = [stage for stage in CODE_STAGE_IDS if stage not in self.stages]
        if missing:
            raise ValueError(f"snapshot is missing stages: {', '.join(missing)}")
        return self
