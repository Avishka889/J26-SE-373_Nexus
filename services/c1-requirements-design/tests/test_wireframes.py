"""The link graph checks, and the one rule that deliberately does not block.

The load bearing tests here are the three about severity, because that is the
design decision this catalogue exists to encode.

A link to a screen that is not there is an error: no reading of the flow makes it
right. A screen nothing reaches is an error, and the test that matters proves it
is checked by walking from the entry rather than by counting inbound links, since
two screens pointing at each other both have an inbound link and neither can be
opened. A screen with no way out is a warning, because confirmation screens are
supposed to stop, and a check that fires on every correct ending is one a reader
learns to skip.

The mutation coverage is pinned rather than trusted: every rule in the catalogue
has to appear in the mutation table, and a rule with no mutation fails the build
rather than sitting there untested.
"""

import json

import pytest
from c1.rules.findings import Finding, Report
from c1.wireframes.build import to_contract
from c1.wireframes.extractor import (
    CouldNotDrawFlow,
    build_wireframe_agent,
    draw_flow,
    prompt_for,
)
from c1.wireframes.plan import MAX_FLOWS, plan_flows
from c1.wireframes.rules import RULE_IDS, reads_as_an_ending, validate_flow
from c1.wireframes.schema import DraftFlow
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sdlc_contracts import ArchitectureGraph, GraphEdge, GraphNode, Position, WireframeFlow

REQUIREMENT_IDS = frozenset({"R-1", "R-2", "R-3"})


def good_flow() -> dict:
    """A journey that holds together.

    Three screens, each reachable, ending on a confirmation. The last screen has
    no way out on purpose: it is the case the dead end rule has to stay quiet
    about, so this fixture doubles as the proof that the exemption works.
    """
    return {
        "name": "Paying for an order",
        "screens": [
            {
                "id": "s1",
                "name": "Your Basket",
                "crumbs": ["Basket"],
                "traces": ["R-1"],
                "blocks": [
                    {"id": "b1", "kind": "summary", "label": "Total", "value": "24.00"},
                    {"id": "b2", "kind": "row", "label": "Two items", "link_id": "l1"},
                ],
                "links": [
                    {"id": "l1", "label": "Checkout", "target_id": "s2", "variant": "primary"}
                ],
            },
            {
                "id": "s2",
                "name": "Card Details",
                "crumbs": ["Basket", "Payment"],
                "traces": ["R-1", "R-2"],
                "blocks": [{"id": "b3", "kind": "field", "label": "Card number"}],
                "links": [
                    {"id": "l2", "label": "Pay now", "target_id": "s3", "variant": "primary"},
                    {"id": "l3", "label": "Back", "target_id": "s1", "variant": "secondary"},
                ],
            },
            {
                "id": "s3",
                "name": "Payment Confirmed",
                "crumbs": ["Basket", "Payment", "Done"],
                "traces": ["R-2"],
                "blocks": [
                    {
                        "id": "b4",
                        "kind": "banner",
                        "label": "Your payment went through",
                        "tone": "positive",
                    }
                ],
                "links": [],
            },
        ],
    }


def check(flow: dict) -> Report:
    return validate_flow(DraftFlow.model_validate(flow), requirement_ids=REQUIREMENT_IDS)


