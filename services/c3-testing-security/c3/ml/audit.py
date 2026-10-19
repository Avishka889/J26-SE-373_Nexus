"""The family split, checked from the files the model was trained and scored on.

The proposal promises that no Juliet family is on both sides of the split. The
study said so, and the check was run by hand on 2026-10-17 and written down in a
review, stored nowhere. This writes it as a file beside the run it is about,
computed from the exported splits and from the predictions the scores came
from, so it can be read and run again rather than believed.

It also says which weights those predictions came from. The trained arm's study
carries no commit, date or weights hash: the weights travel separately from the
repository, and a directory holding the same run record, labels and predictions
as the study is the evidence that the weights in it are that run's.

    python -m c3.ml.audit --prepared ~/datasets/juliet-prepared \\
        --study studies/juliet-trained --weights ~/models/c3-juliet \\
        --commit <sha> --out studies/juliet-trained/split-audit.json
"""

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from .juliet import Example, assign_splits

SPLITS = ("train", "validation", "test")

#: What the study keeps beside its scores, and what a weights directory from the
#: same run holds too.
RUN_FILES = ("run.json", "labels.json", "test-predictions.jsonl")


def _rows(path: Path) -> Iterator[dict]:
    with path.open() as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def split_audit(prepared: Path, predictions: Path, *, seed: str = "c3") -> dict:
    """The split as the exported files hold it, against the rule that made it.

    Each row's split is compared with what `assign_splits` gives its family now,
    so a row in the wrong file and a rule that changed since are both counted,
    and every family is looked for in all three files. The predictions are
    compared with the test split's families: a score over families the test
    split does not have, or missing some it has, is a score of something else.
    """
    families: dict[str, set[str]] = {split: set() for split in SPLITS}
    rows: Counter[str] = Counter()
    kept: list[tuple[str, str, str, str]] = []
    for split in SPLITS:
        for row in _rows(prepared / f"{split}.jsonl"):
            families[split].add(row["family"])
            rows[split] += 1
            kept.append((row["cwe"], row["family"], row["path"], split))

    rule = assign_splits(
        [
            Example(
                cwe=cwe,
                vulnerable=False,
                method="",
                code="",
                family=family,
                path=path,
                flow_variant="",
            )
            for cwe, family, path, _ in kept
        ],
        by="family",
        seed=seed,
    )
    every = set().union(*families.values())
    in_more_than_one = [
        family for family in every if sum(family in families[split] for split in SPLITS) > 1
    ]
    predicted = {row["family"] for row in _rows(predictions)}
    manifest_path = prepared / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}

    return {
        "seed": seed,
        "rule": "by family, stratified within each weakness class (c3.ml.juliet.assign_splits)",
        "families": {split: len(families[split]) for split in SPLITS},
        "rows": {split: rows[split] for split in SPLITS},
        "familiesInMoreThanOneSplit": len(in_more_than_one),
        "rowsWhoseSplitDiffersFromTheRule": sum(
            1 for _, family, _, split in kept if rule[family] != split
        ),
        "predictions": {
            "rows": sum(1 for _ in _rows(predictions)),
            "families": len(predicted),
            "familiesNotInTheTestSplit": len(predicted - families["test"]),
            "testFamiliesWithoutAPrediction": len(families["test"] - predicted),
        },
        "prepared": {key: manifest.get(key) for key in ("dataset", "generatedAt", "archiveSha256")},
    }


def weights_record(model_dir: Path, study_dir: Path) -> dict:
    """The weights' hash, and whether their directory holds the study's own run files."""
    digest = hashlib.sha256()
    weights = model_dir / "weights.pt"
    with weights.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    same = {
        name: (model_dir / name).read_bytes() == (study_dir / name).read_bytes()
        for name in RUN_FILES
        if (model_dir / name).is_file() and (study_dir / name).is_file()
    }
    return {
        "weightsSha256": digest.hexdigest(),
        "weightsBytes": weights.stat().st_size,
        "sameAsTheStudy": same,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", required=True, help="the exported train, validation, test")
    parser.add_argument("--study", required=True, help="the study's directory of run files")
    parser.add_argument("--weights", default="", help="the weights' directory, to hash them")
    parser.add_argument("--seed", default="c3")
    parser.add_argument("--commit", default="", help="the commit this audit ran at")
    parser.add_argument("--out", required=True)
    arguments = parser.parse_args()

    study = Path(arguments.study).expanduser()
    audit = split_audit(
        Path(arguments.prepared).expanduser(),
        study / "test-predictions.jsonl",
        seed=arguments.seed,
    )
    if arguments.weights:
        audit["weights"] = weights_record(Path(arguments.weights).expanduser(), study)
    audit["auditedAt"] = datetime.now(UTC).isoformat()
    audit["commit"] = arguments.commit
    Path(arguments.out).expanduser().write_text(json.dumps(audit, indent=2) + "\n")
    print(json.dumps({key: audit[key] for key in ("families", "rows")}, indent=2))
    print(f"wrote {arguments.out}")


if __name__ == "__main__":
    main()
