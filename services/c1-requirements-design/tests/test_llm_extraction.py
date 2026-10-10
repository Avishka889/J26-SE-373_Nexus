"""LLM extraction, with the model replaced by one that says exactly what we want.

These exercise the pipeline, not the model. `TestModel` returns fixed output, so
each test can put a specific misbehaviour in front of the rules and assert what
they do about it: a fabricated quote, a budget ignored, a confidence score the
model tried to supply.

That is the only way to test this layer honestly. Asserting against a real
provider tests the provider and fails on Tuesdays.
"""

from pathlib import Path

import pytest
from c1.llm.extractor import (
    ExtractionReport,
    build_agent,
    extract_with_model,
    prompt_for,
)
from c1.llm.schema import ExtractionResult
from c1.rules import LOW_CONFIDENCE_BELOW
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

PAYMENTS = (
    "The system shall allow customers to make payments using credit cards and digital wallets. "
    "Integrate Stripe and PayPal. "
    "KYC verification is required before processing payments above $1000. "
    "All transactions must be audited."
)
CALCULATOR = "Build a simple calculator app"


def agent_returning(*requirements: dict) -> Agent[None, ExtractionResult]:
    """An agent whose model returns exactly these requirements."""
    # `gaps` is sent explicitly even though it is optional, so these tests say
    # what the model returned rather than leaning on a default.
    return build_agent(
        TestModel(custom_output_args={"requirements": list(requirements), "gaps": []})
    )


def read(text: str, start: int, end: int) -> dict:
    """A requirement the model claims to have read, quoting correctly."""
    return {
        "text": "A customer pays with a saved card.",
        "source_start": start,
        "source_end": end,
        "source_quote": text[start:end],
        "rationale_kind": "read",
    }


class TestTheModelOnlyReports:
    async def test_a_verified_quote_survives_and_is_the_input_s_own_words(self) -> None:
        agent = agent_returning(read(PAYMENTS, 0, 91))
        extraction, report = await extract_with_model(PAYMENTS, agent=agent)

        requirement = extraction.requirements[0]
        assert requirement.quote is not None
        assert requirement.quote in PAYMENTS
        assert report.spans_refused == 0

    async def test_a_fabricated_quote_is_refused_and_counted(self) -> None:
        # The failure this layer exists to catch: a plausible sentence the brief
        # never contained, reported with confident offsets.
        agent = agent_returning(
            {
                "text": "Refunds are issued automatically within one day.",
                "source_start": 0,
                "source_end": 40,
                "source_quote": "Refunds are issued automatically.",
                "rationale_kind": "read",
            }
        )
        extraction, report = await extract_with_model(PAYMENTS, agent=agent)

        assert report.spans_refused == 1
        requirement = extraction.requirements[0]
        # Kept, but demoted to inferred, and the confidence says so.
        assert requirement.quote is None
        assert any(d.rule == "inferred-not-read" for d in requirement.confidence.deductions)
        assert requirement.confidence.low is True

    async def test_a_real_sentence_with_wrong_offsets_is_recovered(self) -> None:
        # Pointing at the wrong place is arithmetic, not invention. The sentence
        # is genuinely in the brief, so the requirement keeps its quote.
        agent = agent_returning(
            {
                "text": "Stripe and PayPal are integrated.",
                "source_start": 0,
                "source_end": 5,
                "source_quote": "Integrate Stripe and PayPal.",
                "rationale_kind": "read",
            }
        )
        extraction, report = await extract_with_model(PAYMENTS, agent=agent)

        assert report.spans_refused == 0
        assert extraction.requirements[0].quote == "Integrate Stripe and PayPal."

    async def test_an_honestly_inferred_requirement_keeps_no_quote(self) -> None:
        agent = agent_returning(
            {
                "text": "A customer signs in before paying.",
                "source_start": 0,
                "source_end": 0,
                "source_quote": "",
                "rationale_kind": "inferred",
            }
        )
        extraction, report = await extract_with_model(PAYMENTS, agent=agent)

        assert report.self_declared_inferred == 1
        # Not counted as a refused span: it never claimed one.
        assert report.spans_refused == 0
        assert extraction.requirements[0].quote is None


