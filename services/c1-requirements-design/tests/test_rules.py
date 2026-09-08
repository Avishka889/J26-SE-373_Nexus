"""The rule layer: classification, spans, confidence, slots and the pipeline.

These are the checks behind the claims the component makes out loud. Each one
corresponds to a sentence in the write-up, so a failure here is a claim that has
stopped being true rather than a detail that changed.
"""

import pytest
from c1.rules import (
    CEILING,
    LOW_CONFIDENCE_BELOW,
    MAX_QUESTIONS,
    classify,
    extract,
    find_span,
    score,
    unfilled_slots,
    verify_span,
)
from c1.rules.classify import DEFAULT_PRIORITY

CALCULATOR = "Build a simple calculator app"
PAYMENTS = (
    "The system shall allow customers to make payments using credit cards and digital wallets. "
    "Integrate Stripe and PayPal. "
    "KYC verification is required before processing payments above $1000. "
    "All transactions must be audited."
)


class TestClassification:
    @pytest.mark.parametrize(
        ("sentence", "expected"),
        [
            ("The system shall record every payment.", "must"),
            ("The system should notify the customer.", "should"),
            ("A customer may export their history.", "could"),
        ],
    )
    def test_reads_priority_from_the_modal(self, sentence: str, expected: str) -> None:
        assert classify(sentence).priority == expected

    def test_understates_rather_than_overstates_when_no_modal_appears(self) -> None:
        result = classify("The system records every payment.")
        assert result.priority == DEFAULT_PRIORITY == "should"
        # And says it was a default, so the confidence rule can take points off.
        assert result.priority_is_default is True

    def test_the_strongest_modality_wins(self) -> None:
        # A weak clause does not soften a strong one.
        assert classify("Records may be exported, but must be audited.").priority == "must"

    @pytest.mark.parametrize(
        ("sentence", "expected"),
        [
            ("Card data must never be stored.", "constraint"),
            ("The system must comply with PCI DSS.", "constraint"),
            ("Payments settle within two seconds.", "quality"),
            ("The system must be fast.", "quality"),
            ("A customer can pay by card.", "functional"),
        ],
    )
    def test_reads_the_type_from_the_wording(self, sentence: str, expected: str) -> None:
        assert classify(sentence).type == expected

    def test_a_prohibition_is_a_constraint_even_when_it_sounds_like_a_quality(self) -> None:
        # "never" is a quality marker and a prohibition. The prohibition wins,
        # because the sentence restricts the solution rather than grading it.
        assert classify("Card data must never be stored.").type == "constraint"

    def test_functional_is_earned_by_naming_an_action_not_assumed(self) -> None:
        named = classify("A shopper adds items to a cart.")
        assert named.type == "functional"
        assert named.type_is_default is False
        assert "add" in named.evidence

        nothing = classify("It should be nice and modern.")
        assert nothing.type_is_default is True

    def test_attributes_a_quality_by_weight_of_signal(self) -> None:
        result = classify(
            "The system must be secure: records are encrypted and access needs permission."
        )
        assert result.type == "quality"
        assert result.quality_attribute == "security"

    def test_a_prohibition_outranks_the_quality_words_inside_it(self) -> None:
        # "never readable by another tenant" reads as security, but it is a
        # prohibition first: it restricts the solution rather than grading it.
        assert classify("Records are never readable by another tenant.").type == "constraint"

    def test_never_attributes_a_non_quality_requirement(self) -> None:
        # The contract refuses this combination, so the rule must not produce it.
        result = classify("A customer can pay by card.")
        assert result.type != "quality"
        assert result.quality_attribute is None

    def test_shows_its_working(self) -> None:
        result = classify("The system shall encrypt records within two seconds.")
        assert result.evidence, "a classification with no evidence cannot be audited"
        assert len(set(result.evidence)) == len(result.evidence), "evidence repeats itself"


class TestSpanVerification:
    SOURCE = "The system shall audit every payment. Refunds need approval."

    def test_accepts_a_quote_the_input_really_contains(self) -> None:
        check = verify_span(self.SOURCE, 0, 37, "The system shall audit every payment.")
        assert check.verified is True
        assert check.quote == "The system shall audit every payment."

    def test_refuses_a_quote_the_input_does_not_contain(self) -> None:
        # The failure this rule exists for: a plausible sentence that was never
        # written. A better prompt does not fix it; slicing the input does.
        check = verify_span(self.SOURCE, 0, 37, "The system shall audit every refund.")
        assert check.verified is False
        assert check.quote is None
        assert "does not say that" in check.reason

    def test_refuses_offsets_outside_the_input(self) -> None:
        assert verify_span(self.SOURCE, 0, 9999, "anything").verified is False
        assert verify_span(self.SOURCE, -1, 5, "The").verified is False
        assert verify_span(self.SOURCE, 10, 10, "").verified is False

    def test_refuses_a_real_sentence_reported_at_the_wrong_place(self) -> None:
        # Pointing at the wrong sentence is as wrong as pointing at none.
        check = verify_span(self.SOURCE, 0, 37, "Refunds need approval.")
        assert check.verified is False

    def test_forgives_whitespace_and_curly_quotes_and_nothing_else(self) -> None:
        assert verify_span(self.SOURCE, 0, 37, "The system  shall audit every payment.").verified
        # A paraphrase is not a quote.
        assert not verify_span(self.SOURCE, 0, 37, "The system audits payments.").verified

    def test_finds_a_quote_without_being_told_where(self) -> None:
        found = find_span(self.SOURCE, "Refunds need approval.")
        assert found.verified is True
        assert found.quote == "Refunds need approval."

    def test_refuses_to_find_what_is_not_there(self) -> None:
        assert find_span(self.SOURCE, "Refunds are automatic.").verified is False
        assert find_span(self.SOURCE, "   ").verified is False


