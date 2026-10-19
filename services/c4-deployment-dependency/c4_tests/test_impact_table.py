"""Table 5 by hand: files and components a break touched, against what the analysis named.

The counts are worked out here from small sets. The truth's components are
mapped by the impact stage's own module function, from a two module Maven tree
written here, so the table compares what the analysis would have named.
"""

from c4.eval.cases import FailureLocation
from c4.eval.impact_table import aggregate, counts, render_table5, scores, table5
from c4.eval.votes import truth_of

from .test_eval import _case, _observed

TREE = {
    "pom.xml": "<project><artifactId>parent</artifactId></project>",
    "core/pom.xml": "<project><artifactId>core</artifactId></project>",
    "core/src/main/java/A.java": "class A {}",
    "web/pom.xml": "<project><artifactId>web</artifactId></project>",
    "web/src/main/java/B.java": "class B {}",
}


def _usage(files, components, truth_files, truth_components, granularity="module", **extra):
    return {
        "usage": {
            "affectedFiles": files,
            "components": components,
            "truth": {
                "files": truth_files,
                "components": truth_components,
                "granularity": granularity,
            },
            **extra,
        }
    }


class TestTheArithmetic:
    def test_one_right_one_wrong_one_missed_is_a_half_each_way(self) -> None:
        tally = counts({"A", "B"}, {"B", "C"})
        assert tally == {"tp": 1, "fp": 1, "fn": 1}
        assert scores(tally) == {"precision": 0.5, "recall": 0.5, "f1": 0.5}

    def test_naming_nothing_misses_everything_and_has_no_precision(self) -> None:
        assert scores(counts({"A"}, set())) == {"precision": None, "recall": 0.0, "f1": 0.0}

    def test_micro_sums_the_counts_and_macro_averages_the_cases(self) -> None:
        summary = aggregate([counts({"A"}, {"A"}), counts({"B", "C"}, set())])
        assert (summary["tp"], summary["fp"], summary["fn"]) == (1, 0, 2)
        assert summary["micro"]["precision"] == 1.0
        assert summary["micro"]["recall"] == 1 / 3
        assert summary["macroF1"] == 0.5


class TestTheTable:
    def test_granularities_are_never_pooled_and_unknown_truths_are_left_out(self) -> None:
        votes = {
            "maven-case": _usage(
                ["core/A.java"], ["module:core"], ["core/A.java"], ["module:core"]
            ),
            "npm-case": _usage(
                ["src/a.ts"], ["n-items"], ["src/a.ts"], ["n-items"], granularity="graph-node"
            ),
            "no-truth": {"usage": {"affectedFiles": ["x"], "components": []}},
        }

        record = table5(votes)

        assert [row["caseId"] for row in record["cases"]] == ["maven-case", "npm-case"]
        assert record["files"]["cases"] == 2
        assert set(record["components"]) == {"module", "graph-node"}
        assert record["components"]["module"]["cases"] == 1

    def test_the_table_prints_files_and_each_granularity_on_its_own_row(self) -> None:
        record = {
            "study": {"label": "Table 5", "date": "2026-09-28", "votes": "v.json"},
            **table5({"c": _usage(["core/A.java"], [], ["core/A.java"], ["module:core"])}),
        }
        printed = render_table5(record)
        assert "| file | file | 1 | 1 | 0 | 0 | 1.00 | 1.00 | 1.00 | 1.00 |" in printed
        assert "| component | module | 1 | 0 | 0 | 1 | n/a | 0.00 | 0.00 | 0.00 |" in printed


class TestTheTruth:
    def test_failure_files_map_to_the_modules_the_analysis_would_name(self) -> None:
        observed = _observed("failed").model_copy(
            update={
                "failure_locations": [
                    FailureLocation(path="core/src/main/java/A.java", line=3),
                    FailureLocation(path="core/src/main/java/A.java", line=9),
                    FailureLocation(path="web/src/main/java/B.java", line=1),
                ]
            }
        )
        case = _case("t", "1.0.0", "2.0.0", observed)

        truth = truth_of(case, TREE, "module", "u-000000000001")["truth"]

        assert truth["files"] == ["core/src/main/java/A.java", "web/src/main/java/B.java"]
        assert truth["components"] == ["module:core", "module:web"]

    def test_a_case_with_no_known_location_has_no_truth(self) -> None:
        case = _case("t", "1.0.0", "2.0.0", _observed("failed"))
        assert truth_of(case, TREE, "module", "u-000000000001") == {}
