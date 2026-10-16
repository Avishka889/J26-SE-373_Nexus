"""The scanner arm: three tools, one shape, no opinions.

The first of the three arms the study compares, and the cheapest to defend: it
makes no API call, needs no network beyond fetching its own rules, costs
nothing per run, and answers the same way every time. Those four facts are the
baseline the other two arms have to beat on accuracy while losing on all of
them, which is the comparison the pillar exists to make.

Three tools, because no one of them covers the ground:

**Semgrep** reads source in both languages and matches patterns. It is the only
arm that works on the MERN side at all.

**npm audit** knows about published advisories in dependencies, which is
knowledge no amount of reading the project's own code can produce.

**FindSecBugs** traces taint through bytecode, which finds the flows a pattern
misses. It needs the project compiled first, which is why it is the only arm
here that runs a build.

**Why three and not one, measured rather than assumed.** On the seeded Java
sample, pattern rules find the SQL injection and the weak hash and miss the
command injection, the path traversal and the hardcoded credential. The first
two are missed for a reason worth writing down: both need a taint source, and a
pattern over source text has no notion of one. Bytecode analysis does, and
FindSecBugs finds exactly those two. That is the case for a three tool arm,
made by running the tools rather than by predicting what they would say.

The hardcoded credential is missed by both, and that gap is the honest one: it
is what the LLM and trained arms have to close to earn their cost.

**Every candidate carries a location, including the ones that do not have one.**
A dependency advisory is about a package, not a line, so its evidence is the
line in the manifest that asks for that version: the place a reader looks and
the place the fix goes. A package that cannot be found in the manifest yields a
candidate with no resolvable evidence, which the pipeline refuses and counts,
exactly as it refuses a model that invents a line number.
"""

import json
import os
import re
import shutil
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field
from pathlib import Path

from ..detection import Candidate
from ..harness import Sandbox, Step, TargetRepo
from .severity import normalise

#: Which rulesets are asked for. `security-audit` is the broad one, `secrets`
#: adds credential shapes, and the per language packs add what those miss.
#: Registry names rather than a vendored copy, so a rule fix reaches this
#: without a commit here; the version that ran is recorded per run.
RULESETS = ("p/security-audit", "p/secrets")

#: A cold semgrep run fetches its rules. The cap is for a hang.
SEMGREP_TIMEOUT_SECONDS = 900.0
AUDIT_TIMEOUT_SECONDS = 300.0


@dataclass
class ScanOutput:
    """What one tool produced, and whether it produced anything at all."""

    candidates: list[Candidate] = field(default_factory=list)
    tool: str = ""
    version: str = ""
    #: Set when the tool did not run. Never confused with finding nothing: a
    #: scanner that failed and a scanner that found nothing look identical in a
    #: list of zero findings, and only one of them is a result.
    failure: str = ""
    #: Which files this tool actually looked at, repository relative. Paths
    #: rather than a count, so that two tools reading the same six files
    #: report six and not twelve: the number is the denominator a reader uses
    #: to judge how much of the project was examined.
    files: tuple[str, ...] = ()

    @property
    def ran(self) -> bool:
        return not self.failure

    @property
    def files_scanned(self) -> int:
        return len(self.files)


#: A version, as a version looks. Anchored at both ends so that a line of
#: progress chatter containing a number cannot pass for one.
_VERSION = re.compile(r"^\d+\.\d+(\.\d+)?\S*$")


def semgrep_version(sandbox: Sandbox) -> str:
    """The version that actually ran, or nothing.

    The last line of the output was the first version of this, and it recorded
    `Installed 66 packages in 129ms` as the tool version on any run where `uvx`
    had to fetch semgrep first: the chatter arrives after the answer. A finding
    count whose provenance says that cannot be compared with next month's,
    which is the entire reason this function exists.

    Nothing rather than a guess when no line looks like a version. An empty
    provenance field is visibly missing; a wrong one is not.
    """
    result = sandbox.run(
        Step(name="semgrep version", command=("uvx", "semgrep", "--version"), timeout=300)
    )
    if not result.passed:
        return ""
    for line in reversed(result.output.strip().splitlines()):
        candidate = line.strip()
        if _VERSION.match(candidate):
            return candidate
    return ""


