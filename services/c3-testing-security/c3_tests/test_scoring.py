"""The rule that turns predictions into the dissertation's numbers.

Every decision in here changes a number a reader will quote, so each one is
tested for the case that made it a decision: what counts as the same finding,
what happens when an arm reports one weakness five times, and what happens when
an arm is right about a weakness the dataset does not label.
"""

from c3.eval import ClassScore, Scorecard, Span, aligned, score


def _at(cwe: str, path: str, line: int) -> Span:
    return Span(cwe=cwe, path=path, start_line=line, end_line=line)


class TestWhatCountsAsTheSameFinding:
    def test_the_same_class_at_an_overlapping_span_matches(self) -> None:
        card = score([Span("CWE-89", "a.java", 10, 14)], [Span("CWE-89", "a.java", 12, 12)])

        assert card.per_class["CWE-89"].true_positives == 1

    def test_the_right_class_in_the_wrong_file_does_not(self) -> None:
        card = score([_at("CWE-89", "a.java", 10)], [_at("CWE-89", "b.java", 10)])

        assert card.per_class["CWE-89"].true_positives == 0
        assert card.per_class["CWE-89"].false_positives == 1
        assert card.per_class["CWE-89"].false_negatives == 1

    def test_the_wrong_class_at_the_right_place_does_not(self) -> None:
        """A weakness found and misclassified is not a weakness detected, for a
        study that reports per class numbers."""
        card = score([_at("CWE-79", "a.java", 10)], [_at("CWE-89", "a.java", 10)])

        assert card.per_class["CWE-89"].false_negatives == 1

    def test_a_child_class_matches_its_parent(self) -> None:
        """The trained arm learns Juliet's CWE-36 and the scanners report
        CWE-22. Scoring those as a miss would measure vocabulary."""
        card = score([_at("CWE-36", "a.java", 10)], [_at("CWE-22", "a.java", 10)])

        assert card.per_class["CWE-22"].true_positives == 1
        assert aligned("CWE-36") == "CWE-22"

    def test_a_claim_with_no_line_is_about_the_whole_file(self) -> None:
        """A dependency advisory and a method level dataset label both arrive
        without a usable span."""
        card = score([Span("CWE-1321", "package.json")], [Span("CWE-1321", "package.json", 4, 4)])

        assert card.per_class["CWE-1321"].true_positives == 1


class TestReportingOneWeaknessManyTimes:
    def test_five_overlapping_reports_of_one_weakness_earn_one_credit(self) -> None:
        """Otherwise a report full of duplicates has excellent recall, which is
        how an arm can be rewarded for being noisy."""
        predicted = [_at("CWE-89", "a.java", line) for line in (10, 10, 11, 12, 10)]

        card = score(predicted, [Span("CWE-89", "a.java", 9, 13)])

        assert card.per_class["CWE-89"].true_positives == 1
        assert card.per_class["CWE-89"].false_positives == 4

    def test_two_real_weaknesses_can_both_be_found(self) -> None:
        card = score(
            [_at("CWE-89", "a.java", 10), _at("CWE-89", "a.java", 40)],
            [_at("CWE-89", "a.java", 10), _at("CWE-89", "a.java", 40)],
        )

        assert card.per_class["CWE-89"].true_positives == 2
        assert card.per_class["CWE-89"].false_positives == 0


class TestBeingRightAboutSomethingNobodyLabelled:
    def test_a_class_the_dataset_never_labels_is_counted_apart(self) -> None:
        """OWASP Benchmark labels one weakness per servlet. An arm that also
        spots a hardcoded credential is not wrong, and counting it as a false
        positive would punish the arm for seeing more than the ground truth
        records."""
        card = score([_at("CWE-798", "a.java", 3)], [_at("CWE-89", "a.java", 10)])

        assert card.unlabelled_classes == {"CWE-798": 1}
        assert "CWE-798" not in card.per_class, "not a row in a table it has no ground truth in"

    def test_a_class_the_dataset_does_label_is_a_false_positive(self) -> None:
        """The same arm, wrong about where, is wrong."""
        card = score([_at("CWE-89", "a.java", 3)], [_at("CWE-89", "b.java", 10)])

        assert card.unlabelled_classes == {}
        assert card.per_class["CWE-89"].false_positives == 1


