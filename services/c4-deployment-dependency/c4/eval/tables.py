"""The dissertation's tables, regenerated from the study records that produced them.

C3's three rules, kept: one table per epoch and never a pooled one; a
degenerate arm marked wherever it appears; and nothing computed here, only
formatted, so a table cannot disagree with the record it was built from.
"""

import json
from pathlib import Path


def _number(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def render(study: dict) -> str:
    epoch = study["epoch"]
    lines = [
        f"### {epoch['label']}, {epoch['date']}",
        "",
        (
            f"Commit `{epoch['commit']}`, corpus `{epoch['corpusSha256'][:12]}`, rubric "
            f"`{epoch['rubric']}`, split `{epoch['split']}`"
            f"{' (the final evaluation)' if epoch.get('final') else ''}. "
            f"{epoch['cases']} cases, {epoch['labelled']} labelled, {epoch['excluded']} excluded; "
            f"by source {epoch['bySource']}, by ecosystem {epoch['byEcosystem']}."
        ),
        *_made_under(epoch),
        "",
        "| arm | accuracy | macro precision | macro recall | macro F1 | High recall | missed High | abstained |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, arm in study["arms"].items():
        lines.append(
            f"| {_label(name, arm)} | {_number(arm['accuracy'])} | "
            f"{_number(arm['macro_precision'])} | {_number(arm['macro_recall'])} | "
            f"{_number(arm['macro_f1'])} | {_number(arm['high_recall'])} | "
            f"{arm['missed_high']} | {arm['abstained']} |"
        )
    if any("intervals" in arm for arm in study["arms"].values()):
        bootstrap = epoch.get("bootstrap") or {}
        lines += [
            "",
            f"Uncertainty: 95 percent bootstrap intervals ({bootstrap.get('resamples')} "
            f"resamples, seed {bootstrap.get('seed')}), and McNemar's exact test against the "
            "SemVer baseline on the same cases.",
            "",
            "| arm | accuracy | High recall | macro F1 | only this right | only SemVer right | p |",
            "|---|---|---|---|---|---|---|",
        ]
        for name, arm in study["arms"].items():
            intervals = arm.get("intervals") or {}
            versus = arm.get("versusSemver") or {}
            lines.append(
                f"| {_label(name, arm)} | {_interval(intervals.get('accuracy'))} | "
                f"{_interval(intervals.get('highRecall'))} | {_interval(intervals.get('macroF1'))} | "
                f"{versus.get('onlyFirst', '')} | {versus.get('onlySecond', '')} | "
                f"{_number(versus['pValue']) if 'pValue' in versus else ''} |"
            )
    by_ecosystem = study.get("byEcosystem") or {}
    if by_ecosystem:
        lines += [
            "",
            "By ecosystem:",
            "",
            "| arm | ecosystem | cases | accuracy | High recall | missed High | abstained |",
            "|---|---|---|---|---|---|---|",
        ]
        for name, arm in study["arms"].items():
            for ecosystem, arms in by_ecosystem.items():
                scored = arms[name]
                lines.append(
                    f"| {_label(name, arm)} | {ecosystem} | {scored['cases']} | "
                    f"{_number(scored['accuracy'])} | {_number(scored['high_recall'])} | "
                    f"{scored['missed_high']} | {scored['abstained']} |"
                )
    for name, arm in study["arms"].items():
        if arm.get("degenerate"):
            continue
        lines += [
            "",
            f"Confusion, {name} (rows are the observed level):",
            "",
            "| observed | predicted low | predicted medium | predicted high |",
            "|---|---|---|---|",
        ]
        for truth in ("low", "medium", "high"):
            row = arm["confusion"][truth]
            lines.append(f"| {truth} | {row['low']} | {row['medium']} | {row['high']} |")
    return "\n".join(lines) + "\n"


def _interval(value) -> str:
    return "n/a" if not value else f"{value[0]:.2f} to {value[1]:.2f}"


def _label(name: str, arm: dict) -> str:
    if arm.get("degenerate"):
        return f"{name} (degenerate)"
    if arm.get("informational"):
        return f"{name} (informational)"
    if arm.get("exploratory"):
        return f"{name} (exploratory)"
    return name


def _made_under(epoch: dict) -> list[str]:
    """The line naming the votes an arm was read from: the rules, and the model if one ran."""
    made = epoch.get("votes")
    if not made:
        return []
    line = f"Votes recorded {made.get('recordedOn')}; rules {', '.join(made['rules'])}."
    changelog = made.get("changelog")
    if changelog:
        settings = changelog.get("settings") or {}
        line += (
            f" Changelog signal: model `{changelog['model']}`, prompt `{changelog['promptId']}` "
            f"(`{changelog['promptSha256'][:12]}`), max tokens {settings.get('maxTokens')}, "
            f"thinking {settings.get('thinking')}, temperature {settings.get('temperature')}; "
            f"run at `{changelog.get('commit')}` on {changelog.get('recordedOn')}."
        )
    return ["", line]


def render_directory(directory: Path) -> str:
    """Every record under a directory, one table each: the epochs oldest first, then the rest.

    The directory holds more than epochs. Table 6's first part is rendered by its
    own study; a record another module owns, such as Table 7 (the orchestrator's
    monitoring study), is named with the command that prints it, rather than
    guessed at here.
    """
    from .pipeline_study import render_table as render_validity

    records = [(path, json.loads(path.read_text())) for path in sorted(directory.glob("*.json"))]
    epochs = [record for _, record in records if "epoch" in record]
    epochs.sort(key=lambda study: (study["epoch"]["date"], study["epoch"]["label"]))
    parts = [render(study) for study in epochs]
    for path, record in records:
        if "epoch" in record:
            continue
        label = (record.get("study") or {}).get("label", "")
        if label.startswith("Table 5"):
            from .impact_table import render_table5

            parts.append(render_table5(record))
        elif label.startswith("Table 6, part one"):
            parts.append(render_validity(record))
        elif label.startswith("Table 6, latency"):
            from .latency import render as render_latency

            parts.append(render_latency(record))
        elif label.startswith(("Table 7", "Table 6, releases")):
            owner = "table7" if label.startswith("Table 7") else "table6"
            parts.append(
                f"### {label}\n\nRecorded in `{path.name}`; printed by "
                f"`uv run python -m orchestrator.deploy.{owner}`, which owns it.\n"
            )
        else:
            parts.append(f"### {path.name}\n\nNot a record this module knows how to print.\n")
    return "\n".join(parts)
