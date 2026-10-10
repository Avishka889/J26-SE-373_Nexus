"""Scoring by arithmetic, explanation by model, and the guards on both.

The two claims here are the ones a panel will probe. First, that the score is
computed rather than asserted, which means it has to respond to the design and be
able to say why. Second, that the recommendation is an argument rather than a
rubber stamp, which means it has to be capable of a close call and of changing
its mind on a different design.
"""

import json

import pytest
from c1.architecture.explain import (
    TopologyExplanation,
    _citable,
    build_explainer,
    check_no_invented_figures,
    explain_all,
    prompt_for,
)
from c1.architecture.scoring import (
    CANDIDATES,
    ScoringFacts,
    gather_facts,
    margin,
    recommended,
    score_topologies,
)
from pydantic import ValidationError
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sdlc_contracts import (
    ArchitectureGraph,
    ArchitectureStyleNote,
    EntityAttribute,
    GraphEdge,
    GraphNode,
    ParsedRequirement,
    Position,
)

#: Four designs with genuinely different shapes, which is what makes the spread
#: assertions mean anything: one corpus can be fitted, four cannot.
#: Five requirements, not one, because that is what the budget allows for the
#: one line calculator input and therefore what a real run produces. At one it
#: sat a single requirement away from tripping the closeness guard below, which
#: made that guard pass for a reason nothing stated.
CALCULATOR = ScoringFacts(n_requirements=5, n_services=1, n_entities=1)
PAYMENTS = ScoringFacts(
    n_requirements=12,
    n_services=6,
    n_entities=6,
    n_external=2,
    cross_service_writes=1,
    compliance_signal=True,
)
COMMERCE = ScoringFacts(
    n_requirements=12,
    n_services=5,
    n_entities=5,
    n_external=2,
    independent_scaling=True,
)
NOTIFICATIONS = ScoringFacts(
    n_requirements=6,
    n_services=3,
    n_entities=3,
    n_external=2,
    independent_scaling=True,
)
CORPORA = {
    "calculator": CALCULATOR,
    "payments": PAYMENTS,
    "commerce": COMMERCE,
    "notifications": NOTIFICATIONS,
}

STYLE = ArchitectureStyleNote(
    id="clean",
    name="Clean Architecture",
    note="Applies inside whichever shape is chosen, so it is not scored against them.",
)


class TestTheScoreIsArithmetic:
    def test_the_calculator_recommends_the_monolith_out_of_counting(self) -> None:
        best = recommended(CALCULATOR)
        assert best.id == "modular-monolith"
        # And it can say why, in facts rather than in taste.
        assert best.adjustments
        assert "1 services" in best.why or "1 service" in best.why

    def test_every_adjustment_names_the_fact_that_caused_it(self) -> None:
        for name, facts in CORPORA.items():
            for candidate in score_topologies(facts):
                for adjustment in candidate.adjustments:
                    assert adjustment.factor, f"{name}/{candidate.id}: unnamed factor"
                    assert adjustment.points != 0
                    assert adjustment.reason.endswith("."), "a reason is a sentence"

    def test_the_score_is_the_base_plus_its_adjustments(self) -> None:
        # No hidden term: a reader adding up the reasons gets the number.
        bases = {identifier: base for identifier, _name, base, _rule in CANDIDATES}
        for facts in CORPORA.values():
            for candidate in score_topologies(facts):
                expected = bases[candidate.id] + sum(a.points for a in candidate.adjustments)
                assert candidate.score == max(0, min(100, expected))

    def test_the_same_design_scores_the_same_way_twice(self) -> None:
        for facts in CORPORA.values():
            first = [(c.id, c.score) for c in score_topologies(facts)]
            second = [(c.id, c.score) for c in score_topologies(facts)]
            assert first == second

    def test_scores_stay_inside_nought_to_a_hundred(self) -> None:
        extreme = ScoringFacts(
            n_requirements=200,
            n_services=40,
            n_entities=40,
            n_external=20,
            cross_service_writes=15,
            independent_scaling=True,
            compliance_signal=True,
        )
        for candidate in score_topologies(extreme):
            assert 0 <= candidate.score <= 100


