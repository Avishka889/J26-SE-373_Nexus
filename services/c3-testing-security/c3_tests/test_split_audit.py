"""The family split, checked from the files rather than believed.

The proposal promises no Juliet family on both sides of the split. The check was
run by hand on 2026-10-17 and stored nowhere, so the number rested on a review
saying so. These hold the command that writes it beside the run instead.
"""

import hashlib
import json
from pathlib import Path

from c3.ml.audit import split_audit, weights_record
from c3.ml.export import FIELDS
from c3.ml.juliet import Example, assign_splits


def _corpus(tmp_path: Path) -> tuple[Path, Path, list[dict]]:
    """Two weakness classes of ten families, split by the rule, as the export writes them."""
    examples = [
        Example(
            cwe=cwe,
            vulnerable=method == "bad",
            method=method,
            code="{}",
            family=f"{cwe}_family_{number}",
            path=f"{cwe}/{cwe}_family_{number}_01.java",
            flow_variant="01",
        )
        for cwe in ("CWE-89", "CWE-78")
        for number in range(10)
        for method in ("bad", "good")
    ]
    split = assign_splits(examples)
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    rows = [
        dict(
            zip(
                FIELDS,
                (
                    e.code,
                    int(e.vulnerable),
                    e.cwe,
                    e.method,
                    e.family,
                    e.path,
                    "01",
                    split[e.family],
                ),
                strict=True,
            )
        )
        for e in examples
    ]
    for name in ("train", "validation", "test"):
        (prepared / f"{name}.jsonl").write_text(
            "".join(json.dumps(row) + "\n" for row in rows if row["split"] == name)
        )
    (prepared / "manifest.json").write_text(
        json.dumps({"dataset": "a fixture", "generatedAt": "2026-09-09", "archiveSha256": "abc"})
    )
    predictions = tmp_path / "test-predictions.jsonl"
    predictions.write_text(
        "".join(
            json.dumps({"family": row["family"], "trueLabel": row["label"]}) + "\n"
            for row in rows
            if row["split"] == "test"
        )
    )
    return prepared, predictions, rows


class TestTheSplitAsTheFilesHoldIt:
    def test_a_split_made_by_the_rule_holds(self, tmp_path) -> None:
        prepared, predictions, rows = _corpus(tmp_path)

        audit = split_audit(prepared, predictions)

        test_families = {row["family"] for row in rows if row["split"] == "test"}
        assert test_families, "the fixture has to put something in the test split"
        assert audit["familiesInMoreThanOneSplit"] == 0
        assert audit["rowsWhoseSplitDiffersFromTheRule"] == 0
        assert audit["families"]["test"] == len(test_families)
        assert sum(audit["rows"].values()) == len(rows)
        assert audit["predictions"]["testFamiliesWithoutAPrediction"] == 0
        assert audit["predictions"]["familiesNotInTheTestSplit"] == 0
        assert audit["prepared"]["archiveSha256"] == "abc"

    def test_a_family_moved_across_the_split_is_found(self, tmp_path) -> None:
        """One method of a test family written into train: the leak the rule exists to stop."""
        prepared, predictions, rows = _corpus(tmp_path)
        leaked = next(row for row in rows if row["split"] == "test")
        with (prepared / "train.jsonl").open("a") as handle:
            handle.write(json.dumps({**leaked, "split": "train"}) + "\n")

        audit = split_audit(prepared, predictions)

        assert audit["familiesInMoreThanOneSplit"] == 1
        assert audit["rowsWhoseSplitDiffersFromTheRule"] == 1

    def test_a_test_family_with_no_prediction_is_found(self, tmp_path) -> None:
        prepared, predictions, rows = _corpus(tmp_path)
        dropped = next(row["family"] for row in rows if row["split"] == "test")
        kept = [
            line
            for line in predictions.read_text().splitlines()
            if json.loads(line)["family"] != dropped
        ]
        predictions.write_text("".join(line + "\n" for line in kept))

        audit = split_audit(prepared, predictions)

        assert audit["predictions"]["testFamiliesWithoutAPrediction"] == 1


class TestWhichWeightsTheRunCameFrom:
    def test_the_weights_are_hashed_and_matched_to_the_study(self, tmp_path) -> None:
        model, study = tmp_path / "model", tmp_path / "study"
        model.mkdir()
        study.mkdir()
        (model / "weights.pt").write_bytes(b"not real weights")
        for name in ("run.json", "labels.json", "test-predictions.jsonl"):
            (model / name).write_text(name)
            (study / name).write_text(name)

        record = weights_record(model, study)

        assert record["weightsSha256"] == hashlib.sha256(b"not real weights").hexdigest()
        assert record["sameAsTheStudy"] == {
            "run.json": True,
            "labels.json": True,
            "test-predictions.jsonl": True,
        }

    def test_a_different_run_record_is_not_called_the_same_run(self, tmp_path) -> None:
        model, study = tmp_path / "model", tmp_path / "study"
        model.mkdir()
        study.mkdir()
        (model / "weights.pt").write_bytes(b"w")
        (model / "run.json").write_text('{"seed": 13}')
        (study / "run.json").write_text('{"seed": 14}')

        record = weights_record(model, study)

        assert record["sameAsTheStudy"] == {"run.json": False}
