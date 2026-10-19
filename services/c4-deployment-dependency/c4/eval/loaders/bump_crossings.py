"""Maven updates observed on BUMP's own projects, where BUMP has only breaks.

BUMP's 571 records are all breaks, and the Java client gives two negatives: too
few for the Maven side to measure more than its High recall. So BUMP's projects
become clients. Each is taken at the commit before its break, exactly as BUMP's
`-pre` image holds it, crossed with the patch, minor and major updates of its
other direct dependencies, and observed in that image with BUMP's own build
(`mvn clean test`), split into a compile step and a test step. Most crossings
will not break anything; one that does is a break BUMP did not record, labelled
by what was observed like any other case.

**What is crossed.** Versions are read from the project's POMs as written: a
literal `<version>`, or a property. A property several artifacts share moves them
all, and the case names the first. Left out, with nothing guessed:

- the dependency BUMP's record updates, because that update is its own case;
- the project's own modules, and anything under the project's group;
- imported BOMs, versions a parent or a BOM manages, and `${project.*}` versions.

Targets are chosen by `crossings.targets` from Maven Central at capture.

**The control runs once per project**, unmodified, before any crossing. A project
whose control fails here is skipped with its reason: its build is broken in this
environment already, so a crossing on it would say nothing about the update. The
image is pulled for the project, used for its control and its crossings, and
removed afterwards; the image's own Maven repository is used, never a shared
cache, so what BUMP pre-fetched is what the build starts from.

**The client** for the signals is the project at the commit before the break,
read from GitHub (`votes.client_for`): the parent of BUMP's breaking commit,
resolved once by a two deep fetch.
"""

import json
import re
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ...harness.container import Lane, StepSpec
from ...harness.reproduce import Reproduction, new_warnings, observed
from ..cases import CaseClient, CaseUpdate, LabelledCase, Observed
from .crossings import CrossingKind, Releases, selection_order, targets

#: Enough for a multi-module Maven build and its tests; the lane's default is for npm.
MEMORY = "2g"

_NS = re.compile(r"\{[^}]*\}")
_PROPERTY = re.compile(r"^\$\{([^}]+)\}$")


def _steps(workdir: str) -> list[StepSpec]:
    """BUMP's `mvn clean test`, in two steps so a compile break and a test break are told apart."""
    return [
        StepSpec(
            "compile",
            f"cd {workdir} && cp -r /work/overlay/. . 2>/dev/null; mvn -B -ntp clean test-compile",
            timeout=1800,
            downloads=True,
        ),
        StepSpec("test", f"cd {workdir} && mvn -B -ntp test", timeout=1800, downloads=True),
    ]


@dataclass(frozen=True)
class Declared:
    """One dependency a POM declares with a version it writes itself."""

    group: str
    artifact: str
    version: str
    pom: str
    scope: str
    #: The property the version comes from, or None for a literal `<version>`.
    prop: str | None
    #: The POM that defines the property, when there is one.
    prop_pom: str | None


@dataclass(frozen=True)
class Candidate:
    """One thing to update: a literal version, or a property and every artifact on it."""

    package: str
    version: str
    edits: tuple[tuple[str, str | None, str], ...]
    manifest_paths: tuple[str, ...]
    scope: str


@dataclass(frozen=True)
class Crossing:
    record: dict
    candidate: Candidate
    to_version: str
    kind: CrossingKind

    @property
    def key(self) -> str:
        return f"maven:{self.candidate.package}@{self.candidate.version}->{self.to_version}"

    @property
    def case_id(self) -> str:
        slug = re.sub(
            r"[^a-z0-9.]+",
            "-",
            f"{self.candidate.package.split(':')[-1]}-{self.candidate.version}-{self.to_version}",
        )
        return f"bumpx-{self.record['breakingCommit'][:12]}-{slug.strip('-')}"


def _children(element, name: str):
    return [child for child in element if _NS.sub("", child.tag) == name]


def _text(element, name: str) -> str:
    found = _children(element, name)
    return (found[0].text or "").strip() if found else ""


