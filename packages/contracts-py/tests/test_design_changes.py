"""What a design version changed since the one before (review item C1-6)."""

from sdlc_contracts import (
    AcceptanceCriterion,
    SprintPlan,
    UserStory,
    VelocityAssumption,
    diff_stories,
)


def _story(story_id: str, *, title: str = "A person adds a record", points: int = 3) -> UserStory:
    return UserStory(
        id=story_id,
        title=title,
        epic="Records",
        points=points,
        priority="must",
        traces=["R-1"],
        acceptance=[
            AcceptanceCriterion(
                id=f"AC-{story_id}", given="a record", when="they save it", then="it is kept"
            )
        ],
    )


def _plan(proposed: list[UserStory], backlog: list[UserStory] = ()) -> SprintPlan:
    return SprintPlan(
        sprint_name="Sprint 1",
        goal="Records",
        velocity_assumption=VelocityAssumption(points=20, basis="assumed"),
        estimated_points=sum(one.points for one in proposed),
        proposed=list(proposed),
        backlog=list(backlog),
    )


def test_stories_added_removed_and_changed_are_named_by_id() -> None:
    before = _plan([_story("US-1"), _story("US-2"), _story("US-3")])
    after = _plan([_story("US-1"), _story("US-2", points=5), _story("US-4")])

    diff = diff_stories(before, after)

    assert (diff.added, diff.removed, diff.changed) == (["US-4"], ["US-3"], ["US-2"])


def test_a_story_moved_out_of_the_sprint_is_a_change() -> None:
    before = _plan([_story("US-1"), _story("US-2")])
    after = _plan([_story("US-1")], backlog=[_story("US-2")])

    assert diff_stories(before, after).changed == ["US-2"]


def test_with_no_plan_before_every_story_is_new() -> None:
    assert diff_stories(None, _plan([_story("US-1")])).added == ["US-1"]
