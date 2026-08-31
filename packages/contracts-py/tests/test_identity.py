"""Ids that survive a regeneration, which is what makes the two diffs mean anything.

Every test here is an instance of one failure. C1 numbers requirements and
stories by position, the orchestrator stores a new version of both on every
change note, and `diff_requirements` and `diff_contracts` join the two versions
on the id. Reallocate an id in between and the join is not merely wrong: it
reports that everything changed, so the self healing classifier calls every
failing test brittle and the guard is handed repairs to tests that were catching
real breakage.

The scenario in the first test is the one that actually happened, transcribed
from the live run: a change note that said "everything else stays as it is" came
back with six requirements renumbered into five.
"""

import pytest
from sdlc_contracts import (
    AcceptanceCriterion,
    Assumption,
    ClarifyingQuestion,
    ParsedRequirement,
    RequirementsArtefact,
    SprintPlan,
    UserStory,
    VelocityAssumption,
    carry_requirement_ids,
    carry_story_ids,
    diff_requirements,
)
from sdlc_contracts.identity import SAME_THING_ABOVE, overlap


def requirements(*texts: str, ids: list[str] | None = None) -> RequirementsArtefact:
    """An artefact reading as C1 produces one: R-1 upward, in reading order."""
    return RequirementsArtefact(
        requirements=[
            ParsedRequirement(
                id=(ids[index] if ids else f"R-{index + 1}"),
                text=text,
                type="functional",
                priority="must",
                confidence=80,
            )
            for index, text in enumerate(texts)
        ]
    )


def story(
    identifier: str,
    title: str,
    *,
    traces: list[str],
    acceptance: list[tuple[str, str, str]] | None = None,
    points: int = 3,
    priority: str = "must",
) -> UserStory:
    criteria = acceptance or [("an account", "they sign in", "they see the page")]
    return UserStory(
        id=identifier,
        title=title,
        epic="Ordering",
        points=points,
        priority=priority,  # type: ignore[arg-type]
        traces=traces,
        acceptance=[
            AcceptanceCriterion(
                id=f"AC-{identifier.split('-')[1]}-{index}",
                given=given,
                when=when,
                then=then,
            )
            for index, (given, when, then) in enumerate(criteria, start=1)
        ],
    )


def plan(*, proposed: list[UserStory], backlog: list[UserStory] | None = None) -> SprintPlan:
    return SprintPlan(
        sprintName="Sprint 1 (proposed)",
        goal="Ship the basket",
        velocityAssumption=VelocityAssumption(points=20, basis="assumed, not measured"),
        estimatedPoints=sum(one.points for one in proposed),
        proposed=proposed,
        backlog=backlog or [],
    )


SIX = (
    "The system lets a customer add items to a shopping basket.",
    "The system shows the basket total including tax.",
    "The system lets a customer remove an item from the basket.",
    "The system asks for a delivery address before payment.",
    "The system emails a receipt after payment succeeds.",
    "The system keeps the basket for seven days.",
)


class TestTheChangeNoteThatSaidNothingElseChanged:
    """The live failure, and the reason this module exists."""

    def test_a_dropped_requirement_does_not_renumber_its_siblings(self) -> None:
        first = requirements(*SIX)
        # What C1 returned after the note: the same five sentences, read back
        # as R-1 to R-5 because it numbers what it reads.
        again = requirements(*(SIX[:3] + SIX[4:]))

        second, carry = carry_requirement_ids(again, [first])

        assert [one.id for one in second.requirements] == ["R-1", "R-2", "R-3", "R-5", "R-6"]
        assert carry.retired == ("R-4",)
        assert carry.notes == {
            "ids_kept": 5,
            "ids_matched": 0,
            "ids_new": 0,
            "ids_retired": 1,
        }

    def test_and_the_diff_then_reports_one_removal_rather_than_five_changes(self) -> None:
        first = requirements(*SIX)
        second, _ = carry_requirement_ids(requirements(*(SIX[:3] + SIX[4:])), [first])

        diff = diff_requirements(first, second, from_version=1, to_version=2)

        assert diff.removed == ["R-4"]
        assert diff.added == []
        assert diff.changed == []
        # The whole point. Before this, `touched` was every requirement in the
        # project, so every failing test traced to something that "changed" and
        # the classifier had no signal left to give.
        assert diff.touched == frozenset({"R-4"})