def run_semgrep(
    repo: TargetRepo, sandbox: Sandbox, *, rulesets: tuple[str, ...] = RULESETS
) -> ScanOutput:
    """Semgrep over the target, as JSON.

    Run through `uvx` rather than as a workspace dependency: semgrep pins
    `jsonschema<4.26` and the OpenAPI validator this repository already uses
    needs `>=4.26`, so the two cannot share an environment. The version that
    actually ran is recorded, because a finding count without one cannot be
    compared with next month's.
    """
    version = semgrep_version(sandbox)
    command = ["uvx", "semgrep", "--json", "--metrics=off", "--quiet"]
    for ruleset in rulesets:
        command.extend(["--config", ruleset])
    command.append(".")
    step = sandbox.run(
        Step(
            name="semgrep",
            command=tuple(command),
            timeout=SEMGREP_TIMEOUT_SECONDS,
        )
    )
    text = step.output[step.output.find("{") :] if "{" in step.output else ""
    if not text:
        return ScanOutput(
            tool="semgrep",
            version=version,
            failure=f"semgrep {step.outcome} and produced no report: {step.tail[-300:]}",
        )
    try:
        report = json.loads(text)
    except json.JSONDecodeError as error:
        return ScanOutput(
            tool="semgrep", version=version, failure=f"semgrep's report could not be read: {error}"
        )

    candidates = [_from_semgrep(result, repo) for result in report.get("results") or []]
    scanned = (report.get("paths") or {}).get("scanned") or []
    return ScanOutput(
        candidates=[c for c in candidates if c is not None],
        tool="semgrep",
        version=version,
        files=tuple(repo.relative(path) for path in scanned),
    )


def _from_semgrep(result: dict, repo: TargetRepo) -> Candidate | None:
    extra = result.get("extra") or {}
    metadata = extra.get("metadata") or {}
    raw = metadata.get("cwe") or []
    if isinstance(raw, str):
        raw = [raw]
    cwe = normalise(raw[0]) if raw else ""
    if not cwe:
        # A rule with no weakness class cannot be scored by a table keyed on
        # one, and inventing a class for it would be the arm asserting
        # something it was not told.
        return None
    check = str(result.get("check_id") or "")
    return Candidate(
        cwe=cwe,
        title=check.rsplit(".", 1)[-1].replace("-", " ") or cwe,
        path=repo.relative(result.get("path") or "") if repo else str(result.get("path") or ""),
        start_line=int((result.get("start") or {}).get("line") or 1),
        end_line=int((result.get("end") or {}).get("line") or 1),
        message=str(extra.get("message") or "").strip(),
        extra={
            "checkId": check,
            "semgrepSeverity": extra.get("severity"),
            "semgrepConfidence": metadata.get("confidence"),
        },
    )


#: What npm counts as a lockfile. `npm audit` refuses to run without one.
LOCKFILES = ("package-lock.json", "npm-shrinkwrap.json")


