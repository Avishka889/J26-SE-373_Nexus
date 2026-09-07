"""The sprint plan.

A design phase plans work; it does not report on it. There is no burndown here,
no completed points and no per person allocation, because nothing has been built
yet and showing progress against unwritten code is fiction.

Acceptance criteria are contract rather than description: C3 turns them into
test cases, so their shape is load bearing.
"""

from pydantic import Field, model_validator

from .ids import StoryId, Traces
from .requirements import RequirementPriority
from .wire import Prose, WireModel

_PRIORITY_RANK: dict[str, int] = {"must": 0, "should": 1, "could": 2}


class AcceptanceCriterion(WireModel):
    id: str = Field(min_length=1)
    given: Prose = Field(min_length=1)
    when: Prose = Field(min_length=1)
    then: Prose = Field(min_length=1)


class UserStory(WireModel):
    id: StoryId
    title: Prose = Field(min_length=1)
    epic: str = Field(min_length=1)
    #: Estimated, never actual.
    points: int = Field(gt=0)
    priority: RequirementPriority
    traces: Traces
    #: At least one, because a story C3 cannot derive a test from is a story
    #: nobody can tell is finished.
    acceptance: list[AcceptanceCriterion] = Field(min_length=1)


class VelocityAssumption(WireModel):
    points: int = Field(gt=0)
    #: Says out loud where the number came from, because on a new project it is
    #: an assumption rather than a measurement.
    basis: str = Field(min_length=1)


class SprintPlan(WireModel):
    sprint_name: str = Field(min_length=1)
    goal: Prose = Field(min_length=1)
    velocity_assumption: VelocityAssumption
    estimated_points: int = Field(ge=0)
    proposed: list[UserStory] = Field(default_factory=list)
    backlog: list[UserStory] = Field(default_factory=list)

    @model_validator(mode="after")
    def story_ids_are_unique(self) -> "SprintPlan":
        ids = [s.id for s in (*self.proposed, *self.backlog)]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(f"duplicate story ids: {', '.join(duplicates)}")
        return self

    @model_validator(mode="after")
    def estimated_points_match_the_proposal(self) -> "SprintPlan":
        total = sum(s.points for s in self.proposed)
        if self.estimated_points != total:
            raise ValueError(
                f"estimatedPoints is {self.estimated_points} but the proposed stories total {total}"
            )
        return self

    @model_validator(mode="after")
    def both_lists_run_by_priority(self) -> "SprintPlan":
        """The UI states they are ordered by priority, so they have to be."""
        for label, stories in (("proposed", self.proposed), ("backlog", self.backlog)):
            ranks = [_PRIORITY_RANK[s.priority] for s in stories]
            if ranks != sorted(ranks):
                raise ValueError(f"{label} stories are not ordered by priority")
        return self