class TestAScreenThatIsUsedRatherThanFilledIn:
    """A calculator's keys and the read-out above them. With only fields, rows and
    lists every screen was a form or a table, whatever it was for."""

    def keypad(self) -> dict:
        flow = good_flow()
        flow["screens"][1]["blocks"] = [
            {"id": "b3", "kind": "field", "label": "Expression"},
            {"id": "b5", "kind": "display", "label": "Result"},
            *(
                {"id": f"k{index}", "kind": "button", "label": key, "value": key}
                for index, key in enumerate(["7", "8", "9", "+"])
            ),
            {"id": "k9", "kind": "button", "label": "Clear", "value": ""},
        ]
        return flow

    def test_a_display_and_its_buttons_pass_every_rule(self) -> None:
        report = check(self.keypad())

        assert report.ok, [finding.reason for finding in report.errors]

    def test_they_reach_the_contract_as_drawn(self) -> None:
        from c1.wireframes.build import to_contract

        draft = DraftFlow.model_validate(self.keypad())
        flow = to_contract(draft, check(self.keypad()), flow_id="f1", version="v1", traces=["R-1"])

        kinds = [block.kind for block in flow.screens[1].blocks]
        assert kinds == ["field", "display", "button", "button", "button", "button", "button"]


class TestACleanFlowIsClean:
    def test_no_rule_fires_at_all(self) -> None:
        report = check(good_flow())
        # Warnings included: a fixture that trips a warning would make every
        # "this mutation added a warning" test below meaningless.
        assert report.findings == (), f"a clean flow tripped {report.rule_ids()}"
        assert report.ok is True


class TestWhatCountsAsAnEnding:
    @pytest.mark.parametrize(
        "name",
        [
            "Payment Confirmed",
            "Booking Confirmation",
            "Order Receipt",
            "Thank You",
            "Card Declined: Error",
            "Transfer Complete",
            "Page Not Found",
            "Request Submitted",
        ],
    )
    def test_an_ending_is_recognised(self, name: str) -> None:
        assert reads_as_an_ending(name) is True

    @pytest.mark.parametrize(
        "name",
        [
            "Your Basket",
            "Card Details",
            "Choose a Doctor",
            "Order Overview",
            "Account Settings",
        ],
    )
    def test_an_ordinary_screen_is_not_an_ending(self, name: str) -> None:
        assert reads_as_an_ending(name) is False

    def test_confirm_is_an_action_and_confirmed_is_an_ending(self) -> None:
        # The distinction the lexicon is built around. "Confirm Payment" is a
        # screen you act on and must keep its dead end warning; "Payment
        # Confirmed" is a screen you leave.
        assert reads_as_an_ending("Confirm Payment") is False
        assert reads_as_an_ending("Payment Confirmed") is True


# --- one mutation per rule, and the catalogue is pinned to this table ---------


def _add_link(flow: dict, screen: int, **link) -> dict:
    flow["screens"][screen]["links"].append(link)
    return flow


def _dangling_link(flow: dict) -> dict:
    # A new link rather than a repointed one, so s2 stays reachable and this
    # mutation tests one rule instead of knocking over two.
    return _add_link(flow, 0, id="l9", label="Help", target_id="s9", variant="text")


def _self_link(flow: dict) -> dict:
    return _add_link(flow, 0, id="l9", label="Refresh", target_id="s1", variant="text")


def _unreachable_pair(flow: dict) -> dict:
    """Two screens that link to each other and to nothing else.

    The case that makes reachability worth computing: both have an inbound link,
    so any rule that counts inbound links passes this flow, and no reader can
    open either screen.
    """
    flow["screens"].extend(
        [
            {
                "id": "s4",
                "name": "Saved Cards",
                "crumbs": [],
                "traces": ["R-3"],
                "blocks": [{"id": "b5", "kind": "list", "label": "Your cards"}],
                "links": [{"id": "l4", "label": "Add", "target_id": "s5", "variant": "primary"}],
            },
            {
                "id": "s5",
                "name": "Add a Card",
                "crumbs": [],
                "traces": ["R-3"],
                "blocks": [{"id": "b6", "kind": "field", "label": "Card number"}],
                "links": [{"id": "l5", "label": "Back", "target_id": "s4", "variant": "secondary"}],
            },
        ]
    )
    return flow


def _duplicate_screen_id(flow: dict) -> dict:
    flow["screens"][1]["id"] = "s1"
    return flow


def _duplicate_link_id(flow: dict) -> dict:
    return _add_link(flow, 1, id="l2", label="Cancel", target_id="s1", variant="text")


