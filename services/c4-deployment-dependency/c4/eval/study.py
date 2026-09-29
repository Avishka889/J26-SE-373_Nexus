"""Run the arms over the cases and record everything a table will need.

An arm is a function from a case to a level or an abstention. Two are always
there: the SemVer rule alone, which is the baseline and the hybrid's signal
one, and "always High", which is kept in every table and marked degenerate,
because an arm that calls everything High has perfect High recall and has
found nothing. The others are read from a votes record: each signal alone,
each pair, and the hybrid, every combination by the product's own rule, and
the model's stated level, marked informational because no rule uses it.

The study refuses to read the held out cases unless told it is the final
evaluation, and says in its record which split it read.
"""

import hashlib
import json
from collections.abc import Callable, Iterable
from datetime import date

from sdlc_contracts import (
    ARBITRATION_RULE,
    CHANGELOG_RULE,
    SEMVER_RULE,
    USAGE_RULE,
    RiskLevel,
    safety_first,
    semver_level,
)

from ..risk.semver_rule import SameRelease, movement
from .cases import LabelledCase
from .rubric import RUBRIC, Excluded, level
from .scoring import score
from .statistics import BOOTSTRAP_SEED, RESAMPLES, bootstrap, mcnemar

Arm = Callable[[LabelledCase], RiskLevel | None]


def semver_arm(case: LabelledCase) -> RiskLevel | None:
    """The version number alone (FR4)."""
    try:
        moved = movement(case.update.ecosystem, case.update.from_version, case.update.to_version)
    except SameRelease:
        return None
    return semver_level(moved.change)


def always_high(case: LabelledCase) -> RiskLevel | None:
    return "high"


ARMS: dict[str, Arm] = {"semver": semver_arm, "always-high": always_high}


class VotesMissing(RuntimeError):
    """Arms were asked of a votes record that does not cover every case."""


def recorded_arms(votes: dict[str, dict]) -> dict[str, Arm]:
    """The arms a votes record supports, each read from the record and never recomputed.

    `usage` is signal three alone, and `semver+usage` the most cautious of the
    two, which is the hybrid without its changelog signal. The changelog arm,
    and the full hybrid, join only when the record says the changelog was run.
    """

    def vote(case: LabelledCase, signal: str) -> RiskLevel | None:
        entry = votes[case.case_id][signal]
        return entry.get("level") if isinstance(entry, dict) else entry

    def combined(case: LabelledCase, signals: tuple[str, ...]) -> RiskLevel | None:
        return safety_first({s: vote(case, s) for s in signals})[0]  # type: ignore[misc]

    def stated(case: LabelledCase) -> RiskLevel | None:
        call = (votes[case.case_id]["changelog"] or {}).get("model") or {}
        return call.get("statedLevel")

    def gated(case: LabelledCase, others: tuple[str, ...]) -> RiskLevel | None:
        usage = vote(case, "usage")
        return usage if usage is not None else combined(case, others)

    arms: dict[str, Arm] = {
        "usage": lambda case: vote(case, "usage"),
        "semver+usage": lambda case: combined(case, ("semver", "usage")),
        "usage-gated": lambda case: gated(case, ("semver",)),
    }
    if all(entry.get("changelogRun") for entry in votes.values()):
        arms = {
            "changelog": lambda case: vote(case, "changelog"),
            "usage": arms["usage"],
            "semver+changelog": lambda case: combined(case, ("semver", "changelog")),
            "semver+usage": arms["semver+usage"],
            "changelog+usage": lambda case: combined(case, ("changelog", "usage")),
            "hybrid": lambda case: combined(case, ("semver", "changelog", "usage")),
            "changelog-stated": stated,
            "usage-gated": lambda case: gated(case, ("semver", "changelog")),
        }
    return arms


#: Arms whose recall means nothing, marked wherever they are shown.
DEGENERATE = frozenset({"always-high"})

#: Arms no product rule uses, shown for the study and marked wherever they are:
#: the level the model said, where the product uses the level its claims support.
INFORMATIONAL = frozenset({"changelog-stated"})

#: Arms offered for discussion and never a product rule, marked wherever they are:
#: the usage vote where usage voted, and the most cautious of the other signals
#: where it abstained. It asks whether evidence from the project's own code, left
#: to decide alone, beats caution (B6); the product's rule stays the most cautious.
EXPLORATORY = frozenset({"usage-gated"})

#: Every rule an arm read from a votes record is computed by.
RULES = (SEMVER_RULE, CHANGELOG_RULE, USAGE_RULE, ARBITRATION_RULE)


def votes_header(record: dict) -> dict:
    """What a votes record was made under, for the header of every table read from it."""
    changelog = record.get("changelog") or {}
    kept = ("model", "promptId", "promptSha256", "settings", "commit", "recordedOn")
    return {
        "recordedOn": record.get("recordedOn"),
        "rules": list(RULES),
        **({"changelog": {k: changelog[k] for k in kept if k in changelog}} if changelog else {}),
    }