def run_npm_audit(repo: TargetRepo, sandbox: Sandbox) -> ScanOutput:
    """Published advisories against what this project depends on.

    Knowledge the project's own source cannot contain, which is why it is a
    separate tool rather than more rules. `npm audit` exits non zero when it
    finds anything, so the exit status says nothing about whether it worked and
    the report is what decides.

    **A lockfile first.** npm audit refuses to run without one, and every
    testing stage writes the workspace out of the file store again, which
    removes the one the install wrote: on a generated app it never ran (review
    item C3-5). When there is none, one is written from the manifest with no
    scripts run, the way a release pins its dependencies. The install's own is
    not kept on purpose: the harness adds its measurement tools to the
    workspace's manifest, and a lockfile with them in it would report their
    advisories as the app's.

    **npm's errors are failures.** With `--json`, npm reports an error as an
    object on stdout, and its own error lines follow on stderr. The object is
    read on its own, so the lines after it do not make the report unreadable,
    and an error is said as a failure rather than read as a clean audit.
    """
    if not any(repo.read(name) is not None for name in LOCKFILES):
        locked = sandbox.run(
            Step(
                name="npm lockfile",
                command=("npm", "install", "--package-lock-only", "--ignore-scripts"),
                timeout=AUDIT_TIMEOUT_SECONDS,
            )
        )
        if not locked.passed:
            return ScanOutput(
                tool="npm audit",
                failure=(
                    "there is no lockfile to audit, and npm could not write one: "
                    f"{locked.tail[-300:]}"
                ),
            )
    step = sandbox.run(
        Step(name="npm audit", command=("npm", "audit", "--json"), timeout=AUDIT_TIMEOUT_SECONDS)
    )
    start = step.output.find("{")
    if start < 0:
        return ScanOutput(
            tool="npm audit",
            failure=f"npm audit {step.outcome} and produced no report: {step.tail[-300:]}",
        )
    try:
        report, _ = json.JSONDecoder().raw_decode(step.output, start)
    except json.JSONDecodeError as error:
        return ScanOutput(tool="npm audit", failure=f"the audit report could not be read: {error}")
    error = report.get("error") if isinstance(report, dict) else None
    if error:
        said = error if isinstance(error, dict) else {"summary": str(error)}
        return ScanOutput(
            tool="npm audit",
            failure=(
                f"npm reported {said.get('code') or 'an error'}: "
                f"{said.get('summary') or said.get('detail') or 'no reason given'}"
            ),
        )

    manifest = repo.read("package.json") or ""
    candidates: list[Candidate] = []
    for name, entry in (report.get("vulnerabilities") or {}).items():
        for advisory in entry.get("via") or []:
            if not isinstance(advisory, dict):
                # A string here means "vulnerable because of another package",
                # which the other package's own row already reports.
                continue
            cwes = advisory.get("cwe") or []
            cwe = normalise(cwes[0]) if cwes else ""
            line = _manifest_line(manifest, name)
            candidates.append(
                Candidate(
                    cwe=cwe or "CWE-1395",
                    title=str(advisory.get("title") or f"advisory against {name}"),
                    # The manifest is where a reader looks and where the fix
                    # goes. A package that is not in it (a transitive one) gets
                    # line zero, which resolves nowhere and is refused and
                    # counted rather than quietly given the top of the file.
                    path="package.json",
                    start_line=line,
                    end_line=line,
                    message=(
                        f"{name} {entry.get('range') or advisory.get('range') or ''} is affected: "
                        f"{advisory.get('title') or 'see the advisory'} ({advisory.get('url') or ''})"
                    ).strip(),
                    extra={
                        "package": name,
                        "advisory": advisory.get("url"),
                        "npmSeverity": advisory.get("severity"),
                        "direct": bool(entry.get("isDirect")),
                        # About what the project depends on, not about a file
                        # anyone edited, so a scan narrowed to changed files
                        # keeps it.
                        "scope": "project",
                    },
                )
            )
    return ScanOutput(
        candidates=candidates, tool="npm audit", version="", files=(_manifest_path(repo),)
    )


def _manifest_path(repo: TargetRepo) -> str:
    """The manifest the advisories are about, as the repository names it."""
    return repo.relative("package.json")


def _manifest_line(manifest: str, package: str) -> int:
    """Where this dependency is asked for, or zero.

    Zero rather than one on purpose. A transitive dependency is not in the
    manifest, and pointing at its first line would be evidence that resolves
    and is wrong, which is worse than evidence that does not resolve.
    """
    pattern = re.compile(rf'^\s*"{re.escape(package)}"\s*:', re.MULTILINE)
    match = pattern.search(manifest)
    if not match:
        return 0
    return manifest[: match.start()].count("\n") + 1