def _blank_label(flow: dict) -> dict:
    flow["screens"][1]["blocks"][0]["label"] = ""
    return flow


def _unknown_kind(flow: dict) -> dict:
    flow["screens"][0]["blocks"][0]["kind"] = "carousel"
    return flow


def _empty_screen(flow: dict) -> dict:
    flow["screens"][1]["blocks"] = []
    return flow


def _block_wired_to_nothing(flow: dict) -> dict:
    flow["screens"][0]["blocks"][0]["link_id"] = "l7"
    return flow


def _untraced_screen(flow: dict) -> dict:
    flow["screens"][1]["traces"] = []
    return flow


def _invented_trace(flow: dict) -> dict:
    flow["screens"][1]["traces"] = ["R-99"]
    return flow


def _unmarked_dead_end(flow: dict) -> dict:
    # The same screen, renamed so its name no longer says the journey ends.
    flow["screens"][2]["name"] = "Order Overview"
    return flow


#: Every rule, the mutation that trips it, and whether it blocks. The table is
#: the test: a rule added to the catalogue without an entry here fails the build.
MUTATIONS = [
    ("unique-screen-ids", "error", _duplicate_screen_id),
    ("unique-link-ids", "error", _duplicate_link_id),
    ("names-are-present", "error", _blank_label),
    ("kinds-are-known", "error", _unknown_kind),
    ("screen-has-content", "error", _empty_screen),
    ("link-target-exists", "error", _dangling_link),
    ("no-self-link", "error", _self_link),
    ("reachable-from-the-entry", "error", _unreachable_pair),
    ("no-unmarked-dead-end", "warning", _unmarked_dead_end),
    ("block-activates-a-real-link", "error", _block_wired_to_nothing),
    ("screen-is-traced", "error", _untraced_screen),
    ("traces-resolve", "error", _invented_trace),
]


class TestTheRuleCatalogue:
    @pytest.mark.parametrize("rule_id,severity,mutate", MUTATIONS, ids=[m[0] for m in MUTATIONS])
    def test_the_mutation_trips_its_rule(self, rule_id: str, severity: str, mutate) -> None:
        clean = good_flow()
        broken = mutate(good_flow())
        assert broken != clean, "the mutation changed nothing, so this test proves nothing"

        report = check(broken)
        assert rule_id in report.rule_ids(), (
            f"{rule_id} did not fire; what fired was {report.rule_ids()}"
        )
        fired = [f for f in report.findings if f.rule_id == rule_id]
        assert all(f.severity == severity for f in fired)

    def test_every_rule_in_the_catalogue_has_a_mutation(self) -> None:
        # The guard against a rule that ships untested. A catalogue is only worth
        # counting findings from if every entry is known to fire.
        assert {rule_id for rule_id, _, _ in MUTATIONS} == set(RULE_IDS)

    def test_the_catalogue_is_the_size_it_claims(self) -> None:
        assert len(RULE_IDS) == 12
        assert len(set(RULE_IDS)) == 12

    @pytest.mark.parametrize("rule_id,severity,mutate", MUTATIONS, ids=[m[0] for m in MUTATIONS])
    def test_every_finding_says_something_to_both_readers(
        self, rule_id: str, severity: str, mutate
    ) -> None:
        for finding in check(mutate(good_flow())).findings:
            assert finding.reason.strip()
            assert finding.hint.strip()
            # Different jobs: the reason is for a person looking at the design,
            # the hint names ids and says what to do next.
            assert finding.hint != finding.reason


