"""What a stage is pointed at, and how it recognises what it is looking at.

Three kinds of repository reach this component and they arrive differently.
The generated monorepo is written into a workspace from the file store at one
code version. The samples are checked into this repository. A benchmark is
a checkout the evaluation made. After that they are the same thing: a directory
with a stack in it, which is all any lane needs.

The one thing worth stating plainly is what a target is not. It is not the
project's live tree and it is never the repository this platform is developed
in: every lane writes files, installs packages and runs mutation, so a stage
pointed at the wrong directory would be a bad afternoon. `resolve` refuses
anything it cannot recognise rather than guessing, and the sample is found
relative to this package rather than through a path a caller supplies.
"""

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

Stack = Literal["node", "java", "unknown"]

#: The three kinds a stage may be pointed at.
TargetKind = Literal["generated", "sample", "benchmark"]

#: Where the checked-in samples live, relative to this package's root. A
#: constant rather than a search, so a stage cannot be handed a different
#: sample by moving a file.
FIXTURES_DIR = "fixtures"

#: Which sample a target means when it does not say. The Java one, because it
#: is the lane the generated project cannot exercise. Named for what it is: the
#: plan called it `spring-sample`, this constant said so for a week after the
#: fixture was renamed, and every `kind="sample"` target with no name refused.
DEFAULT_SAMPLE = "java-sample"


@runtime_checkable
class TargetLike(Protocol):
    """The orchestrator's `TargetRef`, described rather than imported.

    C3 does not import the orchestrator: it is the component, and the client
    that calls it lives on the other side of the seam. This protocol is the
    shape that crosses, so in process and over HTTP arrive the same.
    """

    kind: str
    code_version: int | None
    path: str


@dataclass(frozen=True)
class TargetRepo:
    """A repository on disk, and what is true about it.

    `apps` is every directory a test runner has to be started in, which in a
    monorepo is more than one: the generated project keeps a web app and an API
    beside each other, each with its own config, and a lane that ran in only
    one of them would report the other's tests as not existing. That is not
    hypothetical; it is what this field was added for, after a filled test in
    `apps/api` was refused because the collector had been started in
    `apps/web`.

    The report always names paths from the repository root, whichever app they
    were run in: a path a reader cannot find in the repository is not evidence.
    """

    root: Path
    kind: str
    stack: Stack
    #: Relative to the root, in the order a reader would look. Never empty.
    apps: tuple[str, ...] = (".",)
    #: What made this the answer, for the report and for a puzzled reader.
    detected_by: str = ""

    @property
    def app_dir(self) -> str:
        """The first app, for the things that need exactly one: a mutation
        scope, the module listing that goes into a prompt."""
        return self.apps[0] if self.apps else "."

    @property
    def app_path(self) -> Path:
        return self.root / self.app_dir

    def app_for(self, path: str) -> str:
        """Which app a repository path belongs to."""
        for app in self.apps:
            if app != "." and path.startswith(f"{app}/"):
                return app
        return self.app_dir

    def relative(self, path: Path | str) -> str:
        """A path as the repository names it, whatever the workspace is called."""
        target = Path(path)
        if not target.is_absolute():
            target = self.app_path / target
        try:
            return target.resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return target.as_posix()

    def read(self, path: str) -> str | None:
        try:
            return (self.root / path).read_text(errors="replace")
        except OSError:
            return None

    def write(self, path: str, content: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)


class UnusableTarget(RuntimeError):
    """A target that cannot be run, saying which and why.

    Never a silent empty report: a stage that could not find its repository has
    not measured a repository with nothing in it.
    """


def samples() -> list[str]:
    """The samples checked in beside this component, by name.

    Read from disk rather than listed in code, because a sample that exists and
    is not offered is invisible and a sample that is offered and does not exist
    is a stage that fails after a person chose it. A directory counts when it
    holds a build file: the fixtures directory is also where a stray download
    would land.
    """
    root = Path(__file__).resolve().parents[2] / FIXTURES_DIR
    if not root.is_dir():
        return []
    found = []
    for entry in sorted(root.iterdir()):
        if entry.is_dir() and any(
            (entry / name).is_file() for name in ("pom.xml", "package.json", "build.gradle")
        ):
            found.append(entry.name)
    return found


def sample_root(name: str = DEFAULT_SAMPLE) -> Path:
    """A checked-in sample, found from this file rather than from a path.

    Walks up from this module to the service package's own root, so it is the
    same directory whatever the working directory is when a stage runs, and it
    is a name rather than a path: a target that could name `../../..` would be
    a stage that could install packages and run mutation in this repository.
    """
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise UnusableTarget(f"{name!r} is not a sample name")
    return Path(__file__).resolve().parents[2] / FIXTURES_DIR / name


