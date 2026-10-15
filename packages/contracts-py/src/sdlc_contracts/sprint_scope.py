"""What this build covers: the sprint's stories, in or out, and why.

The first code stage's artefact. Derived by rules from the approved sprint
plan (sprint 1's proposed stories, by default) and traced to the screens that
cover each story, so "what is being built" is answerable before a line of it
exists.

Its own artefact rather than something recomputed on read, for the reason
every other artefact is one: the human moves stories in and out, and a scope
that was recomputed from the plan each time would silently discard that
decision the moment the plan changed underneath it. `decidedBy` is how a
reader tells the proposal from the choice.
"""

from typing import Any

from pydantic import Field, model_validator

from .ids import RequirementId, StoryId
from .wire import WireModel


class ScopeStoryTraces(WireModel):
    requirement_ids: list[RequirementId] = Field(default_factory=list)
    screen_ids: list[str] = Field(default_factory=list)


class ScopeStory(WireModel):
    """One story's place in the build: in or out, and why it maps anywhere."""

    id: StoryId
    title: str = Field(min_length=1)
    points: int = Field(ge=0)
    in_scope: bool
    #: The sprint it was planned in: 1 for the sprint plan's proposal, and the
    #: next number for each sprint planned from the backlog since. 0 when it is
    #: out of the build.
    sprint: int = Field(default=0, ge=0)
    #: Who put it in or out. "system default" for the sprint 1 proposal.
    decided_by: str = "system default"
    traces: ScopeStoryTraces = Field(default_factory=ScopeStoryTraces)

    @model_validator(mode="before")
    @classmethod
    def a_story_scoped_before_sprints_were_counted_is_sprint_ones(cls, data: Any) -> Any:
        """A scope stored before sprints were counted names none, and what was in it was sprint 1."""
        if isinstance(data, dict):
            in_scope = data.get("inScope", data.get("in_scope"))
            if in_scope and not data.get("sprint"):
                return {**data, "sprint": 1}
        return data

    @model_validator(mode="after")
    def a_story_out_of_the_build_is_in_no_sprint(self) -> "ScopeStory":
        if not self.in_scope and self.sprint:
            raise ValueError(f"{self.id} is out of the build but planned in sprint {self.sprint}")
        return self


class SprintScope(WireModel):
    sprint_name: str = Field(min_length=1)
    stories: list[ScopeStory] = Field(default_factory=list)

    @property
    def in_scope_ids(self) -> list[str]:
        return [story.id for story in self.stories if story.in_scope]
