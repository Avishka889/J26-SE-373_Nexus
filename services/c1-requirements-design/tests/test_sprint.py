"""The sprint plan: what the model writes, and what arithmetic decides.

Most of this file is about the second half. Story points, priorities, ids and the
sprint/backlog split are all computed, and the tests that matter are the ones
proving a model cannot influence them and that the same input twice gives the
same plan.

`test_the_estimator_produces_a_spread` is the counterpart of the architecture
scoring spread test. A formula that gives every story the same number is not an
estimate, it is a rubber stamp with arithmetic painted on it, and it would look
exactly as principled in a screenshot.
"""

import json

import pytest
from c1.sprint.build import DEFAULT_VELOCITY, to_contract
from c1.sprint.estimate import SCALE, estimate_story, priority_of, snap
from c1.sprint.extractor import (
    CouldNotPlanSprint,
    build_sprint_agent,
    plan_sprint,
    prompt_for,
)
from c1.sprint.rules import RULE_IDS, validate_plan
from c1.sprint.schema import DraftPlan, DraftStory
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sdlc_contracts import (
    ArchitectureGraph,
    GraphEdge,
    GraphNode,
    ParsedRequirement,
    Position,
    SprintPlan,
)


def requirement(id: str, text: str, **extra) -> ParsedRequirement:
    base = {"type": "functional", "priority": "must", "confidence": 80}
    return ParsedRequirement(id=id, text=text, **{**base, **extra})


REQUIREMENTS = [
    requirement("R-1", "A customer pays for an order with a saved card."),
    requirement("R-2", "Every payment is recorded."),
    requirement("R-3", "An administrator approves a refund.", priority="should"),
    requirement(
        "R-4",
        "A payment is confirmed within two seconds.",
        type="quality",
        qualityAttribute="performance",
        priority="could",
    ),
]


def node(id: str, kind: str, label: str, traces: list[str], **extra) -> GraphNode:
    return GraphNode(
        id=id, kind=kind, label=label, position=Position(x=0, y=0), traces=traces, **extra
    )


def payments_graph() -> ArchitectureGraph:
    return ArchitectureGraph(
        nodes=[
            node("a1", "actor", "Customer", ["R-1"], actorKind="primary"),
            node("a3", "actor", "Card Network", ["R-1"], actorKind="external_system"),
            node(
                "e1",
                "entity",
                "Payment",
                ["R-1", "R-2"],
                attributes=[{"name": "amount", "type": "number"}],
            ),
            node(
                "e2", "entity", "Refund", ["R-3"], attributes=[{"name": "reason", "type": "string"}]
            ),
            node("m1", "service", "Payment Service", ["R-1", "R-2"]),
        ],
        edges=[
            GraphEdge(
                id="x1", source="a1", target="e1", kind="action", verb="makes", traces=["R-1"]
            ),
        ],
    )


def criterion(
    given="a signed in customer", when="they confirm a payment", then="the payment is charged"
):
    return {"given": given, "when": when, "then": then}


def good_plan() -> dict:
    return {
        "goal": "A customer can pay, and an administrator can refund.",
        "stories": [
            {
                "title": "As a customer, I can pay with a saved card",
                "epic": "Payments",
                "traces": ["R-1", "R-2"],
                "acceptance": [
                    criterion(),
                    criterion(when="the card is declined", then="the reason is shown"),
                ],
            },
            {
                "title": "As an administrator, I can approve a refund",
                "epic": "Refunds",
                "traces": ["R-3"],
                "acceptance": [
                    criterion(when="they approve a refund", then="the refund is recorded")
                ],
            },
            {
                "title": "As a customer, I see my payment confirmed quickly",
                "epic": "Payments",
                "traces": ["R-4"],
                "acceptance": [criterion(then="confirmation appears within two seconds")],
            },
        ],
    }


def check(plan: dict):
    return validate_plan(
        DraftPlan.model_validate(plan), requirements=REQUIREMENTS, graph=payments_graph()
    )


def promote(plan: dict, **kwargs) -> SprintPlan:
    return to_contract(
        DraftPlan.model_validate(plan),
        requirements=REQUIREMENTS,
        graph=payments_graph(),
        **kwargs,
    )


class TestACleanPlanIsClean:
    def test_no_rule_fires_at_all(self) -> None:
        report = check(good_plan())
        assert report.findings == (), f"a clean plan tripped {report.rule_ids()}"


