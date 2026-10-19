"""The explanation rubric (proposal 3.4.5): model written explanations, rated by people.

    uv run --env-file .env python -m c4.eval.explanations explain --cases DIR \
        --votes studies/votes/NAME.json --out DIR [--size 26]
    uv run python -m c4.eval.explanations sample --reports DIR --out sheet.csv [--size 20]
    uv run python -m c4.eval.explanations score --sheets a.csv b.csv --out studies/epochs

**The explanations** are asked of real assessments. `explain` picks cases from a
votes record, stratified the same way, rebuilds each one's assessment from the
whole changelog and impact reports the votes were recorded from (kept outside
the repository), and asks the product's explanation model, which spends one call
per case. A few more are asked than are rated, because the product's own check
refuses an explanation that names another level or quotes what the evidence
does not hold, and a refused one is rule written and not rated.

An explanation can agree with its level and still be no use to a developer, so a
sample is rated 1 to 5 for correctness, relevance and clarity.

**The sample.** Only explanations a model wrote are rated: a rule written
summary is a template, and rating it rates the template. They are drawn from a
directory of risk reports, stratified by final level and by whether the signals
disagreed, one from each stratum in turn, each stratum in a fixed hash order of
its update keys, so the sample is the same every time and nobody picks it.

**The sheet** gives each rater what the developer would see: the update, its
final level and how the level was decided, every signal's vote and the evidence
it rests on, and the explanation. It leaves the three scores and a rater code
to fill.

**No identity is stored.** A rater writes a code such as `R1`, and a sheet whose
rater column holds anything else is refused, so a name or an address cannot
reach the record by accident. Who holds which code is kept by nobody here.

**The scores**: per criterion the mean, the median and the share rated 4 or
more, overall and by final level; and where two raters rated the same item,
how often they gave the same score and how often they were within one.
"""

import argparse
import csv
import hashlib
import json
import re
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path

from sdlc_contracts import RiskReport, UpdateAssessment, safety_first

from .loaders.crossings import selection_order

CRITERIA = ("correctness", "relevance", "clarity")
SAMPLE_SIZE = 20
RATER = re.compile(r"^R[0-9]{1,3}$")

COLUMNS = (
    "item",
    "report",
    "update",
    "finalLevel",
    "decidedBy",
    "advisory",
    "votes",
    "explanation",
    *CRITERIA,
    "rater",
    "comment",
)


@dataclass(frozen=True)
class Candidate:
    report: str
    assessment: UpdateAssessment

    @property
    def disagreement(self) -> bool:
        levels = {vote.level for vote in self.assessment.votes if vote.level is not None}
        return len(levels) > 1

    @property
    def stratum(self) -> tuple[str, bool]:
        return self.assessment.arbitration.final, self.disagreement


def candidates(reports: Path) -> list[Candidate]:
    """Every assessment whose explanation a model wrote and the check kept."""
    found = []
    for path in sorted(reports.glob("*.json")):
        report = RiskReport.model_validate(json.loads(path.read_text()))
        for assessment in report.assessments:
            if assessment.explanation_source == "model" and assessment.explanation.strip():
                found.append(Candidate(path.name, assessment))
    return found


def sample(found: list[Candidate], size: int = SAMPLE_SIZE) -> list[Candidate]:
    """One from each stratum in turn, each stratum in its fixed order, up to `size`."""
    strata: dict[tuple[str, bool], list[Candidate]] = {}
    for candidate in sorted(found, key=lambda c: selection_order(c.assessment.key)):
        strata.setdefault(candidate.stratum, []).append(candidate)
    order = sorted(strata, key=lambda s: (("low", "medium", "high").index(s[0]), s[1]))
    chosen: list[Candidate] = []
    while len(chosen) < size and any(strata[s] for s in order):
        for stratum in order:
            if strata[stratum] and len(chosen) < size:
                chosen.append(strata[stratum].pop(0))
    return chosen


def _level(entry: dict, signal: str):
    value = entry.get(signal)
    return value.get("level") if isinstance(value, dict) else value


def stratum_of(entry: dict) -> tuple[str, bool]:
    """A recorded case's final level by the product's rule, and whether its signals disagreed."""
    levels = {signal: _level(entry, signal) for signal in ("semver", "changelog", "usage")}
    voted = {level for level in levels.values() if level is not None}
    return safety_first(levels)[0], len(voted) > 1