def declared(poms: dict[str, str], *, breaking: str) -> list[Declared]:
    """Every dependency the POMs declare with a version they write, less what is left out."""
    from xml.etree import ElementTree

    parsed = {}
    for path, text in poms.items():
        try:
            parsed[path] = ElementTree.fromstring(text)
        except ElementTree.ParseError:
            continue
    properties: dict[str, dict[str, str]] = {}
    for path, root in parsed.items():
        values = {}
        for block in _children(root, "properties"):
            for prop in block:
                values[_NS.sub("", prop.tag)] = (prop.text or "").strip()
        properties[path] = values
    root_pom = "pom.xml" if "pom.xml" in parsed else min(parsed, key=len, default="")
    project_group = _text(parsed[root_pom], "groupId") if root_pom else ""

    found: list[Declared] = []
    for path, root in parsed.items():
        for dependency in root.iter():
            if _NS.sub("", dependency.tag) != "dependency":
                continue
            group, artifact = _text(dependency, "groupId"), _text(dependency, "artifactId")
            version, scope = _text(dependency, "version"), _text(dependency, "scope")
            if not group or not artifact or not version or scope == "import":
                continue
            if f"{group}:{artifact}" == breaking:
                continue
            if group.startswith("${") or (project_group and group.startswith(project_group)):
                continue
            prop, prop_pom = None, None
            reference = _PROPERTY.match(version)
            if reference:
                prop = reference.group(1)
                if prop.startswith("project."):
                    continue
                for owner in (path, root_pom):
                    if prop in properties.get(owner, {}):
                        version, prop_pom = properties[owner][prop], owner
                        break
                else:
                    continue
            if not re.match(r"^[0-9]", version):
                continue
            found.append(Declared(group, artifact, version, path, scope, prop, prop_pom))
    return found


def candidates(found: list[Declared]) -> list[Candidate]:
    """One update per set of places that must move together.

    An artifact at one version is one update wherever it is written, and a property
    moves every artifact that uses it, so declarations that share either are
    joined. The update is named for its first artifact, and moves every place.
    """
    parent: dict[int, int] = {index: index for index in range(len(found))}

    def root(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    first_by: dict[tuple, int] = {}
    for index, item in enumerate(found):
        keys = [("artifact", item.group, item.artifact, item.version)]
        if item.prop:
            keys.append(("prop", item.prop_pom, item.prop))
        for key in keys:
            if key in first_by:
                parent[root(index)] = root(first_by[key])
            else:
                first_by[key] = index
    components: dict[int, list[Declared]] = {}
    for index, item in enumerate(found):
        components.setdefault(root(index), []).append(item)

    result = []
    for items in components.values():
        items.sort(key=lambda d: (d.group, d.artifact, d.pom))
        first = items[0]
        edits = sorted(
            {
                (item.prop_pom or item.pom, item.prop, "")
                if item.prop
                else (item.pom, None, f"{item.group}:{item.artifact}")
                for item in items
            },
            key=lambda edit: (edit[0], edit[1] or "", edit[2]),
        )
        result.append(
            Candidate(
                package=f"{first.group}:{first.artifact}",
                version=first.version,
                edits=tuple(edits),
                manifest_paths=tuple(sorted({item.pom for item in items})),
                scope=first.scope or "compile",
            )
        )
    return sorted(result, key=lambda c: (c.package, c.version))


def _move_literal(text: str, coordinate: str, old: str, new: str) -> tuple[str, int]:
    """Move one artifact's literal `<version>` inside its own `<dependency>` block."""
    group, artifact = coordinate.split(":", 1)
    moved = 0

    def bump(match: re.Match) -> str:
        nonlocal moved
        block = match.group(0)
        if f"<groupId>{group}</groupId>" not in block:
            return block
        if f"<artifactId>{artifact}</artifactId>" not in block:
            return block
        updated, hits = re.subn(
            rf"<version>\s*{re.escape(old)}\s*</version>",
            f"<version>{new}</version>",
            block,
            count=1,
        )
        moved += hits
        return updated

    return re.sub(r"<dependency>.*?</dependency>", bump, text, flags=re.DOTALL), moved


def edited(poms: dict[str, str], candidate: Candidate, new: str) -> dict[str, str]:
    """The POMs the update changes, with the version moved, as text so nothing else moves."""
    changed: dict[str, str] = {}
    for pom, prop, coordinate in candidate.edits:
        text = changed.get(pom, poms[pom])
        if prop:
            pattern = re.compile(
                rf"(<{re.escape(prop)}>)\s*{re.escape(candidate.version)}\s*(</{re.escape(prop)}>)"
            )
            text, count = pattern.subn(rf"\g<1>{new}\g<2>", text, count=1)
        else:
            text, count = _move_literal(text, coordinate, candidate.version, new)
        if not count:
            raise ValueError(f"{candidate.package}: {pom} has no {candidate.version} to move")
        changed[pom] = text
    return changed


def crossings(
    record: dict, found: list[Candidate], releases: dict[str, Releases]
) -> list[Crossing]:
    """Every candidate's patch, minor and major targets, in the fixed hash order."""
    every = [
        Crossing(record, candidate, target, kind)
        for candidate in found
        if candidate.package in releases
        for kind, target in targets(candidate.version, releases[candidate.package]).items()
    ]
    return sorted(every, key=lambda crossing: selection_order(crossing.key))


def image_of(record: dict) -> str:
    return str(record["preCommitReproductionCommand"]).split()[-1]


def _docker(*args: str, timeout: int = 1800) -> str:
    done = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
    )
    if done.returncode != 0:
        raise RuntimeError(
            f"docker {args[0]} failed: {(done.stderr or done.stdout).strip()[-400:]}"
        )
    return done.stdout