class TestItIsARecommendationNotARubberStamp:
    #: Designs where the answer is genuinely arguable: several services, several
    #: entities, something outside the design's control. A scorer that is miles
    #: ahead on one of these is not weighing anything, it has a favourite.
    CONTESTED = ("payments", "commerce", "notifications")

    @pytest.mark.parametrize("name", CONTESTED)
    def test_a_contested_design_is_never_a_landslide(self, name: str) -> None:
        facts = CORPORA[name]
        assert margin(facts) <= 30, f"{name}: winner ahead by {margin(facts)}"

    def test_a_trivial_design_is_allowed_a_decisive_winner(self) -> None:
        """The other side of the same coin, and the reason the guard above is not
        applied to everything.

        A calculator is one service and one thing it stores. The monolith is not
        narrowly better for it, it is obviously better, and a cap on the margin
        would make the honest answer a failure. This asserts the shape of a
        confident recommendation instead: the right winner, clear of the rest, and
        still with the costs written down.

        The cap used to cover this corpus and passed only because the fixture said
        one requirement. At five, which is what the budget allows for the real
        input, the margin is 37. Nobody would have found that until they added a
        sixth requirement to an unrelated test.
        """
        best = recommended(CALCULATOR)
        assert best.id == "modular-monolith"
        assert margin(CALCULATOR) > 30, (
            "the obvious answer stopped being obvious; if the scoring changed, "
            "this corpus is the place to argue about it"
        )
        # Decisive is not the same as unexamined. Every shape still carries what
        # it would cost, which is what stops a landslide reading as a rubber stamp.
        assert len(best.adjustments) >= 1

    def test_a_different_design_gets_a_different_answer(self) -> None:
        # The strongest evidence that the facts are doing the work: change the
        # design and the recommendation changes.
        winners = {name: recommended(facts).id for name, facts in CORPORA.items()}
        assert len(set(winners.values())) > 1, f"one shape always wins: {winners}"
        assert winners["calculator"] == "modular-monolith"
        assert winners["commerce"] == "microservices"

    def test_it_can_say_that_two_shapes_are_close(self) -> None:
        # A scorer that cannot express "these are nearly equal" is asserting
        # confidence it does not have.
        assert margin(NOTIFICATIONS) < 10

    def test_scaling_apart_is_what_flips_it(self) -> None:
        # One fact, changed alone, moves the recommendation. That is the whole
        # claim about the scoring responding to the design.
        without = ScoringFacts(n_requirements=12, n_services=5, n_entities=5, n_external=2)
        with_scaling = ScoringFacts(
            n_requirements=12, n_services=5, n_entities=5, n_external=2, independent_scaling=True
        )
        assert recommended(without).id == "modular-monolith"
        assert recommended(with_scaling).id == "microservices"

    def test_a_code_style_is_never_scored_against_a_deployment_shape(self) -> None:
        # "Clean Architecture 71 versus Microservices 68" compares two different
        # axes, and a panel will say so.
        ids = {identifier for identifier, *_rest in CANDIDATES}
        for style in ("clean", "layered", "mvc", "hexagonal"):
            assert style not in ids


