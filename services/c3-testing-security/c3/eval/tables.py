"""The dissertation's tables, built from the runs that produced them.

    uv run python -m c3.eval --tables studies/

`Study.table` is what a person reads while a run is still warm. This is the
other half of that sentence: the stored JSON formatted properly, months later,
by something that cannot quietly disagree with the artefact it read.

**Why this is a command and not a spreadsheet.** Every number in the write-up
has to be traceable to the run that produced it, and a table pasted into a
document by hand stops being traceable the moment anything is re-run. Pointing
this at the studies directory regenerates every table from the files on disk,
so a table that disagrees with an artefact cannot survive a regeneration.

**Three rules it enforces, each of which this project learned the hard way.**

*Epochs are never pooled.* One table per epoch, with the label, the commit and
the dataset above it. Numbers from two epochs sit in two tables even when the
columns match, because a rule or a model changed between them and the reader
has to see that before comparing.

*An incomplete pass is marked wherever it appears.* Epoch 9's prompted arm read
39 of its 108 chunks before a quota stopped it, scored worst of three, and
produced the conclusion that the free scanner was the most accurate arm. Epoch
10 gave the same arm the whole corpus and it scored best. The row carried a
warning in prose and still misled, so the mark travels with the number here.

*A degenerate arm is marked too.* An arm that flags everything has perfect
recall and has found nothing, and its recall must never be read as a result.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Studies read from here have already been scored. Nothing in this module
#: computes a metric: it formats what a run recorded, and a number this file
#: cannot find is a number it leaves blank rather than derives.
ARM_ORDER = ("scanner", "trained", "llm", "merged")


@dataclass(frozen=True)
class Loaded:
    """One study file, with where it came from."""

    path: Path
    body: dict[str, Any]

    @property
    def epoch(self) -> dict[str, Any]:
        return self.body.get("epoch") or {}

    @property
    def label(self) -> str:
        return str(self.epoch.get("label") or "unlabelled")


def load(directory: Path) -> list[Loaded]:
    """Every detection study under a directory, oldest epoch first.

    A file that is not a detection study is skipped rather than guessed at:
    the same directory holds heal reports and label files, and a formatter that
    tried to read one as the other would put a number in a table that means
    something else.
    """
    found: list[Loaded] = []
    for path in sorted(directory.rglob("*.json")):
        try:
            body = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(body, dict) and "arms" in body and "epoch" in body:
            found.append(Loaded(path=path, body=body))
    return sorted(found, key=lambda one: str(one.epoch.get("at") or ""))


def _number(value: Any, places: int = 3) -> str:
    """A figure as a reader should see it, or the fact that nobody reported one.

    "not reported" rather than a zero or a dash, because those two are
    different facts and the cost column is exactly where they get confused: a
    free tier is charged nothing and an arm that makes no API call spends
    nothing, and neither of those is a price nobody published.
    """
    if value is None:
        return "not reported"
    if isinstance(value, bool) or not isinstance(value, int | float):
        return str(value)
    return f"{value:.{places}f}" if places else f"{round(value):,}"


def _marks(arm: dict[str, Any]) -> str:
    """What a reader has to know before quoting this row."""
    notes = []
    if arm.get("failures"):
        notes.append("incomplete")
    if arm.get("degenerate"):
        notes.append("degenerate")
    return " ".join(f"**{note}**" for note in notes)


def _ordered(arms: list[dict[str, Any]]) -> list[dict[str, Any]]:
    known = {name: index for index, name in enumerate(ARM_ORDER)}
    return sorted(arms, key=lambda arm: known.get(arm.get("arm", ""), len(known)))


def provenance(studies: list[Loaded]) -> str:
    """Every epoch in one place, so a number can be chased to its run."""
    lines = [
        "## Provenance",
        "",
        "Every table below names its epoch. This is where an epoch names its run.",
        "",
        "| epoch | when | commit | target | slice | file |",
        "|---|---|---|---|---|---|",
    ]
    for study in studies:
        epoch = study.epoch
        when = str(epoch.get("at") or "")[:10]
        lines.append(
            f"| `{study.label}` | {when} | `{epoch.get('commit') or 'unrecorded'}` "
            f"| {study.body.get('target', '')} | {epoch.get('note') or ''} "
            f"| `{study.path.name}` |"
        )
    return "\n".join(lines)


def arms_table(study: Loaded) -> str:
    """One epoch's arms, as the comparison the study exists to make."""
    epoch = study.epoch
    lines = [
        f"### {study.label}",
        "",
        f"{study.body.get('target', '')}, {epoch.get('note') or ''}, "
        f"{study.body.get('groundTruthCount', 0)} real weaknesses. "
        f"Commit `{epoch.get('commit') or 'unrecorded'}`.",
        "",
        "| arm | model | precision | recall | macro F1 | findings | refused "
        "| flagged | seconds | tokens | cost | offline | |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for arm in _ordered(study.body.get("arms") or []):
        detection = arm.get("detection") or {}
        fraction = arm.get("flaggedFraction")
        tokens = (arm.get("promptTokens") or 0) + (arm.get("completionTokens") or 0)
        lines.append(
            f"| {arm.get('arm', '')} | `{arm.get('modelId', '')}` "
            f"| {_number(detection.get('precision'))} | {_number(detection.get('recall'))} "
            f"| {_number(arm.get('macroF1'))} | {arm.get('found', 0):,} "
            f"| {arm.get('refused', 0)} "
            f"| {'n/a' if fraction is None else f'{fraction:.0%}'} "
            f"| {_number(arm.get('durationSeconds'), 0)} | {tokens:,} "
            f"| {_number(arm.get('costUsd'), 4)} "
            f"| {'yes' if arm.get('offline') else 'no'} | {_marks(arm)} |"
        )
    incomplete = [arm for arm in (study.body.get("arms") or []) if arm.get("failures")]
    if incomplete:
        lines += ["", "Marked **incomplete**, and the mark is the point:"]
        for arm in incomplete:
            first = str(arm["failures"][-1])[:160]
            lines.append(f"- `{arm.get('arm')}` did not finish its pass. {first}")
    degenerate = [arm for arm in (study.body.get("arms") or []) if arm.get("degenerate")]
    for arm in degenerate:
        lines += [
            "",
            f"Marked **degenerate**: `{arm.get('arm')}` flagged "
            f"{arm.get('found', 0):,} of the {arm.get('unitsExamined', 0):,} units it examined. "
            "Its recall is an artefact of that and is not a result.",
        ]
    return "\n".join(lines)


def per_class_table(study: Loaded) -> str:
    """Every arm's per weakness class scores for one epoch, side by side.

    Side by side rather than one table per arm, because the question a reader
    has is which arm to use for which class, and that is unanswerable from
    three tables on three pages.
    """
    arms = _ordered([arm for arm in (study.body.get("arms") or []) if arm.get("perClass")])
    if not arms:
        return ""
    classes: dict[str, int] = {}
    for arm in arms:
        for row in arm["perClass"]:
            classes[row["cwe"]] = max(classes.get(row["cwe"], 0), int(row.get("support") or 0))

    names = [arm.get("arm", "") for arm in arms]
    lines = [
        f"#### {study.label}: F1 by weakness class",
        "",
        "| CWE | support | " + " | ".join(names) + " |",
        "|---|---|" + "---|" * len(names),
    ]
    for cwe, support in sorted(classes.items(), key=lambda pair: (-pair[1], pair[0])):
        cells = []
        for arm in arms:
            row = next((one for one in arm["perClass"] if one["cwe"] == cwe), None)
            cells.append(_number(row.get("f1")) if row else "not scored")
        lines.append(f"| {cwe} | {support} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def build(directory: Path) -> str:
    """Every table, from every study under a directory."""
    studies = load(directory)
    if not studies:
        return f"No detection studies under {directory}."
    parts = [
        "# Detection tables",
        "",
        "Generated from the stored runs by `python -m c3.eval --tables`. "
        "Every number here is in a file beside it; nothing is computed on the way out.",
        "",
        provenance(studies),
        "",
        "## The arms, by epoch",
        "",
        "One table per epoch. Numbers from two epochs are never put in one table, "
        "because a rule, a model or a corpus changed between them.",
        "",
    ]
    for study in studies:
        parts += [arms_table(study), ""]
    parts += ["## By weakness class", ""]
    for study in studies:
        table = per_class_table(study)
        if table:
            parts += [table, ""]
    return "\n".join(parts).rstrip() + "\n"