class TestReachabilityIsWalkedNotCounted:
    def test_two_screens_pointing_at_each_other_are_still_unreachable(self) -> None:
        report = check(_unreachable_pair(good_flow()))
        unreachable = [f for f in report.errors if f.rule_id == "reachable-from-the-entry"]

        assert {f.subject for f in unreachable} == {"s4", "s5"}
        # Both have an inbound link, which is exactly why counting them would
        # have passed this flow.
        assert report.ok is False

    def test_the_entry_screen_is_never_reported_as_unreachable(self) -> None:
        # It has no inbound link by definition, and a rule that fired on it
        # would fire on every flow ever generated.
        report = check(good_flow())
        assert "reachable-from-the-entry" not in report.rule_ids()

    def test_a_screen_reached_only_through_another_is_reachable(self) -> None:
        report = check(good_flow())
        assert not [f for f in report.findings if f.subject == "s3"]

    def test_an_entry_with_no_id_reports_once_and_not_per_screen(self) -> None:
        # One real cause should not become a page of findings.
        flow = good_flow()
        flow["screens"][0]["id"] = ""
        report = check(flow)
        assert "reachable-from-the-entry" not in report.rule_ids()
        assert "names-are-present" in report.rule_ids()


class TestADeadEndIsShownNotRefused:
    def test_an_unmarked_dead_end_warns_and_does_not_block(self) -> None:
        report = check(_unmarked_dead_end(good_flow()))

        assert "no-unmarked-dead-end" in report.rule_ids()
        # The whole point of the severity choice: the flow is still promotable.
        assert report.ok is True
        assert report.errors == ()

    def test_a_named_ending_is_not_reported_at_all(self) -> None:
        report = check(good_flow())
        assert "no-unmarked-dead-end" not in report.rule_ids()

    def test_the_warning_says_which_screen_and_carries_its_traces(self) -> None:
        warning = next(
            f
            for f in check(_unmarked_dead_end(good_flow())).warnings
            if f.rule_id == "no-unmarked-dead-end"
        )
        assert warning.subject == "s3"
        assert warning.traces == ("R-2",)


# --- promotion ----------------------------------------------------------------


def promote(flow: dict) -> WireframeFlow:
    draft = DraftFlow.model_validate(flow)
    report = validate_flow(draft, requirement_ids=REQUIREMENT_IDS)
    assert report.ok
    return to_contract(draft, report, flow_id="flow-a1", version="v3", traces=["R-1", "R-2"])


class TestPromotion:
    def test_the_ending_is_marked_terminal_and_nothing_else_is(self) -> None:
        flow = promote(good_flow())
        assert [s.terminal for s in flow.screens] == [False, False, True]

    def test_the_marker_and_the_warning_come_from_one_decision(self) -> None:
        # A screen exempt from the dead end warning is exactly a screen marked
        # terminal. If these ever disagree, a reader seeing no warnings could not
        # conclude the endings were the marked ones.
        raw = good_flow()
        promoted = promote(raw)
        warned = {f.subject for f in check(raw).findings if f.rule_id == "no-unmarked-dead-end"}
        for screen in promoted.screens:
            if not screen.links:
                assert screen.terminal is (screen.id not in warned)

    def test_the_model_cannot_set_terminal(self) -> None:
        # Enforcement by type, the same way the explanation agent cannot produce
        # a score. Asking for it in the draft is not a validation failure; the
        # field does not exist to ask for.
        assert "terminal" not in DraftFlow.model_json_schema()["$defs"]["DraftScreen"]["properties"]

    def test_coverage_is_not_claimed_at_generation_time(self) -> None:
        # Flows never see the sprint plan, so a flow asserting which story it
        # covers would be asserting something nothing checked.
        assert promote(good_flow()).covers_story_ids == []

    def test_flow_traces_come_from_the_brief_not_the_screens(self) -> None:
        flow = promote(good_flow())
        assert flow.traces == ["R-1", "R-2"]

    def test_the_blocks_and_links_survive_intact(self) -> None:
        flow = promote(good_flow())
        basket = flow.screens[0]
        assert [b.id for b in basket.blocks] == ["b1", "b2"]
        assert basket.blocks[1].link_id == "l1"
        assert basket.links[0].target_id == "s2"
        assert flow.screens[2].blocks[0].tone == "positive"

    def test_a_promoted_flow_satisfies_the_contract_validators(self) -> None:
        # The rules exist so this never raises. If a rule is missing, this is
        # where a raw ValueError would surface instead of a readable finding.
        WireframeFlow.model_validate(promote(good_flow()).model_dump(by_alias=True))


