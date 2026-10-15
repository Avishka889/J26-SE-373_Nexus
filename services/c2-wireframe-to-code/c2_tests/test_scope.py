"""Scope is derived, traced both ways, and slices without guessing."""

from c2.rules.scope import derive_scope, scoped_requirement_ids, scoped_screen_ids
from sdlc_contracts import (
    AcceptanceCriterion,
    SprintPlan,
    UserStory,
    VelocityAssumption,
    WireframeCoverageRow,
    WireframesArtefact,
)


def _story(id: str, title: str, points: int = 3, traces: list[str] | None = None) -> UserStory:
    return UserStory(
        id=id,
        title=title,
        epic="Ordering",
        points=points,
        priority="must",
        traces=traces or ["R-1"],
        acceptance=[
            AcceptanceCriterion(
                id=f"{id}-a1",
                given="a signed in shopper",
                when="they complete the flow",
                then="the result is recorded",
            )
        ],
    )


def _plan() -> SprintPlan:
    return SprintPlan(
        sprint_name="Sprint 1 (proposed)",
        goal="Orders flow end to end.",
        velocity_assumption=VelocityAssumption(points=20, basis="assumed for a first sprint"),
        estimated_points=3,
        proposed=[_story("US-1", "Browse the catalog", traces=["R-1", "R-2"])],
        backlog=[_story("US-2", "Monthly report", points=5, traces=["R-9"])],
    )


def _wireframes() -> WireframesArtefact:
    return WireframesArtefact(
        flows=[],
        coverage=[
            WireframeCoverageRow(
                story_id="US-1",
                story_title="Browse the catalog",
                screen_ids=["shop/catalog", "shop/product"],
                covered=True,
            ),
            WireframeCoverageRow(
                story_id="US-2",
                story_title="Monthly report",
                screen_ids=[],
                covered=False,
                needs_screen=False,
            ),
        ],
    )


class TestDeriveScope:
    def test_proposed_is_in_and_backlog_is_out(self) -> None:
        scope = derive_scope(_plan(), _wireframes())
        by_id = {story.id: story for story in scope.stories}
        assert by_id["US-1"].in_scope is True
        assert by_id["US-2"].in_scope is False
        assert all(story.decided_by == "system default" for story in scope.stories)

    def test_traces_arrive_from_both_directions(self) -> None:
        scope = derive_scope(_plan(), _wireframes())
        story = next(s for s in scope.stories if s.id == "US-1")
        assert story.traces.requirement_ids == ["R-1", "R-2"]
        assert story.traces.screen_ids == ["shop/catalog", "shop/product"]

    def test_the_slices_read_only_what_is_in_scope(self) -> None:
        scope = derive_scope(_plan(), _wireframes())
        assert scoped_screen_ids(scope) == ["shop/catalog", "shop/product"]
        assert scoped_requirement_ids(scope) == ["R-1", "R-2"]

    def test_a_story_with_no_screens_is_visible_as_exactly_that(self) -> None:
        scope = derive_scope(_plan(), _wireframes())
        story = next(s for s in scope.stories if s.id == "US-2")
        assert story.traces.screen_ids == []
