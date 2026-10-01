"""Run the study, or regenerate its tables.

    uv run python -m c4.eval --cases DIR --epoch "Epoch 1" --commit SHA --out studies/
    uv run python -m c4.eval --cases DIR --epoch "Final" --commit SHA --split held-out --final
    uv run python -m c4.eval --bump ~/.cache/sdlc-c4/bump --epoch "Epoch 1, BUMP" --commit SHA
    uv run python -m c4.eval --tables studies/

The cases are `LabelledCase` JSON files, one per case, or every record of a git
checkout of BUMP read through its loader (`--bump`). The study record is
written to `--out` named after the epoch, and the table is printed. `--tables`
regenerates every table from the records in a directory, which is the only way
a table in the write up should be produced.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from .cases import LabelledCase
from .loaders.bump import load_checkout
from .study import HeldOutRefused, VotesMissing, run, votes_header
from .tables import render, render_directory


def load_cases(directory: Path) -> list[LabelledCase]:
    return [
        LabelledCase.model_validate(json.loads(path.read_text()))
        for path in sorted(directory.glob("*.json"))
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m c4.eval", description=__doc__)
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--bump", type=Path, help="a git checkout of chains-project/bump")
    parser.add_argument("--epoch")
    parser.add_argument("--commit")
    parser.add_argument("--split", default="dev", choices=["dev", "held-out", "all"])
    parser.add_argument("--final", action="store_true")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--tables", type=Path)
    parser.add_argument(
        "--votes", type=Path, help="a votes record (python -m c4.eval.votes) to read arms from"
    )
    args = parser.parse_args(argv)

    if args.tables:
        print(render_directory(args.tables))
        return 0
    if not ((args.cases or args.bump) and args.epoch and args.commit):
        parser.error("--cases or --bump, --epoch and --commit are required to run a study")
    if args.cases and args.bump:
        parser.error("one corpus per study: --cases or --bump, not both")

    record = json.loads(args.votes.read_text()) if args.votes else None
    try:
        study = run(
            load_cases(args.cases) if args.cases else load_checkout(args.bump),
            epoch=args.epoch,
            commit=args.commit,
            split=args.split,
            final=args.final,
            votes=record["votes"] if record else None,
            votes_made=votes_header(record) if record else None,
        )
    except (HeldOutRefused, VotesMissing) as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return 2
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^a-z0-9]+", "-", args.epoch.lower()).strip("-")
        (args.out / f"{name}.json").write_text(json.dumps(study, indent=2, sort_keys=True) + "\n")
    print(render(study))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
