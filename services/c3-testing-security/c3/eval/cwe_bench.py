"""CWE-Bench-Java: 120 real CVEs in real projects, as ground truth.

The other benchmark this study needs, and it measures something OWASP Benchmark
cannot. OWASP is 2,740 generated servlets: every weakness is reachable, every
file is small, and every case was written to be found. CWE-Bench-Java is 120
CVEs in projects like ActiveMQ, DSpace and the AWS SDK, where the vulnerable
method is somewhere inside a real codebase and nothing was arranged for the
benefit of a scanner. An arm that does well on the first and badly on the
second has learned the shape of a benchmark.

**What the repository contains, and what it does not.** It carries the seed
data: which project, which commit, which CWE, and which methods the fix
touched, with line spans. It carries no source at all. The authors' own script
fetches and builds all 120 projects across three JDKs, two Maven versions and
Gradle, and needs Oracle downloads that require an account. This module fetches
one project at a time at the exact buggy commit and does not build anything,
which is what the plan chose: source slices without the build farm.

**The ground truth is where the fix landed, which is not exactly where the
weakness is.** A fix may add a check in a helper, or touch a caller rather than
the sink. The benchmark's authors make the same approximation, and it is the
only one available without hand labelling 120 CVEs, but it means a miss here is
sometimes an arm that found the right weakness in the wrong method. This is
recorded rather than smoothed over: it is the reason a number from this corpus
should be read beside OWASP's rather than instead of it.

**Only the bytecode arm loses.** FindSecBugs needs compiled classes and these
projects are not built, so on this corpus the scanner arm is semgrep alone.
That is a fact about the measurement and it belongs in the row rather than in a
footnote.
"""

import csv
import subprocess
from pathlib import Path

from .benchmarks import Benchmark, commit_of
from .scoring import Span

#: The seed data, relative to the checkout.
PROJECT_INFO = "data/project_info.csv"
FIX_INFO = "data/fix_info.csv"

CLONE = "git clone --depth 1 https://github.com/iris-sast/cwe-bench-java.git"

#: How long one project's fetch may take. These are real repositories and some
#: of them are large even at depth one.
FETCH_TIMEOUT_SECONDS = 900.0


def seeds(root: str | Path) -> list[dict]:
    """The 120 projects, as rows.

    Read from `project_info.csv` rather than from the fix table, because the
    fix table carries 31 slugs from a larger collection that this dataset does
    not contain and joining the other way round would score projects that are
    not in the benchmark.
    """
    base = Path(root)
    labels = base / PROJECT_INFO
    if not labels.is_file():
        raise FileNotFoundError(
            f"{labels} is not there. CWE-Bench-Java is MIT licensed seed data and is "
            f"cloned rather than vendored: `{CLONE}`, then fetch the projects you want "
            "with fetch_project."
        )
    with labels.open(newline="") as handle:
        return [row for row in csv.DictReader(handle) if row.get("project_slug")]


def fixes(root: str | Path) -> dict[str, list[dict]]:
    """The fix spans, grouped by project.

    Rows whose project is not one of the 120 are dropped: they belong to a
    larger collection this checkout does not carry, and keeping them would put
    weaknesses into a denominator no arm was ever shown.
    """
    base = Path(root)
    known = {row["project_slug"] for row in seeds(base)}
    grouped: dict[str, list[dict]] = {}
    with (base / FIX_INFO).open(newline="") as handle:
        for row in csv.DictReader(handle):
            slug = row.get("project_slug") or ""
            if slug in known and (row.get("file") or "").endswith(".java"):
                grouped.setdefault(slug, []).append(row)
    return grouped


