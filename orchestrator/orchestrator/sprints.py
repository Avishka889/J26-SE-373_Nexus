"""Planning the next sprint from the backlog, and naming what a build covers.

C1 divides the stories between the first sprint and the backlog by the
velocity assumption, in priority order, stopping at the first story that does
not fit (`c1/sprint/build.py`). The code phase builds the first sprint.
Planning the next one takes the stories still out of the build the same way,
so sprint 2 is what the sprint plan would have proposed next, and then
generates the code once, for all of it: the build grows by an increment rather
than being replaced by the next sprint alone.

A person's decision about a story is an overlay beside the scope
(`story_scope`), which the scope stage reads. It was a bare in or out; it now
records the sprint the story was planned in as well, and both shapes are read.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from sdlc_contracts import NextSprint, NextSprintStory, SprintPlan


@dataclass(frozen=True)
class StoryChoice:
    """A person's decision about one story: in the build or not, and in which sprint."""

    in_scope: bool
    #: The sprint it was planned in, 0 when it is out of the build.
    sprint: int


def choice_of(value: Any) -> StoryChoice:
    """A stored decision, in either shape.

    A bare in or out was made before sprints were counted, when what was in
    the build was the first sprint's.
    """
    if isinstance(value, dict):
        in_scope = bool(value.get("inScope"))
        return StoryChoice(in_scope, max(int(value.get("sprint") or 1), 1) if in_scope else 0)
    in_scope = bool(value)
    return StoryChoice(in_scope, 1 if in_scope else 0)


def choice_value(choice: StoryChoice) -> dict[str, Any]:
    """A decision as the overlay stores it."""
    return {"inScope": choice.in_scope, "sprint": choice.sprint}


def latest_choices(overlay_rows: Iterable[Any]) -> dict[str, StoryChoice]:
    """Each story's newest decision across versions. Overlays come oldest first."""
    found: dict[str, StoryChoice] = {}
    for row in overlay_rows:
        if row["kind"] == "story_scope":
            found[row["target_id"]] = choice_of(row["value"])
    return found


def planned(plan: SprintPlan, choices: dict[str, StoryChoice]) -> dict[str, int]:
    """The sprint each of the plan's stories is planned in, 0 for one out of the build.

    The proposed stories are the first sprint and the backlog is out, until a
    person decides otherwise.
    """
    sprints: dict[str, int] = {}
    for default, stories in ((1, plan.proposed), (0, plan.backlog)):
        for story in stories:
            choice = choices.get(story.id)
            sprints[story.id] = choice.sprint if choice is not None else default
    return sprints


def latest_sprint(plan: SprintPlan, choices: dict[str, StoryChoice]) -> int:
    """The newest sprint anything is planned in, which a story moved in on its own joins."""
    return max(planned(plan, choices).values(), default=0) or 1


def next_sprint(plan: SprintPlan, choices: dict[str, StoryChoice]) -> NextSprint:
    """The next sprint as the sprint plan divides one.

    The stories out of the build, in the plan's order, which is priority order
    (the proposed list and then the backlog, as C1 split one ranked list), up
    to the velocity assumption. It stops at the first story that does not fit
    rather than packing smaller ones around it, and it always takes one, for
    the reasons C1 gives. Empty when every story is in the build.
    """
    sprints = planned(plan, choices)
    velocity = plan.velocity_assumption.points
    picked = []
    spent = 0
    for story in (*plan.proposed, *plan.backlog):
        if sprints[story.id]:
            continue
        if picked and spent + story.points > velocity:
            break
        picked.append(story)
        spent += story.points
    return NextSprint(
        number=max(sprints.values(), default=0) + 1,
        stories=[
            NextSprintStory(id=one.id, title=one.title, points=one.points, priority=one.priority)
            for one in picked
        ],
        points=spent,
        velocity=velocity,
        velocity_basis=plan.velocity_assumption.basis,
    )


def scope_name(plan_name: str, sprints: Iterable[int]) -> str:
    """What a build covers, by sprint: the plan's own name while it is the first sprint alone."""
    numbers = sorted({number for number in sprints if number > 0})
    if numbers in ([], [1]):
        return plan_name
    if len(numbers) == 1:
        return f"Sprint {numbers[0]}"
    return f"Sprints {', '.join(str(number) for number in numbers[:-1])} and {numbers[-1]}"