def choose(votes: dict[str, dict], size: int) -> list[str]:
    """Case ids from a votes record, one from each stratum in turn, each in a fixed hash order."""
    strata: dict[tuple[str, bool], list[str]] = {}
    for case_id in sorted(votes, key=selection_order):
        strata.setdefault(stratum_of(votes[case_id]), []).append(case_id)
    order = sorted(strata, key=lambda s: (("low", "medium", "high").index(s[0]), s[1]))
    chosen: list[str] = []
    while len(chosen) < size and any(strata[s] for s in order):
        for stratum in order:
            if strata[stratum] and len(chosen) < size:
                chosen.append(strata[stratum].pop(0))
    return chosen


async def explained(
    case_ids: list[str], cases_dir: Path, studies: Path, reports: Path, *, model: str
) -> dict[str, RiskReport]:
    """Each chosen case's real assessment, rebuilt from the kept reports, then explained.

    One report per case: two cases can share an update on different clients, where
    the usage evidence differs, and a report assesses an update once.
    """
    from datetime import UTC, datetime

    from sdlc_contracts import ChangelogReport, ImpactReport

    from ..risk.assess import assess
    from ..risk.explain import explain
    from .__main__ import load_cases
    from .votes import client_for, update_for

    by_id = {case.case_id: case for case in load_cases(cases_dir)}
    changelog = ChangelogReport.model_validate_json((reports / "changelog-report.json").read_text())
    explained_by_case: dict[str, RiskReport] = {}
    for case_id in case_ids:
        case = by_id[case_id]
        update = update_for(case, client_for(case, studies).files)
        impact_path = reports / f"{case_id}.impact.json"
        impact = (
            ImpactReport.model_validate_json(impact_path.read_text())
            if impact_path.exists()
            else None
        )
        risk = RiskReport(
            version=1,
            generated_at=datetime.now(UTC),
            assessments=[assess(update, changelog, impact)],
        )
        explained_by_case[case_id] = await explain(risk, model=model)
    return explained_by_case


def spend(reports: list[RiskReport]) -> dict[str, int]:
    """What the explanations cost, read from each call's record, retries included."""
    assessments = [assessment for report in reports for assessment in report.assessments]
    calls = [a.explanation_call for a in assessments if a.explanation_call is not None]
    return {
        "calls": len(calls),
        "requests": sum(call.requests for call in calls),
        "promptTokens": sum(call.prompt_tokens for call in calls),
        "completionTokens": sum(call.completion_tokens for call in calls),
        "keptByTheCheck": sum(a.explanation_source == "model" for a in assessments),
        "withDashesReplaced": sum(a.explanation_dashes_replaced > 0 for a in assessments),
    }


def _votes(assessment: UpdateAssessment) -> str:
    return " | ".join(
        f"{vote.signal}: {vote.level or 'abstained'}: {vote.rationale}" for vote in assessment.votes
    )


def write_sheet(chosen: list[Candidate], out: Path) -> None:
    with out.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for number, candidate in enumerate(chosen, start=1):
            assessment = candidate.assessment
            writer.writerow(
                {
                    "item": number,
                    "report": candidate.report,
                    "update": assessment.key,
                    "finalLevel": assessment.arbitration.final,
                    "decidedBy": ", ".join(assessment.arbitration.decided_by),
                    "advisory": assessment.arbitration.advisory,
                    "votes": _votes(assessment),
                    "explanation": assessment.explanation,
                    **dict.fromkeys(CRITERIA, ""),
                    "rater": "",
                    "comment": "",
                }
            )


class SheetRefused(ValueError):
    """A filled sheet that cannot be scored as it is, and why."""


def read_sheet(path: Path) -> list[dict]:
    rows = []
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            rater = (row.get("rater") or "").strip()
            if not RATER.match(rater):
                raise SheetRefused(
                    f"{path.name} item {row.get('item')}: the rater column must hold a code "
                    "such as R1, never a name"
                )
            scores = {}
            for criterion in CRITERIA:
                raw = (row.get(criterion) or "").strip()
                if not raw.isdigit() or not 1 <= int(raw) <= 5:
                    raise SheetRefused(
                        f"{path.name} item {row.get('item')}: {criterion} must be 1 to 5, "
                        f"not {raw!r}"
                    )
                scores[criterion] = int(raw)
            rows.append(
                {
                    "item": int(row["item"]),
                    "update": row["update"],
                    "finalLevel": row["finalLevel"],
                    "rater": rater,
                    **scores,
                }
            )
    return rows


def _summary(values: list[int]) -> dict:
    return {
        "n": len(values),
        "mean": statistics.fmean(values) if values else None,
        "median": statistics.median(values) if values else None,
        "fourOrMore": sum(value >= 4 for value in values) / len(values) if values else None,
    }