#: Pinned in the sample's build as well; named here because the harness invokes
#: the goal directly rather than through a lifecycle phase.
SPOTBUGS_PLUGIN = "com.github.spotbugs:spotbugs-maven-plugin:4.9.3.0"

#: Where the report turns up. The first is where the sample's build is
#: configured to put it; the second is the plugin's own default, which is what
#: a project that does not configure spotbugs at all will use.
SPOTBUGS_XML = ("target/spotbugs/spotbugsXml.xml", "target/spotbugsXml.xml")

#: Where the FindSecBugs rules live once Maven has fetched them once. Passed on
#: the command line so the arm works on a project whose build has never heard
#: of SpotBugs, which is every project it will meet outside this repository.
FINDSECBUGS_JAR = "com/h3xstream/findsecbugs/findsecbugs-plugin"

#: A cold run compiles the project and downloads the analyser. The cap is for
#: a hang rather than for slowness.
SPOTBUGS_TIMEOUT_SECONDS = 1500.0

#: Maven's source roots, tried in order when turning a package relative path
#: back into one the repository knows.
_SOURCE_ROOTS = ("src/main/java", "src/test/java")


def run_findsecbugs(repo: TargetRepo, sandbox: Sandbox) -> ScanOutput:
    """SpotBugs with the FindSecBugs rules, over compiled bytecode.

    The only arm that needs a build, and the reason it earns one: it traces
    taint from a source to a sink, so it sees flows that no pattern over source
    text can. On the seeded sample it finds the command injection and the path
    traversal that semgrep misses, which is the complementarity argument in two
    findings rather than in a paragraph.

    Reports only the security category. SpotBugs also finds style and
    correctness problems, and this is the security arm: a report mixing the two
    would make the study's precision a number about SpotBugs' opinion of naming
    conventions.
    """
    maven = _maven_for(repo)
    if not maven:
        return ScanOutput(
            tool="findsecbugs",
            failure=(
                "this target has no Maven wrapper and there is no maven on PATH, so the "
                "only arm that needs a build could not run. A missing tool is a missing "
                "measurement, not a clean scan."
            ),
        )
    command = [maven, "-B", "-q", "compile", f"{SPOTBUGS_PLUGIN}:spotbugs"]
    rules = _findsecbugs_jar()
    if rules:
        # Without this the goal runs SpotBugs' own rules and finds style
        # problems, which would be this arm reporting on naming conventions
        # under a security heading.
        command.append(f"-Dspotbugs.pluginList={rules}")
    command.extend(
        ["-Dspotbugs.effort=Max", "-Dspotbugs.threshold=Low", "-Dspotbugs.xmlOutput=true"]
    )
    step = sandbox.run(
        Step(
            name="findsecbugs",
            command=tuple(command),
            cwd=repo.app_dir,
            timeout=SPOTBUGS_TIMEOUT_SECONDS,
        )
    )
    raw = next(
        (found for found in (repo.read(repo.relative(name)) for name in SPOTBUGS_XML) if found),
        "",
    )
    if not raw:
        return ScanOutput(
            tool="findsecbugs",
            failure=f"spotbugs {step.outcome} and left no report: {step.tail[-300:]}",
        )
    try:
        candidates, version = parse_spotbugs(raw, repo)
    except ElementTree.ParseError as error:
        return ScanOutput(tool="findsecbugs", failure=f"the report could not be read: {error}")
    return ScanOutput(
        candidates=candidates,
        tool="findsecbugs",
        version=version,
        files=_java_sources(repo),
    )