class TestAnIdIsNeverHandedToSomethingElse:
    def test_a_retired_id_stays_retired_when_a_later_version_adds_one(self) -> None:
        first = requirements(*SIX)
        second, _ = carry_requirement_ids(requirements(*(SIX[:3] + SIX[4:])), [first])
        # R-4 is gone and R-6 is the highest ever used, so the new requirement
        # is R-7. Filling the gap at R-4 is exactly the defect.
        third_read = requirements(*(SIX[:3] + SIX[4:]), "The system offers a gift receipt.")

        third, carry = carry_requirement_ids(third_read, [first, second])

        assert [one.id for one in third.requirements] == [
            "R-1",
            "R-2",
            "R-3",
            "R-5",
            "R-6",
            "R-7",
        ]
        assert carry.fresh == ("R-7",)

    def test_the_high_water_mark_spans_every_version_not_just_the_last(self) -> None:
        """A version that drops the highest id must not let it be reissued."""
        first = requirements("Alpha accepts a customer order.", "Beta accepts a supplier order.")
        second, _ = carry_requirement_ids(requirements("Alpha accepts a customer order."), [first])
        assert [one.id for one in second.requirements] == ["R-1"]

        third, carry = carry_requirement_ids(
            requirements("Alpha accepts a customer order.", "Gamma accepts a refund request."),
            [first, second],
        )

        # R-2 named the supplier requirement in version 1. Version 3's new
        # requirement is not it.
        assert [one.id for one in third.requirements] == ["R-1", "R-3"]
        assert carry.fresh == ("R-3",)


class TestARewordedRequirementIsTheSameRequirement:
    def test_it_keeps_its_id_so_the_diff_can_say_changed(self) -> None:
        first = requirements(*SIX)
        reworded = "A customer can add items to the shopping basket."
        assert overlap(SIX[0], reworded) >= SAME_THING_ABOVE, "the fixture has to be a rewording"

        second, carry = carry_requirement_ids(requirements(reworded, *SIX[1:]), [first])

        assert second.requirements[0].id == "R-1"
        assert carry.matched == ("R-1",)
        diff = diff_requirements(first, second, from_version=1, to_version=2)
        assert [change.requirement_id for change in diff.changed] == ["R-1"]
        assert diff.added == [] and diff.removed == []

    def test_an_identity_that_was_inferred_says_so(self) -> None:
        """`kept` is observed and `matched` is inferred, and the run records both.

        A figure in the writeup that rests on an inferred identity is weaker
        than one that rests on identical text, and the only way to say which is
        to count them separately at the moment the decision is made.
        """
        first = requirements(*SIX)
        second, carry = carry_requirement_ids(
            requirements("A customer can add items to the shopping basket.", *SIX[1:]), [first]
        )

        assert carry.notes == {
            "ids_kept": 5,
            "ids_matched": 1,
            "ids_new": 0,
            "ids_retired": 0,
        }
        assert set(carry.kept) | set(carry.matched) == {one.id for one in second.requirements}


