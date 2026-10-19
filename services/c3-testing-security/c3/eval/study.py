"""The three way comparison: what each arm found, and what it cost to find it.

Contribution A in one table. Each arm answers the same question over the same
files, and the result is per class precision, recall and F1 beside duration,
tokens, money and whether the arm needed the network. Reporting only accuracy
would make the trained arm look like a worse language model instead of a
different kind of tool, and reporting only cost would make the scanners look
like the answer to everything.

**The comparison includes the combination, not only the three.** Merging the
arms is a fourth result with its own row, because the interesting question is
usually not which arm wins but whether two cheap ones together beat an
expensive one. The merge preserves origin, so the row can say which arms
contributed to each finding it got right.

**Every row carries its epoch.** Model id, date, the commit, the dataset split
and the seed. Numbers from two epochs are never averaged, and the file this
writes is the unit that gets quoted: a table without provenance is a table
nobody can defend at a viva.
"""

import json
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from ..detection import Candidate, DetectionResult, merge
from .scoring import ClassScore, Scorecard, Span, combine, detected, score

#: Above this share of what it examined, an arm is no longer discriminating
#: and its recall is an artefact. Blunt on purpose: a sanity check on the
#: measurement rather than a judgement about the arm.
DEGENERATE_ABOVE = 0.95


class Detector(Protocol):
    arm: str
    model_id: str
    offline: bool

    async def scan(self, root: str, files: list[str]) -> DetectionResult: ...


@dataclass
class ArmResult:
    """One arm on one target: what it found, what it missed, what it cost."""

    arm: str
    model_id: str
    scorecard: Scorecard
    #: Did it find the weakness at all, whatever it called it. Beside the per
    #: class table rather than instead of it: a classifier choosing from
    #: thirty three classes and a rule that already knows the class it matched
    #: are not doing the same work, and scoring only by class would compare a
    #: lookup against a decision and call the difference accuracy.
    found_at_all: ClassScore
    duration_seconds: float
    prompt_tokens: int
    completion_tokens: int
    #: List price for the tokens, computed from the counts rather than billed.
    #: Null when the model is unpriced. Never confused with free.
    cost_usd: float | None
    offline: bool
    files_scanned: int
    found: int
    refused: int
    #: How many things the arm looked at, in whatever unit it works in.
    units_examined: int = 0
    failures: list[str] = field(default_factory=list)

    @property
    def flagged_fraction(self) -> float | None:
        """How much of what it looked at this arm called a weakness.

        Null when the arm counts no units, not zero. The first live run of the
        prompted arm reported `0%` flagged beside thirteen findings, because
        that arm works in files rather than methods and never sets a unit
        count. Zero there reads as an arm that flagged nothing, which is the
        opposite of what happened, and it is the same mistake the mutation
        score already refuses to make.
        """
        return self.found / self.units_examined if self.units_examined else None

    @property
    def degenerate(self) -> bool:
        """Whether this arm has stopped discriminating.

        An arm that flags nearly everything has perfect recall and has found
        nothing, and its recall must not be read as a result. The threshold is
        deliberately blunt: this is a sanity check on the measurement, not a
        judgement about the arm.

        An arm with no unit count is not degenerate and is not clean either:
        the question was not asked of it, and false is the honest answer to
        "has this been shown to flag everything".
        """
        fraction = self.flagged_fraction
        return fraction is not None and fraction >= DEGENERATE_ABOVE

    def as_dict(self) -> dict:
        return {
            "arm": self.arm,
            "modelId": self.model_id,
            "durationSeconds": self.duration_seconds,
            "promptTokens": self.prompt_tokens,
            "completionTokens": self.completion_tokens,
            "costUsd": self.cost_usd,
            "offline": self.offline,
            "filesScanned": self.files_scanned,
            "found": self.found,
            "refused": self.refused,
            "unitsExamined": self.units_examined,
            "flaggedFraction": (
                round(self.flagged_fraction, 4) if self.flagged_fraction is not None else None
            ),
            "degenerate": self.degenerate,
            "detection": {
                "precision": round(self.found_at_all.precision, 4),
                "recall": round(self.found_at_all.recall, 4),
                "f1": round(self.found_at_all.f1, 4),
            },
            "failures": self.failures,
            **self.scorecard.as_dict(),
        }