class HeldOutRefused(RuntimeError):
    """The held out cases were asked for outside the final evaluation."""


def corpus_hash(cases: Iterable[LabelledCase]) -> str:
    """One hash over every case, so a table names exactly what it was computed on."""
    digest = hashlib.sha256()
    for case in sorted(cases, key=lambda c: c.case_id):
        digest.update(
            json.dumps(case.model_dump(by_alias=True, mode="json"), sort_keys=True).encode()
        )
    return digest.hexdigest()


def run(
    cases: list[LabelledCase],
    *,
    epoch: str,
    commit: str,
    split: str = "dev",
    final: bool = False,
    arms: dict[str, Arm] | None = None,
    today: date | None = None,
    votes: dict[str, dict] | None = None,
    votes_made: dict | None = None,
) -> dict:
    """Score every arm on the cases of one split, and return the record a table is built from.

    With a votes record, the arms it supports join the table beside SemVer and
    "always High"; every chosen case must be in it.
    """
    if split == "held-out" and not final:
        raise HeldOutRefused(
            "the held out cases are read once, for the final evaluation; pass final to read them"
        )
    chosen = [case for case in cases if case.split == split] if split != "all" else list(cases)
    arms = dict(arms or ARMS)
    if votes is not None:
        missing = sorted(case.case_id for case in chosen if case.case_id not in votes)
        if missing:
            raise VotesMissing(f"the votes record has nothing for {', '.join(missing)}")
        arms = {"semver": semver_arm, **recorded_arms(votes), "always-high": always_high}

    labelled: list[tuple[LabelledCase, RiskLevel]] = []
    excluded = []
    for case in chosen:
        truth = level(case.observed)
        if isinstance(truth, Excluded):
            excluded.append({"caseId": case.case_id, "reason": truth.reason})
        else:
            labelled.append((case, truth))

    predictions = {
        case.case_id: {name: arm(case) for name, arm in arms.items()} for case, _ in labelled
    }
    truths = [truth for _, truth in labelled]
    by_arm = {}
    for name in arms:
        pairs = [(truth, predictions[case.case_id][name]) for case, truth in labelled]
        by_arm[name] = {
            **score(pairs).as_dict(),
            "degenerate": name in DEGENERATE,
            "informational": name in INFORMATIONAL,
            "exploratory": name in EXPLORATORY,
            "intervals": {
                "accuracy": bootstrap(pairs, lambda s: s.accuracy),
                "highRecall": bootstrap(pairs, lambda s: s.high_recall),
                "macroF1": bootstrap(pairs, lambda s: s.macro_f1),
            },
        }
        if name != "semver" and "semver" in arms:
            by_arm[name]["versusSemver"] = mcnemar(
                truths,
                [predictions[case.case_id][name] for case, _ in labelled],
                [predictions[case.case_id]["semver"] for case, _ in labelled],
            )
    # Scored per ecosystem as well as together, because a corpus whose Maven
    # side is mostly breaks and whose npm side is mostly not would otherwise
    # report one number that describes neither.
    by_ecosystem = {
        ecosystem: {
            name: score(
                [
                    (truth, predictions[case.case_id][name])
                    for case, truth in labelled
                    if case.update.ecosystem == ecosystem
                ]
            ).as_dict()
            for name in arms
        }
        for ecosystem in sorted({case.update.ecosystem for case, _ in labelled})
    }
    return {
        "epoch": {
            "label": epoch,
            "date": (today or date.today()).isoformat(),
            "commit": commit,
            "rubric": RUBRIC,
            "bootstrap": {"seed": BOOTSTRAP_SEED, "resamples": RESAMPLES},
            "split": split,
            "final": final,
            "corpusSha256": corpus_hash(chosen),
            "cases": len(chosen),
            "labelled": len(labelled),
            "excluded": len(excluded),
            "bySource": _count(case.source for case in chosen),
            "byEcosystem": _count(case.update.ecosystem for case in chosen),
            **({"votes": votes_made} if votes_made else {}),
        },
        "arms": by_arm,
        "byEcosystem": by_ecosystem,
        "cases": [
            {
                "caseId": case.case_id,
                "truth": truth,
                "sourceChange": case.source_change,
                "predictions": predictions[case.case_id],
                **({"votes": votes[case.case_id]} if votes is not None else {}),
            }
            for case, truth in labelled
        ],
        "excluded": excluded,
    }


def _count(values: Iterable[str]) -> dict[str, int]:
    counted: dict[str, int] = {}
    for value in values:
        counted[value] = counted.get(value, 0) + 1
    return dict(sorted(counted.items()))
