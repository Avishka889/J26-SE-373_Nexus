"""Table 6, latency: how long an update's assessment took, against NFR1's 30 seconds.

    uv run python -m c4.eval.latency --votes studies/votes/NAME.json --out studies/epochs

Read from a votes record, where each signal's time was kept as it ran:

- **the changelog step**: the model call's own duration, retries included, when
  the model was asked; nothing when the signal abstained before asking;
- **the usage step**: the impact stage for that update, charged its whole index
  build and API diff, which is the cautious reading of the budget.

An assessment is the two together (arbitration is a comparison of three values
and is not timed). Retrieval, fetching release notes and registry answers, is
not in a votes record and is not claimed here: NFR1 bounds the assessment, and a
slow registry is not the engine being slow.

The table gives the median, the 95th percentile and the maximum, how many
assessments stayed within the budget, and which did not.
"""

import argparse
import json
import math
import sys
from pathlib import Path

BUDGET_SECONDS = 30.0


def _percentile(values: list[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


def per_case(votes: dict[str, dict]) -> list[dict]:
    rows = []
    for case_id, entry in sorted(votes.items()):
        changelog = entry.get("changelog") or {}
        model = changelog.get("model") or {}
        usage = entry.get("usage") or {}
        changelog_seconds = float(model.get("durationSeconds") or 0.0)
        usage_seconds = float(usage.get("seconds") or 0.0)
        rows.append(
            {
                "caseId": case_id,
                "changelogSeconds": changelog_seconds,
                "modelAsked": bool(model),
                "usageSeconds": usage_seconds,
                "assessmentSeconds": round(changelog_seconds + usage_seconds, 3),
            }
        )
    return rows


def latency(votes: dict[str, dict], *, budget: float = BUDGET_SECONDS) -> dict:
    rows = per_case(votes)
    seconds = [row["assessmentSeconds"] for row in rows]
    over = [row for row in rows if row["assessmentSeconds"] > budget]
    return {
        "budgetSeconds": budget,
        "cases": len(rows),
        "p50": _percentile(seconds, 0.5),
        "p95": _percentile(seconds, 0.95),
        "max": max(seconds) if seconds else None,
        "withinBudget": len(rows) - len(over),
        "over": [
            {
                "caseId": row["caseId"],
                "assessmentSeconds": row["assessmentSeconds"],
                "changelogSeconds": row["changelogSeconds"],
                "usageSeconds": row["usageSeconds"],
            }
            for row in over
        ],
        "perCase": rows,
    }


def _seconds(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f} s"


def render(record: dict) -> str:
    header = record.get("study") or {}
    lines = [
        f"### {header.get('label', 'Table 6, latency')}, {header.get('date', '')}",
        "",
        f"From the votes recorded {header.get('votesRecordedOn', '')} (`{header.get('votes', '')}`), "
        f"{record['cases']} assessments against NFR1's {record['budgetSeconds']:.0f} s. "
        "Retrieval is not in a votes record and not claimed.",
        "",
        "| median | 95th percentile | maximum | within budget |",
        "|---|---|---|---|",
        f"| {_seconds(record['p50'])} | {_seconds(record['p95'])} | {_seconds(record['max'])} | "
        f"{record['withinBudget']} of {record['cases']} |",
    ]
    if record["over"]:
        lines += [
            "",
            "Over budget:",
            "",
            "| case | assessment | changelog step | usage step |",
            "|---|---|---|---|",
        ]
        for row in record["over"]:
            lines.append(
                f"| {row['caseId']} | {_seconds(row['assessmentSeconds'])} | "
                f"{_seconds(row['changelogSeconds'])} | {_seconds(row['usageSeconds'])} |"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    from datetime import date

    parser = argparse.ArgumentParser(
        prog="python -m c4.eval.latency",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--votes", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    recorded = json.loads(args.votes.read_text())
    record = {
        "study": {
            "label": "Table 6, latency",
            "date": date.today().isoformat(),
            "votes": args.votes.name,
            "votesRecordedOn": recorded.get("recordedOn"),
        },
        **latency(recorded["votes"]),
    }
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        target = args.out / f"table-6-latency-{args.votes.stem}.json"
        target.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    print(render(record))
    return 0


if __name__ == "__main__":
    sys.exit(main())