@dataclass
class Epoch:
    """What makes a number quotable.

    Recorded at the moment the number is produced rather than reconstructed
    later, because a run's model, prompts and rules are exactly the things that
    have already changed by the time anybody asks.
    """

    label: str
    commit: str = ""
    dataset: str = ""
    split_seed: str = ""
    note: str = ""
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


#: A detection slice is drawn with nothing random: a benchmark is read in its own
#: order and a slice is its first rows, so the same slice comes back every run.
#: Recorded as a word rather than left empty, which read as a seed nobody kept.
NO_SEED = "none"


def detection_epoch(
    *,
    label: str,
    commit: str = "",
    dataset: str = "",
    taken: int,
    total: int,
    unit: str = "files",
) -> Epoch:
    """A detection run's epoch, saying how much of the benchmark it read and how."""
    note = (
        f"all {total} {unit}"
        if taken >= total
        else f"the first {taken} of {total} {unit}, in the benchmark's own order"
    )
    return Epoch(label=label, commit=commit, dataset=dataset, split_seed=NO_SEED, note=note)


@dataclass
class Study:
    """One run of the comparison, ready to be written down."""

    epoch: Epoch
    target: str
    truth_count: int
    arms: list[ArmResult] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "epoch": asdict(self.epoch),
            "target": self.target,
            "groundTruthCount": self.truth_count,
            "arms": [arm.as_dict() for arm in self.arms],
        }

    def write(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.as_dict(), indent=2) + "\n")

    def table(self) -> str:
        """The comparison as text, for a terminal and for a first draft.

        Deliberately not the dissertation's table. This is what a person reads
        while the run is still warm, and the JSON beside it is what gets
        formatted properly later.
        """
        header = f"{'arm':10} {'foundP':>7} {'foundR':>7} {'macroF1':>8} {'found':>6} "
        header += f"{'flagged':>8} {'secs':>7} {'tokens':>8} {'cost':>8}  offline"
        lines = [header, "-" * len(header)]
        for arm in self.arms:
            micro = arm.scorecard.micro
            cost = "unreported" if arm.cost_usd is None else f"{arm.cost_usd:.4f}"
            del micro
            flagged = (
                f"{arm.flagged_fraction:.0%}" + ("!" if arm.degenerate else "")
                if arm.flagged_fraction is not None
                else "n/a"
            )
            lines.append(
                f"{arm.arm:10} {arm.found_at_all.precision:7.3f} "
                f"{arm.found_at_all.recall:7.3f} {arm.scorecard.macro_f1:8.3f} "
                f"{arm.found:6} {flagged:>8} {arm.duration_seconds:7.1f} "
                f"{arm.prompt_tokens + arm.completion_tokens:8} {cost:>8}  {arm.offline}"
            )
        degenerate = [arm.arm for arm in self.arms if arm.degenerate]
        if degenerate:
            lines.append("")
            lines.append(
                f"! {', '.join(degenerate)} flagged nearly everything it looked at. "
                "Its recall is an artefact of that and is not a result."
            )
        return "\n".join(lines)


def _add(scores: Iterable[ClassScore]) -> ClassScore:
    """Several detection counts as one, for a corpus scored project by
    project."""
    total = ClassScore(cwe="any weakness")
    for found in scores:
        total.true_positives += found.true_positives
        total.false_positives += found.false_positives
        total.false_negatives += found.false_negatives
    return total


