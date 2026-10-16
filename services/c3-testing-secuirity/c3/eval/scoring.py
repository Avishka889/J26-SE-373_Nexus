"""Precision, recall and F1, per weakness class, computed here rather than there.

The trained arm's GPU hours happen on Colab and the scanners run in a sandbox,
but every number that reaches the dissertation is computed by this module, from
predictions the arms wrote down. The reason is not tidiness: a notebook's
accuracy line is not reviewable, cannot be re-run against a changed definition
of a match, and disappears when the runtime is recycled. Predictions are data
and are kept; scores are derived and are recomputed.

**What counts as a match is a decision, not a detail.** A detection arm names a
weakness class at a location, and ground truth names one too. Requiring the
same line would score the arms on how they round a span; requiring only the
same file would call a finding in the wrong function correct. So a prediction
matches when the class agrees, after the parent and child alignment, and the
spans overlap. That rule is stated once, here, and every arm is scored by it.

**Macro rather than micro, and both reported.** Juliet's classes differ in size
by two orders of magnitude, so a micro average is a report about CWE-190. The
macro average weights each class once, which is what a claim about detecting
weaknesses in general means. Both are computed, because a large gap between
them is itself a finding about the arm.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

from ..detect.severity import ALIASES, normalise

#: The row a class blind score is filed under. Every finding counts as the
#: same kind of thing, because the question is whether the weakness was found
#: at all rather than what it was called.
ANY = "any weakness"


def aligned(cwe: str) -> str:
    """One spelling for one weakness, so two arms are compared and not two
    vocabularies."""
    key = normalise(cwe)
    return ALIASES.get(key, key)


@dataclass(frozen=True)
class Span:
    """One claim: a weakness class somewhere in a file."""

    cwe: str
    path: str
    start_line: int = 0
    end_line: int = 0

    def overlaps(self, other: "Span") -> bool:
        if self.path != other.path:
            return False
        if not (self.start_line and other.start_line):
            # A claim with no location is about the file, which is how a
            # dependency advisory and a method level label both arrive.
            return True
        return self.start_line <= other.end_line and other.start_line <= self.end_line

    def matches(self, other: "Span") -> bool:
        return aligned(self.cwe) == aligned(other.cwe) and self.overlaps(other)


@dataclass
class ClassScore:
    """One weakness class, and how an arm did on it."""

    cwe: str
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0

    @property
    def support(self) -> int:
        """How many were really there. A precision without it is unreadable."""
        return self.true_positives + self.false_negatives

    @property
    def precision(self) -> float:
        found = self.true_positives + self.false_positives
        return self.true_positives / found if found else 0.0

    @property
    def recall(self) -> float:
        return self.true_positives / self.support if self.support else 0.0

    @property
    def f1(self) -> float:
        total = self.precision + self.recall
        return 2 * self.precision * self.recall / total if total else 0.0

    def as_dict(self) -> dict:
        return {
            "cwe": self.cwe,
            "support": self.support,
            "truePositives": self.true_positives,
            "falsePositives": self.false_positives,
            "falseNegatives": self.false_negatives,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
        }


@dataclass
class Scorecard:
    """One arm on one dataset: the per class table and its two averages."""

    per_class: dict[str, ClassScore] = field(default_factory=dict)
    #: Predictions that matched nothing and named a class the ground truth
    #: never contains. Kept apart from the per class false positives because
    #: they say something different: not that the arm was wrong about where,
    #: but that it was looking for something this dataset does not label.
    unlabelled_classes: dict[str, int] = field(default_factory=dict)

    @property
    def macro_f1(self) -> float:
        """Each class counted once, which is what a claim about detecting
        weaknesses in general means."""
        scored = [score for score in self.per_class.values() if score.support]
        return sum(score.f1 for score in scored) / len(scored) if scored else 0.0

    @property
    def micro(self) -> ClassScore:
        """Every finding counted once, which is a report about the largest
        class when the classes differ in size by two orders of magnitude."""
        total = ClassScore(cwe="micro")
        for score in self.per_class.values():
            total.true_positives += score.true_positives
            total.false_positives += score.false_positives
            total.false_negatives += score.false_negatives
        return total

    def as_dict(self) -> dict:
        micro = self.micro
        return {
            "perClass": [
                score.as_dict()
                for score in sorted(self.per_class.values(), key=lambda s: -s.support)
            ],
            "macroF1": round(self.macro_f1, 4),
            "microPrecision": round(micro.precision, 4),
            "microRecall": round(micro.recall, 4),
            "microF1": round(micro.f1, 4),
            "unlabelledClasses": dict(sorted(self.unlabelled_classes.items())),
        }


def combine(cards: Iterable[Scorecard]) -> Scorecard:
    """Several scorecards as one, by adding the counts per class.

    How a corpus of separate projects is scored. CWE-Bench-Java is 120
    repositories with one CVE each, so each is scored on its own and the
    totals are added: averaging the projects' F1 scores instead would weight a
    repository with one weakness the same as one with a hundred and forty.

    This is also where a class can end up with no ground truth at all, when one
    project's arm reported a class that no project in the corpus labels, which
    is why the macro average skips rows with no support.
    """
    total = Scorecard()
    for card in cards:
        for cwe, score_for in card.per_class.items():
            row = total.per_class.setdefault(cwe, ClassScore(cwe=cwe))
            row.true_positives += score_for.true_positives
            row.false_positives += score_for.false_positives
            row.false_negatives += score_for.false_negatives
        for cwe, count in card.unlabelled_classes.items():
            total.unlabelled_classes[cwe] = total.unlabelled_classes.get(cwe, 0) + count
    return total


def detected(predicted: Iterable[Span], truth: Iterable[Span]) -> ClassScore:
    """Did it find the weakness, whatever it decided to call it.

    Reported beside the per class table rather than instead of it, because the
    two answer different questions and one arm can be strong at one and weak at
    the other. The trained arm is exactly that case: on the seeded sample it
    flags all five weaknesses and names two of them correctly, and a table that
    only scored the naming would report it as having found two.

    This is also what makes the comparison fair in the other direction. A
    pattern scanner that matches a rule already knows the class it matched, so
    class agreement costs it nothing; a classifier has to choose from
    thirty three. Scoring only by class would compare a lookup against a
    decision and call the difference accuracy.
    """
    blind = [
        Span(cwe=ANY, path=s.path, start_line=s.start_line, end_line=s.end_line) for s in truth
    ]
    guessed = [
        Span(cwe=ANY, path=s.path, start_line=s.start_line, end_line=s.end_line) for s in predicted
    ]
    card = score(guessed, blind)
    return card.per_class.get(aligned(ANY), ClassScore(cwe=ANY))


def score(predicted: Iterable[Span], truth: Iterable[Span]) -> Scorecard:
    """One arm's predictions against ground truth, per weakness class.

    Greedy one to one: each true weakness is credited to at most one
    prediction, and each prediction claims at most one. Without that, an arm
    that reports the same weakness under five overlapping spans would score
    five true positives for finding one thing, which is how a report full of
    duplicates becomes a report with excellent recall.
    """
    remaining = list(truth)
    claimed: set[int] = set()
    card = Scorecard()
    labelled = {aligned(span.cwe) for span in remaining}

    # Indexed by path, because only a same path span can ever match and the
    # unindexed search is every prediction against every truth: on OWASP
    # Benchmark that is eleven million comparisons and minutes of a run whose
    # scanners took seconds. Per path lists keep their original order, so the
    # greedy first unclaimed choice is exactly the one the plain loop made.
    by_path: dict[str, list[int]] = {}
    for index, actual in enumerate(remaining):
        by_path.setdefault(actual.path, []).append(index)

    for prediction in predicted:
        key = aligned(prediction.cwe)
        hit = next(
            (
                index
                for index in by_path.get(prediction.path, ())
                if index not in claimed and prediction.matches(remaining[index])
            ),
            None,
        )
        if hit is None:
            if key not in labelled:
                card.unlabelled_classes[key] = card.unlabelled_classes.get(key, 0) + 1
                continue
            card.per_class.setdefault(key, ClassScore(cwe=key)).false_positives += 1
            continue
        claimed.add(hit)
        card.per_class.setdefault(key, ClassScore(cwe=key)).true_positives += 1

    for index, actual in enumerate(remaining):
        if index in claimed:
            continue
        key = aligned(actual.cwe)
        card.per_class.setdefault(key, ClassScore(cwe=key)).false_negatives += 1
    return card