# --- the flow plan ------------------------------------------------------------


def node(id: str, kind: str, label: str, **extra) -> GraphNode:
    return GraphNode(
        id=id, kind=kind, label=label, position=Position(x=0, y=0), traces=["R-1"], **extra
    )


def payments_graph() -> ArchitectureGraph:
    return ArchitectureGraph(
        nodes=[
            node("a1", "actor", "Customer", actorKind="primary"),
            node("a2", "actor", "Administrator", actorKind="primary"),
            node("a3", "actor", "Payment Gateway", actorKind="external_system"),
            node("a4", "actor", "Auditor", actorKind="primary"),
            node("e1", "entity", "Payment", attributes=[{"name": "amount", "type": "number"}]),
            node("e2", "entity", "Refund", attributes=[{"name": "reason", "type": "string"}]),
            node("m1", "service", "Payment Service"),
        ],
        edges=[
            GraphEdge(
                id="x1", source="a1", target="e1", kind="action", verb="makes", traces=["R-1"]
            ),
            GraphEdge(
                id="x2", source="a1", target="e2", kind="action", verb="requests", traces=["R-2"]
            ),
            GraphEdge(
                id="x3", source="a2", target="e2", kind="action", verb="approves", traces=["R-3"]
            ),
            GraphEdge(id="x4", source="m1", target="e1", kind="data", verb="owns", traces=["R-1"]),
        ],
    )


class TestTheFlowPlan:
    def test_one_journey_per_primary_actor_that_does_something(self) -> None:
        briefs = plan_flows(payments_graph())
        assert [b.actor_id for b in briefs] == ["a1", "a2"]

    def test_an_external_system_gets_no_journey(self) -> None:
        # A payment gateway is an actor and nobody clicks through its screens.
        assert "a3" not in {b.actor_id for b in plan_flows(payments_graph())}

    def test_an_actor_who_does_nothing_gets_no_journey(self) -> None:
        # The Auditor is in the graph and has no action edge. Drawing screens for
        # them would be inventing scope nothing asked for.
        assert "a4" not in {b.actor_id for b in plan_flows(payments_graph())}

    def test_the_busiest_actor_comes_first(self) -> None:
        briefs = plan_flows(payments_graph())
        assert briefs[0].actor_id == "a1"
        assert len(briefs[0].actions) == 2

    def test_the_brief_carries_the_entities_and_the_traces(self) -> None:
        customer = plan_flows(payments_graph())[0]
        assert customer.entity_ids == ("e1", "e2")
        assert customer.traces == ("R-1", "R-2")
        assert customer.actions == ("makes Payment", "requests Refund")

    def test_the_cap_drops_the_least_involved_actor(self) -> None:
        graph = payments_graph()
        for index in range(5):
            graph.nodes.append(node(f"b{index}", "actor", f"Person {index}", actorKind="primary"))
            graph.edges.append(
                GraphEdge(
                    id=f"y{index}",
                    source=f"b{index}",
                    target="e1",
                    kind="action",
                    verb="views",
                    traces=["R-1"],
                )
            )
        briefs = plan_flows(graph)
        assert len(briefs) == MAX_FLOWS
        # The Customer does two things and everyone else does one, so the cap
        # must not be able to cut them.
        assert briefs[0].actor_id == "a1"

    def test_a_system_with_no_acting_actor_still_gets_one_journey(self) -> None:
        # The calculator shape: one service, one entity, nobody named.
        thin = ArchitectureGraph(
            nodes=[
                node(
                    "e1", "entity", "Calculation", attributes=[{"name": "result", "type": "number"}]
                ),
                node("m1", "service", "Calculator"),
            ],
            edges=[
                GraphEdge(
                    id="x1", source="m1", target="e1", kind="data", verb="owns", traces=["R-1"]
                )
            ],
        )
        briefs = plan_flows(thin)
        assert len(briefs) == 1
        assert briefs[0].actor_id is None
        assert briefs[0].entity_ids == ("e1",)
        assert briefs[0].traces == ("R-1",)