def combine_studies(studies: Sequence[Study], *, epoch: Epoch, target: str) -> Study:
    """Several per project runs as one row per arm.

    Counts add and costs add; the scorecard is combined per class rather than
    averaged, so a repository with one weakness does not weigh the same as one
    with a hundred and forty. Failures are kept whole: a corpus where the
    bytecode arm could not run on eleven of twenty projects is not a corpus
    where it ran.
    """
    together = Study(
        epoch=epoch,
        target=target,
        truth_count=sum(study.truth_count for study in studies),
    )
    for arm in dict.fromkeys(result.arm for study in studies for result in study.arms):
        rows = [result for study in studies for result in study.arms if result.arm == arm]
        costs = [row.cost_usd for row in rows]
        together.arms.append(
            ArmResult(
                arm=arm,
                model_id=rows[0].model_id,
                scorecard=combine(row.scorecard for row in rows),
                found_at_all=_add(row.found_at_all for row in rows),
                duration_seconds=round(sum(row.duration_seconds for row in rows), 3),
                prompt_tokens=sum(row.prompt_tokens for row in rows),
                completion_tokens=sum(row.completion_tokens for row in rows),
                cost_usd=sum(costs) if all(cost is not None for cost in costs) else None,  # type: ignore[arg-type]
                offline=all(row.offline for row in rows),
                files_scanned=sum(row.files_scanned for row in rows),
                found=sum(row.found for row in rows),
                refused=sum(row.refused for row in rows),
                units_examined=sum(row.units_examined for row in rows),
                failures=[failure for row in rows for failure in row.failures],
            )
        )
    return together


def spans_of(candidates: Sequence[Candidate]) -> list[Span]:
    return [
        Span(
            cwe=candidate.cwe,
            path=candidate.path,
            start_line=candidate.start_line,
            end_line=candidate.end_line,
        )
        for candidate in candidates
    ]


def _result_for(
    arm: str, model_id: str, result: DetectionResult, truth: Sequence[Span]
) -> ArmResult:
    return ArmResult(
        arm=arm,
        model_id=model_id,
        scorecard=score(spans_of(result.candidates), truth),
        found_at_all=detected(spans_of(result.candidates), truth),
        duration_seconds=result.run.duration_seconds,
        prompt_tokens=result.run.prompt_tokens,
        completion_tokens=result.run.completion_tokens,
        cost_usd=result.run.cost_usd,
        offline=result.run.offline,
        files_scanned=result.run.files_scanned,
        found=len(result.candidates),
        refused=len(result.refused),
        units_examined=result.units_examined,
        failures=list(result.failures),
    )


async def run_study(
    detectors: Sequence[Detector],
    root: str,
    files: list[str],
    truth: Sequence[Span],
    *,
    epoch: Epoch,
    target: str = "",
) -> Study:
    """Run every arm over the same files and score them by the same rule.

    Sequentially, and that is not an oversight. This machine has under six
    gigabytes of memory, the trained arm loads a model and the scanners start a
    JVM, and two of those at once is a swap storm rather than a measurement. It
    also makes the reported durations mean something: an arm's latency measured
    while two others fought it for memory is a number about the machine.
    """
    study = Study(epoch=epoch, target=target or root, truth_count=len(truth))
    results: list[DetectionResult] = []
    for detector in detectors:
        result = await detector.scan(root, files)
        results.append(result)
        study.arms.append(_result_for(detector.arm, detector.model_id, result, truth))

    if len(results) > 1:
        combined = merge(results)
        study.arms.append(
            ArmResult(
                arm="merged",
                model_id=" + ".join(detector.model_id for detector in detectors),
                scorecard=score(spans_of(combined), truth),
                found_at_all=detected(spans_of(combined), truth),
                duration_seconds=round(sum(r.run.duration_seconds for r in results), 3),
                prompt_tokens=sum(r.run.prompt_tokens for r in results),
                completion_tokens=sum(r.run.completion_tokens for r in results),
                cost_usd=_total_cost(results),
                # True only when every arm it is made of is, which is the
                # honest reading: a combination is as offline as its most
                # demanding member.
                offline=all(r.run.offline for r in results),
                files_scanned=max((r.run.files_scanned for r in results), default=0),
                found=len(combined),
                refused=sum(len(r.refused) for r in results),
                units_examined=max((r.units_examined for r in results), default=0),
                failures=[failure for r in results for failure in r.failures],
            )
        )
    return study


def _total_cost(results: Sequence[DetectionResult]) -> float | None:
    """The sum, or null when any arm did not report one.

    Null rather than a partial total: a cost that silently omits the arm that
    did not say is a cost that will be quoted as though it were complete.
    """
    known = [result.run.cost_usd for result in results]
    return sum(known) if all(cost is not None for cost in known) else None  # type: ignore[arg-type]