class TestAmbiguityResolvesToNew:
    def test_two_equally_plausible_predecessors_mean_neither_lends_its_id(self) -> None:
        """When the wording does not say which requirement this is, it is new.

        The alternative is a coin toss that silently attaches a test's history
        to the wrong requirement, which is worse than losing the history.
        """
        first = requirements(
            "The system shows a customer their order history.",
            "The system shows a customer their order total.",
        )

        second, carry = carry_requirement_ids(
            requirements("The system shows a customer their order."), [first]
        )

        assert [one.id for one in second.requirements] == ["R-3"]
        assert carry.fresh == ("R-3",)
        assert sorted(carry.retired) == ["R-1", "R-2"]

    def test_but_a_clear_winner_still_wins(self) -> None:
        first = requirements(
            "The system shows a customer their order history.",
            "The system emails a receipt after payment succeeds.",
        )

        second, carry = carry_requirement_ids(
            requirements("A customer sees their order history."), [first]
        )

        assert [one.id for one in second.requirements] == ["R-1"]
        assert carry.matched == ("R-1",)


class TestEverythingPointingAtARequirementMovesWithIt:
    def test_assumption_and_question_traces_follow_the_new_ids(self) -> None:
        first = requirements(*SIX)
        again = requirements(*(SIX[:3] + SIX[4:]))
        # C1 wrote these against its own placeholder numbering, where R-4 is the
        # receipt requirement that this project calls R-5.
        again = again.model_copy(
            update={
                "assumptions": [
                    Assumption(id="A-1", text="Receipts are emailed, not posted.", traces=["R-4"])
                ],
                "questions": [
                    ClarifyingQuestion(
                        id="Q-1", question="Which tax rate applies?", traces=["R-2", "R-4"]
                    )
                ],
            }
        )

        second, _ = carry_requirement_ids(again, [first])

        assert second.assumptions[0].traces == ["R-5"]
        assert second.questions[0].traces == ["R-2", "R-5"]

    def test_a_trace_that_stopped_resolving_is_refused_rather_than_stored(self) -> None:
        """The artefact's own validator is the backstop, and it is run.

        `model_copy` does not validate, so a mistake in the remapping would
        otherwise write an artefact whose traces point at nothing. Proven by
        asking for an artefact whose trace was already broken.
        """
        broken = requirements("The system does one thing.").model_copy(
            update={
                "assumptions": [Assumption(id="A-1", text="Something.", traces=["R-9"])],
            }
        )

        with pytest.raises(ValueError, match="unknown requirements"):
            carry_requirement_ids(broken, [])


class TestTheFirstVersion:
    def test_reads_as_c1_wrote_it(self) -> None:
        current, carry = carry_requirement_ids(requirements(*SIX), [])

        assert [one.id for one in current.requirements] == [f"R-{n}" for n in range(1, 7)]
        assert len(carry.fresh) == 6
        assert carry.retired == ()


class TestTheAnswerDoesNotDependOnTheOrderTheListArrivedIn:
    def test_a_shuffled_reading_gives_every_carried_requirement_the_same_id(self) -> None:
        first = requirements(*SIX)
        forwards, _ = carry_requirement_ids(requirements(*SIX), [first])
        backwards, _ = carry_requirement_ids(requirements(*reversed(SIX)), [first])

        assert {one.text: one.id for one in forwards.requirements} == {
            one.text: one.id for one in backwards.requirements
        }


class TestAStoryKeepsItsIdThroughAReplan:
    def test_when_it_slides_from_the_sprint_into_the_backlog(self) -> None:
        """The move a change note causes, and the reader's first question."""
        first = plan(
            proposed=[
                story("US-1", "Add items to the basket", traces=["R-1"]),
                story("US-2", "See the basket total", traces=["R-2"]),
            ]
        )
        # The note added work, so the total story moved out of the sprint and
        # C1 renumbered it to US-3 on the way.
        replanned = plan(
            proposed=[
                story("US-1", "Add items to the basket", traces=["R-1"]),
                story("US-2", "Email a receipt", traces=["R-5"]),
            ],
            backlog=[story("US-3", "See the basket total", traces=["R-2"])],
        )

        second, carry = carry_story_ids(replanned, [first])

        assert [one.id for one in second.proposed] == ["US-1", "US-3"]
        assert [one.id for one in second.backlog] == ["US-2"]
        assert carry.fresh == ("US-3",)

    def test_when_the_model_retitles_it_but_it_realises_the_same_requirements(self) -> None:
        """The strongest rung, and it reads no wording at all.

        Requirement ids are stable by the time stories are identified, so the
        set of requirements a story realises is an identity that a model's
        choice of words cannot move.
        """
        first = plan(proposed=[story("US-1", "Add items to the basket", traces=["R-1", "R-3"])])
        renamed = plan(proposed=[story("US-1", "Put products in the cart", traces=["R-3", "R-1"])])

        second, carry = carry_story_ids(renamed, [first])

        assert [one.id for one in second.proposed] == ["US-1"]
        assert carry.kept == ("US-1",)


