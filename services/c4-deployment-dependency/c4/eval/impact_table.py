"""Table 5: did the impact analysis name the files and components a break really touched?

    uv run python -m c4.eval.impact_table --votes studies/votes/NAME.json --out studies/epochs

The truth is where an observed break pointed: a case's failure locations, from
the compiler in BUMP's own reproduction (`c4.eval.locations`). The prediction is
what the usage signal's impact analysis named as affected: its files, and its
components. Both are read from a votes record, where the truth's files were
mapped to components by the same function the analysis maps its own with, so
like is compared with like.

- Per case: true positives, false positives and false negatives, over files and
  over components.
- Micro precision, recall and F1 over the summed counts, and macro F1 as the
  mean of the per case F1s.
- **Never pooled.** Files and components are separate rows, and components are
  reported per granularity: a Maven module is not a graph node.

A case whose analysis named nothing (it abstained, or found no use) still
counts: everything it missed is a false negative. Only cases with known failure
locations are read, and the table says how many that is.
"""

import argparse
import json
import sys
from pathlib import Path


def counts(truth: set[str], predicted: set[str]) -> dict[str, int]:
    return {
        "tp": len(truth & predicted),
        "fp": len(predicted - truth),
        "fn": len(truth - predicted),
    }


def _ratio(top: int, bottom: int) -> float | None:
    return top / bottom if bottom else None


def scores(tally: dict[str, int]) -> dict[str, float | None]:
    precision = _ratio(tally["tp"], tally["tp"] + tally["fp"])
    recall = _ratio(tally["tp"], tally["tp"] + tally["fn"])
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall
        else (0.0 if precision is not None or recall is not None else None)
    )
    return {"precision": precision, "recall": recall, "f1": f1}


def aggregate(tallies: list[dict[str, int]]) -> dict:
    summed = {key: sum(t[key] for t in tallies) for key in ("tp", "fp", "fn")}
    per_case = [scores(t)["f1"] for t in tallies]
    defined = [value for value in per_case if value is not None]
    return {
        "cases": len(tallies),
        **summed,
        "micro": scores(summed),
        "macroF1": sum(defined) / len(defined) if defined else None,
    }


def table5(votes: dict[str, dict]) -> dict:
    """Every case with a known truth, scored over files and over components."""
    rows = []
    for case_id, entry in sorted(votes.items()):
        usage = entry.get("usage") or {}
        truth = usage.get("truth")
        if not truth:
            continue
        rows.append(
            {
                "caseId": case_id,
                "granularity": truth["granularity"],
                "abstained": usage.get("abstained") or "",
                "files": counts(set(truth["files"]), set(usage.get("affectedFiles") or [])),
                "components": (
                    counts(set(truth["components"]), set(usage.get("components") or []))
                    if truth["components"]
                    else None
                ),
            }
        )
    granularities = sorted({row["granularity"] for row in rows if row["components"]})
    return {
        "cases": rows,
        "files": aggregate([row["files"] for row in rows]),
        "components": {
            granularity: aggregate(
                [
                    row["components"]
                    for row in rows
                    if row["components"] and row["granularity"] == granularity
                ]
            )
            for granularity in granularities
        },
    }


def _number(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def render_table5(record: dict) -> str:
    header = record.get("study") or {}
    lines = [
        f"### {header.get('label', 'Table 5: impact analysis against failure locations')}, "
        f"{header.get('date', '')}",
        "",
        f"From the votes recorded {header.get('votesRecordedOn', '')} (`{header.get('votes', '')}`): "
        f"{len(record['cases'])} case(s) with known failure locations.",
        "",
        "| level | granularity | cases | TP | FP | FN | precision | recall | F1 | macro F1 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]

    def row(level: str, granularity: str, summary: dict) -> str:
        micro = summary["micro"]
        return (
            f"| {level} | {granularity} | {summary['cases']} | {summary['tp']} | {summary['fp']} | "
            f"{summary['fn']} | {_number(micro['precision'])} | {_number(micro['recall'])} | "
            f"{_number(micro['f1'])} | {_number(summary['macroF1'])} |"
        )

    lines.append(row("file", "file", record["files"]))
    for granularity, summary in record["components"].items():
        lines.append(row("component", granularity, summary))
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    from datetime import date

    parser = argparse.ArgumentParser(
        prog="python -m c4.eval.impact_table",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--votes", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    recorded = json.loads(args.votes.read_text())
    record = {
        "study": {
            "label": "Table 5: impact analysis against failure locations",
            "date": date.today().isoformat(),
            "votes": args.votes.name,
            "votesRecordedOn": recorded.get("recordedOn"),
        },
        **table5(recorded["votes"]),
    }
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        target = args.out / f"table-5-{args.votes.stem}.json"
        target.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(render_table5(record))
    return 0


if __name__ == "__main__":
    sys.exit(main())
