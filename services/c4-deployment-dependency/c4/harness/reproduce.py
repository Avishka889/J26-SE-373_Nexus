"""Observe what one update does to one project: a control run, then the same with the update.

Both runs start from the same files in a fresh container each. The control run
installs the project with the dependency pinned at the installed version; the
candidate run pins it at the target version. Everything else is identical, so
any difference between the two is the update's.

What comes back is exactly what a labelled case stores: each step's outcome for
both runs, and the warning or deprecation lines that appeared only with the
update and name the package. The rubric turns that into a level; nothing here
decides one.
"""

import re
from dataclasses import dataclass
from pathlib import Path

from ..eval.cases import ObservedStep
from .container import Lane, StepRun, StepSpec

_WARNING = re.compile(r"(deprecat|warn)", re.IGNORECASE)

#: What differs between two runs of the same line: a leading timestamp (depd
#: prints an RFC 1123 date, loggers an ISO one, Vite a time of day), node's
#: process id, and a duration. Without this, a deprecation both runs print
#: would count as new.
_VOLATILE = (
    (re.compile(r"^[A-Z][a-z]{2}, \d{2} [A-Z][a-z]{2} \d{4} \d{2}:\d{2}:\d{2} GMT\s+"), ""),
    (re.compile(r"^\[?\d{4}-\d{2}-\d{2}[T ][\d:.]+Z?\]?\s+"), ""),
    (re.compile(r"^\d{1,2}:\d{2}:\d{2}(?:\s?[AP]M)?\s+"), ""),
    (re.compile(r"\(node:\d+\)"), "(node)"),
    (re.compile(r"\b\d+(?:\.\d+)?\s?(?:ms|s)\b"), "<duration>"),
)


def normalise(line: str) -> str:
    """A line as it would read in any run: timestamps, process ids and durations removed."""
    text = line.strip()
    for pattern, replacement in _VOLATILE:
        text = pattern.sub(replacement, text)
    return text


#: Where the pin check sits inside the container, beside the project.
INSTALLED_SCRIPT = ".c4/installed.mjs"

#: What the pin check prints when a place resolves another version than pinned.
PIN_NOT_APPLIED = "C4-PIN-NOT-APPLIED"


class PinNotApplied(RuntimeError):
    """The install finished and the package is not at the pinned version.

    That is the harness failing, not the update, so it is raised rather than
    recorded: a run that did not test the version it names must stop the study.
    """


def installed_script() -> str:
    return (Path(__file__).parent / "installed.mjs").read_text()


@dataclass(frozen=True)
class Reproduction:
    baseline: list[ObservedStep]
    candidate: list[ObservedStep]
    warnings: list[str]


def observed(run: StepRun) -> ObservedStep:
    return ObservedStep(
        name=run.name,  # type: ignore[arg-type]
        command=run.command,
        exit_code=run.exit_code,
        outcome=run.outcome,  # type: ignore[arg-type]
        seconds=round(run.seconds, 2) if run.seconds is not None else None,
        tail=run.tail,
    )


def new_warnings(baseline: list[StepRun], candidate: list[StepRun], package: str) -> list[str]:
    """Warning lines the update brought, that name the package, and that the control did not show.

    Lines are compared, and kept, in their normalised form, so the same warning
    printed at a different second or by a different process is not new.
    """
    seen = {normalise(line) for run in baseline for line in run.output.splitlines()}
    short = package.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    found: list[str] = []
    for run in candidate:
        for line in run.output.splitlines():
            text = normalise(line)
            if (
                text
                and text not in seen
                and text not in found
                and _WARNING.search(text)
                and (package in text or short in text)
            ):
                found.append(text)
    return found


def pin_step(package: str, version: str, workspaces: tuple[str, ...] = ()) -> StepSpec:
    """Install the whole project with one dependency held at one exact version.

    Two moves. The first writes the version into the manifests and the lockfile
    without installing anything; a package several workspaces declare is held
    there in each of them, as an update to it would be, and `workspaces` is
    empty for a project without workspaces. The second installs the whole tree
    exactly as the lockfile now says, as CI would. One `npm install` with `-w`
    would not do: npm then installs only that workspace's dependencies, and the
    rest of the project would fail for want of packages it never lost.
    """
    where = "".join(f" -w {workspace}" for workspace in workspaces)
    quiet = "--ignore-scripts --no-audit --no-fund"
    places = " ".join(workspaces)
    return StepSpec(
        "resolution",
        f"npm install {package}@{version} --save-exact --package-lock-only {quiet}{where}"
        f" && npm ci {quiet}"
        f" && node {INSTALLED_SCRIPT} {package} {version} {places}".rstrip(),
        timeout=900,
        downloads=True,
    )


def compare(
    lane: Lane,
    control: tuple[dict[str, str], list[StepSpec]],
    candidate: tuple[dict[str, str], list[StepSpec]],
    *,
    package: str,
) -> Reproduction:
    """Run the control and the candidate, each in a fresh container, and set them side by side."""
    before = lane.run(*control)
    after = lane.run(*candidate)
    return Reproduction(
        baseline=[observed(run) for run in before.steps],
        candidate=[observed(run) for run in after.steps],
        warnings=new_warnings(before.steps, after.steps, package),
    )


def reproduce(
    lane: Lane,
    files: dict[str, str],
    *,
    package: str,
    old: str,
    new: str,
    steps: list[StepSpec],
    workspaces: tuple[str, ...] = (),
) -> Reproduction:
    """An npm update: the same files, with the dependency pinned at `old` and then at `new`.

    Each install is followed by a check that every place the package was pinned
    in resolves exactly that version, and a run where it does not is raised as
    `PinNotApplied` rather than returned.
    """
    files = {**files, INSTALLED_SCRIPT: installed_script()}
    reproduction = compare(
        lane,
        (files, [pin_step(package, old, workspaces), *steps]),
        (files, [pin_step(package, new, workspaces), *steps]),
        package=package,
    )
    for step in (*reproduction.baseline, *reproduction.candidate):
        if step.name == "resolution" and PIN_NOT_APPLIED in step.tail:
            raise PinNotApplied(step.tail.strip().splitlines()[-1])
    return reproduction