# --- one mutation per rule ----------------------------------------------------


def _no_goal(plan: dict) -> dict:
    plan["goal"] = ""
    return plan


def _duplicate_story(plan: dict) -> dict:
    plan["stories"].append(dict(plan["stories"][0]))
    return plan


def _untraced_story(plan: dict) -> dict:
    plan["stories"][1]["traces"] = []
    return plan


def _invented_trace(plan: dict) -> dict:
    plan["stories"][1]["traces"] = ["R-99"]
    return plan


def _no_acceptance(plan: dict) -> dict:
    plan["stories"][1]["acceptance"] = []
    return plan


def _then_restates_when(plan: dict) -> dict:
    plan["stories"][1]["acceptance"][0]["then"] = plan["stories"][1]["acceptance"][0]["when"]
    return plan


def _uncovered_requirement(plan: dict) -> dict:
    plan["stories"] = [s for s in plan["stories"] if s["traces"] != ["R-3"]]
    return plan


def _oversized_story(plan: dict) -> dict:
    # Everything at once: every requirement, and a criterion per behaviour.
    plan["stories"][0]["traces"] = ["R-1", "R-2", "R-3", "R-4"]
    plan["stories"][0]["acceptance"] = [criterion(then=f"outcome {n}") for n in range(14)]
    return plan


def _role_then_system(plan: dict) -> dict:
    # A real Groq run wrote four of sixteen stories this way: a role that
    # appears nowhere in the requirements, then a sentence about the system.
    plan["stories"][0]["title"] = (
        "As a system administrator, the system ingests temperature readings from sensors."
    )
    return plan


MUTATIONS = [
    ("names-are-present", "error", _no_goal),
    ("no-duplicate-story", "error", _duplicate_story),
    ("story-is-traced", "error", _untraced_story),
    ("traces-resolve", "error", _invented_trace),
    ("story-has-acceptance", "error", _no_acceptance),
    ("acceptance-is-well-formed", "error", _then_restates_when),
    ("requirement-coverage", "warning", _uncovered_requirement),
    ("story-is-small-enough", "warning", _oversized_story),
    ("story-has-a-real-role", "error", _role_then_system),
]


class TestTheRuleCatalogue:
    @pytest.mark.parametrize("rule_id,severity,mutate", MUTATIONS, ids=[m[0] for m in MUTATIONS])
    def test_the_mutation_trips_its_rule(self, rule_id: str, severity: str, mutate) -> None:
        broken = mutate(good_plan())
        assert broken != good_plan(), "the mutation changed nothing, so this test proves nothing"

        report = check(broken)
        assert rule_id in report.rule_ids(), (
            f"{rule_id} did not fire; what fired was {report.rule_ids()}"
        )
        assert all(f.severity == severity for f in report.findings if f.rule_id == rule_id)

    def test_every_rule_in_the_catalogue_has_a_mutation(self) -> None:
        assert {rule_id for rule_id, _, _ in MUTATIONS} == set(RULE_IDS)

    @pytest.mark.parametrize("rule_id,severity,mutate", MUTATIONS, ids=[m[0] for m in MUTATIONS])
    def test_every_finding_says_something_to_both_readers(self, rule_id, severity, mutate) -> None:
        for finding in check(mutate(good_plan())).findings:
            assert finding.reason.strip()
            assert finding.hint.strip()
            assert finding.hint != finding.reason


class TestCoverageIsReportedNotEnforced:
    def test_an_uncovered_requirement_warns_and_does_not_block(self) -> None:
        report = check(_uncovered_requirement(good_plan()))
        assert "requirement-coverage" in report.rule_ids()
        assert report.ok is True

    def test_the_warning_names_the_requirement_and_says_it_is_a_must(self) -> None:
        plan = good_plan()
        plan["stories"] = [s for s in plan["stories"] if s["traces"] != ["R-1", "R-2"]]
        warning = next(f for f in check(plan).warnings if f.rule_id == "requirement-coverage")
        assert "R-1" in warning.reason and "R-2" in warning.reason
        assert "must-haves" in warning.reason
        assert warning.traces == ("R-1", "R-2")


