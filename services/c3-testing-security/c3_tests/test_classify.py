"""Is this failing test stale, or is it telling the truth?

The decision that decides whether a repair is even attempted, so the cases that
matter most are the ones where the answer is "do not touch it": a test tracing
only to things that did not move is a regression and is flagged, and a test
tracing to nothing at all is undecided rather than guessed at in either
direction.

The referee is driven with scripted answers. No model is called, and the cheats
under test are the ones a model actually offers: a confident verdict citing a
change that was never supplied.
"""

import json

from c3.heal import classify, summarise
from c3.heal.classify import endpoints_touched
from c3.heal.referee import (
    build_referee,
    changes_for,
    check_citation,
    prompt_for,
    referee,
)
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from sdlc_contracts import (
    ContractDiff,
    EndpointChange,
    RequirementChange,
    RequirementDiff,
    TestCase,
    TestTrace,
)


def _case(name: str = "a failing test", *, endpoint_id: str = "", **traces) -> TestCase:
    """One failing test with the traces a caller cares about.

    `endpoint_id` is a convenience for the common case of one endpoint. The
    trace itself holds a list, because a criterion test is written for a story
    and a story can be served by several.
    """
    return TestCase(
        id=f"a.test.ts::{name}",
        name=name,
        outcome="failed",
        message="expected 5, received 6",
        traces=TestTrace(**({"endpoint_ids": [endpoint_id]} if endpoint_id else {}), **traces),
    )


def _contracts(*changed: str, added: tuple[str, ...] = (), removed: tuple[str, ...] = ()):
    return ContractDiff(
        from_version=1,
        to_version=2,
        added=list(added),
        removed=list(removed),
        changed=[EndpointChange(endpoint_id=e, field="response") for e in changed],
    )


def _requirements(*changed: str, added: tuple[str, ...] = ()):
    return RequirementDiff(
        from_version=1,
        to_version=2,
        added=list(added),
        changed=[
            RequirementChange(requirement_id=r, field="text", before="old", after="new")
            for r in changed
        ],
    )


class TestTheRules:
    def test_a_test_whose_endpoint_moved_is_brittle(self) -> None:
        verdict = classify(_case(endpoint_id="get-orders"), contracts=_contracts("get-orders"))

        assert verdict.classification == "brittle"
        assert verdict.classified_by == "trace-changed"
        assert verdict.evidence.changed_artefacts == ["get-orders"]

    async def test_a_test_whose_requirement_was_reworded_is_brittle(self) -> None:
        """The case a tool pointed at a repository cannot see: nobody else
        knows which requirement this test exists for."""
        verdict = classify(
            _case(requirement_ids=["R-1"]),
            contracts=_contracts(),
            requirements=_requirements("R-1"),
        )

        assert verdict.classification == "brittle"
        assert verdict.evidence.changed_artefacts == ["R-1"]

    def test_a_test_tracing_only_to_unchanged_things_is_a_regression(self) -> None:
        """The one that must never be repaired: nothing it depends on was
        supposed to move, so the code is wrong, not the test."""
        verdict = classify(
            _case(endpoint_id="get-products", requirement_ids=["R-9"]),
            contracts=_contracts("get-orders"),
            requirements=_requirements("R-1"),
        )

        assert verdict.classification == "regression"
        assert verdict.classified_by == "trace-unchanged"
        assert verdict.evidence.changed_artefacts == []

    def test_a_removed_endpoint_counts_as_a_change(self) -> None:
        """A test against an endpoint the contract stopped promising is testing
        something nobody asked for any more."""
        verdict = classify(
            _case(endpoint_id="get-orders"), contracts=_contracts(removed=("get-orders",))
        )

        assert verdict.classification == "brittle"

    def test_a_test_that_traces_to_nothing_is_undecided(self) -> None:
        """Not a regression. An empty trace is an absence of evidence, and
        calling it either way would be inventing some."""
        verdict = classify(_case(), contracts=_contracts("get-orders"))

        assert verdict.classification == "undecided"
        assert verdict.classified_by == "unclassified"
        assert verdict.needs_referee

    def test_without_any_diff_nothing_is_classified(self) -> None:
        """Two versions are the whole signal. With one, there is no question
        the rules can answer."""
        verdict = classify(_case(endpoint_id="get-orders"))

        assert verdict.classification == "undecided"

    def test_the_evidence_names_what_the_test_was_written_from(self) -> None:
        """Read by people, so the story is in it even though nothing diffs
        stories."""
        verdict = classify(
            _case(story_id="US-1", requirement_ids=["R-1"], endpoint_id="get-orders"),
            contracts=_contracts("get-orders"),
        )

        assert verdict.evidence.traced_to == ["US-1", "R-1", "get-orders"]

    def test_the_counts_say_how_often_the_rules_sufficed(self) -> None:
        """A classifier whose rules decide almost everything is a different
        contribution from one that defers to a model."""
        verdicts = {
            "a": classify(_case(endpoint_id="get-orders"), contracts=_contracts("get-orders")),
            "b": classify(_case(endpoint_id="get-products"), contracts=_contracts("get-orders")),
            "c": classify(_case(), contracts=_contracts("get-orders")),
        }

        assert summarise(verdicts) == {
            "trace-changed": 1,
            "trace-unchanged": 1,
            "unclassified": 1,
        }

    def test_an_absent_diff_touches_nothing(self) -> None:
        assert endpoints_touched(None) == frozenset()