class TestConfidence:
    def test_never_reaches_certainty(self) -> None:
        best = score(
            text="The system shall audit every payment.",
            source="The system shall audit every payment.",
            quote="The system shall audit every payment.",
            classification=classify("The system shall audit every payment."),
        )
        assert best.value == CEILING < 100
        assert best.deductions == ()

    def test_costs_the_most_for_being_inferred_rather_than_read(self) -> None:
        sentence = "The system shall audit every payment."
        read = score(
            text=sentence, source=sentence, quote=sentence, classification=classify(sentence)
        )
        inferred = score(
            text=sentence, source=sentence, quote=None, classification=classify(sentence)
        )
        assert inferred.value < read.value
        assert any(d.rule == "inferred-not-read" for d in inferred.deductions)

    def test_flags_a_requirement_that_says_nothing_the_system_does(self) -> None:
        sentence = "It should be nice and modern."
        result = score(
            text=sentence, source=sentence, quote=sentence, classification=classify(sentence)
        )
        assert result.low is True
        assert result.value < LOW_CONFIDENCE_BELOW
        assert any(d.rule == "no-action" for d in result.deductions)

    def test_flags_a_quality_with_no_number_in_it(self) -> None:
        sentence = "The system must be fast."
        result = score(
            text=sentence, source=sentence, quote=sentence, classification=classify(sentence)
        )
        assert any(d.rule == "quality-without-a-number" for d in result.deductions)

    def test_notices_words_the_input_never_used(self) -> None:
        result = score(
            text="Administrators reconcile settlement batches nightly.",
            source="Customers can pay by card.",
            quote=None,
            classification=classify("Administrators reconcile settlement batches nightly."),
        )
        assert any(d.rule == "words-not-in-the-input" for d in result.deductions)

    def test_notices_a_near_duplicate(self) -> None:
        sentence = "A customer can pay using a saved card."
        result = score(
            text=sentence,
            source=sentence,
            quote=sentence,
            classification=classify(sentence),
            siblings=("A customer can pay with a saved card.",),
        )
        assert any(d.rule == "near-duplicate" for d in result.deductions)

    def test_every_deduction_explains_itself_to_a_reader(self) -> None:
        result = score(
            text="It should be nice.",
            source="Something else entirely.",
            quote=None,
            classification=classify("It should be nice."),
        )
        assert result.deductions
        for deduction in result.deductions:
            assert deduction.rule and deduction.points > 0
            assert deduction.reason.endswith("."), "a reason is a sentence, not a label"
            assert len(deduction.reason) > 25
        assert result.why

    def test_never_goes_below_zero_however_much_is_wrong(self) -> None:
        result = score(
            text="Zzz qqq wibble.",
            source="Something else entirely.",
            quote=None,
            classification=classify("Zzz qqq wibble."),
            siblings=("Zzz qqq wibble.",),
        )
        assert result.value >= 0