class TestAnEmptyThenIsNotATest:
    def test_a_then_that_restates_its_when_is_refused(self) -> None:
        # It generates a test that reports green while asserting nothing, which
        # is worse than generating no test at all.
        report = check(_then_restates_when(good_plan()))
        assert "acceptance-is-well-formed" in report.rule_ids()
        assert report.ok is False

    def test_case_and_spacing_do_not_get_it_through(self) -> None:
        plan = good_plan()
        plan["stories"][1]["acceptance"][0]["then"] = (
            "  " + plan["stories"][1]["acceptance"][0]["when"].upper() + " "
        )
        assert "acceptance-is-well-formed" in check(plan).rule_ids()

    @pytest.mark.parametrize("part", ["given", "when", "then"])
    def test_every_part_is_required(self, part: str) -> None:
        plan = good_plan()
        plan["stories"][0]["acceptance"][0][part] = ""
        report = check(plan)
        assert "acceptance-is-well-formed" in report.rule_ids()
        assert part in next(
            f.reason for f in report.errors if f.rule_id == "acceptance-is-well-formed"
        )


# --- estimation ---------------------------------------------------------------


class TestTheEstimator:
    def test_points_land_on_the_planning_scale(self) -> None:
        for story in DraftPlan.model_validate(good_plan()).stories:
            estimate = estimate_story(story, graph=payments_graph(), requirements=REQUIREMENTS)
            assert estimate.points in SCALE

    def test_it_produces_a_spread(self) -> None:
        # The counterpart of the architecture scoring spread test. A formula that
        # gives every story the same number is a rubber stamp with arithmetic
        # painted on it.
        points = {
            estimate_story(story, graph=payments_graph(), requirements=REQUIREMENTS).points
            for story in DraftPlan.model_validate(good_plan()).stories
        }
        assert len(points) > 1, f"every story estimated at {points}, which is not an estimate"

    def test_an_external_system_costs_more_than_an_entity(self) -> None:
        # Integrating somebody else's system is the expensive part of most
        # stories, and the weighting has to say so.
        plain = DraftStory(title="t", epic="e", traces=["R-2"], acceptance=[])
        external = DraftStory(title="t", epic="e", traces=["R-1"], acceptance=[])
        graph, reqs = payments_graph(), REQUIREMENTS
        assert (
            estimate_story(external, graph=graph, requirements=reqs).raw
            > estimate_story(plain, graph=graph, requirements=reqs).raw
        )

    def test_a_quality_requirement_is_weighted(self) -> None:
        quality = DraftStory(title="t", epic="e", traces=["R-4"], acceptance=[])
        estimate = estimate_story(quality, graph=payments_graph(), requirements=REQUIREMENTS)
        assert any("quality requirement" in reason for reason in estimate.because)

    def test_the_reasons_add_up_to_the_raw_number(self) -> None:
        # The deductions are published, so they have to be the actual arithmetic
        # rather than prose written next to it.
        story = DraftPlan.model_validate(good_plan()).stories[0]
        estimate = estimate_story(story, graph=payments_graph(), requirements=REQUIREMENTS)
        added = 1 + sum(
            int(reason.rsplit("+", 1)[1].rstrip(")"))
            for reason in estimate.because
            if "+" in reason
        )
        assert added == estimate.raw

    @pytest.mark.parametrize(
        "raw,expected", [(1, 1), (4, 5), (6, 5), (7, 8), (9, 8), (11, 13), (30, 21)]
    )
    def test_snapping_rounds_to_the_nearest_card(self, raw: int, expected: int) -> None:
        assert snap(raw) == expected

    def test_a_tie_rounds_up(self) -> None:
        # Slightly pessimistic disappoints nobody; slightly optimistic misses a
        # sprint. 4 is equidistant from 3 and 5.
        assert snap(4) == 5

    def test_the_same_story_always_estimates_the_same(self) -> None:
        story = DraftPlan.model_validate(good_plan()).stories[0]
        runs = {
            estimate_story(story, graph=payments_graph(), requirements=REQUIREMENTS).points
            for _ in range(5)
        }
        assert len(runs) == 1


class TestPriorityIsInherited:
    def test_a_story_takes_the_highest_priority_it_realises(self) -> None:
        story = DraftStory(title="t", epic="e", traces=["R-3", "R-1"], acceptance=[])
        assert priority_of(story, REQUIREMENTS) == "must"

    def test_a_story_on_a_should_stays_a_should(self) -> None:
        story = DraftStory(title="t", epic="e", traces=["R-3"], acceptance=[])
        assert priority_of(story, REQUIREMENTS) == "should"