class TestThePrompt:
    def test_it_offers_only_the_requirement_ids_that_exist(self) -> None:
        brief = plan_flows(payments_graph())[0]
        prompt = prompt_for(brief, payments_graph(), ["R-1", "R-2", "R-3"])
        assert "R-1, R-2, R-3" in prompt

    def test_it_names_the_actor_and_what_they_do(self) -> None:
        brief = plan_flows(payments_graph())[0]
        prompt = prompt_for(brief, payments_graph(), ["R-1"])
        assert "Customer" in prompt
        assert "makes Payment" in prompt

    def test_it_grounds_the_screens_in_the_entity_fields(self) -> None:
        brief = plan_flows(payments_graph())[0]
        prompt = prompt_for(brief, payments_graph(), ["R-1"])
        assert "Payment: amount" in prompt

    def test_it_says_what_the_journey_s_requirements_ask_for(self) -> None:
        """The drawer saw actors, actions and field names and never what anybody
        asked for, so every journey came out as the same forms and lists."""
        brief = plan_flows(payments_graph())[0]
        said = [(rid, f"what {rid} asks for") for rid in (*brief.traces, "R-99")]

        prompt = prompt_for(brief, payments_graph(), [*brief.traces, "R-99"], said)

        assert "What the requirements say" in prompt
        for rid in brief.traces:
            assert f"{rid}: what {rid} asks for" in prompt
        assert "R-99: what R-99 asks for" not in prompt, "another journey's requirement"


# --- the repair loop ----------------------------------------------------------


class Recorder:
    """Scripted flows, and a record of what the model was asked each time."""

    def __init__(self, *flows: dict) -> None:
        self.flows = list(flows)
        self.prompts: list[str] = []

    def as_function(self):
        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            self.prompts.append(_last_user_text(messages))
            flow = self.flows[min(len(self.prompts) - 1, len(self.flows) - 1)]
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(flow))])

        return respond


def _last_user_text(messages: list[ModelMessage]) -> str:
    for message in reversed(messages):
        for part in getattr(message, "parts", []):
            content = getattr(part, "content", None)
            if isinstance(content, str) and content.strip():
                return content
    return ""


def agent_for(recorder: Recorder):
    return build_wireframe_agent(FunctionModel(recorder.as_function()))


async def run_loop(recorder: Recorder):
    brief = plan_flows(payments_graph())[0]
    return await draw_flow(
        brief,
        payments_graph(),
        agent=agent_for(recorder),
        requirement_ids=["R-1", "R-2", "R-3"],
        version="v1",
    )


class TestTheHintsActuallyTravel:
    async def test_the_second_prompt_names_what_the_first_answer_broke(self) -> None:
        recorder = Recorder(_dangling_link(good_flow()), good_flow())
        await run_loop(recorder)

        assert len(recorder.prompts) == 2
        first, second = recorder.prompts
        assert first != second
        assert "s9" in second, "the hint did not name the broken destination"
        assert "l9" in second, "the hint did not name the offending link"
        assert "s9" not in first, "the failure leaked into the first ask"

    async def test_the_repaired_flow_is_the_one_returned(self) -> None:
        recorder = Recorder(_dangling_link(good_flow()), good_flow())
        flow, report = await run_loop(recorder)

        assert report.attempts == 2
        assert report.repaired is True
        assert report.errors_per_attempt == (("link-target-exists",), ())
        assert [screen.id for screen in flow.screens] == ["s1", "s2", "s3"]

    async def test_a_warning_never_triggers_a_repair(self) -> None:
        # Sending warnings back would teach the model to link confirmation
        # screens to the start to silence the check, which is a worse prototype.
        recorder = Recorder(_unmarked_dead_end(good_flow()))
        flow, report = await run_loop(recorder)

        assert len(recorder.prompts) == 1
        assert report.attempts == 1
        assert [f.rule_id for f in report.warnings] == ["no-unmarked-dead-end"]
        # And the warning travelled with the flow rather than being dropped.
        assert report.warnings[0].subject == "s3"
        assert flow.screens[2].terminal is False


