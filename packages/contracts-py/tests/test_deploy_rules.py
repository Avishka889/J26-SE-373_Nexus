"""The rules as truth tables.

Each rule is small enough to state completely, so the tests state it: every row
a reader could ask about is a row here, and the arbitration is checked against
all sixty four combinations of three signals that may vote or abstain.
"""

from itertools import product

import pytest
from sdlc_contracts.deploy_rules import (
    SIGNALS,
    changelog_level,
    classify_window,
    most_cautious,
    safety_first,
    semver_level,
    strategy_for,
    usage_level,
)

LEVELS = (None, "low", "medium", "high")


class TestTheSemverRule:
    @pytest.mark.parametrize(
        ("change", "level"),
        [
            ("major", "high"),
            ("minor", "medium"),
            ("patch", "low"),
            ("prerelease", "low"),
            ("build-only", "low"),
            ("beyond-patch", "low"),
            ("qualifier", "low"),
            ("downgrade", None),
            ("non-semver", None),
            ("unparseable", None),
        ],
    )
    def test_fr4_literally_and_nothing_guessed(self, change, level) -> None:
        assert semver_level(change) == level


class TestTheChangelogRule:
    def test_a_breaking_claim_is_high_whatever_else_was_said(self) -> None:
        assert (
            changelog_level(["fix", "breaking", "feature"], notes_found=True, refused=0) == "high"
        )

    def test_a_removal_is_high(self) -> None:
        assert changelog_level(["removal"], notes_found=True, refused=0) == "high"

    @pytest.mark.parametrize("kind", ["behavioural", "deprecation"])
    def test_a_change_to_watch_is_medium(self, kind) -> None:
        assert changelog_level([kind, "fix"], notes_found=True, refused=0) == "medium"

    @pytest.mark.parametrize("kind", ["security", "fix", "feature", "other"])
    def test_everything_else_is_low(self, kind) -> None:
        assert changelog_level([kind], notes_found=True, refused=0) == "low"

    def test_notes_that_say_nothing_the_rule_names_are_a_quiet_release(self) -> None:
        assert changelog_level([], notes_found=True, refused=0) == "low"

    def test_no_notes_is_no_evidence(self) -> None:
        assert changelog_level([], notes_found=False, refused=0) is None

    def test_notes_whose_every_claim_was_refused_are_no_evidence(self) -> None:
        """Not low: a model that invented every quote has shown nothing about
        the release, and calling that quiet would reward the invention."""
        assert changelog_level([], notes_found=True, refused=3) is None

    def test_a_refused_claim_cannot_raise_the_level(self) -> None:
        """The refused breaking claim is simply not an input."""
        assert changelog_level(["fix"], notes_found=True, refused=1) == "low"


class TestTheUsageRule:
    @pytest.mark.parametrize(
        "kind", ["removed", "signature-changed", "renamed", "breaking-behaviour"]
    )
    def test_a_broken_symbol_in_use_is_high(self, kind) -> None:
        assert usage_level(["touched", kind], changed_symbols_known=True) == "high"

    @pytest.mark.parametrize("kind", ["behaviour-changed", "deprecated"])
    def test_a_changed_symbol_in_use_is_medium(self, kind) -> None:
        assert usage_level([kind], changed_symbols_known=True) == "medium"

    def test_nothing_changed_in_use_is_low_project_specific_impact(self) -> None:
        assert usage_level([], changed_symbols_known=True) == "low"

    def test_with_no_changed_symbols_known_there_is_nothing_to_look_for(self) -> None:
        assert usage_level([], changed_symbols_known=False) is None


class TestSafetyFirstArbitration:
    @pytest.mark.parametrize("votes", list(product(LEVELS, repeat=3)))
    def test_every_combination_takes_the_most_cautious_vote_cast(self, votes) -> None:
        by_signal = dict(zip(SIGNALS, votes, strict=True))
        final, decided_by = safety_first(by_signal)

        cast = [level for level in votes if level is not None]
        if not cast:
            assert (final, decided_by) == ("high", ())
            return
        assert final == most_cautious(cast)
        assert decided_by == tuple(s for s in SIGNALS if by_signal[s] == final)
        assert decided_by, "somebody decided a level that was voted"

    def test_one_cautious_signal_outvotes_two_calm_ones(self) -> None:
        """The row the whole design turns on: SemVer and the notes both say a
        patch is harmless, and the project's own code uses what it broke."""
        assert safety_first({"semver": "low", "changelog": "low", "usage": "high"}) == (
            "high",
            ("usage",),
        )

    def test_an_abstention_is_not_a_vote(self) -> None:
        assert safety_first({"semver": "medium", "changelog": None, "usage": "low"}) == (
            "medium",
            ("semver",),
        )

    def test_nothing_voted_means_nothing_supports_a_lower_level(self) -> None:
        assert safety_first({"semver": None, "changelog": None, "usage": None}) == ("high", ())


class TestTheStrategy:
    @pytest.mark.parametrize(
        ("final", "strategy"),
        [("low", "automatic"), ("medium", "approval"), ("high", "approval-with-rollback")],
    )
    def test_fr17(self, final, strategy) -> None:
        assert strategy_for(final) == strategy


class TestTheHealthRule:
    """`health-rule/1`, one row per state, and the rows that separate neighbours."""

    V = "a" * 64
    OTHER = "b" * 64

    def _rounds(self, *pattern: tuple[bool, float | None]) -> list:
        return [(ok, ms, self.V if ok else None) for ok, ms in pattern]

    @pytest.mark.parametrize(
        ("pattern", "idle", "state"),
        [
            ([(True, 40.0)] * 2, None, "unknown"),
            ([(True, 40.0)] * 5, None, "healthy"),
            ([(True, 40.0), (False, None), (True, 45.0), (True, 42.0)], None, "degraded"),
            ([(True, 3000.0)] * 4, None, "degraded"),
            ([(True, 40.0), (False, None), (False, None), (False, None)], None, "down"),
            ([(False, None), (True, 50.0), (True, 40.0)], 1200.0, "cold-start"),
            ([(True, 15000.0), (True, 50.0), (True, 40.0)], 1200.0, "cold-start"),
            ([(True, 15000.0), (True, 50.0), (True, 40.0)], 60.0, "degraded"),
            # Render's documented wake of about a minute is a cold start; past the
            # allowance of half as much again, it is not.
            ([(True, 60000.0), (True, 50.0), (True, 40.0)], 1200.0, "cold-start"),
            ([(True, 95000.0), (True, 50.0), (True, 40.0)], 1200.0, "degraded"),
            # Slow after the first round too: not waking, slow.
            ([(True, 15000.0), (True, 3000.0), (True, 3000.0)], 1200.0, "degraded"),
            ([(False, None), (True, 50.0), (False, None), (True, 40.0)], 1200.0, "degraded"),
        ],
    )
    def test_each_row(self, pattern, idle, state) -> None:
        found, evidence = classify_window(
            self._rounds(*pattern), expected=self.V, idle_seconds=idle
        )
        assert found == state and evidence

    def test_another_candidate_answering_well_is_still_down(self) -> None:
        rounds = [(True, 30.0, self.OTHER)] * 4
        state, evidence = classify_window(rounds, expected=self.V)
        assert state == "down" and "not the verified" in evidence
