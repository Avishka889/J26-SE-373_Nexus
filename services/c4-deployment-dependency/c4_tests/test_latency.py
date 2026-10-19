"""Table 6's latency, by hand: each assessment's two timed steps, against NFR1's 30 seconds."""

from c4.eval.latency import latency, render


def _vote(changelog: float | None, usage: float) -> dict:
    return {
        "changelog": {"model": {"durationSeconds": changelog}} if changelog is not None else {},
        "usage": {"seconds": usage},
    }


VOTES = {
    "a": _vote(None, 5.0),
    "b": _vote(10.0, 5.0),
    "c": _vote(20.0, 15.0),
    "d": _vote(1.0, 1.0),
}


def test_an_assessment_is_the_model_call_and_the_usage_step() -> None:
    record = latency(VOTES)
    by_case = {row["caseId"]: row for row in record["perCase"]}
    assert by_case["a"]["assessmentSeconds"] == 5.0 and not by_case["a"]["modelAsked"]
    assert by_case["c"]["assessmentSeconds"] == 35.0


def test_the_budget_counts_and_names_what_went_over() -> None:
    record = latency(VOTES)
    assert (record["withinBudget"], record["cases"]) == (3, 4)
    assert [row["caseId"] for row in record["over"]] == ["c"]
    # Sorted 2, 5, 15, 35: the median is the second, the 95th percentile the fourth.
    assert (record["p50"], record["p95"], record["max"]) == (5.0, 35.0, 35.0)


def test_the_table_prints_the_summary_and_the_cases_over() -> None:
    printed = render({"study": {"label": "Table 6, latency", "date": "d"}, **latency(VOTES)})
    assert "| 5.0 s | 35.0 s | 35.0 s | 3 of 4 |" in printed
    assert "| c | 35.0 s | 20.0 s | 15.0 s |" in printed
