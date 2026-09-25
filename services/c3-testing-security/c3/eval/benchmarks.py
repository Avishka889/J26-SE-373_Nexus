"""Ground truth from public benchmarks, read at evaluation time and never vendored.

The seeded sample proves the arms run. It cannot say whether they are any good:
five weaknesses that this repository wrote are five weaknesses this repository
knew how to write. A number worth quoting comes from a corpus somebody else
labelled, and this module reads those labels.

**Never vendored, and that is a licence decision rather than a preference.**
OWASP Benchmark is GPL-2.0. Copying it into this repository would put this
repository's licence in question, so it is cloned beside the workspace at
evaluation time, its commit is recorded in the epoch, and nothing from it is
committed here. SecBench.js is excluded outright: it carries no licence at all,
so there is no version of vendoring or of redistributing it that is allowed.

**The decoys are the point.** OWASP Benchmark pairs each real weakness with
test cases that look like it and are safe: 2,740 cases of which 1,415 are real.
Recall alone could be bought by reporting every file, and the 1,325 decoys are
what stops that. They are loaded separately so a report can say how many traps
each arm fell into, which is a more useful sentence than a precision figure.
"""

import csv
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .scoring import Span

#: Where the benchmark keeps its labels and its servlets.
OWASP_LABELS = "expectedresults-1.2.csv"
OWASP_TESTCASES = "src/main/java/org/owasp/benchmark/testcode"

#: The clone command, written down rather than performed: this repository does
#: not run it, a person does, and then points the study at the result.
OWASP_CLONE = "git clone --depth 1 https://github.com/OWASP-Benchmark/BenchmarkJava.git"


@dataclass(frozen=True)
class Benchmark:
    """A labelled corpus on disk: what to scan, and what is really there."""

    name: str
    root: Path
    files: list[str]
    truth: list[Span]
    #: Cases that look like a weakness and are not. Not ground truth and not
    #: noise: they are the reason a precision number from this corpus means
    #: something.
    decoys: list[Span]
    commit: str = ""
    licence: str = ""

    @property
    def epoch_note(self) -> str:
        return (
            f"{self.name} at {self.commit or 'an unrecorded commit'}, "
            f"{len(self.truth)} real weaknesses and {len(self.decoys)} decoys "
            f"over {len(self.files)} files, {self.licence}"
        )


def commit_of(root: str | Path) -> str:
    """The checkout's commit, for the epoch. Empty when it is not a clone."""
    try:
        found = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return found.stdout.strip() if found.returncode == 0 else ""


def owasp(root: str | Path) -> Benchmark:
    """OWASP Benchmark 1.2: 2,740 servlets, one weakness or one decoy each.

    The labels are a CSV of test name, category, whether it is real, and the
    CWE. A row marked real is ground truth; a row marked not is a decoy. Both
    are located at the file rather than at a line, because that is the
    granularity the benchmark labels at, and claiming a line the benchmark
    never specified would be inventing precision on the ground truth's behalf.
    """
    base = Path(root)
    labels = base / OWASP_LABELS
    if not labels.is_file():
        raise FileNotFoundError(
            f"{labels} is not there. OWASP Benchmark is GPL-2.0 and is never vendored: "
            f"clone it beside the workspace with `{OWASP_CLONE}` and point the study at it."
        )
    truth: list[Span] = []
    decoys: list[Span] = []
    files: list[str] = []
    with labels.open(newline="") as handle:
        for row in csv.reader(handle):
            if len(row) < 4 or row[0].startswith("#"):
                continue
            name, _category, real, cwe = row[0].strip(), row[1], row[2].strip(), row[3].strip()
            if not name or not cwe.isdigit():
                continue
            path = f"{OWASP_TESTCASES}/{name}.java"
            if not (base / path).is_file():
                continue
            files.append(path)
            span = Span(cwe=f"CWE-{cwe}", path=path)
            (truth if real.lower() == "true" else decoys).append(span)
    return Benchmark(
        name="OWASP Benchmark 1.2",
        root=base,
        files=files,
        truth=truth,
        decoys=decoys,
        commit=commit_of(base),
        licence="GPL-2.0, checked out and never vendored",
    )


def decoys_hit(predicted: list[Span], decoys: list[Span]) -> int:
    """How many traps an arm walked into.

    A separate count from precision because it says something precision does
    not: these are not findings in the wrong place, they are findings in a
    place built to look exactly like the right one.
    """
    by_path: dict[str, list[Span]] = {}
    for decoy in decoys:
        by_path.setdefault(decoy.path, []).append(decoy)
    return sum(
        1
        for prediction in predicted
        if any(prediction.matches(decoy) for decoy in by_path.get(prediction.path, ()))
    )
