"""Table 4's numbers, computed one way for every arm.

Accuracy, macro precision, recall and F1 over the three levels, and High recall
reported on its own because NFR4 puts not missing a genuinely risky update ahead
of overall accuracy. An arm that abstained on a case is scored as if it had said
High, which is what the platform does with no vote, and its abstentions are
counted beside the score so a high recall bought by abstaining can be seen.

Macro averages run over the levels that occur in either the truth or the
predictions, and a level never predicted scores zero precision rather than being
dropped, so an arm cannot improve its average by never saying Medium.
"""

from dataclasses import asdict, dataclass

from sdlc_contracts import RiskLevel

LEVELS: tuple[RiskLevel, ...] = ("low", "medium", "high")


@dataclass(frozen=True)
class Scores:
    cases: int
    accuracy: float
    macro_precision: float
    macro_recall: float
    macro_f1: float
    #: None when no case is truly High, because a recall over nothing is not zero.
    high_recall: float | None
    missed_high: int
    abstained: int
    #: Truth, then prediction, then count.
    confusion: dict[str, dict[str, int]]

    def as_dict(self) -> dict:
        return asdict(self)


def _ratio(top: int, bottom: int) -> float:
    return top / bottom if bottom else 0.0


def score(pairs: list[tuple[RiskLevel, RiskLevel | None]]) -> Scores:
    """Score predictions against observed levels. A None prediction is an abstention."""
    confusion = {truth: {predicted: 0 for predicted in LEVELS} for truth in LEVELS}
    abstained = 0
    for truth, predicted in pairs:
        if predicted is None:
            abstained += 1
            predicted = "high"
        confusion[truth][predicted] += 1

    total = len(pairs)
    correct = sum(confusion[level][level] for level in LEVELS)
    present = [
        level
        for level in LEVELS
        if sum(confusion[level].values()) or sum(confusion[t][level] for t in LEVELS)
    ]
    precisions, recalls, f1s = [], [], []
    for level in present:
        true_positive = confusion[level][level]
        predicted_as = sum(confusion[t][level] for t in LEVELS)
        actually = sum(confusion[level].values())
        precision = _ratio(true_positive, predicted_as)
        recall = _ratio(true_positive, actually)
        precisions.append(precision)
        recalls.append(recall)
        f1s.append(
            _ratio(2 * precision * recall, precision + recall) if precision + recall else 0.0
        )

    truly_high = sum(confusion["high"].values())
    return Scores(
        cases=total,
        accuracy=_ratio(correct, total),
        macro_precision=sum(precisions) / len(present) if present else 0.0,
        macro_recall=sum(recalls) / len(present) if present else 0.0,
        macro_f1=sum(f1s) / len(present) if present else 0.0,
        high_recall=_ratio(confusion["high"]["high"], truly_high) if truly_high else None,
        missed_high=truly_high - confusion["high"]["high"],
        abstained=abstained,
        confusion=confusion,
    )
