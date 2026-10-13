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
    BacklogDependency,
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


#: How many areas of work a goal names before it counts the rest.
_AREAS_NAMED = 3


def _listed(names: list[str]) -> str:
    """Up to three names as a phrase, and a count of the rest."""
    shown, rest = names[:_AREAS_NAMED], len(names) - _AREAS_NAMED
    if rest > 0:
        return f"{', '.join(shown)} and {rest} more area{'s' if rest > 1 else ''}"
    if len(shown) == 1:
        return shown[0]
    return f"{', '.join(shown[:-1])} and {shown[-1]}"


def sprint_goal(proposed: list[UserStory]) -> str:
    """What this sprint delivers, said from the stories it took on.

    Written here, after the split, rather than by the model before it: the
    model's sentence described every story it had written, so a sprint that took
    on one of three said it delivered all three (review item C1-5). The areas
    are the stories' epics, in the order the sprint takes them, and the first
    story is the highest priority one, which is what the sprint is for.
    """
    areas: dict[str, str] = {}
    for story in proposed:
        areas.setdefault(story.epic.strip().lower(), story.epic.strip())
    first = proposed[0].title.strip().rstrip(".")
    if len(proposed) == 1:
        return f"Deliver {_listed(list(areas.values()))}: {first}."
    return (
        f"Deliver {_listed(list(areas.values()))}, {len(proposed)} stories, starting with: {first}."
    )


#: The connections a story needs both ends of. A constraint edge says which rule
#: binds a node, which is not something to build first.
_NEEDED_EDGES = frozenset({"action", "data", "dependency"})
#: What a story builds. An actor is a person or somebody else's system.
_BUILT_KINDS = frozenset({"entity", "service"})


def backlog_dependencies(
    proposed: list[UserStory], backlog: list[UserStory], graph: ArchitectureGraph
) -> list[BacklogDependency]:
    """The sprint's stories that need something only a backlog story builds.

    The sprint is divided by priority and size, and neither knows what a story
    stands on (review item C1-5). The design does: a connection carries the
    requirements that drew it, so a story realising one of them needs both of
    its ends. An end is built by the sprint when a story in the sprint realises
    a requirement the node traces to. When none does, and a backlog story does,
    the sprint cannot be finished as proposed without that story.

    Reported rather than repaired. Moving the backlog story in would put a lower
    priority ahead of what the velocity left out, which is a decision for the
    person reading the plan.
    """
    delivered = {trace for story in proposed for trace in story.traces}
    nodes = {node.id: node for node in graph.nodes}

    found: dict[tuple[str, str], BacklogDependency] = {}
    for story in proposed:
        mine = set(story.traces)
        for edge in graph.edges:
            if edge.kind not in _NEEDED_EDGES or not mine & set(edge.traces):
                continue
            source, target = nodes.get(edge.source), nodes.get(edge.target)
            if source is None or target is None:
                # An edge to nothing is the graph rules' finding, not this one.
                continue
            for end in (source, target):
                if end.kind not in _BUILT_KINDS or delivered & set(end.traces):
                    continue
                for waiting in backlog:
                    if set(waiting.traces) & set(end.traces):
                        found.setdefault(
                            (story.id, waiting.id),
                            BacklogDependency(
                                storyId=story.id,
                                needs=waiting.id,
                                because=(
                                    f"{source.label} {edge.verb} {target.label}, and nothing "
                                    f"in this sprint builds {end.label}"
                                ),
                            ),
                        )
    return list(found.values())


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
        goal=sprint_goal(proposed),
        velocityAssumption=VelocityAssumption(points=velocity, basis=VELOCITY_BASIS),
        estimatedPoints=spent,
        proposed=proposed,
        backlog=backlog,
        backlogDependencies=backlog_dependencies(proposed, backlog, graph),
    )