def parse_spotbugs(raw: str, repo: TargetRepo) -> tuple[list[Candidate], str]:
    """SpotBugs' XML as candidates, with the weakness class the tool assigned.

    `cweid` is an attribute on every bug instance, so the class comes from the
    analyser rather than from a table maintained here. A finding without one is
    dropped: this component scores by weakness class, and inventing a class for
    a finding that did not carry one would be the arm asserting something it
    was never told.
    """
    root = ElementTree.fromstring(raw)
    version = root.get("version", "")
    candidates: list[Candidate] = []
    for bug in root.iter("BugInstance"):
        if bug.get("category") != "SECURITY":
            continue
        cwe = normalise(bug.get("cweid") or "")
        if not cwe:
            continue
        line = _primary_line(bug)
        if line is None:
            continue
        path = _repo_path(repo, line.get("sourcepath") or "")
        if not path:
            continue
        start = int(line.get("start") or 1)
        end = int(line.get("end") or start)
        candidates.append(
            Candidate(
                cwe=cwe,
                title=(bug.findtext("ShortMessage") or bug.get("type") or cwe).strip(),
                path=path,
                start_line=start,
                end_line=max(start, end),
                message=(bug.findtext("LongMessage") or "").strip(),
                extra={
                    "bugType": bug.get("type"),
                    "rank": bug.get("rank"),
                    "priority": bug.get("priority"),
                },
            )
        )
    return candidates, version


def _maven_for(repo: TargetRepo) -> str:
    """The wrapper if the project ships one, else maven if the machine has one.

    Preferring the wrapper is not a style choice: it pins the Maven version the
    project was built with, and a benchmark built with a different one is a
    different measurement.
    """
    if (repo.app_path / "mvnw").is_file():
        return "./mvnw"
    return "mvn" if shutil.which("mvn") else ""


def _findsecbugs_jar() -> str:
    """The newest FindSecBugs jar Maven has already fetched, or nothing.

    Found rather than downloaded: this is a scanner, not an installer, and a
    tool that quietly pulls a jar from the internet mid scan is a tool nobody
    can run offline.
    """
    home = Path(os.environ.get("MAVEN_HOME_REPO") or Path.home() / ".m2" / "repository")
    versions = sorted((home / FINDSECBUGS_JAR).glob("*/findsecbugs-plugin-*.jar"))
    return str(versions[-1]) if versions else ""


def _java_sources(repo: TargetRepo) -> tuple[str, ...]:
    """Which files the analyser had to look at.

    The files that produced a finding would be a different set wearing this
    name, and this one is the denominator a reader uses to judge how much of
    the project was actually examined.
    """
    found: list[str] = []
    for app in repo.apps:
        base = repo.root if app in (".", "") else repo.root / app
        for root in _SOURCE_ROOTS:
            directory = base / root
            if directory.is_dir():
                found.extend(repo.relative(path) for path in sorted(directory.rglob("*.java")))
    return tuple(dict.fromkeys(found))


def _primary_line(bug: ElementTree.Element) -> ElementTree.Element | None:
    """The sink, not the enclosing class.

    A bug instance carries several source lines: the class it is in, the method
    it is in, and the statement the analyser is actually complaining about. The
    last of those is a direct child marked primary, and it is the only one a
    reader can act on. The nested ones span the whole class, so reporting one
    would be a finding that points at forty lines and means one.
    """
    direct = [element for element in bug if element.tag == "SourceLine"]
    for element in direct:
        if element.get("primary") == "true":
            return element
    if direct:
        return direct[0]
    # No primary line at all: better the method's range than nothing, since a
    # finding with no location is a finding a reader cannot check.
    return next(iter(bug.iter("SourceLine")), None)


def _repo_path(repo: TargetRepo, sourcepath: str) -> str:
    """`com/example/A.java` as the path the repository knows it by.

    SpotBugs reports a package relative path, because a package relative path
    is what the class file records. A finding a reader cannot open is not
    evidence, so every source root of every app is tried and a path that
    matches nothing on disk is dropped rather than guessed at.
    """
    if not sourcepath:
        return ""
    for app in repo.apps:
        base = "" if app in (".", "") else f"{app}/"
        for root in _SOURCE_ROOTS:
            candidate = f"{base}{root}/{sourcepath}"
            if repo.read(candidate) is not None:
                return candidate
    return ""