def spans_for(rows: list[dict], cwe: str) -> list[Span]:
    """One project's fix locations as scoreable spans.

    The method span when there is one, the class span when the fix was to a
    class variable and there is no method. Falling back to the class rather
    than dropping the row keeps fifteen real weaknesses in the denominator; a
    class span is wide, and a wide truth span is a generous match rather than a
    wrong one.
    """
    found: list[Span] = []
    for row in rows:
        start = _line(row.get("method_start")) or _line(row.get("class_start"))
        end = _line(row.get("method_end")) or _line(row.get("class_end")) or start
        if not start:
            continue
        found.append(Span(cwe=cwe, path=row["file"], start_line=start, end_line=max(start, end)))
    return found


def _line(value: str | None) -> int:
    text = (value or "").strip()
    return int(text) if text.isdigit() else 0


def project_slugs(root: str | Path, *, cwe: str = "", limit: int = 0) -> list[str]:
    """Which projects to run over, optionally one weakness class at a time.

    A subset is the normal case rather than a shortcut: each project is a real
    repository, and fetching all 120 is tens of gigabytes for a study that can
    say something useful from twenty.
    """
    from ..detect.severity import normalise

    wanted = normalise(cwe)
    chosen = [
        row["project_slug"]
        for row in seeds(root)
        if not wanted or normalise(row.get("cwe_id", "")) == wanted
    ]
    return chosen[:limit] if limit else chosen


def fetch_project(root: str | Path, slug: str, into: str | Path) -> Path:
    """One project's source at the exact commit the CVE reproduces on.

    A depth one fetch of that single commit rather than a clone: the history is
    not evidence and some of these repositories are enormous. Nothing is built,
    so the fetched tree is what a source reading arm sees and is not what a
    bytecode arm can use.
    """
    row = next((seed for seed in seeds(root) if seed["project_slug"] == slug), None)
    if row is None:
        raise KeyError(f"{slug} is not one of this benchmark's projects")
    target = Path(into) / slug
    if (target / ".git").is_dir():
        return target
    target.mkdir(parents=True, exist_ok=True)
    commit = row["buggy_commit_id"]
    for command in (
        ["git", "init", "--quiet"],
        ["git", "remote", "add", "origin", row["github_url"]],
        ["git", "fetch", "--quiet", "--depth", "1", "origin", commit],
        ["git", "checkout", "--quiet", "FETCH_HEAD"],
    ):
        done = subprocess.run(
            command,
            cwd=target,
            capture_output=True,
            text=True,
            timeout=FETCH_TIMEOUT_SECONDS,
            check=False,
        )
        if done.returncode != 0:
            raise RuntimeError(
                f"{' '.join(command)} failed for {slug}: {done.stderr.strip()[:300]}"
            )
    return target


def project(root: str | Path, slug: str, sources: str | Path) -> Benchmark:
    """One fetched project, with its ground truth.

    A benchmark of one, because that is how this corpus is scored: each project
    is its own repository with its own CVE, and running an arm over all of them
    at once would be running it over 120 unrelated codebases and averaging.
    """
    row = next((seed for seed in seeds(root) if seed["project_slug"] == slug), None)
    if row is None:
        raise KeyError(f"{slug} is not one of this benchmark's projects")
    from ..detect.severity import normalise

    checkout = Path(sources) / slug
    cwe = normalise(row["cwe_id"])
    truth = [
        span
        for span in spans_for(fixes(root).get(slug, []), cwe)
        if (checkout / span.path).is_file()
    ]
    files = [
        path.relative_to(checkout).as_posix()
        for path in sorted(checkout.rglob("*.java"))
        if ".git" not in path.parts
    ]
    return Benchmark(
        name=f"CWE-Bench-Java {slug}",
        root=checkout,
        files=files,
        truth=truth,
        # This corpus has no decoys: every project contains one real CVE and
        # nothing was planted to look like it. Precision here is measured
        # against the rest of a real codebase, which is a harder question than
        # a decoy and a less answerable one.
        decoys=[],
        commit=row["buggy_commit_id"] or commit_of(checkout),
        licence="MIT seed data, sources fetched from their own repositories",
    )