class TestCountingTheFacts:
    def test_reads_the_counts_off_the_graph(self) -> None:
        graph = ArchitectureGraph(
            nodes=[
                GraphNode(
                    id="a1",
                    kind="actor",
                    label="Customer",
                    position=Position(x=0, y=0),
                    traces=["R-1"],
                    actorKind="primary",
                ),
                GraphNode(
                    id="a2",
                    kind="actor",
                    label="Provider",
                    position=Position(x=0, y=1),
                    traces=["R-1"],
                    actorKind="external_system",
                ),
                GraphNode(
                    id="e1",
                    kind="entity",
                    label="Payment",
                    position=Position(x=1, y=0),
                    traces=["R-1"],
                    attributes=[EntityAttribute(name="id", type="UUID")],
                ),
                GraphNode(
                    id="m1",
                    kind="service",
                    label="Pay",
                    position=Position(x=2, y=0),
                    traces=["R-1"],
                ),
                GraphNode(
                    id="m2",
                    kind="service",
                    label="Audit",
                    position=Position(x=2, y=1),
                    traces=["R-1"],
                ),
            ],
            edges=[
                GraphEdge(
                    id="d1", source="m1", target="e1", kind="data", verb="owns", traces=["R-1"]
                ),
                GraphEdge(
                    id="d2", source="m2", target="e1", kind="data", verb="writes", traces=["R-1"]
                ),
            ],
        )
        facts = gather_facts(
            [
                ParsedRequirement(
                    id="R-1",
                    text="Payments must comply with PCI DSS.",
                    type="constraint",
                    priority="must",
                    confidence=90,
                )
            ],
            graph,
        )

        assert facts.n_services == 2
        assert facts.n_entities == 1
        assert facts.n_external == 1
        # Two services write the same entity: a transaction across a boundary.
        assert facts.cross_service_writes == 1
        assert facts.compliance_signal is True
        assert facts.independent_scaling is False

    def test_notices_a_requirement_asking_for_one_part_to_scale_apart(self) -> None:
        facts = gather_facts(
            [
                ParsedRequirement(
                    id="R-1",
                    text="One storefront's traffic cannot degrade another storefront.",
                    type="quality",
                    priority="should",
                    confidence=60,
                    qualityAttribute="performance",
                )
            ],
            ArchitectureGraph(),
        )
        assert facts.independent_scaling is True


class TestTheModelWritesWordsNotNumbers:
    def test_the_output_type_has_no_score_field(self) -> None:
        # Enforcement by type rather than by hoping the prompt is obeyed.
        assert "score" not in TopologyExplanation.model_fields

    def test_a_card_with_only_upside_is_refused_by_the_type(self) -> None:
        with pytest.raises(ValidationError):
            TopologyExplanation(rationale="Fine.", pros=["Fast"], cons=["Only one"])

    @pytest.mark.parametrize(
        "prose",
        [
            "Supports 10,000 concurrent users.",
            "Responds in under 200ms.",
            "Handles 5000 requests per second.",
        ],
    )
    def test_catches_a_figure_the_design_never_stated(self, prose: str) -> None:
        assert check_no_invented_figures(prose, PAYMENTS)

    def test_allows_a_figure_that_is_one_of_the_counted_facts(self) -> None:
        # 6 services and 6 entities are real counts for this design.
        assert check_no_invented_figures("The 6 services stay in one deployment.", PAYMENTS) == []

    def test_a_stray_bullet_character_never_reaches_the_card(self) -> None:
        # A real run produced ".Requires external stores for entities". The
        # meaning is fine; the punctuation is noise the model did not mean.
        explanation = TopologyExplanation(
            rationale="Fine.",
            pros=[".Requires external stores", "- another"],
            cons=["* costly", "complex to run"],
        )
        assert explanation.pros == ["Requires external stores", "Another"]
        assert explanation.cons == ["Costly", "Complex to run"]

    def test_allows_prose_with_no_figures_at_all(self) -> None:
        assert (
            check_no_invented_figures("Everything scales together, which is cheaper.", PAYMENTS)
            == []
        )


def explainer_returning(payload: dict, *, then: dict | None = None):
    """A model that returns this explanation, then optionally a second one."""
    calls: list[int] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(1)
        body = payload if (len(calls) == 1 or then is None) else then
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(body))])

    return build_explainer(FunctionModel(respond)), calls


