"""The extraction budget, and the two anchors it is calibrated against.

This is the arithmetic the component's first honesty claim rests on, so it is
pinned rather than left to drift. A change that moves either anchor changes what
the demo produces from a one line prompt, and that is exactly the number a viva
panel will ask about.
"""

import pytest
from c1.rules.measure import (
    MAX_BUDGET,
    MIN_BUDGET,
    budget_for,
    find_verb_object_pairs,
    measure,
    split_sentences,
)

#: Seven words. The claim is that this yields a handful, not a dozen.
CALCULATOR = "Build a simple calculator app"

#: The payments brief. Its hand written fixture arrived at twelve requirements
#: independently, before this rule existed, which is what makes it an anchor
#: rather than a target fitted after the fact.
PAYMENTS = (
    "The system shall allow customers to make payments using credit cards and digital wallets. "
    "Integrate Stripe and PayPal. "
    "KYC verification is required before processing payments above $1000. "
    "All transactions must be audited."
)


class TestTheAnchors:
    def test_a_seven_word_prompt_budgets_a_handful(self) -> None:
        result = measure(CALCULATOR)
        assert result.evidence == 1
        assert result.budget == 5

    def test_the_payments_brief_budgets_twelve(self) -> None:
        result = measure(PAYMENTS)
        assert result.evidence == 6
        assert result.budget == 12

    def test_the_thin_input_budgets_far_less_than_the_full_one(self) -> None:
        # The property that matters more than either number: more input earns
        # more requirements, and a short prompt cannot earn a long list.
        assert measure(CALCULATOR).budget < measure(PAYMENTS).budget / 2


class TestTheBudget:
    @pytest.mark.parametrize(
        ("evidence", "expected"),
        [(0, 3), (1, 5), (2, 6), (4, 9), (6, 12), (10, 18), (18, 30), (40, 30)],
    )
    def test_grows_with_evidence_and_stops(self, evidence: int, expected: int) -> None:
        assert budget_for(evidence) == expected

    def test_never_leaves_its_bounds(self) -> None:
        for evidence in range(0, 200):
            assert MIN_BUDGET <= budget_for(evidence) <= MAX_BUDGET

    def test_never_shrinks_as_evidence_grows(self) -> None:
        budgets = [budget_for(n) for n in range(0, 60)]
        assert budgets == sorted(budgets)


class TestSplittingTheInput:
    def test_reads_sentences_when_there_is_punctuation(self) -> None:
        assert len(split_sentences(PAYMENTS)) == 4

    def test_falls_back_to_clauses_when_there_is_none(self) -> None:
        # A prompt typed into a box rarely has full stops, and treating a list
        # of four features as one piece of evidence would underbudget it.
        parts = split_sentences("catalog browsing, a shopping cart and order management")
        assert len(parts) == 3

    def test_does_not_split_a_phrase_that_is_one_idea(self) -> None:
        assert split_sentences("fast and reliable") == ["fast and reliable"]

    def test_says_nothing_about_nothing(self) -> None:
        assert split_sentences("") == []
        assert measure("").budget == MIN_BUDGET


class TestReadingVerbsAndObjects:
    def test_reads_the_passive_voice_backwards(self) -> None:
        # "transactions must be audited" puts the object in front of the verb,
        # and a forward only reading finds the end of the sentence instead.
        pairs = find_verb_object_pairs("All transactions must be audited.")
        assert ("audit", "transactions") in pairs

    def test_reads_the_active_voice_forwards(self) -> None:
        pairs = find_verb_object_pairs("The system stores customer records.")
        assert ("store", "customer") in pairs

    def test_counts_one_verb_phrase_once_however_many_things_it_names(self) -> None:
        # "Integrate Stripe and PayPal" is one thing being asked for. Counting
        # the providers separately would budget a list of vendors like a list of
        # features.
        pairs = find_verb_object_pairs("Integrate Stripe and PayPal.")
        assert len([p for p in pairs if p[0] == "integrate"]) == 1

    def test_counts_the_same_verb_and_object_once_across_forms(self) -> None:
        pairs = find_verb_object_pairs("Process payments. Processing payments is audited.")
        assert len([p for p in pairs if p == ("process", "payments")]) == 1

    def test_ignores_a_sentence_with_no_action_in_it(self) -> None:
        assert find_verb_object_pairs("The weather is pleasant today.") == []
