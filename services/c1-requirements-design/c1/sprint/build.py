"""Turning a draft plan into the contract type, and deciding every number on the way.

Ids in sequence, priority inherited, points counted, and the sprint filled to the
velocity assumption in priority order. None of it is asked of the model, and all
of it is reproducible from the same input.

The split stops at the first story that does not fit rather than packing the
sprint with whatever else is small enough. Packing would deliver more points and
would put a could-have in the sprint while a must-have sat in the backlog, which
is a worse plan that measures better. Stopping keeps the sprint strictly
highest-priority-first, which is what a reader assumes when they see the two
lists.

One story is always proposed, even when it is bigger than the whole velocity
assumption. An empty sprint is not a plan, and the honest way to show a story
nobody can fit is to plan it and let the "too big to plan" warning say so.
"""

from sdlc_contracts import (
    AcceptanceCriterion,
    ArchitectureGraph,
    ParsedRequirement,
    SprintPlan,
    UserStory,
    VelocityAssumption,
)

from .estimate import Estimate, estimate_story, priority_of
from .schema import DraftPlan, DraftStory

#: A planning placeholder, not a measurement, and the basis below says so in the
#: artefact itself. There is no delivered sprint to measure on a new project, and
#: a figure derived from the design would be worse: it would look computed.
DEFAULT_VELOCITY = 20
VELOCITY_BASIS = (
    "assumed, not measured: this project has delivered no sprint yet, so this is a "
    "planning placeholder to divide the work against rather than a team's observed rate"
)

_PRIORITY_RANK = {"must": 0, "should": 1, "could": 2}


def _story(
    draft: DraftStory,
    *,
    number: int,
    priority: str,
    estimate: Estimate,
) -> UserStory:
    story_id = f"US-{number}"
    return UserStory(
        id=story_id,
        title=draft.title,
        epic=draft.epic,
        points=estimate.points,
        priority=priority,  # type: ignore[arg-type]
        traces=list(draft.traces),
        acceptance=[
            AcceptanceCriterion(
                id=f"AC-{number}-{index}",
                given=criterion.given,
                when=criterion.when,
                then=criterion.then,
            )
            for index, criterion in enumerate(draft.acceptance, start=1)
        ],
    )


def to_contract(
    draft: DraftPlan,
    *,
    requirements: list[ParsedRequirement],
    graph: ArchitectureGraph,
    sprint_name: str = "Sprint 1 (proposed)",
    velocity: int = DEFAULT_VELOCITY,
) -> SprintPlan:
    """The plan as the artefact stores it, with every number decided here."""
    ranked = sorted(
        enumerate(draft.stories),
        # Priority first, then the order they were written, so two runs over the
        # same draft produce the same plan. There is no second ranking dimension
        # to invent.
        key=lambda pair: (_PRIORITY_RANK[priority_of(pair[1], requirements)], pair[0]),
    )

    proposed: list[UserStory] = []
    backlog: list[UserStory] = []
    spent = 0
    full = False
    for number, (_position, drafted) in enumerate(ranked, start=1):
        story = _story(
            drafted,
            number=number,
            priority=priority_of(drafted, requirements),
            estimate=estimate_story(drafted, graph=graph, requirements=requirements),
        )
        # Always take the first, however big: an empty sprint is not a plan, and
        # the rules already warn when a story is too big to size.
        fits = not proposed or spent + story.points <= velocity
        if full or not fits:
            # Everything after the first story that does not fit goes to the
            # backlog, even if it would have fitted. Slotting a smaller
            # lower-priority story in around the one that overflowed delivers
            # more points and makes a worse plan.
            full = True
            backlog.append(story)
        else:
            proposed.append(story)
            spent += story.points

    return SprintPlan(
        sprintName=sprint_name,
        goal=draft.goal,
        velocityAssumption=VelocityAssumption(points=velocity, basis=VELOCITY_BASIS),
        estimatedPoints=spent,
        proposed=proposed,
        backlog=backlog,
    )