class TestTheGuardInPractice:
    async def test_an_invented_figure_is_sent_back_rather_than_shown(self) -> None:
        bad = {
            "rationale": "This comfortably supports 10000 concurrent users.",
            "pros": ["Scales well"],
            "cons": ["Costly", "Complex"],
        }
        good = {
            "rationale": "With 6 services and one write crossing a boundary, one deployment "
            "keeps that write in a single transaction.",
            "pros": ["One thing to deploy"],
            "cons": ["Everything scales together", "Boundaries hold only if reviewed"],
        }
        agent, calls = explainer_returning(bad, then=good)
        scored = score_topologies(PAYMENTS)

        recommendation, _ = await explain_all(scored, PAYMENTS, agent=agent, style=STYLE)

        # It asked again rather than passing the invented figure through.
        assert len(calls) > len(scored)
        for candidate in recommendation.candidates:
            assert "10000" not in candidate.rationale

    async def test_the_scores_come_from_the_arithmetic_not_the_model(self) -> None:
        payload = {
            "rationale": "Reasonable here.",
            "pros": ["One deployment"],
            "cons": ["Scales together", "Needs discipline"],
        }
        agent, _ = explainer_returning(payload)
        scored = score_topologies(PAYMENTS)

        recommendation, _ = await explain_all(scored, PAYMENTS, agent=agent, style=STYLE)

        by_id = {candidate.id: candidate.score for candidate in recommendation.candidates}
        for candidate in scored:
            assert by_id[candidate.id] == candidate.score
        assert recommendation.recommended_candidate_id == scored[0].id

    async def test_nobody_has_chosen_yet(self) -> None:
        payload = {
            "rationale": "Reasonable here.",
            "pros": ["One deployment"],
            "cons": ["Scales together", "Needs discipline"],
        }
        agent, _ = explainer_returning(payload)
        recommendation, _ = await explain_all(
            score_topologies(CALCULATOR), CALCULATOR, agent=agent, style=STYLE
        )
        # The recommendation is an argument; the gate is where a human answers it.
        assert recommendation.selected_candidate_id is None
        assert recommendation.selected_by is None

    def test_the_prompt_carries_the_facts_and_the_scoring_reasons(self) -> None:
        best = score_topologies(PAYMENTS)[0]
        prompt = prompt_for(best, PAYMENTS)
        assert "services: 6" in prompt
        assert "What the scoring noticed" in prompt
        # And never the score itself, which the model must not be able to echo.
        assert str(best.score) not in prompt.split("What the scoring noticed")[0]


@pytest.mark.live
@pytest.mark.filterwarnings("ignore::ResourceWarning")
@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
class TestAgainstARealProvider:
    """Whether a real model explains a score without inventing evidence for it."""

    async def test_writes_grounded_prose_for_every_shape(
        self, allow_live_requests: None, live_model_name: str, live
    ) -> None:
        scored = score_topologies(PAYMENTS)
        recommendation, _ = await explain_all(
            scored, PAYMENTS, agent=await live(build_explainer(live_model_name)), style=STYLE
        )

        assert len(recommendation.candidates) == len(scored)
        for candidate in recommendation.candidates:
            assert candidate.rationale.strip()
            assert len(candidate.cons) >= 2, "a card with only upside is not an assessment"
            # The guard is an output validator, so anything reaching here already
            # passed it. Asserting again is the belt: a figure that slipped
            # through would be the one a reader believes.
            assert (
                check_no_invented_figures(
                    " ".join([candidate.rationale, *candidate.pros, *candidate.cons]), PAYMENTS
                )
                == []
            )

        # And the scores are still the counted ones, untouched by the model.
        by_id = {c.id: c.score for c in recommendation.candidates}
        assert by_id == {c.id: c.score for c in scored}