# --- promotion ----------------------------------------------------------------


class TestPromotion:
    def test_ids_are_allocated_in_sequence(self) -> None:
        plan = promote(good_plan())
        assert [s.id for s in (*plan.proposed, *plan.backlog)] == ["US-1", "US-2", "US-3"]

    def test_the_model_cannot_set_points_priority_or_ids(self) -> None:
        # Enforcement by type. The fields do not exist to be asked for, which is
        # why the catalogue has no rule about them: they cannot go wrong.
        fields = DraftPlan.model_json_schema()["$defs"]["DraftStory"]["properties"]
        assert "points" not in fields
        assert "priority" not in fields
        assert "id" not in fields

    def test_acceptance_ids_are_derived_from_the_story(self) -> None:
        first = promote(good_plan()).proposed[0]
        assert [c.id for c in first.acceptance] == ["AC-1-1", "AC-1-2"]

    def test_stories_run_by_priority_in_both_lists(self) -> None:
        plan = promote(good_plan())
        # Which the contract also enforces, so this is really asserting that the
        # ordering happens here rather than blowing up there.
        ranks = [s.priority for s in plan.proposed]
        assert ranks == sorted(ranks, key=["must", "should", "could"].index)

    def test_estimated_points_are_the_proposed_total(self) -> None:
        plan = promote(good_plan())
        assert plan.estimated_points == sum(s.points for s in plan.proposed)

    def test_the_velocity_assumption_says_it_is_an_assumption(self) -> None:
        assumption = promote(good_plan()).velocity_assumption
        assert assumption.points == DEFAULT_VELOCITY
        assert "not measured" in assumption.basis
        assert "no sprint" in assumption.basis or "delivered no sprint" in assumption.basis

    def test_the_sprint_fills_to_the_velocity_and_the_rest_waits(self) -> None:
        plan = promote(good_plan(), velocity=5)
        assert plan.proposed, "an empty sprint is not a plan"
        assert plan.estimated_points <= max(5, plan.proposed[0].points)
        assert plan.backlog

    def test_one_story_is_always_proposed_however_big(self) -> None:
        plan = promote(good_plan(), velocity=1)
        assert len(plan.proposed) == 1
        assert plan.proposed[0].points > 1

    def test_nothing_is_slotted_in_around_an_overflowing_story(self) -> None:
        # Packing the sprint with a smaller lower priority story delivers more
        # points and makes a worse plan, so everything after the first story
        # that does not fit waits.
        plan = promote(good_plan(), velocity=5)
        cutoff = len(plan.proposed)
        ordered = [*plan.proposed, *plan.backlog]
        assert ordered[cutoff:] == plan.backlog
        assert [s.id for s in ordered] == ["US-1", "US-2", "US-3"]

    def test_the_same_draft_always_gives_the_same_plan(self) -> None:
        first = promote(good_plan()).model_dump(by_alias=True)
        second = promote(good_plan()).model_dump(by_alias=True)
        assert first == second

    def test_a_promoted_plan_satisfies_the_contract_validators(self) -> None:
        SprintPlan.model_validate(promote(good_plan()).model_dump(by_alias=True))


# --- the repair loop ----------------------------------------------------------


class Recorder:
    def __init__(self, *plans: dict) -> None:
        self.plans = list(plans)
        self.prompts: list[str] = []

    def as_function(self):
        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            self.prompts.append(_last_user_text(messages))
            plan = self.plans[min(len(self.prompts) - 1, len(self.plans) - 1)]
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(plan))])

        return respond


def _last_user_text(messages: list[ModelMessage]) -> str:
    for message in reversed(messages):
        for part in getattr(message, "parts", []):
            content = getattr(part, "content", None)
            if isinstance(content, str) and content.strip():
                return content
    return ""


async def run_loop(recorder: Recorder):
    return await plan_sprint(
        REQUIREMENTS,
        payments_graph(),
        agent=build_sprint_agent(FunctionModel(recorder.as_function())),
    )