class TestACarriedStorysCriteria:
    def test_are_numbered_for_the_id_the_story_kept(self) -> None:
        """Otherwise the fix leaves a story called US-2 holding AC-3-1."""
        first = plan(
            proposed=[
                story("US-1", "Add items", traces=["R-1"]),
                story(
                    "US-2",
                    "See the total",
                    traces=["R-2"],
                    acceptance=[
                        ("a basket with two items", "the customer views it", "the total is shown"),
                        ("a taxable item", "the customer views the basket", "tax is included"),
                    ],
                ),
            ]
        )
        # C1 ranked the total story third this time, so it wrote AC-3-*.
        replanned = plan(
            proposed=[
                story("US-1", "Add items", traces=["R-1"]),
                story("US-2", "Email a receipt", traces=["R-5"]),
                story(
                    "US-3",
                    "See the total",
                    traces=["R-2"],
                    acceptance=[
                        ("a taxable item", "the customer views the basket", "tax is included"),
                        ("an empty basket", "the customer views it", "the total is zero"),
                    ],
                ),
            ]
        )

        second, _ = carry_story_ids(replanned, [first])

        total = next(one for one in second.proposed if one.title == "See the total")
        assert total.id == "US-2"
        # The criterion that says the same thing keeps the id it had, and the new
        # one is numbered above every criterion this story has ever had rather
        # than taking the retired first one's number.
        assert [one.id for one in total.acceptance] == ["AC-2-2", "AC-2-3"]


class TestACriterionIsNeverMatchedBySimilarity:
    def test_two_criteria_that_differ_in_one_clause_do_not_swap_ids(self) -> None:
        """A criterion is formulaic, so shared wording is not shared identity.

        These two share four content words out of five and are plainly different
        criteria. The similarity rung scores them as one and would hand the
        second the first one's id, which is why criteria use the exact rung
        alone. A criterion that changed by a word is a new criterion: that loses
        a little history and cannot claim the wrong one.
        """
        shown = ("a basket with two items", "the customer views it", "the total is shown")
        taxed = ("a basket with two items", "the customer views it", "tax is included")
        assert overlap(" ".join(shown), " ".join(taxed)) >= SAME_THING_ABOVE, (
            "the fixture only means something if similarity would have matched them"
        )
        first = plan(proposed=[story("US-1", "See the total", traces=["R-1"], acceptance=[shown])])
        replaced = plan(
            proposed=[story("US-1", "See the total", traces=["R-1"], acceptance=[taxed])]
        )

        second, _ = carry_story_ids(replaced, [first])

        assert [one.id for one in second.proposed[0].acceptance] == ["AC-1-2"]


class TestOverlap:
    @pytest.mark.parametrize(
        ("left", "right", "expected"),
        [
            ("The system emails a receipt.", "The system emails a receipt.", 1.0),
            ("The system emails a receipt.", "", 0.0),
            # Every word is noise or too short, so there is nothing to compare
            # and the answer is zero rather than a division by nothing.
            ("It will be", "It will be", 0.0),
        ],
    )
    def test_says_how_much_two_sentences_are_about_the_same_thing(
        self, left: str, right: str, expected: float
    ) -> None:
        assert overlap(left, right) == expected
