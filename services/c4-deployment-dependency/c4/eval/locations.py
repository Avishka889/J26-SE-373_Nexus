"""Where each BUMP break pointed: the compiler's files and lines, from BUMP's own reproduction.

    uv run python -m c4.eval.locations --cases studies/cases/corpus [--limit 5]

Table 5 compares the files the impact analysis named with the files a break
really touched. For a BUMP compilation failure those are the files `javac`
reported, and BUMP publishes an image per break that reproduces it. This runs
that image, one case at a time, never the dataset's whole bundle:

1. pull the case's breaking image;
2. run it as BUMP's own reproduction command does, and keep its output;
3. read the compiler's errors from it (`bump.failure_locations`), relative to
   the image's working directory, so the paths are the project's own;
4. write them into the case, with the log's hash and last lines on the step;
5. remove the image, unless asked to keep it.

Only compilation failures (`COMPILATION_FAILURE`, `WERROR_FAILURE`) are read: a
test failure's location is a stack trace, not a compiler error, and is not
guessed at. A case that already has locations is skipped, so an interrupted run
resumes. A run whose output names no compiler error is reported and leaves the
case as it was.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable
from datetime import date
from pathlib import Path

from .cases import LabelledCase
from .loaders.bump import failure_locations

COMPILER_CATEGORIES = frozenset({"COMPILATION_FAILURE", "WERROR_FAILURE"})

#: A BUMP build can download what its image did not carry; generous, not endless.
RUN_TIMEOUT_SECONDS = 1800

Run = Callable[[list[str], float], tuple[int, str]]


def _run(command: list[str], timeout: float) -> tuple[int, str]:
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired as error:
        # What was captured before the timeout comes back as bytes, whatever `text` said.
        partial = error.stdout or b""
        text = partial.decode(errors="replace") if isinstance(partial, bytes) else partial
        return 124, text + f"\ntimed out after {timeout:.0f}s"
    return done.returncode, done.stdout + done.stderr


def wanted(case: LabelledCase) -> bool:
    return (
        case.source == "bump"
        and case.observed.failure_category in COMPILER_CATEGORIES
        and not case.observed.failure_locations
        and bool(case.client.image)
    )


def locate(case: LabelledCase, *, run: Run = _run, keep_image: bool = False) -> LabelledCase | None:
    """The case with its failure locations, or None when the run named no compiler error."""
    image = case.client.image
    code, output = run(["docker", "pull", "-q", image], 1800)
    if code != 0:
        raise RuntimeError(f"docker pull {image} failed: {output.strip()[-500:]}")
    try:
        code, workdir = run(
            ["docker", "image", "inspect", "--format", "{{.Config.WorkingDir}}", image], 60
        )
        if code != 0 or not workdir.strip():
            raise RuntimeError(f"{image} names no working directory: {workdir.strip()[-300:]}")
        _, log = run(["docker", "run", "--rm", image], RUN_TIMEOUT_SECONDS)
    finally:
        if not keep_image:
            run(["docker", "rmi", "-f", image], 300)
    found = failure_locations(log, workdir=workdir.strip())
    if not found:
        return None
    candidate = [
        step.model_copy(
            update={
                "log_sha256": hashlib.sha256(log.encode()).hexdigest(),
                "tail": "\n".join(log.strip().splitlines()[-20:]),
            }
        )
        for step in case.observed.candidate
    ]
    return case.model_copy(
        update={
            "observed": case.observed.model_copy(
                update={"failure_locations": found, "candidate": candidate}
            ),
            "provenance": (
                f"{case.provenance}; failure locations read from running {image} on "
                f"{date.today().isoformat()}"
            ),
        }
    )


def run_over(
    cases_dir: Path, *, limit: int | None, run: Run = _run, keep_image: bool = False, log=print
) -> dict[str, int]:
    counts = {"located": 0, "no-compiler-error": 0, "failed": 0}
    todo = []
    for path in sorted(cases_dir.glob("*.json")):
        case = LabelledCase.model_validate(json.loads(path.read_text()))
        if wanted(case):
            todo.append((path, case))
    for path, case in todo[:limit] if limit else todo:
        log(f"  {case.case_id}: {case.client.image}", flush=True)
        try:
            located = locate(case, run=run, keep_image=keep_image)
        except Exception as error:  # one image cannot stop the rest
            counts["failed"] += 1
            log(f"    failed: {error}", flush=True)
            continue
        if located is None:
            counts["no-compiler-error"] += 1
            log("    the run named no compiler error; left as it was", flush=True)
            continue
        body = json.dumps(located.model_dump(by_alias=True, mode="json"), indent=2, sort_keys=True)
        path.write_text(body + "\n")
        counts["located"] += 1
        log(f"    {len(located.observed.failure_locations)} location(s)", flush=True)
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m c4.eval.locations",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--keep-images", action="store_true")
    args = parser.parse_args(argv)
    counts = run_over(args.cases, limit=args.limit, keep_image=args.keep_images)
    print(", ".join(f"{name} {count}" for name, count in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
