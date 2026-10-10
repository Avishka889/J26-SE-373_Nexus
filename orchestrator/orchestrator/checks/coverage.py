"""Which stories have a screen, derived when the snapshot is read.

Both fields here are computed rather than stored, and the reason is the same one
that keeps `outdated` and `progress` off the wire: a stored copy of a
relationship between two artefacts goes stale the moment either of them is
regenerated, and it goes stale silently.

`coversStoryIds` is one of them, which is easy to miss because it is a field on
the stored flow. Nothing writes it. Wireframes are generated before the sprint
plan exists and from the graph rather than from the stories, so the component
that draws a flow has no story to name. The link is trace overlap: both sides
independently said which requirements they serve, and where those overlap the
same piece of the system is being planned and drawn.

That independence is what makes the number worth having. A flow told which story
to satisfy would have said it satisfied it.
"""

import re

from sdlc_contracts import (
    ArchitectureGraph,
    SprintPlan,
    UserStory,
    WireframeCoverageRow,
    WireframesArtefact,
)

#: "As a Delivery Driver, ..." and "As an operator, ...".
_ROLE = re.compile(r"^\s*As\s+(?:an?|the)\s+([^,]+),", re.IGNORECASE)


#: Roles that name software rather than a person. "As the system, I quarantine
#: the consignment" is how honest background work should read, and "As a calling
#: system" is another service.
_NOT_A_PERSON = frozenset({"system", "platform", "service"})


def needs_a_screen(story: UserStory, graph: ArchitectureGraph | None) -> bool:
    """Whether it makes sense to expect a screen for this story.

    Only three things say no: a story written from nobody's point of view, one
    whose role is software, and one performed by another system the design names
    as external. Everything else is somebody's story and is scored.

    Deliberately conservative, and the first attempt was not. Requiring the role
    to match a `primary` actor exactly looked more accurate on one run and hid
    real gaps on others: a design whose actors are "Clinician" and
    "Administrator" has stories about a doctor and a compliance officer, and
    matching on the label excused all of them from coverage. A near miss in
    wording is not evidence that nobody performs the story, and a coverage table
    that quietly drops what it could not recognise is the failure this metric
    exists to prevent.

    So the graph is consulted for one thing only: whether the role is a system
    this design already knows is external. Everything human, named in the graph
    or not, keeps its row in the score.
    """
    match = _ROLE.match(story.title)
    if match is None:
        # No role at all: it is not written as anyone's story.
        return False

    role = match.group(1).strip().lower()
    if role in _NOT_A_PERSON or role.endswith(" system"):
        return False

    if graph is not None:
        external = {
            node.label.strip().lower()
            for node in graph.nodes
            if node.kind == "actor" and node.actor_kind == "external_system"
        }
        if role in external:
            return False

    return True


def stories_of(sprint: SprintPlan | None) -> list[UserStory]:
    """Every story in the plan, sprint first, in the order a reader sees them."""
    if sprint is None:
        return []
    return [*sprint.proposed, *sprint.backlog]


def with_coverage(
    wireframes: WireframesArtefact,
    sprint: SprintPlan | None,
    graph: ArchitectureGraph | None = None,
) -> WireframesArtefact:
    """The flows with their covered stories filled in, and the table beside them."""
    stories = stories_of(sprint)
    flows = [
        flow.model_copy(
            update={
                "covers_story_ids": [
                    story.id for story in stories if set(flow.traces) & set(story.traces)
                ]
            }
        )
        for flow in wireframes.flows
    ]

    rows = [
        WireframeCoverageRow(
            storyId=story.id,
            storyTitle=story.title,
            # Composite `flowId/screenId`, so a screen id is unambiguous across
            # flows that both number their screens from one.
            screenIds=(
                screens := [
                    f"{flow.id}/{screen.id}"
                    for flow in flows
                    if story.id in flow.covers_story_ids
                    for screen in flow.screens
                ]
            ),
            covered=bool(screens),
            needsScreen=needs_a_screen(story, graph),
        )
        # Every story gets a row, including the ones with no screen and the ones
        # that should not have one. A table listing only what was covered reads a
        # hundred percent every time, and one that silently drops what it could
        # not classify hides the classification instead of the gap.
        for story in stories
    ]

    return wireframes.model_copy(update={"flows": flows, "coverage": rows})