#: Where a node monorepo keeps the things a test runner has to be started in.
#: Looked for in this order, and all of them are used: a project with a web app
#: and an API has two suites, two configs and one report.
NODE_APPS = ("apps/api", "apps/web", "packages/app")


def detect(root: Path) -> tuple[Stack, tuple[str, ...], str]:
    """Which stack is in this directory, where its runners are, and how we know.

    Deliberately shallow. A `pom.xml` or a `package.json` at a place a build
    tool would look for one is the answer; a search of the whole tree would
    find a fixture inside a benchmark and run it instead of the project.
    """
    if (root / "pom.xml").is_file():
        return "java", (".",), "a pom.xml at the root"

    members = tuple(app for app in NODE_APPS if (root / app / "package.json").is_file())
    if members:
        # A workspace root is not where the tests live, and it is not where the
        # configs live either: the web app wants jsdom and the API does not.
        return "node", members, "a package.json in " + ", ".join(members)
    if (root / "package.json").is_file():
        return "node", (".",), "a package.json at the root"
    return "unknown", (".",), "no pom.xml and no package.json anywhere a build tool would look"


def resolve(
    target: TargetLike, *, workspace: Path | str | None = None, must_run: bool = True
) -> TargetRepo:
    """The directory a stage should work in, or a refusal that says why.

    `workspace` is where the caller materialised a generated project. The
    orchestrator writes the file store's contents there before the stage runs,
    which is how a stage always sees exactly the version the run pinned rather
    than whatever is newest.

    `must_run` is what separates the two kinds of stage. A test lane needs a
    runner, so a directory with no recognised build is refused rather than
    reported as a suite of zero tests. A security scan needs only files: a
    repository with no `pom.xml` and no `package.json` still has source in it,
    and declining to look at it would be the security stage refusing its own
    job over a build system it does not use.
    """
    kind = target.kind
    if kind == "sample":
        # `path` names which sample, not where it is.
        name = target.path or DEFAULT_SAMPLE
        root = sample_root(name)
        if not root.is_dir():
            raise UnusableTarget(
                f"the sample {name!r} should be checked in at {FIXTURES_DIR}/{name} "
                "and is not there"
            )
    elif kind == "generated":
        given = workspace or target.path
        if not given:
            raise UnusableTarget(
                "a generated target is a workspace the caller materialises from the "
                "file store, and no path was given. The stage that resolves it has "
                "to write the code version's files out first."
            )
        root = Path(given)
        if not root.is_dir():
            raise UnusableTarget(f"the materialised workspace {root} is not there")
    elif kind == "benchmark":
        if not target.path:
            raise UnusableTarget("a benchmark target needs the path of its checkout")
        root = Path(target.path)
        if not root.is_dir():
            raise UnusableTarget(f"the benchmark checkout {root} is not there")
    else:
        raise UnusableTarget(
            f"{kind!r} is not a target kind. It is one of: generated, sample, benchmark."
        )

    stack, apps, why = detect(root)
    if stack == "unknown" and must_run:
        raise UnusableTarget(
            f"{root} has no stack this component can run: {why}. Nothing was run "
            "and nothing was measured."
        )
    return TargetRepo(root=root, kind=kind, stack=stack, apps=apps, detected_by=why)


#: Never copied into a workspace: build output and caches belong to the
#: workspace that made them, and `node_modules` is the reason a second run is
#: seconds rather than minutes.
NOT_COPIED = ("node_modules", ".git", "target", ".stryker-tmp", "dist", "coverage", ".c3")


def stage_copy(source: TargetRepo, workspace: Path | str) -> TargetRepo:
    """The same repository, in a directory a lane may write to.

    Every lane installs packages, writes reports and runs mutation, so a stage
    pointed at the checked-in sample would leave a `node_modules` and a
    `reports/` inside this repository the first time it ran. The copy is what
    gets measured; the checked-in tree stays as it was committed.

    The destination is reused rather than recreated, so an install already done
    is not done again, and files deleted from the source are cleared out of it
    first: a stale test file left behind would be run and counted.
    """
    destination = Path(workspace)
    destination.mkdir(parents=True, exist_ok=True)
    kept = {name for name in NOT_COPIED}
    for existing in destination.iterdir():
        if existing.name in kept:
            continue
        if existing.is_dir():
            shutil.rmtree(existing, ignore_errors=True)
        else:
            existing.unlink(missing_ok=True)
    shutil.copytree(
        source.root,
        destination,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(*NOT_COPIED),
    )
    return TargetRepo(
        root=destination,
        kind=source.kind,
        stack=source.stack,
        apps=source.apps,
        detected_by=source.detected_by,
    )