def project_poms(image: str) -> tuple[str, dict[str, str]]:
    """The image's working directory, and every POM under it, by path within the project.

    The image is pulled first: inspecting one that is not here yet fails, where
    creating a container would have pulled it silently.
    """
    _docker("pull", "-q", image, timeout=1800)
    workdir = _docker("image", "inspect", "--format", "{{.Config.WorkingDir}}", image).strip()
    container = _docker("create", image).strip()
    try:
        with tempfile.TemporaryDirectory(prefix="c4-bumpx-") as scratch:
            archive = Path(scratch) / "tree.tar"
            with archive.open("wb") as handle:
                subprocess.run(
                    ["docker", "cp", f"{container}:{workdir}", "-"],
                    stdout=handle,
                    check=True,
                    timeout=600,
                )
            poms: dict[str, str] = {}
            with tarfile.open(archive) as tree:
                for member in tree.getmembers():
                    # Only the POMs the project wrote: a build leaves `.flattened-pom.xml`
                    # and the like beside them, which are outputs, not sources.
                    if member.isfile() and member.name.rsplit("/", 1)[-1] == "pom.xml":
                        relative = member.name.split("/", 1)[1] if "/" in member.name else ""
                        handle = tree.extractfile(member)
                        if relative and handle is not None:
                            poms[relative] = handle.read().decode("utf-8", errors="replace")
    finally:
        _docker("rm", "-f", container, timeout=120)
    return workdir, poms


def lane_for(image: str) -> Lane:
    return Lane(image, memory=MEMORY)


def control(lane: Lane, workdir: str):
    """The project as BUMP's pre image holds it, built once."""
    return lane.run({}, _steps(workdir))


def observe_crossing(lane: Lane, workdir: str, poms, crossing: Crossing, before) -> Reproduction:
    """The candidate run with the version moved, beside the project's one control run."""
    overlay = {
        f"overlay/{path}": text
        for path, text in edited(poms, crossing.candidate, crossing.to_version).items()
    }
    after = lane.run(overlay, _steps(workdir))
    return Reproduction(
        baseline=[observed(run) for run in before.steps],
        candidate=[observed(run) for run in after.steps],
        warnings=new_warnings(before.steps, after.steps, crossing.candidate.package),
    )