def agreement(rows: list[dict]) -> dict[str, dict]:
    """For items two raters scored: how often they agreed exactly, and within one point."""
    by_item: dict[str, list[dict]] = {}
    for row in rows:
        by_item.setdefault(row["update"], []).append(row)
    pairs = [
        (first, second)
        for ratings in by_item.values()
        for index, first in enumerate(ratings)
        for second in ratings[index + 1 :]
        if first["rater"] != second["rater"]
    ]
    result = {}
    for criterion in CRITERIA:
        differences = [abs(a[criterion] - b[criterion]) for a, b in pairs]
        result[criterion] = {
            "pairs": len(differences),
            "exact": sum(d == 0 for d in differences) / len(differences) if differences else None,
            "withinOne": (
                sum(d <= 1 for d in differences) / len(differences) if differences else None
            ),
        }
    return result


def score(rows: list[dict]) -> dict:
    levels = sorted({row["finalLevel"] for row in rows})
    return {
        "ratings": len(rows),
        "raters": len({row["rater"] for row in rows}),
        "items": len({row["update"] for row in rows}),
        "overall": {c: _summary([row[c] for row in rows]) for c in CRITERIA},
        "byLevel": {
            level: {
                c: _summary([row[c] for row in rows if row["finalLevel"] == level])
                for c in CRITERIA
            }
            for level in levels
        },
        "agreement": agreement(rows),
    }


def _number(value) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def render(record: dict) -> str:
    header = record["study"]
    lines = [
        f"### {header['label']}, {header['date']}",
        "",
        f"{record['ratings']} ratings of {record['items']} explanations by {record['raters']} "
        "rater(s), each 1 to 5.",
        "",
        "| criterion | mean | median | rated 4 or more | exact agreement | within one |",
        "|---|---|---|---|---|---|",
    ]
    for criterion in CRITERIA:
        overall = record["overall"][criterion]
        agreed = record["agreement"][criterion]
        lines.append(
            f"| {criterion} | {_number(overall['mean'])} | {_number(overall['median'])} | "
            f"{_number(overall['fourOrMore'])} | {_number(agreed['exact'])} | "
            f"{_number(agreed['withinOne'])} |"
        )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    from datetime import date

    parser = argparse.ArgumentParser(
        prog="python -m c4.eval.explanations",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    asked = commands.add_parser("explain")
    asked.add_argument("--cases", type=Path, required=True)
    asked.add_argument("--votes", type=Path, required=True)
    asked.add_argument("--studies", type=Path, default=Path("studies"))
    asked.add_argument("--reports", type=Path, default=None)
    asked.add_argument("--size", type=int, default=SAMPLE_SIZE + 6)
    asked.add_argument("--out", type=Path, required=True)
    drawn = commands.add_parser("sample")
    drawn.add_argument("--reports", type=Path, required=True)
    drawn.add_argument("--out", type=Path, required=True)
    drawn.add_argument("--size", type=int, default=SAMPLE_SIZE)
    scored = commands.add_parser("score")
    scored.add_argument("--sheets", type=Path, nargs="+", required=True)
    scored.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if args.command == "explain":
        import asyncio

        from .changelog_pass import MODEL
        from .votes import REPORTS

        recorded = json.loads(args.votes.read_text())
        chosen = choose(recorded["votes"], args.size)
        report = asyncio.run(
            explained(
                chosen,
                args.cases,
                args.studies,
                args.reports or REPORTS / args.votes.stem.removesuffix("-changelog"),
                model=MODEL,
            )
        )
        args.out.mkdir(parents=True, exist_ok=True)
        for case_id, explained_report in report.items():
            (args.out / f"{case_id}.json").write_text(
                explained_report.model_dump_json(by_alias=True, indent=2) + "\n"
            )
        spent = spend(list(report.values()))
        print(
            f"{len(chosen)} asked, {spent['keptByTheCheck']} kept by the check, into {args.out}\n"
            f"{spent['requests']} requests, {spent['promptTokens']} tokens in, "
            f"{spent['completionTokens']} out; dashes replaced in {spent['withDashesReplaced']}"
        )
        return 0
    if args.command == "sample":
        found = candidates(args.reports)
        chosen = sample(found, args.size)
        write_sheet(chosen, args.out)
        print(f"{len(chosen)} of {len(found)} model written explanations, into {args.out}")
        return 0
    try:
        rows = [row for sheet in args.sheets for row in read_sheet(sheet)]
    except SheetRefused as refused:
        print(f"refused: {refused}", file=sys.stderr)
        return 2
    record = {
        "study": {
            "label": "The explanation rubric",
            "date": date.today().isoformat(),
            "sheets": {
                sheet.name: hashlib.sha256(sheet.read_bytes()).hexdigest() for sheet in args.sheets
            },
        },
        **score(rows),
    }
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "explanation-rubric.json").write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n"
        )
    print(render(record))
    return 0


if __name__ == "__main__":
    sys.exit(main())