class TestTheAverages:
    def _lopsided(self) -> Scorecard:
        """One huge class the arm is good at, one small class it is bad at.

        Juliet's classes differ in size by two orders of magnitude, which is
        exactly when the two averages disagree.
        """
        truth = [_at("CWE-190", "a.java", line) for line in range(1, 101)]
        truth += [_at("CWE-89", "b.java", line) for line in range(1, 3)]
        predicted = [_at("CWE-190", "a.java", line) for line in range(1, 101)]
        return score(predicted, truth)

    def test_the_macro_average_counts_each_class_once(self) -> None:
        card = self._lopsided()

        assert card.per_class["CWE-190"].f1 == 1.0
        assert card.per_class["CWE-89"].f1 == 0.0
        assert card.macro_f1 == 0.5

    def test_the_micro_average_is_a_report_about_the_largest_class(self) -> None:
        """Both are reported, because a large gap between them is itself a
        finding about the arm."""
        card = self._lopsided()

        assert card.micro.f1 > 0.98

    def test_support_travels_with_every_row(self) -> None:
        """A precision without it is unreadable: 1.0 over two examples and 1.0
        over two thousand are not the same claim."""
        card = self._lopsided()

        assert card.as_dict()["perClass"][0]["support"] == 100
        assert card.as_dict()["perClass"][0]["cwe"] == "CWE-190"

    def test_a_row_with_no_ground_truth_is_left_out_of_the_macro_average(self) -> None:
        """Reachable when scorecards are combined across datasets, where one
        dataset labels a class and another does not. Averaging a zero for the
        second would invent a failure and halve a perfect score."""
        card = Scorecard(
            per_class={
                "CWE-89": ClassScore(cwe="CWE-89", true_positives=4),
                "CWE-78": ClassScore(cwe="CWE-78", false_positives=3),
            }
        )

        assert card.per_class["CWE-78"].support == 0
        assert card.macro_f1 == 1.0

    def test_a_class_nobody_labelled_does_not_drag_the_macro_average_down(self) -> None:
        """A class with no ground truth has no recall to report, so averaging a
        zero for it would invent a failure and halve a perfect score."""
        card = score(
            [_at("CWE-190", "a.java", 1), _at("CWE-798", "a.java", 3)],
            [_at("CWE-190", "a.java", 1)],
        )

        assert card.macro_f1 == 1.0
        assert card.unlabelled_classes == {"CWE-798": 1}


class TestAnArmThatFoundNothing:
    def test_every_real_weakness_is_a_miss(self) -> None:
        card = score([], [_at("CWE-89", "a.java", 10), _at("CWE-78", "b.java", 2)])

        assert card.macro_f1 == 0.0
        assert card.per_class["CWE-89"].false_negatives == 1
        assert card.per_class["CWE-78"].recall == 0.0


class TestTheClassBlindScore:
    """Ignoring the class must not quietly become ignoring the location.

    "Found it, called it something else" and "pointed at the wrong function in
    the right file" are different, and only the first should count. Without
    this the class blind score degrades into same file scoring, which is the
    rule the module docstring rejects.
    """

    def test_the_right_place_under_the_wrong_name_counts(self) -> None:
        from c3.eval.scoring import detected

        found = detected([_at("CWE-90", "a.java", 62)], [_at("CWE-798", "a.java", 62)])

        assert found.true_positives == 1

    def test_the_wrong_place_in_the_right_file_does_not(self) -> None:
        from c3.eval.scoring import detected

        found = detected([_at("CWE-90", "a.java", 5)], [_at("CWE-798", "a.java", 62)])

        assert found.true_positives == 0
        assert (found.false_positives, found.false_negatives) == (1, 1)

    def test_a_span_that_overlaps_counts(self) -> None:
        from c3.eval.scoring import detected

        found = detected([Span("CWE-89", "a.java", 33, 39)], [_at("CWE-22", "a.java", 36)])

        assert found.true_positives == 1

    def test_two_weaknesses_in_one_file_are_two(self) -> None:
        """Otherwise an arm that flags one method in a file with three
        weaknesses scores full recall on it."""
        from c3.eval.scoring import detected

        truth = [_at("CWE-89", "a.java", 10), _at("CWE-22", "a.java", 50)]

        found = detected([_at("CWE-89", "a.java", 10)], truth)

        assert (found.true_positives, found.false_negatives) == (1, 1)
