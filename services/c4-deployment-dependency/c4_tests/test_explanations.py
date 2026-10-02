"""The explanation rubric's tooling: a fixed stratified sample, a blind sheet, and scores by hand.

Risk reports come from the real assessment, with explanations set here, since
what is checked is which explanations are drawn and how ratings are read, not
what a model would write.
"""

import csv
import json

import pytest
from c4.eval.explanations import (
    CRITERIA,
    SheetRefused,
    candidates,
    read_sheet,
    sample,
    score,
    spend,
    write_sheet,
)
from c4.risk import assess

from .test_assessment import _changelog, _update, _updates

MAJOR = _update("acme", old="1.0.0", new="2.0.0", change="major")
PATCH = _update("beta")
MINOR = _update("gamma", old="1.0.0", new="1.1.0", change="minor")


def _reports(tmp_path, *, rule_written: str | None = None):
    """One report whose updates' explanations a model wrote, except one written by rule."""
    report = assess.report(
        _updates(MAJOR, PATCH, MINOR),
        _changelog((MAJOR, "removal", "high"), (PATCH, "fix", "low"), (MINOR, "removal", "high")),
        None,
        version=3,
    )
    assessments = [
        assessment.model_copy(
            update={
                "explanation": f"Why {assessment.package} is {assessment.arbitration.final}.",
                "explanation_source": "rule" if assessment.package == rule_written else "model",
            }
        )
        for assessment in report.assessments
    ]
    path = tmp_path / "risk-report-3.json"
    path.write_text(
        json.dumps(
            report.model_copy(update={"assessments": assessments}).model_dump(
                by_alias=True, mode="json"
            )
        )
    )
    return tmp_path


class TestTheSample:
    def test_only_model_written_explanations_are_rated(self, tmp_path) -> None:
        found = candidates(_reports(tmp_path, rule_written="beta"))
        assert sorted(c.assessment.package for c in found) == ["acme", "gamma"]

    def test_it_takes_each_stratum_in_turn_and_is_the_same_every_time(self, tmp_path) -> None:
        found = candidates(_reports(tmp_path))

        first = sample(found, size=3)
        again = sample(list(reversed(found)), size=3)

        assert [c.assessment.key for c in first] == [c.assessment.key for c in again]
        # The low stratum first, then the high ones: gamma's minor is High by its
        # changelog alone, where SemVer said Medium, so its signals disagree.
        assert [c.stratum for c in first] == [("low", False), ("high", False), ("high", True)]

    def test_the_sheet_leaves_the_scores_and_the_rater_to_fill(self, tmp_path) -> None:
        sheet = tmp_path / "sheet.csv"
        write_sheet(sample(candidates(_reports(tmp_path)), size=2), sheet)
        with sheet.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 2
        assert all(row[c] == "" for row in rows for c in (*CRITERIA, "rater"))
        assert rows[0]["explanation"].startswith("Why ")


def _filled(tmp_path, name: str, rows: list[dict]):
    path = tmp_path / name
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["item", "update", "finalLevel", *CRITERIA, "rater"]
        )
        writer.writeheader()
        writer.writerows(rows)
    return path


def _rating(item, rater, correctness, relevance=4, clarity=4, level="high"):
    return {
        "item": item,
        "update": f"u{item}",
        "finalLevel": level,
        "correctness": correctness,
        "relevance": relevance,
        "clarity": clarity,
        "rater": rater,
    }


class TestTheScores:
    def test_a_name_in_the_rater_column_is_refused(self, tmp_path) -> None:
        sheet = _filled(tmp_path, "a.csv", [_rating(1, "alice@example.com", 4)])
        with pytest.raises(SheetRefused, match="never a name"):
            read_sheet(sheet)

    def test_a_score_outside_one_to_five_is_refused(self, tmp_path) -> None:
        sheet = _filled(tmp_path, "a.csv", [_rating(1, "R1", 6)])
        with pytest.raises(SheetRefused, match="must be 1 to 5"):
            read_sheet(sheet)

    def test_the_summary_and_agreement_by_hand(self, tmp_path) -> None:
        first = _filled(tmp_path, "a.csv", [_rating(1, "R1", 4), _rating(2, "R1", 5)])
        second = _filled(tmp_path, "b.csv", [_rating(1, "R2", 4), _rating(2, "R2", 3)])

        result = score(read_sheet(first) + read_sheet(second))

        correctness = result["overall"]["correctness"]
        assert (correctness["n"], correctness["mean"], correctness["fourOrMore"]) == (4, 4.0, 0.75)
        # Item 1: 4 and 4, the same; item 2: 5 and 3, two apart.
        assert result["agreement"]["correctness"] == {"pairs": 2, "exact": 0.5, "withinOne": 0.5}
        assert (result["raters"], result["items"]) == (2, 2)


RECORDED = {
    "calm": {"semver": "low", "changelog": {"level": "low"}, "usage": {"level": None}},
    "loud": {"semver": "high", "changelog": {"level": "high"}, "usage": {"level": "high"}},
    "split": {"semver": "medium", "changelog": {"level": "high"}, "usage": {"level": "low"}},
    "silent": {"semver": None, "changelog": {"level": None}, "usage": {"level": None}},
}


class TestWhichCasesAreExplained:
    def test_the_final_level_is_the_products_and_disagreement_ignores_abstentions(self) -> None:
        from c4.eval.explanations import stratum_of

        assert stratum_of(RECORDED["calm"]) == ("low", False)
        assert stratum_of(RECORDED["split"]) == ("high", True)
        # Nothing voted: the most cautious rule calls it High, and nothing disagreed.
        assert stratum_of(RECORDED["silent"]) == ("high", False)

    def test_each_stratum_gives_one_in_turn_and_the_order_is_fixed(self) -> None:
        from c4.eval.explanations import choose

        first = choose(RECORDED, size=3)
        again = choose(dict(reversed(list(RECORDED.items()))), size=3)

        assert first == again
        assert first[0] == "calm" and set(first[1:]) <= {"loud", "split", "silent"}
        assert len(set(first)) == 3


class TestTheSpend:
    def test_it_is_summed_from_each_calls_record_and_counts_cleaned_prose(self) -> None:
        from sdlc_contracts import ModelCall

        report = assess.report(
            _updates(MAJOR, PATCH),
            _changelog((MAJOR, "removal", "high"), (PATCH, "fix", "low")),
            None,
            version=1,
        )

        def called(requests: int, tokens_in: int, tokens_out: int) -> ModelCall:
            return ModelCall(
                model_id="deepseek:deepseek-flash",
                prompt_id="explain-assessment/2",
                prompt_sha256="0" * 64,
                outcome="answered",
                requests=requests,
                prompt_tokens=tokens_in,
                completion_tokens=tokens_out,
            )

        major, patch = report.assessments
        explained = report.model_copy(
            update={
                "assessments": [
                    major.model_copy(
                        update={
                            "explanation_source": "model",
                            "explanation_call": called(1, 900, 80),
                            "explanation_dashes_replaced": 2,
                        }
                    ),
                    patch.model_copy(
                        update={
                            "explanation_source": "rule",
                            "explanation_call": called(4, 3600, 400),
                        }
                    ),
                ]
            }
        )

        assert spend([explained]) == {
            "calls": 2,
            "requests": 5,
            "promptTokens": 4500,
            "completionTokens": 480,
            "keptByTheCheck": 1,
            "withDashesReplaced": 1,
        }
