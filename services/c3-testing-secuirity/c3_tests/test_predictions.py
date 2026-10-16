"""Scoring what Colab brings back.

The GPU hours happen elsewhere and the numbers happen here, so this is where
the trained arm's results become quotable. Two questions are kept apart on
purpose: whether it can tell a vulnerable method from a safe one, and whether
it can say which weakness it is. Two thirds of Juliet's methods are safe, so a
model that answers "safe" to everything scores 0.68 on the first question and
nothing at all on the second, and one mixed number would hide that.
"""

import json

from c3.eval.predictions import detection, key_of, per_class, report


def _row(**overrides) -> dict:
    base = {
        "path": "CWE89_SQL_Injection__console_readLine_06.java",
        "method": "bad",
        "family": "CWE89_SQL_Injection__console_readLine",
        "trueLabel": 1,
        "trueCwe": "CWE-89",
        "predictedLabel": 1,
        "predictedCwe": "CWE-89",
        "score": 0.9,
    }
    return {**base, **overrides}


class TestTellingTheTwoQuestionsApart:
    def test_a_model_that_calls_everything_safe_scores_nothing_for_it(self) -> None:
        """The failure mode this split exists to expose. It looks respectable
        on accuracy because most of Juliet is safe."""
        rows = [_row(predictedLabel=0) for _ in range(2)]
        rows += [_row(method=f"good{n}", trueLabel=0, predictedLabel=0) for n in range(4)]

        found = detection(rows)

        assert found.accuracy > 0.6, "and this is why accuracy alone is not the number"
        assert found.recall == 0.0
        assert found.f1 == 0.0

    def test_classification_is_only_asked_about_real_weaknesses(self) -> None:
        """Asking a model which weakness a safe method has is asking a question
        with no answer."""
        rows = [_row(), _row(method="goodG2B1", trueLabel=0, predictedLabel=0)]

        card = per_class(rows)

        assert card.per_class["CWE-89"].support == 1

    def test_a_missed_weakness_is_a_miss_in_both_tables(self) -> None:
        """It classified nothing, so counting it as classified would be
        crediting a model for a method it never flagged."""
        rows = [_row(predictedLabel=0)]

        assert detection(rows).recall == 0.0
        assert per_class(rows).per_class["CWE-89"].recall == 0.0

    def test_the_right_method_with_the_wrong_class_is_a_wrong_answer(self) -> None:
        """Not a discovery. This model chooses from a fixed list, so naming
        CWE-78 for a CWE-89 method is wrong, and leaving it in the bucket the
        scanners use for unlabelled classes would drop its false positives."""
        rows = [_row(predictedCwe="CWE-78")]

        card = per_class(rows)

        assert card.per_class["CWE-89"].false_negatives == 1
        assert card.per_class["CWE-78"].false_positives == 1
        assert card.unlabelled_classes == {}

    def test_a_child_class_counts_as_its_parent(self) -> None:
        """The model learns Juliet's CWE-36 and the scanners report CWE-22.
        The same alignment that grades them grades this."""
        rows = [_row(trueCwe="CWE-22", predictedCwe="CWE-36")]

        assert per_class(rows).per_class["CWE-22"].true_positives == 1


class TestNamingOneMethod:
    def test_two_methods_in_one_file_are_two_keys(self) -> None:
        """Juliet puts `bad` and four `good` variants in one file, and a key of
        the path alone would collapse them into one."""
        assert key_of(_row()) != key_of(_row(method="goodG2B1"))

    def test_the_same_method_name_in_two_files_is_two_keys(self) -> None:
        assert key_of(_row()) != key_of(_row(path="CWE89_SQL_Injection__other_06.java"))


class TestTheReport:
    def test_it_carries_the_provenance_the_run_wrote_down(self, tmp_path) -> None:
        """A number that cannot name the model, the split and the seed that
        produced it is not a number anybody can use."""
        (tmp_path / "test-predictions.jsonl").write_text(
            "\n".join(
                json.dumps(row)
                for row in [_row(), _row(method="goodG2B1", trueLabel=0, predictedLabel=0)]
            )
        )
        (tmp_path / "run.json").write_text(
            json.dumps(
                {
                    "baseModel": "microsoft/graphcodebert-base",
                    "seed": 13,
                    "splitRule": {"by": "family", "seed": "c3"},
                }
            )
        )

        found = report(tmp_path)

        assert found["run"]["baseModel"] == "microsoft/graphcodebert-base"
        assert found["run"]["splitRule"]["by"] == "family"
        assert found["detection"]["examples"] == 2
        assert found["classification"]["perClass"][0]["cwe"] == "CWE-89"
        assert found["families"] == 1

    def test_a_run_with_no_provenance_file_still_reports_its_numbers(self, tmp_path) -> None:
        """A missing run.json is a gap in the record, not a reason to refuse to
        read predictions somebody spent GPU hours producing."""
        (tmp_path / "test-predictions.jsonl").write_text(json.dumps(_row()) + "\n")

        found = report(tmp_path)

        assert found["run"] == {}
        assert found["detection"]["recall"] == 1.0


class TestTheCatchAllClass:
    """The model can answer "vulnerable, but not one of these", and that answer
    has no CWE number. It is still an answer and it is still wrong on a test
    split that contains none of the classes it stands for."""

    def test_it_is_counted_under_a_name_rather_than_a_blank(self) -> None:
        card = per_class([_row(predictedCwe="other")])

        assert "other" in card.per_class
        assert "" not in card.per_class
        assert card.per_class["other"].false_positives == 1

    def test_the_real_class_still_records_the_miss(self) -> None:
        card = per_class([_row(predictedCwe="other")])

        assert card.per_class["CWE-89"].false_negatives == 1