class TestAFigureIsGroundedByItsUnitNotItsDigits:
    """What "invented" means, after a whole stage died on the old definition.

    The guard used to allow only the counted facts, so an explanation quoting the
    brief's own "99.5 percent" was refused. The model kept reaching for the most
    relevant number there was, the guard kept sending it back, and the retries
    ran out.

    Widening it to "the digits appear in the facts or the brief" would have been
    worse than the bug. Small integers are in every brief: "under 2 seconds" puts
    2 into the allowed set, 3 is a count in most designs, and "a team of 2 to 3
    engineers" would then pass as grounded. Almost any small-number claim would.

    So a figure is grounded when the number and the word after it both match.
    """

    #: A design whose brief states three figures, none of them a count.
    COLD_CHAIN = ScoringFacts(
        n_requirements=29,
        n_services=10,
        n_entities=8,
        n_external=4,
        cross_service_writes=3,
        independent_scaling=True,
        compliance_signal=True,
        source_figures=frozenset({("99.5", "percent"), ("30", "second"), ("2", "second")}),
    )

    @pytest.mark.parametrize(
        "prose",
        [
            "It must stay available 99.5 percent of the time.",
            "Readings appear within 30 seconds.",
            "The dashboard loads in under 2 seconds.",
        ],
    )
    def test_a_figure_the_brief_states_is_not_an_invention(self, prose: str) -> None:
        assert check_no_invented_figures(prose, self.COLD_CHAIN) == []

    def test_a_count_is_citable_under_the_name_it_was_counted_by(self) -> None:
        assert (
            check_no_invented_figures("There are 10 services and 8 entities.", self.COLD_CHAIN)
            == []
        )

    def test_the_digits_alone_do_not_ground_a_claim(self) -> None:
        # The case that decides the whole design. Both numbers are individually
        # grounded: 2 from the brief's "2 seconds", 3 from cross service writes.
        # Neither was ever said about engineers.
        refused = check_no_invented_figures(
            "This suits a team of 2 to 3 engineers.", self.COLD_CHAIN
        )
        assert refused, "digit-only grounding lets any small-number claim through"
        assert "3 engineers" in refused

    @pytest.mark.parametrize(
        "prose",
        [
            "Supports 10,000 concurrent users.",
            "Responds in under 200ms.",
            "Handles 5000 requests per second.",
        ],
    )
    def test_the_class_of_invention_this_exists_for_is_still_refused(self, prose: str) -> None:
        assert check_no_invented_figures(prose, self.COLD_CHAIN)

    def test_a_refusal_quotes_what_the_model_wrote(self) -> None:
        # The list goes back to the model. Being told it invented "200 m" when it
        # wrote "200ms" is a correction it cannot act on.
        assert check_no_invented_figures("Responds in under 200ms.", self.COLD_CHAIN) == ["200ms"]
        assert check_no_invented_figures("Supports 10,000 users.", self.COLD_CHAIN) == [
            "10,000 users"
        ]

    def test_a_plural_is_not_a_different_figure(self) -> None:
        # "8 entity" and "8 entities" are the same claim.
        assert check_no_invented_figures("There are 8 entity records.", self.COLD_CHAIN) == []

    def test_a_percent_sign_and_the_word_are_the_same_unit(self) -> None:
        # The brief writes "99.5 percent"; prose may write "99.5%".
        assert check_no_invented_figures("Available 99.5% of the time.", self.COLD_CHAIN) == []

    def test_a_design_with_no_stated_figures_still_allows_its_counts(self) -> None:
        # source_figures empty is the ordinary case for a thin brief.
        bare = ScoringFacts(n_requirements=5, n_services=1, n_entities=2)
        assert check_no_invented_figures("One service holds 2 entities.", bare) == []
        assert check_no_invented_figures("Handles 900 users.", bare)