class TestTheRulesDecideNotTheModel:
    async def test_the_model_cannot_report_a_type_or_a_priority(self) -> None:
        # The output schema has no field for either, so this is enforced by the
        # type rather than by hoping the prompt is obeyed.
        from c1.llm.schema import ExtractedRequirement

        fields = set(ExtractedRequirement.model_fields)
        assert "type" not in fields
        assert "priority" not in fields
        assert "confidence" not in fields
        assert "quality_attribute" not in fields

    async def test_classification_comes_from_the_words_not_the_model(self) -> None:
        agent = agent_returning(
            {
                "text": "Card data must never be stored.",
                "source_start": 0,
                "source_end": 0,
                "source_quote": "",
                "rationale_kind": "inferred",
            }
        )
        extraction, _ = await extract_with_model(PAYMENTS, agent=agent)
        requirement = extraction.requirements[0]

        assert requirement.classification.type == "constraint"
        assert requirement.classification.priority == "must"
        # And it can show which words decided that.
        assert requirement.classification.evidence

    async def test_confidence_is_computed_and_explains_itself(self) -> None:
        agent = agent_returning(read(PAYMENTS, 0, 91))
        extraction, _ = await extract_with_model(PAYMENTS, agent=agent)

        confidence = extraction.requirements[0].confidence
        assert 0 <= confidence.value <= 98
        assert confidence.why


class TestTheBudgetIsEnforcedNotRequested:
    async def test_the_budget_appears_in_the_prompt(self) -> None:
        # A model that knows the target usually respects it, which is worth the
        # sentence even though the truncation below is what guarantees it.
        assert "about 5" in prompt_for(CALCULATOR, 5)

    async def test_a_model_that_ignores_its_budget_is_truncated_and_counted(self) -> None:
        # The calculator brief budgets 5. Hand back 12.
        agent = agent_returning(
            *[
                {
                    "text": f"The system does thing number {n}.",
                    "source_start": 0,
                    "source_end": 0,
                    "source_quote": "",
                    "rationale_kind": "inferred",
                }
                for n in range(12)
            ]
        )
        extraction, report = await extract_with_model(CALCULATOR, agent=agent)

        assert extraction.measurement.budget == 5
        assert len(extraction.requirements) == 5
        assert report.returned == 12
        assert report.over_budget == 7

    async def test_the_overrun_is_reported_rather_than_smoothed_over(self) -> None:
        # How often a model ignores its budget is a number about the model, and
        # the pipeline is the only place that can measure it.
        report = ExtractionReport(returned=12, over_budget=7, spans_refused=3)
        assert report.span_failure_rate == 0.25
        assert ExtractionReport().span_failure_rate == 0.0

    async def test_ids_are_renumbered_with_no_gaps_after_truncation(self) -> None:
        agent = agent_returning(
            *[
                {
                    "text": f"The system stores record number {n}.",
                    "source_start": 0,
                    "source_end": 0,
                    "source_quote": "",
                    "rationale_kind": "inferred",
                }
                for n in range(12)
            ]
        )
        extraction, _ = await extract_with_model(CALCULATOR, agent=agent)
        ids = [requirement.id for requirement in extraction.requirements]
        assert ids == [f"R-{n + 1}" for n in range(len(ids))]


class TestTheWholeArtefact:
    async def test_produces_something_the_contract_accepts(self) -> None:
        agent = agent_returning(read(PAYMENTS, 0, 91), read(PAYMENTS, 92, 120))
        extraction, _ = await extract_with_model(PAYMENTS, agent=agent)

        artefact = extraction.to_artefact()
        assert artefact.requirements
        # The contract caps open questions and refuses an attribute on a non
        # quality requirement, so this passing is itself a check on the rules.
        assert len(artefact.questions) <= 3

    async def test_a_model_that_returns_nothing_still_produces_an_honest_artefact(self) -> None:
        agent = agent_returning()
        extraction, report = await extract_with_model(PAYMENTS, agent=agent)

        assert report.returned == 0
        assert extraction.requirements == ()
        # And the unanswered questions are still asked, because the input still
        # left them open.
        assert extraction.questions

    async def test_flags_everything_when_a_model_invents_the_lot(self) -> None:
        agent = agent_returning(
            *[
                {
                    "text": f"Administrators reconcile settlement batch {n} nightly.",
                    "source_start": 0,
                    "source_end": 0,
                    "source_quote": "",
                    "rationale_kind": "inferred",
                }
                for n in range(3)
            ]
        )
        extraction, _ = await extract_with_model(CALCULATOR, agent=agent)

        # Every one inferred, and about words the brief never used.
        for requirement in extraction.requirements:
            assert requirement.confidence.value < LOW_CONFIDENCE_BELOW
            assert requirement.quote is None