class TestTheLoopIsBounded:
    async def test_a_clean_flow_is_asked_for_once(self) -> None:
        recorder = Recorder(good_flow())
        _, report = await run_loop(recorder)

        assert len(recorder.prompts) == 1
        assert report.clean_first_time is True
        assert report.repaired is False

    async def test_a_model_that_never_fixes_it_stops_after_two(self) -> None:
        recorder = Recorder(_dangling_link(good_flow()), _dangling_link(good_flow()), good_flow())
        with pytest.raises(CouldNotDrawFlow) as raised:
            await run_loop(recorder)

        assert len(recorder.prompts) == 2, "it should not have reached the third answer"
        assert raised.value.attempts == 2
        assert raised.value.flow_id == "flow-a1"
        # The caller has to be able to fail the stage with reasons, not a stack
        # trace, so the findings come with the exception.
        assert "link-target-exists" in raised.value.report.rule_ids()
        assert "leads nowhere" in str(raised.value)


class TestTheSharedFindingType:
    def test_a_finding_becomes_something_the_frontend_can_render(self) -> None:
        finding = Finding(
            rule_id="no-unmarked-dead-end",
            severity="warning",
            reason="A reader who opens it is stuck.",
            hint="Add a link.",
            subject="s3",
            traces=("R-2",),
        )
        contract = finding.to_contract()
        assert contract.rule_id == "no-unmarked-dead-end"
        assert contract.reason == "A reader who opens it is stuck."
        assert contract.traces == ["R-2"]


@pytest.mark.live
class TestAgainstARealModel:
    async def test_it_draws_a_journey_whose_links_all_land(
        self, allow_live_requests, live_model_name: str, live
    ) -> None:
        graph = payments_graph()
        brief = plan_flows(graph)[0]
        agent = await live(build_wireframe_agent(live_model_name))

        flow, report = await draw_flow(
            brief,
            graph,
            agent=agent,
            requirement_ids=["R-1", "R-2", "R-3"],
            version="v1",
        )

        print(f"\nflow={flow.name!r} screens={len(flow.screens)} attempts={report.attempts}")
        for screen in flow.screens:
            ending = " (ending)" if screen.terminal else ""
            ways_out = ", ".join(f"{link.label} -> {link.target_id}" for link in screen.links)
            print(f"  {screen.id} {screen.name}{ending}: {ways_out or 'no way out'}")
        for warning in report.warnings:
            print(f"  warning {warning.rule_id}: {warning.reason}")

        # Every claim the rules make, re-asserted against a real answer. Screen
        # traces are not among them: they are checked on the draft and dropped
        # at promotion, so `draw_flow` returning at all is the proof they passed.
        known = {screen.id for screen in flow.screens}
        assert len(flow.screens) >= 2
        assert flow.traces, "the flow traced to nothing"
        for screen in flow.screens:
            assert screen.blocks, f"{screen.id} came back empty"
            for link in screen.links:
                assert link.target_id in known
                assert link.target_id != screen.id

        # And the endings are marked by rule rather than claimed by the model.
        for screen in flow.screens:
            assert screen.terminal == reads_as_an_ending(screen.name)
