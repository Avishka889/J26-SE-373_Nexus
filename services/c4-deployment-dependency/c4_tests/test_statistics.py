"""Table 4's uncertainty and its paired test, checked by hand; the exploratory row; the tables command.

McNemar's p values are worked out here from the binomial tail, so the table's
number is never only as right as the code that printed it. The tables command
is run over the directory of records this repository keeps, because it broke
once when a record of another kind was put beside the epochs.
"""

from pathlib import Path

from c4.eval.statistics import bootstrap, mcnemar
from c4.eval.study import recorded_arms
from c4.eval.tables import render_directory

from .test_eval import _case, _observed

EPOCHS = Path(__file__).resolve().parents[1] / "studies" / "epochs"


class TestMcNemar:
    def test_six_to_one_discordant_is_p_one_eighth(self) -> None:
        # Discordant 7, the smaller side 1: tail (C(7,0) + C(7,1)) / 2^7 = 8/128, doubled.
        truths = ["high"] * 7 + ["low"] * 3
        first = ["high"] * 6 + ["low"] + ["low"] * 3
        second = ["low"] * 6 + ["high"] + ["low"] * 3

        result = mcnemar(truths, first, second)

        assert (result["onlyFirst"], result["onlySecond"]) == (6, 1)
        assert result["pValue"] == 0.125

    def test_arms_that_agree_everywhere_do_not_differ(self) -> None:
        assert mcnemar(["low", "high"], ["low", "high"], ["low", "high"])["pValue"] == 1.0

    def test_an_abstention_is_scored_as_high(self) -> None:
        result = mcnemar(["high", "low"], [None, "low"], ["low", "low"])
        assert (result["onlyFirst"], result["onlySecond"]) == (1, 0)


class TestBootstrap:
    def test_it_brackets_the_estimate_and_repeats_itself(self) -> None:
        pairs = [("high", "high")] * 8 + [("low", "high")] * 2

        first = bootstrap(pairs, lambda s: s.accuracy)
        again = bootstrap(pairs, lambda s: s.accuracy)

        assert first == again
        low, high = first
        assert low <= 0.8 <= high

    def test_nothing_to_resample_has_no_interval(self) -> None:
        assert bootstrap([], lambda s: s.accuracy) is None

    def test_a_metric_that_is_never_defined_has_no_interval(self) -> None:
        # No case is truly High, so High recall is undefined on every resample.
        assert bootstrap([("low", "low")] * 5, lambda s: s.high_recall) is None


class TestTheExploratoryRow:
    def test_usage_decides_where_it_voted_and_caution_where_it_did_not(self) -> None:
        voted = _case("a", "1.0.0", "2.0.0", _observed("passed"))
        silent = _case("b", "1.0.0", "2.0.0", _observed("passed"))
        votes = {
            voted.case_id: {"semver": "high", "usage": {"level": "low"}, "changelogRun": False},
            silent.case_id: {"semver": "high", "usage": {"level": None}, "changelogRun": False},
        }

        gated = recorded_arms(votes)["usage-gated"]

        assert gated(voted) == "low"
        assert gated(silent) == "high"


def test_every_record_the_repository_keeps_can_be_printed() -> None:
    printed = render_directory(EPOCHS)
    assert "### Epoch 3, seed set" in printed
    assert "### Table 6, part one" in printed
    assert "orchestrator.deploy.table7" in printed
