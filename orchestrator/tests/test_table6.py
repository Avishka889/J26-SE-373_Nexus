"""Table 6's ledger parts, by hand: how releases and rollbacks ended, controlled apart from organic."""

from orchestrator.deploy.table6 import render, tally


def _row(identifier: str, kind: str, state: str, *, target="local", verified=False, **extra):
    return {
        "id": identifier,
        "kind": kind,
        "state": state,
        "target": target,
        "verified": verified,
        "project_id": "p1",
        "fault_injected": extra.pop("fault", None),
        "authorised": extra.pop("authorised", {}),
    }


ROWS = [
    _row("r1", "release", "succeeded", verified=True),
    _row("r2", "release", "failed"),
    _row("r3", "release", "rolled-back", verified=True, fault="stop-container"),
    _row("r4", "release", "awaiting-rollback-approval", target="cloud"),
    _row("r5", "release", "pending"),
    _row("b1", "rollback", "succeeded", verified=True, authorised={"deploymentId": "r3"}),
    _row("b2", "rollback", "failed", authorised={"deploymentId": "r4"}),
]


def test_releases_are_counted_by_target_and_by_how_they_ended() -> None:
    releases = tally(ROWS)["releases"]
    # r3 was verified before its injected fault, so it counts as a verified release.
    assert releases["local"] == {
        "ended": 3,
        "verified": 2,
        "failedBeforeTraffic": 1,
        "failedAfterTraffic": 0,
    }
    assert releases["cloud"] == {
        "ended": 1,
        "verified": 0,
        "failedBeforeTraffic": 0,
        "failedAfterTraffic": 1,
    }


def test_a_rollback_is_controlled_only_when_its_release_had_a_fault_injected() -> None:
    rollbacks = tally(ROWS)["rollbacks"]
    assert rollbacks["controlled"] == {"ended": 1, "restored": 1}
    assert rollbacks["organic"] == {"ended": 1, "restored": 0}


def test_the_table_says_what_it_counted_and_names_nobody() -> None:
    record = {
        "study": {
            "label": "Table 6, releases and rollbacks",
            "date": "2026-09-28",
            "commit": "abc1234",
            "projects": 1,
        },
        **tally(ROWS),
    }

    printed = render(record)

    assert "| local | 3 | 2 of 3 (67%) | 1 | 0 |" in printed
    assert "| in controlled episodes | 1 | 1 of 1 (100%) |" in printed
    assert "postgresql" not in printed