class TestTheHintsActuallyTravel:
    async def test_the_second_prompt_names_what_the_first_answer_broke(self) -> None:
        recorder = Recorder(_invented_trace(good_plan()), good_plan())
        await run_loop(recorder)

        assert len(recorder.prompts) == 2
        first, second = recorder.prompts
        assert "R-99" in second, "the hint did not name the invented requirement"
        assert "R-99" not in first

    async def test_a_warning_never_triggers_a_repair(self) -> None:
        recorder = Recorder(_uncovered_requirement(good_plan()))
        plan, report = await run_loop(recorder)

        assert len(recorder.prompts) == 1
        assert [f.rule_id for f in report.warnings] == ["requirement-coverage"]
        assert plan.proposed

    async def test_a_model_that_never_fixes_it_stops_after_two(self) -> None:
        recorder = Recorder(_invented_trace(good_plan()), _invented_trace(good_plan()), good_plan())
        with pytest.raises(CouldNotPlanSprint) as raised:
            await run_loop(recorder)

        assert len(recorder.prompts) == 2
        assert "traces-resolve" in raised.value.report.rule_ids()


class TestThePrompt:
    def test_it_shows_the_design_as_well_as_the_requirements(self) -> None:
        # A model given only requirements writes one story per requirement, which
        # is a restatement rather than a plan.
        prompt = prompt_for(REQUIREMENTS, payments_graph())
        assert "R-1 (must, functional)" in prompt
        assert "Payment Service" in prompt
        assert "Payment" in prompt

    def test_it_refuses_to_ask_for_the_numbers(self) -> None:
        from c1.sprint.extractor import INSTRUCTIONS

        assert "Do not give points, priorities or story ids" in INSTRUCTIONS


@pytest.mark.live
class TestAgainstARealModel:
    async def test_it_writes_stories_whose_criteria_could_become_tests(
        self, allow_live_requests, live_model_name: str, live
    ) -> None:
        agent = await live(build_sprint_agent(live_model_name))
        plan, report = await plan_sprint(REQUIREMENTS, payments_graph(), agent=agent)

        print(f"\ngoal={plan.goal!r} attempts={report.attempts}")
        print(f"sprint={plan.estimated_points} of {plan.velocity_assumption.points} points")
        for story in (*plan.proposed, *plan.backlog):
            where = "sprint" if story in plan.proposed else "backlog"
            print(f"  {story.id} [{story.priority} {story.points}pt {where}] {story.title}")
            for c in story.acceptance:
                print(f"      given {c.given} / when {c.when} / then {c.then}")
        for warning in report.warnings:
            print(f"  warning {warning.rule_id}: {warning.reason}")

        known = {r.id for r in REQUIREMENTS}
        assert plan.proposed
        for story in (*plan.proposed, *plan.backlog):
            assert story.acceptance, f"{story.id} has no criteria"
            assert set(story.traces) <= known
            assert story.points in SCALE
            for c in story.acceptance:
                assert c.then.strip().lower() != c.when.strip().lower()


class TestAStoryBelongsToSomeone:
    """A named role that the sentence then abandons is nobody's story.

    Groq wrote four of sixteen this way in a real run, always inventing a role
    like "system administrator" that appears nowhere in the requirements, always
    to describe background work that has no actor at all. Sonnet 5 wrote none of
    twenty four. A rule catches it on either, and costs nothing to check.
    """

    def test_a_role_followed_by_the_system_is_refused(self) -> None:
        plan = good_plan()
        plan["stories"][0]["title"] = (
            "As a system administrator, the system raises an alert when a container drifts."
        )
        assert "story-has-a-real-role" in check(plan).rule_ids()

    def test_the_hint_offers_both_ways_out(self) -> None:
        plan = good_plan()
        plan["stories"][0]["title"] = "As a warehouse operator, the system ingests readings."
        hint = next(f.hint for f in check(plan).findings if f.rule_id == "story-has-a-real-role")
        assert "warehouse operator" in hint
        assert "As the system" in hint

    def test_honest_background_work_is_allowed(self) -> None:
        # This is what a story with no actor should look like, and Sonnet 5
        # already writes them this way. Refusing it would push the model back
        # towards inventing a role.
        plan = good_plan()
        plan["stories"][0]["title"] = "As the system, I quarantine a consignment when it alerts."
        assert "story-has-a-real-role" not in check(plan).rule_ids()

    def test_an_ordinary_story_is_untouched(self) -> None:
        plan = good_plan()
        plan["stories"][0]["title"] = (
            "As a Delivery Driver, I can capture a signature at each stop."
        )
        assert "story-has-a-real-role" not in check(plan).rule_ids()
