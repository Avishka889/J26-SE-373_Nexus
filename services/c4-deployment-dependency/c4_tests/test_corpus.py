"""The corpus plan: what each source gives, chosen by rule, one case per update.

BUMP records are made here in BUMP's own shape; the platform's crossings are
made directly. What is held to account is the selection (the worked case always
in, a quota per version change, both splits, a fixed order nobody picks), the
rule that one update is one case however many days offer it, and the plan's
arithmetic.
"""

from datetime import date

from c4.eval.corpus import BUMP_QUOTA, Planned, one_per_update, render_plan, select_bump
from c4.eval.loaders.bump import case_from_record
from c4.eval.loaders.npm_platform import Crossing
from c4.eval.seed import WORKED_CASE


def _record(commit: str, change: str, *, new: str = "2.0.0") -> dict:
    return {
        "breakingCommit": commit,
        "project": "p",
        "projectOrganisation": "o",
        "failureCategory": "COMPILATION_FAILURE",
        "updatedDependency": {
            "dependencyGroupID": "g",
            "dependencyArtifactID": f"a{commit[-8:]}",
            "previousVersion": "1.0.0",
            "newVersion": new,
            "versionUpdateType": change,
        },
    }


def _bump(commit: str, change: str):
    return case_from_record(_record(commit, change), dataset_commit="c", captured_at="2026-01-01")


def _crossing(package: str, old: str, new: str, kind="minor") -> Crossing:
    return Crossing(package, old, new, kind, (), ("package.json",), "prod")


class TestBump:
    def test_the_worked_case_is_always_in_and_each_change_takes_its_quota(self) -> None:
        worked = _bump(WORKED_CASE.removeprefix("bump-") + "0" * 28, "patch")
        many = [
            _bump(f"{index:040x}", change)
            for index, change in enumerate(["major", "minor", "patch", "other"] * 40)
        ]

        chosen = select_bump([*many, worked])

        assert chosen[0].case_id == WORKED_CASE
        counts: dict[str, int] = {}
        for case in chosen[1:]:
            counts[case.source_change] = counts.get(case.source_change, 0) + 1
        assert counts == BUMP_QUOTA

    def test_both_splits_are_drawn_from(self) -> None:
        many = [_bump(f"{index:040x}", "major") for index in range(200)]
        splits = {case.split for case in select_bump(many)}
        assert splits == {"dev", "held-out"}

    def test_the_order_is_fixed_not_the_listing(self) -> None:
        many = [_bump(f"{index:040x}", "minor") for index in range(80)]
        assert [c.case_id for c in select_bump(many)] == [
            c.case_id for c in select_bump(list(reversed(many)))
        ]


class TestOneCasePerUpdate:
    def test_an_update_a_later_day_offers_again_is_not_taken_twice(self) -> None:
        by_day = {
            date(2026, 6, 1): [_crossing("vite", "6.4.2", "8.3.1", "major")],
            date(2026, 7, 1): [
                _crossing("vite", "6.4.2", "8.3.1", "major"),
                _crossing("vite", "6.4.5", "8.3.1", "major"),
            ],
        }

        fresh = one_per_update(by_day)

        assert [c.from_version for c in fresh[date(2026, 6, 1)]] == ["6.4.2"]
        # From another version, it is another update.
        assert [c.from_version for c in fresh[date(2026, 7, 1)]] == ["6.4.5"]


class TestThePlan:
    def test_it_counts_by_source_and_estimates_only_what_is_observed(self) -> None:
        planned = [
            Planned("b1", "bump", "maven", "minor", "dev", True),
            Planned("b2", "bump", "maven", "major", "held-out", True),
            Planned("p1", "npm-platform", "npm", "patch", "dev", False),
        ]

        table = render_plan(planned)

        assert "| bump | maven | 2 | 0 | 1 | 1 | major 1, minor 1 |" in table
        assert "| npm-platform | npm | 0 | 1 | 1 | 0 | patch 1 |" in table
        assert "3 cases: npm 1, Maven 2. 1 to observe, about 0.1 hours" in table


class TestPinningEachDay:
    def test_a_pin_is_tried_twice_and_a_day_that_never_pins_is_left_out(self, monkeypatch) -> None:
        from c4.eval import corpus
        from c4.intake.lockfile import PinFailed

        failures = {corpus.PLATFORM_DATES[0]: 1, corpus.PLATFORM_DATES[1]: 5}
        asked: list[date] = []

        def scripted(studies, *, cache, on, pins):
            asked.append(on)
            if failures.get(on, 0) > 0:
                failures[on] -= 1
                raise PinFailed(f"npm could not resolve the tree on {on}")
            return ({}, None, None, [])

        monkeypatch.setattr(corpus, "platform_tree", scripted)
        said: list[str] = []

        trees = corpus.platform_trees(
            None, cache=None, pins=None, log=lambda *a, **k: said.append(a[0])
        )

        assert corpus.PLATFORM_DATES[0] in trees  # failed once, then pinned
        assert corpus.PLATFORM_DATES[1] not in trees  # failed both times
        assert asked.count(corpus.PLATFORM_DATES[1]) == 2
        assert len(said) == 3


class TestALostDownload:
    def test_a_case_every_attempt_lost_a_download_is_not_written(self, tmp_path) -> None:
        from c4.eval.cases import CaseClient, CaseUpdate, LabelledCase, Observed, ObservedStep
        from c4.eval.seed import _keep

        def case(outcome: str) -> LabelledCase:
            return LabelledCase(
                case_id=f"c-{outcome}",
                source="hand",
                client=CaseClient(kind="seeded"),
                update=CaseUpdate(ecosystem="npm", package="p", from_version="1", to_version="2"),
                observed=Observed(
                    method="container-reproduction",
                    captured_at="2026-09-28",
                    baseline=[ObservedStep(name="test", outcome="passed")],
                    candidate=[ObservedStep(name="resolution", outcome=outcome)],
                ),
                provenance="written for the test",
            )

        _keep(case("unavailable"), 3, tmp_path)
        _keep(case("passed"), 1, tmp_path)

        assert sorted(path.name for path in tmp_path.glob("*.json")) == ["c-passed.json"]