class Recorder:
    """Scripted referee answers, with every prompt kept."""

    def __init__(self, answers: list[dict]) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    def as_function(self) -> FunctionModel:
        def respond(messages, info):
            texts = [
                part.content
                for message in messages
                for part in getattr(message, "parts", [])
                if getattr(part, "part_kind", "") == "user-prompt"
            ]
            self.prompts.append(texts[-1] if texts else "")
            return ModelResponse(
                parts=[ToolCallPart(info.output_tools[0].name, json.dumps(self.answers.pop(0)))]
            )

        return FunctionModel(respond)


def _agent(recorder: Recorder):
    return build_referee(recorder.as_function())


async def _verdict(recorder: Recorder, case: TestCase, contracts, requirements=None):
    return await referee(_agent(recorder), case, contracts=contracts, requirements=requirements)


class TestACriterionTestReachesTheContractDiff:
    """Half the classifier's signal could not apply to most of its input.

    Its two inputs are the requirement diff and the contract diff. Until
    2026-09-26 a criterion test carried no endpoint at all, so the contract half
    had nothing to match against on every test this component writes from a
    criterion, which on generated code is most of them. A criterion test broken
    by the API moving underneath it could only be read through whether its
    requirement happened to be reworded at the same time, and a change note that
    renames a field without rewording the criterion does not do that.
    """

    def test_a_story_served_by_a_changed_endpoint_is_brittle(self) -> None:
        case = _case(
            story_id="US-2",
            requirement_ids=["R-6"],
            endpoint_ids=["get-tasks", "post-tasks"],
        )

        verdict = classify(case, contracts=_contracts("get-tasks"))

        assert verdict.classification == "brittle"
        assert verdict.classified_by == "trace-changed"
        assert verdict.evidence.changed_artefacts == ["get-tasks"]

    def test_and_one_served_only_by_unchanged_endpoints_is_a_regression(self) -> None:
        """The seeded bug case: the code broke and nothing it depends on moved."""
        case = _case(story_id="US-4", requirement_ids=["R-4"], endpoint_ids=["delete-tasks-id"])

        verdict = classify(case, contracts=_contracts("get-tasks"))

        assert verdict.classification == "regression"
        assert verdict.classified_by == "trace-unchanged"

    def test_every_endpoint_the_story_traces_is_in_the_evidence(self) -> None:
        """A reader confirming the verdict needs all of what it was read from,
        not the one that happened to match."""
        case = _case(story_id="US-2", endpoint_ids=["get-tasks", "post-tasks"])

        verdict = classify(case, contracts=_contracts("post-tasks"))

        assert verdict.evidence.traced_to == ["US-2", "get-tasks", "post-tasks"]


