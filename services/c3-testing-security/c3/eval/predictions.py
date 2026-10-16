"""What the trained arm predicted, scored here rather than in the notebook.

Colab produces a file of predictions and this produces the numbers. The
separation is deliberate: a notebook's accuracy line cannot be reviewed, cannot
be recomputed when the definition of a match changes, and disappears when the
runtime is reclaimed. Predictions are data and are kept; scores are derived and
are recomputed.

**Two questions, answered separately, because they are different.** Whether the
model can tell a vulnerable method from a safe one is detection, and it is
scored over every test example. Whether it can say which weakness it is looking
at is classification, and it is only meaningful on the methods that really are
vulnerable. A single number that mixed them would let a model that calls
everything safe look respectable, since two thirds of Juliet's methods are.

**Per class through the same rule as every other arm.** Each method becomes a
location, so the scorer that grades the scanners grades this too, with the same
parent and child alignment: a model that learned Juliet's CWE-36 and a
benchmark that says CWE-22 are talking about the same weakness.
"""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

from .scoring import ClassScore, Scorecard, Span, score

#: What the model calls a weakness that is not one of the scored classes. It
#: has no CWE number, so it needs a name of its own or it reads as a blank row.
OTHER = "other"


@dataclass(frozen=True)
class Detection:
    """The binary question: vulnerable or not, over every test example."""

    scored: ClassScore
    total: int

    @property
    def precision(self) -> float:
        return self.scored.precision

    @property
    def recall(self) -> float:
        return self.scored.recall

    @property
    def f1(self) -> float:
        return self.scored.f1

    @property
    def accuracy(self) -> float:
        correct = self.scored.true_positives + (
            self.total
            - self.scored.true_positives
            - self.scored.false_positives
            - self.scored.false_negatives
        )
        return correct / self.total if self.total else 0.0

    def as_dict(self) -> dict:
        return {
            "examples": self.total,
            "accuracy": round(self.accuracy, 4),
            "precision": round(self.scored.precision, 4),
            "recall": round(self.scored.recall, 4),
            "f1": round(self.scored.f1, 4),
            "truePositives": self.scored.true_positives,
            "falsePositives": self.scored.false_positives,
            "falseNegatives": self.scored.false_negatives,
        }


def read_predictions(path: str | Path) -> list[dict]:
    text = Path(path).read_text()
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def key_of(row: dict) -> str:
    """One method, named so that two rows for it cannot be confused.

    The file plus the method, because Juliet puts `bad` and four `good`
    variants in one file and a key of the path alone would collapse them.
    """
    return f"{row.get('path', '')}::{row.get('method', '')}"


def detection(rows: list[dict]) -> Detection:
    """Vulnerable or not, over every example.

    Reported apart from the per class table because a model that calls
    everything safe scores two thirds on Juliet, and a single mixed number
    would hide that.
    """
    found = ClassScore(cwe="vulnerable")
    for row in rows:
        actual = int(row.get("trueLabel", 0))
        predicted = int(row.get("predictedLabel", 0))
        if predicted and actual:
            found.true_positives += 1
        elif predicted and not actual:
            found.false_positives += 1
        elif actual and not predicted:
            found.false_negatives += 1
    return Detection(scored=found, total=len(rows))


def per_class(rows: list[dict]) -> Scorecard:
    """Which weakness, over the methods that really have one.

    A method is a location, so this goes through the same scorer as the
    scanners: same class after alignment, same greedy one to one. A vulnerable
    method the model called safe is a miss here as well as in the detection
    table, which is correct: it classified nothing.
    """
    truth = [
        Span(cwe=str(row.get("trueCwe", "")), path=key_of(row))
        for row in rows
        if int(row.get("trueLabel", 0)) == 1
    ]
    predicted = [
        Span(cwe=str(row.get("predictedCwe", "")), path=key_of(row))
        for row in rows
        if int(row.get("predictedLabel", 0)) == 1
    ]
    card = score(predicted, truth)

    # The one place this arm is scored differently from the scanners, and the
    # reason is the task. A scanner naming a weakness the ground truth never
    # records may have found something real, so those are counted apart. This
    # model chooses from a fixed list of classes, so answering CWE-78 for a
    # CWE-89 method is a wrong answer rather than a discovery, and leaving it
    # in the unlabelled bucket would quietly drop its false positives.
    for cwe, count in card.unlabelled_classes.items():
        # The catch all has no CWE number, so it normalises to nothing and
        # would otherwise appear as a nameless row. It is a real answer, and a
        # wrong one on a test split that contains no train only classes, so it
        # gets the name the model was given for it.
        name = cwe or OTHER
        row = card.per_class.setdefault(name, ClassScore(cwe=name))
        row.false_positives += count
    card.unlabelled_classes.clear()
    return card


def report(model_dir: str | Path) -> dict:
    """The trained arm's numbers, with the provenance the run wrote down."""
    directory = Path(model_dir)
    rows = read_predictions(directory / "test-predictions.jsonl")
    run = {}
    if (directory / "run.json").is_file():
        run = json.loads((directory / "run.json").read_text())
    card = per_class(rows)
    return {
        "modelDir": str(directory),
        "run": run,
        "detection": detection(rows).as_dict(),
        "classification": card.as_dict(),
        "families": len({row.get("family", "") for row in rows}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, help="the directory Colab produced")
    parser.add_argument("--out", default="", help="where to write the study json")
    arguments = parser.parse_args()

    found = report(arguments.model)
    run = found["run"]
    print(f"base model: {run.get('baseModel', 'not recorded')}")
    print(f"split rule: {(run.get('splitRule') or {}).get('by', 'not recorded')}")
    print(f"test families: {found['families']}")
    print()
    print("detection, vulnerable or not, over every test example:")
    for name, value in found["detection"].items():
        print(f"  {name:16} {value}")
    print()
    print("classification, over the methods that really are vulnerable:")
    print(f"  macro F1 {found['classification']['macroF1']}")
    print(f"{'cwe':10} {'support':>8} {'precision':>10} {'recall':>8} {'f1':>7}")
    for row in found["classification"]["perClass"]:
        print(
            f"{row['cwe']:10} {row['support']:8} {row['precision']:10.3f} "
            f"{row['recall']:8.3f} {row['f1']:7.3f}"
        )

    if arguments.out:
        Path(arguments.out).write_text(json.dumps(found, indent=2) + "\n")
        print(f"\nwrote {arguments.out}")


if __name__ == "__main__":
    main()