def pre_commit(repo_url: str, breaking: str) -> str:
    """The parent of BUMP's breaking commit: the commit its pre image was built from."""
    with tempfile.TemporaryDirectory(prefix="c4-bumpx-git-") as scratch:
        for command in (
            ["git", "init", "-q"],
            ["git", "remote", "add", "origin", f"{repo_url}.git"],
            ["git", "fetch", "-q", "--depth", "2", "origin", breaking],
        ):
            subprocess.run(command, cwd=scratch, check=True, capture_output=True, timeout=600)
        done = subprocess.run(
            ["git", "rev-parse", "FETCH_HEAD^"],
            cwd=scratch,
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
    return done.stdout.strip()


def case_for(
    crossing: Crossing,
    reproduction: Reproduction,
    *,
    parent: str,
    toolchain: str,
    captured_at: str,
    dataset_commit: str,
) -> LabelledCase:
    record = crossing.record
    repo_url = f"https://github.com/{record['projectOrganisation']}/{record['project']}"
    return LabelledCase(
        case_id=crossing.case_id,
        source="bump-crossing",
        client=CaseClient(kind="github", repo_url=repo_url, commit=parent, image=image_of(record)),
        update=CaseUpdate(
            ecosystem="maven",
            package=crossing.candidate.package,
            from_version=crossing.candidate.version,
            to_version=crossing.to_version,
            manifest_paths=list(crossing.candidate.manifest_paths),
            scope=crossing.candidate.scope,
        ),
        source_change=crossing.kind,
        observed=Observed(
            method="container-reproduction",
            captured_at=captured_at,
            toolchain=toolchain,
            baseline=reproduction.baseline,
            candidate=reproduction.candidate,
            warnings=reproduction.warnings,
        ),
        provenance=(
            f"bump_crossings loader: {repo_url} at {parent[:12]}, the commit before BUMP's break "
            f"{record['breakingCommit'][:12]} (BUMP, chains-project/bump, MIT, at "
            f"{dataset_commit[:12]}), its {crossing.candidate.package} crossed with the "
            f"{crossing.kind} update Maven Central listed at capture, built in {image_of(record)}"
        ),
    )


#: How many crossings the corpus takes, and how many from any one project, so
#: no project's habits stand for the ecosystem.
QUOTA = 40
PER_PROJECT = 2

#: Projects left out by the owner's decision, never pulled, and why. Recorded in
#: the skip log like any other skip, so the corpus says what it did not try.
DROPPED = {
    "googleapis/google-cloud-java": (
        "dropped by the owner on 2026-09-28: its BUMP image did not pull within the "
        "30 minute limit, and every retry would cost another 30 minutes"
    ),
}


def records_of(cases: list[LabelledCase], benchmark: Path) -> list[dict]:
    """The BUMP records behind the chosen cases, one per project, in the cases' order."""
    seen: set[str] = set()
    found = []
    for case in cases:
        matches = sorted(benchmark.glob(f"{case.case_id.removeprefix('bump-')}*.json"))
        if not matches:
            continue
        record = json.loads(matches[0].read_text())
        project = f"{record['projectOrganisation']}/{record['project']}"
        if project not in seen:
            seen.add(project)
            found.append(record)
    return found


def toolchain_of(image: str) -> str:
    said = _docker("run", "--rm", "--entrypoint", "sh", image, "-c", "mvn -v 2>&1 | head -3")
    return f"{image} ({' '.join(said.split())})"


def _control_in(image: str, workdir: str):
    return control(lane_for(image), workdir)


def _observe_in(image: str, workdir: str, poms, crossing: Crossing, before) -> Reproduction:
    return observe_crossing(lane_for(image), workdir, poms, crossing, before)


def _remove(image: str) -> None:
    subprocess.run(["docker", "rmi", "-f", image], capture_output=True, check=False)


def build(
    records: list[dict],
    out: Path,
    skips: Path,
    *,
    releases_for,
    captured_at: str,
    dataset_commit: str,
    quota: int = QUOTA,
    per_project: int = PER_PROJECT,
    log=print,
    read=project_poms,
    run_control=_control_in,
    observe=_observe_in,
    parent_of=pre_commit,
    toolchain=toolchain_of,
    remove=_remove,
) -> int:
    """Observe crossings project by project until the quota is met; how many the corpus holds.

    `releases_for(packages)` answers what Maven Central lists for each package.
    Everything already written counts toward the quota and is not observed again,
    and a project already recorded as skipped is not tried again. Only reasons
    that belong to the project are recorded as skips (its control fails here,
    nothing it writes has a newer release); a failure of Docker, git or the
    network is said and tried again on the next run. The operations
    that touch Docker, git and the network are parameters, so the rules here can
    be held to account without them.
    """
    skipped = json.loads(skips.read_text()) if skips.exists() else []
    tried = {entry["breakingCommit"] for entry in skipped}
    held = len(list(out.glob("bumpx-*.json")))
    for record in records:
        if held >= quota:
            break
        commit = record["breakingCommit"]
        if commit in tried or list(out.glob(f"bumpx-{commit[:12]}-*.json")):
            continue
        image = image_of(record)
        project = f"{record['projectOrganisation']}/{record['project']}"
        if project in DROPPED:
            log(f"  {project}: {DROPPED[project]}", flush=True)
            skipped.append(
                {"project": project, "breakingCommit": commit, "reason": DROPPED[project]}
            )
            skips.write_text(json.dumps(skipped, indent=2, sort_keys=True) + "\n")
            continue
        log(f"  {project} at the commit before {commit[:12]}", flush=True)
        reason = None
        broke = None
        try:
            workdir, poms = read(image)
            dependency = record["updatedDependency"]
            breaking = f"{dependency['dependencyGroupID']}:{dependency['dependencyArtifactID']}"
            found = candidates(declared(poms, breaking=breaking))
            every = crossings(record, found, releases_for([c.package for c in found]))
            if not every:
                reason = "no dependency written with a version that has a newer release"
            else:
                before = run_control(image, workdir)
                if any(step.outcome == "unavailable" for step in before.steps):
                    raise RuntimeError("a download failed in the control run")
                if not all(step.outcome == "passed" for step in before.steps):
                    failing = [step.name for step in before.steps if step.outcome != "passed"]
                    reason = f"the control run fails here, at {', '.join(failing)}"
                else:
                    said = toolchain(image)
                    parent = parent_of(
                        f"https://github.com/{record['projectOrganisation']}/{record['project']}",
                        commit,
                    )
                    for crossing in every[: min(per_project, quota - held)]:
                        reproduction = observe(image, workdir, poms, crossing, before)
                        if any(step.outcome == "unavailable" for step in reproduction.candidate):
                            log(
                                f"    {crossing.case_id}: a download failed; not written, "
                                "and observed again next run",
                                flush=True,
                            )
                            continue
                        case = case_for(
                            crossing,
                            reproduction,
                            parent=parent,
                            toolchain=said,
                            captured_at=captured_at,
                            dataset_commit=dataset_commit,
                        )
                        body = json.dumps(
                            case.model_dump(by_alias=True, mode="json"), indent=2, sort_keys=True
                        )
                        (out / f"{case.case_id}.json").write_text(body + "\n")
                        log(f"    wrote {case.case_id}", flush=True)
                        held += 1
        except Exception as error:  # one project cannot stop the rest
            # Docker, git or the network, not the project: said, and tried again next run.
            broke = f"{type(error).__name__}: {str(error)[-300:]}"
        finally:
            remove(image)
        if broke:
            log(f"    not read this time, and tried again next run: {broke}", flush=True)
        elif reason:
            log(f"    skipped: {reason}", flush=True)
            skipped.append({"project": project, "breakingCommit": commit, "reason": reason})
            skips.write_text(json.dumps(skipped, indent=2, sort_keys=True) + "\n")
    return held