class TestTheReferee:
    def test_it_is_shown_every_change_as_one_quotable_line(self) -> None:
        changes = changes_for(_contracts("get-orders"), _requirements("R-1", added=("R-2",)))

        assert [change.label for change in changes] == ["E1", "R2", "R3"]
        assert "endpoint get-orders changed its response" in changes[0].line
        assert "requirement R-1 changed its text" in changes[2].line

    async def test_a_verdict_citing_something_it_was_given_is_taken(self) -> None:
        recorder = Recorder(
            [
                {
                    "classification": "brittle",
                    "cited_change": "E1",
                    "reasoning": "the response shape moved",
                }
            ]
        )

        verdict = await _verdict(recorder, _case(), _contracts("get-orders"))

        assert verdict.classification == "brittle"
        assert verdict.classified_by == "model-referee"
        assert verdict.evidence.cited_diff_span == "E1"
        assert verdict.evidence.referee_reasoning

    async def test_a_verdict_citing_something_it_invented_is_refused(self) -> None:
        """The failure mode the probe measures a provider for, here as the
        thing that stops a fabricated verdict reaching the repair loop."""
        recorder = Recorder(
            [
                {"classification": "brittle", "cited_change": "E9 endpoint nobody mentioned"},
                {"classification": "brittle", "cited_change": "still made up"},
            ]
        )

        verdict = await _verdict(recorder, _case(), _contracts("get-orders"))

        assert verdict.classification == "undecided", "an invented citation decides nothing"
        assert verdict.classified_by == "unclassified"
        assert "cited evidence it was not given" in verdict.evidence.referee_reasoning

    async def test_the_refusal_reason_travels_back_and_a_good_second_answer_is_taken(self) -> None:
        recorder = Recorder(
            [
                {"classification": "brittle", "cited_change": "invented"},
                {"classification": "regression", "cited_change": "E1"},
            ]
        )

        verdict = await _verdict(recorder, _case(), _contracts("get-orders"))

        assert verdict.classification == "regression"
        assert "was refused" in recorder.prompts[1]

    async def test_undecided_is_an_answer_the_referee_may_give(self) -> None:
        """Better than a guess: it reaches a person, and a wrong `brittle`
        sends a real bug to be papered over."""
        recorder = Recorder([{"classification": "undecided", "cited_change": "E1"}])

        verdict = await _verdict(recorder, _case(), _contracts("get-orders"))

        assert verdict.classification == "undecided"
        assert verdict.classified_by == "model-referee", "a model was asked, and that is counted"

    async def test_with_nothing_changed_no_model_is_called_at_all(self) -> None:
        recorder = Recorder([])

        verdict = await _verdict(recorder, _case(), _contracts())

        assert verdict.classification == "undecided"
        assert recorder.prompts == [], "there was nothing to referee"
        assert "nothing changed" in verdict.evidence.referee_reasoning

    async def test_the_prompt_carries_the_failure_and_the_changes(self) -> None:
        recorder = Recorder([{"classification": "brittle", "cited_change": "E1"}])

        await _verdict(recorder, _case(endpoint_id="get-orders"), _contracts("get-orders"))

        prompt = recorder.prompts[0]
        assert "expected 5, received 6" in prompt
        assert "get-orders" in prompt
        assert "[E1]" in prompt


class TestTheCitationCheck:
    def test_the_label_alone_counts(self) -> None:
        changes = changes_for(_contracts("get-orders"), None)

        assert check_citation("E1", changes)[0]
        assert check_citation("[E1]", changes)[0]
        assert check_citation(changes[0].line, changes)[0]

    def test_nothing_and_invention_do_not(self) -> None:
        changes = changes_for(_contracts("get-orders"), None)

        assert not check_citation("", changes)[0]
        assert not check_citation("E7", changes)[0]
        assert "was not supplied" in check_citation("something else", changes)[1]

    def test_the_prompt_says_so_when_nothing_moved(self) -> None:
        assert "nothing changed" in prompt_for(_case(), [])