class TestSlots:
    def test_asks_about_what_a_thin_input_left_open(self) -> None:
        findings = unfilled_slots(CALCULATOR, ("R-1",))
        ids = [finding.slot.id for finding in findings]
        assert "roles" in ids
        assert "persistence" in ids

    def test_says_nothing_about_what_the_input_already_settled(self) -> None:
        settled = unfilled_slots(
            "Doctors and nurses sign in with a password. Records are stored in a database.",
            ("R-1",),
        )
        ids = [finding.slot.id for finding in settled]
        assert "roles" not in ids
        assert "auth" not in ids
        assert "persistence" not in ids

    def test_does_not_ask_about_things_the_input_has_nothing_to_do_with(self) -> None:
        # A calculator notifies nobody, so asking which channel would be noise
        # dressed as diligence.
        ids = [finding.slot.id for finding in unfilled_slots(CALCULATOR, ("R-1",))]
        assert "notification-channel" not in ids
        assert "money-units" not in ids

    def test_a_trigger_word_does_not_fire_from_inside_a_longer_word(self) -> None:
        # The bug this closes: "over" occurs inside "coverage", so a cold chain
        # brief was asked which currency its temperature threshold was in.
        text = "Drivers work in areas with unreliable coverage across the region."
        ids = [finding.slot.id for finding in unfilled_slots(text, ("R-1",))]
        assert "money-units" not in ids

    def test_a_filled_word_does_not_count_from_inside_a_longer_word(self) -> None:
        # The same bug on the other side of the check. "sign in" fills the auth
        # slot; "design" must not, or a design document silently answers it.
        ids = [finding.slot.id for finding in unfilled_slots("A design tool.", ("R-1",))]
        assert "auth" in ids

    def test_money_is_asked_about_when_the_input_actually_names_money(self) -> None:
        text = "Refunds above the agreed amount need approval before the payment is sent."
        ids = [finding.slot.id for finding in unfilled_slots(text, ("R-1",))]
        assert "money-units" in ids

    def test_money_is_not_asked_about_for_a_threshold_that_is_not_money(self) -> None:
        # A temperature range is a threshold, a limit and a bound, and none of
        # those make it a sum of money.
        text = "Raise an alert when a container goes outside its permitted range."
        ids = [finding.slot.id for finding in unfilled_slots(text, ("R-1",))]
        assert "money-units" not in ids

    def test_ranks_the_most_consequential_first(self) -> None:
        findings = unfilled_slots(CALCULATOR, ("R-1",))
        weights = [finding.weight for finding in findings]
        assert weights == sorted(weights, reverse=True)

    def test_every_slot_can_both_ask_and_assume(self) -> None:
        from c1.rules import SLOTS

        for slot in SLOTS:
            assert slot.question.endswith("?")
            assert slot.assumption.endswith(".")
            assert 1 <= slot.criticality <= 5
            assert 1 <= slot.blast_radius <= 5


class TestTheRuleOnlyPipeline:
    def test_a_seven_word_prompt_yields_a_handful_with_assumptions(self) -> None:
        result = extract(CALCULATOR)
        artefact = result.to_artefact()

        # The claim, in one assertion: not dozens of confident requirements.
        assert 1 <= len(artefact.requirements) <= 5
        assert artefact.assumptions or artefact.questions
        assert len(artefact.questions) <= MAX_QUESTIONS

    def test_reads_the_payments_brief_into_its_sentences(self) -> None:
        result = extract(PAYMENTS)
        assert len(result.requirements) == 4
        # And stays well inside a budget that allows more, because the rules only
        # read what is written rather than inventing to fill it.
        assert len(result.requirements) <= result.measurement.budget
        assert result.over_budget == 0

    def test_quotes_only_the_input_s_own_words(self) -> None:
        for requirement in extract(PAYMENTS).requirements:
            assert requirement.quote is not None
            assert requirement.quote in PAYMENTS

    def test_produces_an_artefact_the_contract_accepts(self) -> None:
        # The contract caps open questions and refuses an attribute on a non
        # quality requirement, so this passing is itself a check on the rules.
        artefact = extract(PAYMENTS).to_artefact()
        assert artefact.requirements
        ids = [requirement.id for requirement in artefact.requirements]
        assert ids == [f"R-{n + 1}" for n in range(len(ids))]

    def test_never_opens_more_than_three_questions(self) -> None:
        wordy = " ".join(f"The system does thing number {n}." for n in range(40))
        assert len(extract(wordy).to_artefact().questions) <= MAX_QUESTIONS

    def test_truncates_to_the_budget_and_reports_the_overrun(self) -> None:
        # Forty terse sentences earn a budget well below forty.
        wordy = " ".join(f"The system stores record number {n}." for n in range(40))
        result = extract(wordy)
        assert len(result.requirements) == result.measurement.budget
        assert result.over_budget == 40 - result.measurement.budget

    def test_keeps_the_readings_it_was_most_sure_of(self) -> None:
        mixed = " ".join(
            ["The system shall store every record."] * 2
            + ["Hmm."] * 20
            + ["A customer shall export their history."]
        )
        kept = extract(mixed).requirements
        # The confident readings survive truncation; the noise does not fill it.
        assert any("store every record" in r.text for r in kept)

    def test_says_something_rather_than_nothing_for_an_empty_input(self) -> None:
        result = extract("")
        assert len(result.requirements) == 1
        assert result.requirements[0].quote is None
        assert result.requirements[0].confidence.low is True

    def test_writes_no_em_or_en_dash(self) -> None:
        for text in (CALCULATOR, PAYMENTS, ""):
            artefact = extract(text).to_artefact()
            serialised = artefact.model_dump_json()
            # These are the characters being forbidden, so they have to appear
            # here to be checked for.
            assert "—" not in serialised
            assert "–" not in serialised  # noqa: RUF001
