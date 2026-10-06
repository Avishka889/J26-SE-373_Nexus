"""Table 7's arithmetic, by hand, and its conditions, on real containers.

The scores are checked against matrices worked out by hand, so a number in the
table is never only as right as the code that printed it. The Docker test puts
four containers into the states that do not depend on how fast this machine
is (healthy, a host waking, stopped, another candidate) and shows the monitor
names each, and that the study leaves nothing behind.
"""

import subprocess

import pytest
from orchestrator.deploy import table7
from orchestrator.deploy.table7 import CONDITIONS, STATES, confusion, render_table, scores


def _episode(known: str, detected: str, condition: str = "c") -> dict:
    return {"condition": condition, "known": known, "detected": detected}


class TestTheScores:
    def test_the_matrix_counts_known_by_detected(self) -> None:
        episodes = [
            _episode("healthy", "healthy"),
            _episode("healthy", "healthy"),
            _episode("degraded", "cold-start"),
            _episode("down", "down"),
        ]

        matrix = confusion(episodes)

        assert matrix["healthy"]["healthy"] == 2
        assert matrix["degraded"]["cold-start"] == 1
        assert matrix["down"]["down"] == 1
        assert sum(sum(row.values()) for row in matrix.values()) == 4
        assert set(matrix) == set(STATES) and all(
            set(row) == set(STATES) for row in matrix.values()
        )

    def test_accuracy_precision_and_recall_by_hand(self) -> None:
        # Known degraded 4: found degraded 3, cold-start 1. Known cold-start 2: both found.
        # Known down 2: found down 1, degraded 1.
        episodes = (
            [_episode("degraded", "degraded")] * 3
            + [_episode("degraded", "cold-start")]
            + [_episode("cold-start", "cold-start")] * 2
            + [_episode("down", "down"), _episode("down", "degraded")]
        )

        result = scores(episodes)

        assert (result["total"], result["correct"]) == (8, 6)
        assert result["accuracy"] == 6 / 8
        degraded = result["perState"]["degraded"]
        assert (degraded["support"], degraded["detected"]) == (4, 4)
        assert degraded["precision"] == 3 / 4 and degraded["recall"] == 3 / 4
        cold = result["perState"]["cold-start"]
        assert cold["precision"] == 2 / 3 and cold["recall"] == 1.0
        down = result["perState"]["down"]
        assert down["precision"] == 1.0 and down["recall"] == 1 / 2
        # Neither known nor found: no row, rather than a row of zeros that reads as a score.
        assert "healthy" not in result["perState"] and "unknown" not in result["perState"]

    def test_no_episodes_has_no_accuracy(self) -> None:
        assert scores([])["accuracy"] is None

    def test_the_table_prints_every_condition_and_the_accuracy(self) -> None:
        episodes = [
            {**_episode(item.known, item.known, item.name), "correct": True} for item in CONDITIONS
        ]
        record = {
            "study": {
                "label": "Table 7: monitoring state detection",
                "date": "2026-09-28",
                "commit": "abc1234",
                "docker": "29",
                "rule": "health-rule/1",
                "repeats": 1,
                "window": {"rounds": 5, "intervalSeconds": 2.0},
                "conditions": [
                    {"name": item.name, "known": item.known, "how": item.how} for item in CONDITIONS
                ],
            },
            "episodes": episodes,
            **scores(episodes),
        }

        table = render_table(record)

        assert all(f"| {item.name} |" in table for item in CONDITIONS)
        assert f"Accuracy: {len(CONDITIONS)} of {len(CONDITIONS)} (100%)." in table


def _docker_answers() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, check=False).returncode == 0
    except FileNotFoundError:
        return False


def _leftovers() -> str:
    return subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"label=sdlc.c4.lane={table7.LANE}"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()


@pytest.mark.docker
async def test_each_steady_condition_is_named_for_what_it_is() -> None:
    if not _docker_answers():
        pytest.skip("no Docker daemon answers")
    wanted = ("healthy", "waking after an idle spell", "stopped", "another candidate")
    image, _ = table7.build_image()
    try:
        found = {
            item.name: await table7.episode(item, image, repeat=1)
            for item in CONDITIONS
            if item.name in wanted
        }
    finally:
        subprocess.run(["docker", "rmi", "-f", image], capture_output=True, check=False)

    assert {name: episode["detected"] for name, episode in found.items()} == {
        "healthy": "healthy",
        "waking after an idle spell": "cold-start",
        "stopped": "down",
        "another candidate": "down",
    }
    assert "not the verified" in found["another candidate"]["evidence"]
    assert _leftovers() == ""
