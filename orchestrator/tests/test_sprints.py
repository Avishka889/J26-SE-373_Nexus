"""Dividing the next sprint as the sprint plan divides one, without a database.

C1 fills a sprint to the velocity assumption in priority order and stops at the
first story that does not fit, always taking one. The next sprint is divided
the same way from what is still out of the build, so these hold the same rules
and the decisions a person already made.
"""

from orchestrator.sprints import (
    StoryChoice,
    choice_of,
    latest_sprint,
    next_sprint,
    scope_name,
)
from sdlc_contracts import AcceptanceCriterion, SprintPlan, UserStory, VelocityAssumption


def _story(number: int, points: int, priority: str = "should") -> UserStory:
    return UserStory(
        id=f"US-{number}",
        title=f"Story {number}",
        epic="Records",
        points=points,
        priority=priority,  # type: ignore[arg-type]
        traces=["R-1"],
        acceptance=[
            AcceptanceCriterion(id=f"AC-{number}-1", given="a record", when="saved", then="kept")
        ],
    )


def _plan(*backlog: UserStory, velocity: int = 20) -> SprintPlan:
    first = _story(1, 5, "must")
    return SprintPlan(
        sprint_name="Sprint 1 (proposed)",
        goal="Records can be kept.",
        velocity_assumption=VelocityAssumption(points=velocity, basis="assumed, not measured"),
        estimated_points=first.points,
        proposed=[first],
        backlog=list(backlog),
    )


class TestADecisionAsStored:
    def test_a_bare_in_was_the_first_sprints(self) -> None:
        assert choice_of(True) == StoryChoice(True, 1)
        assert choice_of(False) == StoryChoice(False, 0)

    def test_a_decision_names_its_sprint(self) -> None:
        assert choice_of({"inScope": True, "sprint": 3}) == StoryChoice(True, 3)
        assert choice_of({"inScope": True}) == StoryChoice(True, 1)
        assert choice_of({"inScope": False, "sprint": 2}) == StoryChoice(False, 0)


class TestTheNextSprint:
    def test_it_fills_to_the_velocity_and_stops_at_the_first_that_does_not_fit(self) -> None:
        """US-5 would fit after US-4 overflows, and is left for later all the same."""
        plan = _plan(_story(2, 8), _story(3, 8), _story(4, 8), _story(5, 3))

        sprint = next_sprint(plan, {})

        assert sprint.number == 2
        assert [story.id for story in sprint.stories] == ["US-2", "US-3"]
        assert sprint.points == 16 and sprint.velocity == 20

    def test_it_always_takes_one_however_big(self) -> None:
        sprint = next_sprint(_plan(_story(2, 30)), {})

        assert [story.id for story in sprint.stories] == ["US-2"]

    def test_it_counts_on_from_the_newest_sprint_planned(self) -> None:
        plan = _plan(_story(2, 8), _story(3, 8), _story(4, 8))
        planned = {"US-2": StoryChoice(True, 2), "US-3": StoryChoice(True, 2)}

        sprint = next_sprint(plan, planned)

        assert sprint.number == 3
        assert [story.id for story in sprint.stories] == ["US-4"]

    def test_a_proposed_story_taken_out_comes_back_first(self) -> None:
        """The plan's order is its priority order, proposed stories first."""
        plan = _plan(_story(2, 8))

        sprint = next_sprint(plan, {"US-1": StoryChoice(False, 0)})

        assert [story.id for story in sprint.stories] == ["US-1", "US-2"]

    def test_with_every_story_in_the_build_it_is_empty(self) -> None:
        sprint = next_sprint(_plan(_story(2, 8)), {"US-2": StoryChoice(True, 2)})

        assert sprint.stories == [] and sprint.points == 0

    def test_a_story_moved_in_on_its_own_joins_the_newest_sprint(self) -> None:
        plan = _plan(_story(2, 8), _story(3, 8))

        assert latest_sprint(plan, {}) == 1
        assert latest_sprint(plan, {"US-2": StoryChoice(True, 2)}) == 2


class TestWhatABuildIsCalled:
    def test_the_first_sprint_alone_keeps_the_plans_name(self) -> None:
        assert scope_name("Sprint 1 (proposed)", [1, 1]) == "Sprint 1 (proposed)"
        assert scope_name("Sprint 1 (proposed)", []) == "Sprint 1 (proposed)"

    def test_more_than_one_sprint_is_named_by_each(self) -> None:
        assert scope_name("Sprint 1 (proposed)", [1, 2, 2]) == "Sprints 1 and 2"
        assert scope_name("Sprint 1 (proposed)", [3, 1, 2]) == "Sprints 1, 2 and 3"
        assert scope_name("Sprint 1 (proposed)", [2]) == "Sprint 2"
