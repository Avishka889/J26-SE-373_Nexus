"""Which stories are in this build. Rules only, derived from the approved plan.

The default scope is the sprint plan's proposed list, which is what "sprint 1"
means in the plan C1 shipped. Every story row carries its traces both ways:
requirement ids from the story itself, screen ids through the coverage rows,
so the contract generator downstream can slice screens by scope without
guessing, and a story that maps to nothing is visible as exactly that.

The human toggles stories in the stage afterwards; that is an overlay, not a
regeneration of this artefact, so what the rules derived stays on record.
"""

from sdlc_contracts import (
    GraphEdge,
    ScopeStory,
    ScopeStoryTraces,
    SprintPlan,
    SprintScope,
    WireframesArtefact,
)


def derive_scope(sprint: SprintPlan, wireframes: WireframesArtefact) -> SprintScope:
    """The proposed stories in scope, the backlog out, traces attached."""
    screens_by_story: dict[str, list[str]] = {
        row.story_id: list(row.screen_ids) for row in wireframes.coverage
    }

    def story_row(story, in_scope: bool) -> ScopeStory:
        return ScopeStory(
            id=story.id,
            title=story.title,
            points=story.points,
            in_scope=in_scope,
            decided_by="system default",
            traces=ScopeStoryTraces(
                requirement_ids=list(story.traces),
                screen_ids=screens_by_story.get(story.id, []),
            ),
        )

    stories = [story_row(story, True) for story in sprint.proposed] + [
        story_row(story, False) for story in sprint.backlog
    ]
    return SprintScope(sprint_name=sprint.sprint_name, stories=stories)


def scoped_screen_ids(scope: SprintScope) -> list[str]:
    """Every screen an in scope story reaches, deduplicated, order kept."""
    seen: dict[str, None] = {}
    for story in scope.stories:
        if not story.in_scope:
            continue
        for screen_id in story.traces.screen_ids:
            seen.setdefault(screen_id, None)
    return list(seen)


def scoped_requirement_ids(scope: SprintScope) -> list[str]:
    seen: dict[str, None] = {}
    for story in scope.stories:
        if not story.in_scope:
            continue
        for requirement_id in story.traces.requirement_ids:
            seen.setdefault(requirement_id, None)
    return list(seen)


def scoped_actions(edges: list[GraphEdge], scope: SprintScope) -> list[GraphEdge]:
    """The action edges this build may take: an action belongs to the sprint whose stories trace it.

    One that only backlog stories trace waits for its sprint. Taking every
    action on an entity the sprint already shows built the backlog a sprint
    early, so planning the next sprint added nothing. One that no story traces
    at all goes with its entity, as before, or no sprint would ever build it.
    """
    in_scope = set(scoped_requirement_ids(scope))
    claimed = {rid for story in scope.stories for rid in story.traces.requirement_ids}
    return [
        edge
        for edge in edges
        if edge.kind == "action" and (set(edge.traces) & in_scope or not set(edge.traces) & claimed)
    ]