class TestNothingCallsOutByAccident:
    """The guard that keeps this suite free and deterministic.

    Worth a test of its own, because the first time it was checked the failure
    came from a missing API key rather than from the guard, which proves nothing:
    on a developer machine with a key exported, an un-overridden agent would have
    called a provider and billed for it.
    """

    async def test_a_forgotten_override_cannot_reach_a_provider(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A key is present, so the only thing standing between this and a real
        # request is the guard.
        monkeypatch.setenv("GROQ_API_KEY", "gsk_shaped_like_a_key_but_never_used")
        with pytest.raises(RuntimeError, match="ALLOW_MODEL_REQUESTS is False"):
            await extract_with_model(CALCULATOR, agent=build_agent("groq:any-model"))

    def test_the_model_name_is_configuration_not_a_literal(self) -> None:
        # An evaluation records which model produced a number. A name hardcoded
        # in the pipeline makes that number impossible to reproduce.
        from c1.llm import extractor

        source = Path(extractor.__file__).read_text()
        assert "llama" not in source
        assert "gpt-" not in source
        assert "claude-" not in source


@pytest.mark.live
# The provider's HTTP client tears its sockets down after the event loop has
# gone, which this suite would otherwise report as a failing test: the workspace
# runs with warnings as errors, and an unraisable ResourceWarning in teardown
# reads as "the model got it wrong" when it means "the socket closed late". The
# exemption is scoped to these two tests, so warnings stay fatal everywhere else.
@pytest.mark.filterwarnings("ignore::ResourceWarning")
@pytest.mark.filterwarnings("ignore::pytest.PytestUnraisableExceptionWarning")
class TestAgainstARealProvider:
    """Runs only with `-m live`, and only with a key in the environment.

    This is where the model is actually measured. Everything above tests the
    pipeline; this tests whether a real provider can read a brief at all, and it
    asserts properties rather than exact output, because exact output from a
    model is not a stable thing to assert.
    """

    async def test_reads_the_calculator_brief_without_inventing_a_domain(
        self, allow_live_requests: None, live_agent: Agent[None, ExtractionResult]
    ) -> None:
        extraction, _report = await extract_with_model(CALCULATOR, agent=live_agent)

        assert extraction.requirements, "the model returned nothing at all"
        assert len(extraction.requirements) <= extraction.measurement.budget

        # The leakage guard: a calculator brief must not produce a payment app.
        forbidden = ("payment", "kyc", "invoice", "checkout", "card", "bank")
        blob = " ".join(r.text.lower() for r in extraction.requirements)
        for word in forbidden:
            assert word not in blob, f"the model invented {word} from seven words"

        # And the mirror assertion, without which an empty answer passes above.
        assert any("calculat" in r.text.lower() for r in extraction.requirements)

    async def test_respects_or_is_held_to_its_budget(
        self, allow_live_requests: None, live_agent: Agent[None, ExtractionResult]
    ) -> None:
        extraction, report = await extract_with_model(PAYMENTS, agent=live_agent)
        assert len(extraction.requirements) <= extraction.measurement.budget
        # Not an assertion that it behaved, a record of whether it did.
        print(
            f"\nreturned={report.returned} over_budget={report.over_budget} "
            f"spans_refused={report.spans_refused} "
            f"span_failure_rate={report.span_failure_rate:.2f}"
        )


class TestGapsTheModelRaises:
    """The half of the question stream the slot table cannot supply.

    The table holds the decisions every project faces. It cannot hold the ones
    that belong to a domain, which is how a cold chain brief was asked which
    currency its temperature threshold was in. The model names those, under the
    same evidence rule as a requirement: point at the sentence, or be discarded.
    """

    BRIEF = (
        "Raise an alert when a container goes outside its permitted range. "
        "Drivers work from a mobile application."
    )
    SENTENCE = "Raise an alert when a container goes outside its permitted range."

    def agent_with_gaps(self, *gaps: dict) -> Agent[None, ExtractionResult]:
        return build_agent(
            TestModel(
                custom_output_args={
                    "requirements": [read(self.BRIEF, 0, len(self.SENTENCE))],
                    "gaps": list(gaps),
                }
            )
        )

    def gap(self, question: str, *, quote: str | None = None) -> dict:
        """A gap pointing at the first sentence, correctly unless told otherwise."""
        return {
            "question": question,
            "assumption": "Assumed the range is supplied as configuration.",
            "source_start": 0,
            "source_end": len(self.SENTENCE),
            "source_quote": self.SENTENCE if quote is None else quote,
        }

    async def test_a_grounded_gap_becomes_a_question(self) -> None:
        agent = self.agent_with_gaps(self.gap("What is the permitted range, and in what units?"))
        extraction, report = await extract_with_model(self.BRIEF, agent=agent)

        asked = [finding.slot.question for finding in extraction.questions]
        assert "What is the permitted range, and in what units?" in asked
        assert report.gaps_returned == 1
        assert report.gaps_refused == 0

    async def test_a_gap_whose_quote_is_not_in_the_brief_is_discarded(self) -> None:
        # A requirement with a bad span survives as inferred, because the
        # sentence it states may still be true. A question about something the
        # brief never said has nothing to fall back on, so it goes.
        agent = self.agent_with_gaps(
            self.gap("What is the maximum humidity?", quote="Humidity must stay below 60 percent.")
        )
        extraction, report = await extract_with_model(self.BRIEF, agent=agent)

        asked = [finding.slot.question for finding in extraction.questions]
        assumed = [finding.slot.assumption for finding in extraction.assumptions]
        assert "What is the maximum humidity?" not in asked
        assert "Assumed the range is supplied as configuration." not in assumed
        assert report.gaps_refused == 1

    async def test_a_gap_with_its_offsets_wrong_but_its_words_real_is_kept(self) -> None:
        """The recovery a requirement already had. A question pointing at a
        sentence of this brief was discarded for arithmetic alone, and the
        generic table filled its place: the same questions for every project.
        """
        wrong = {**self.gap("What is the permitted range, and in what units?"), "source_start": 7}
        agent = self.agent_with_gaps(wrong)

        extraction, report = await extract_with_model(self.BRIEF, agent=agent)

        asked = [finding.slot.question for finding in extraction.questions]
        assert "What is the permitted range, and in what units?" in asked
        assert (report.gaps_recovered, report.gaps_refused) == (1, 0)

    async def test_a_gap_outranks_the_generic_slots(self) -> None:
        # Both streams compete for three places. The gap read this brief; the
        # slots fired because a lexicon did not find certain words.
        agent = self.agent_with_gaps(self.gap("What is the permitted range, and in what units?"))
        extraction, _ = await extract_with_model(self.BRIEF, agent=agent)

        assert extraction.questions[0].slot.question == (
            "What is the permitted range, and in what units?"
        )

    async def test_three_gaps_fill_the_cap_and_the_slots_become_assumptions(self) -> None:
        # Nothing is dropped: a slot that loses its place is still a decision
        # somebody lives with, so it is stated where it can be corrected.
        agent = self.agent_with_gaps(
            self.gap("What is the permitted range, and in what units?"),
            self.gap("How long must temperature history be retained?"),
            self.gap("What happens to a consignment that was already delivered?"),
        )
        extraction, _ = await extract_with_model(self.BRIEF, agent=agent)

        assert len(extraction.questions) == 3
        assert all(f.slot.id.startswith("input-gap-") for f in extraction.questions)
        assert extraction.assumptions, "the slots it displaced must still be stated"
        assert any(not f.slot.id.startswith("input-gap-") for f in extraction.assumptions)

    async def test_gaps_keep_the_order_the_model_read_them_in(self) -> None:
        # They share one weight, so the tie is broken by id, and the id is
        # zero padded for exactly this reason.
        agent = self.agent_with_gaps(
            *(self.gap(f"Question {n}?") for n in range(1, 12)),
        )
        extraction, _ = await extract_with_model(self.BRIEF, agent=agent)

        assert [f.slot.question for f in extraction.questions] == [
            "Question 1?",
            "Question 2?",
            "Question 3?",
        ]

    async def test_a_model_that_raises_no_gaps_still_gets_the_table(self) -> None:
        # The table is the floor, not an optional extra: a model that says
        # nothing must not leave the reader with no questions at all.
        agent = self.agent_with_gaps()
        extraction, report = await extract_with_model(self.BRIEF, agent=agent)

        assert report.gaps_returned == 0
        assert extraction.questions, "the slot table still has to answer for itself"