class TestTheAdviceOnARetry:
    """What the model is told when a figure is refused.

    Spent on every attempt, so a misleading one costs the whole stage. The first
    version printed the comparison pairs, which are exploded into single words so
    that "8 entities" and "8 entity" match. As advice that read "1 cross, 1
    service, 1 write, 11 service": fragments, and two different counts for the
    same word.
    """

    FACTS = ScoringFacts(
        n_requirements=29,
        n_services=11,
        n_entities=8,
        n_external=4,
        cross_service_writes=1,
        compliance_signal=True,
        source_figures=frozenset({("99.5", "percent"), ("30", "second")}),
    )

    def test_it_names_counts_the_way_a_reader_would_say_them(self) -> None:
        advice = _citable(self.FACTS)
        assert "11 services" in advice
        assert "8 entities" in advice
        assert "4 external systems" in advice

    def test_it_does_not_offer_word_fragments(self) -> None:
        advice = _citable(self.FACTS)
        for fragment in ("1 cross,", "1 write", "4 system,", "8 entity,"):
            assert fragment not in advice, f"{fragment!r} is not a figure anyone can cite"

    def test_it_does_not_offer_two_counts_for_the_same_word(self) -> None:
        # "1 service" and "11 service" both appeared, from cross_service_writes
        # and n_services. A model told both has been told nothing.
        advice = _citable(self.FACTS)
        assert "1 service," not in advice

    def test_it_includes_what_the_requirements_stated(self) -> None:
        advice = _citable(self.FACTS)
        assert "99.5 percent" in advice
        assert "30 second" in advice

    def test_a_design_whose_requirements_state_no_figures_still_lists_its_counts(self) -> None:
        bare = ScoringFacts(n_requirements=5, n_services=1, n_entities=2)
        advice = _citable(bare)
        assert "5 requirements" in advice
        assert "from the requirements" not in advice


class TestFiguresRealModelsActuallyWrote:
    """Sentences taken verbatim from a run, and what the guard did to them.

    Every one of these was refused by the first version of the rule, which
    required the fact's noun to be the very next word. Each refusal cost a retry
    out of three, on a stage that calls the model once per candidate shape, so
    three of them could end it.
    """

    FACTS = ScoringFacts(
        n_requirements=29,
        n_services=12,
        n_entities=8,
        n_external=4,
        cross_service_writes=2,
        independent_scaling=True,
        compliance_signal=True,
        source_figures=frozenset({("99.5", "percent"), ("30", "second"), ("2", "second")}),
    )

    @pytest.mark.parametrize(
        "prose",
        [
            # An adjective between the number and its noun.
            "This design already decomposes into 12 distinct services around 8 entities.",
            "With 12 discrete services and independent scaling already a requirement",
            # A hyphenated compound where the facts name separate words.
            "keeps those 2 shared-write operations as simple, local transactions",
            "With 12 distinct services identified but only 2 cross-service writes",
            # Plain, and already worked.
            "With 4 external systems to isolate and compliance in scope",
            "Readings appear within 30 seconds and the dashboard loads in under 2 seconds.",
            "Available 99.5% of the time.",
        ],
    )
    def test_grounded_prose_is_not_refused(self, prose: str) -> None:
        assert check_no_invented_figures(prose, self.FACTS) == []

    @pytest.mark.parametrize(
        ("prose", "quoted"),
        [
            ("Supports 10,000 concurrent users.", "10,000 concurrent users"),
            ("Responds in under 200ms.", "200ms"),
            ("Handles 5000 requests per second.", "5000 requests per second"),
        ],
    )
    def test_an_invention_is_refused_and_quoted_as_written(self, prose: str, quoted: str) -> None:
        # The refusal goes back to the model. Being told it invented "200" when
        # it wrote "200ms" is a correction it cannot act on.
        assert check_no_invented_figures(prose, self.FACTS) == [quoted]

    def test_a_wrong_count_is_still_wrong_next_to_the_right_word(self) -> None:
        # The window must not become "any number near any fact word". There are
        # twelve services, so ten of them is a claim about nothing.
        assert check_no_invented_figures("There are 10 services.", self.FACTS) == ["10 services"]

    def test_the_window_does_not_reach_into_the_next_clause(self) -> None:
        # Three words. If it reached further, a number could borrow a noun from
        # a sentence it has nothing to do with.
        prose = "It took 7 long hard frustrating weeks, though there are 12 services."
        assert "7 long hard frustrating" in " ".join(check_no_invented_figures(prose, self.FACTS))
