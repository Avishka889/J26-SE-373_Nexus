"""The scanner arm, and the rule that turns a weakness class into a severity.

Two claims here and they are different in kind. The severity table is checked
by arithmetic against published vectors, because it either computes 9.8 for SQL
injection or it does not. The scanners are checked by running them, because
what a rule pack finds this month is not a thing that can be reasoned about.

The recall numbers below are deliberately not asserted at a threshold. What
semgrep finds on this fixture is a fact about semgrep and this fixture, and
pinning it would turn a rule pack update into a test failure while telling
nobody anything. What is asserted is the shape, the provenance, and the
refusals.
"""

import json
import shutil
from pathlib import Path

import pytest
from c3.detect import (
    factors_for,
    normalise,
    parse_spotbugs,
    run_findsecbugs,
    run_npm_audit,
    run_semgrep,
)
from c3.detect.scanners import _manifest_line, semgrep_version
from c3.harness import Sandbox, resolve, stage_copy
from c3.harness.sandbox import StepResult
from c3.harness.targets import TargetRepo
from sdlc_contracts.validation_report import cvss_base_score, severity_of

from . import jdk
from .test_targets import Ref

needs_semgrep = pytest.mark.skipif(shutil.which("uvx") is None, reason="needs uvx for semgrep")
needs_npm = pytest.mark.skipif(shutil.which("npm") is None, reason="needs npm")
# The wrapper needs a JDK and FindSecBugs needs the bytecode it produces, so
# this is the same requirement as compiling the sample rather than a weaker one.
needs_maven = jdk.needs_jdk

GOLDEN = Path(__file__).parent / "golden" / "java"


def _golden(name: str) -> str:
    return (GOLDEN / name).read_text()


class TestTheSeverityRule:
    def test_the_spellings_a_scanner_uses_all_normalise(self) -> None:
        """Semgrep reports the class and its full title in one string, npm
        audit reports the bare id, and nothing may reach the report in two
        spellings."""
        assert normalise("CWE-89: Improper Neutralization of Special Elements") == "CWE-89"
        assert normalise("CWE-1321") == "CWE-1321"
        assert normalise("cwe-79") == "CWE-79"
        assert normalise("nonsense") == ""
        assert normalise("") == ""

    @pytest.mark.parametrize(
        ("cwe", "expected", "band"),
        [
            ("CWE-89", 9.8, "critical"),
            ("CWE-78", 9.8, "critical"),
            ("CWE-22", 7.5, "high"),
            ("CWE-79", 6.1, "medium"),
            ("CWE-327", 5.9, "medium"),
            ("CWE-798", 9.1, "critical"),
        ],
    )
    def test_each_class_scores_what_the_published_vector_scores(self, cwe, expected, band) -> None:
        """The arithmetic is the specification's, so these are checkable
        against any CVE carrying the same vector."""
        factors, why = factors_for(cwe)

        assert cvss_base_score(factors) == expected
        assert severity_of(cvss_base_score(factors)) == band
        assert why, "a severity nobody can argue with is a severity nobody can check"

    def test_an_unknown_class_is_unremarkable_rather_than_absent(self) -> None:
        """A weakness the table has never heard of is worth a look and is not
        worth an alarm, and the reasoning says which it is."""
        factors, why = factors_for("CWE-99999")

        assert 0 < cvss_base_score(factors) < 7.0
        assert "no rule for this weakness class" in why

    def test_the_same_finding_under_two_spellings_scores_the_same(self) -> None:
        """Scanners disagree about whether a weak hash is 327 or 328, and a
        severity that moved with the scanner would be a severity about the
        scanner."""
        assert cvss_base_score(factors_for("CWE-327")[0]) == cvss_base_score(
            factors_for("CWE-328")[0]
        )


class TestFindingTheLineAnAdvisoryIsAbout:
    def test_a_declared_dependency_points_at_its_own_line(self) -> None:
        manifest = '{\n  "name": "x",\n  "dependencies": {\n    "minimist": "0.0.8"\n  }\n}\n'

        assert _manifest_line(manifest, "minimist") == 4

    def test_a_transitive_one_points_nowhere_rather_than_at_line_one(self) -> None:
        """Evidence that resolves and is wrong is worse than evidence that does
        not resolve: the first is believed."""
        manifest = '{\n  "dependencies": {\n    "express": "5.1.0"\n  }\n}\n'

        assert _manifest_line(manifest, "minimist") == 0


@pytest.mark.sandbox
@needs_semgrep
class TestSemgrepAgainstTheSeededSample:
    """What the tool really finds, run rather than predicted."""

    def test_it_finds_the_seeded_sql_injection_and_weak_hash(self, tmp_path) -> None:
        repo = stage_copy(resolve(Ref(kind="sample", path="java-sample")), tmp_path / "ws")

        output = run_semgrep(repo, Sandbox(repo.root))

        assert output.ran, output.failure
        assert output.version, "the version that ran is part of every number's provenance"
        found = {candidate.cwe for candidate in output.candidates}
        assert "CWE-89" in found
        assert found & {"CWE-327", "CWE-328"}, "the weak hash, under whichever spelling"

    def test_every_candidate_points_at_a_line_that_exists(self, tmp_path) -> None:
        """The discipline the whole pillar turns on, applied to the arm least
        likely to break it."""
        repo = stage_copy(resolve(Ref(kind="sample", path="java-sample")), tmp_path / "ws")

        output = run_semgrep(repo, Sandbox(repo.root))

        for candidate in output.candidates:
            source = repo.read(candidate.path)
            assert source is not None, f"{candidate.path} is not in the repository"
            lines = source.splitlines()
            assert 1 <= candidate.start_line <= len(lines)
            assert candidate.end_line <= len(lines)

    def test_what_it_misses_and_why_that_is_the_argument(self, tmp_path) -> None:
        """Recorded as a fact, not asserted as a threshold.

        The sample seeds five weaknesses. Pattern rules find the two that are
        visible in one line and miss the command injection and the path
        traversal, both of which need a taint source that a fixture of static
        methods does not have. That is the case for the other two arms and for
        evaluating on benchmarks with real entry points, and it is measured
        here rather than assumed.
        """
        repo = stage_copy(resolve(Ref(kind="sample", path="java-sample")), tmp_path / "ws")

        output = run_semgrep(repo, Sandbox(repo.root))
        found = {candidate.cwe for candidate in output.candidates}

        seeded = {"CWE-89", "CWE-78", "CWE-22", "CWE-798"}
        print(f"\nsemgrep {output.version} on the seeded sample: found {sorted(found)}")
        print(f"  of the seeded set it missed: {sorted(seeded - found)}")
        assert found, "an arm that finds nothing at all is a broken arm, not a clean repository"


@pytest.mark.sandbox
@needs_npm
class TestNpmAuditAgainstAKnownAdvisory:
    def test_an_advisory_becomes_a_candidate_anchored_in_the_manifest(self, tmp_path) -> None:
        """A dependency advisory is about a package, not a line. Its evidence
        is where the version is asked for, which is where a reader looks and
        where the fix goes."""
        from c3.harness import node_lane

        root = tmp_path / "ws"
        root.mkdir()
        (root / "package.json").write_text(
            json.dumps(
                {"name": "audit-probe", "private": True, "dependencies": {"minimist": "0.0.8"}},
                indent=2,
            )
            + "\n"
        )
        repo = resolve(Ref(kind="benchmark", path=str(root)))
        sandbox = Sandbox(repo.root)
        assert node_lane.install(repo, sandbox).passed

        output = run_npm_audit(repo, sandbox)

        assert output.ran, output.failure
        assert output.candidates, "minimist 0.0.8 has published advisories"
        candidate = output.candidates[0]
        assert candidate.path == "package.json"
        assert candidate.start_line > 0
        manifest = (repo.read("package.json") or "").splitlines()
        assert "minimist" in manifest[candidate.start_line - 1]
        assert candidate.cwe.startswith("CWE-")
        assert candidate.extra["package"] == "minimist"

    def test_a_clean_project_is_not_a_failed_scan(self, tmp_path) -> None:
        """Zero findings and a scanner that fell over look identical in a list
        of zero findings, and only one of them is a result."""
        from c3.harness import node_lane

        root = tmp_path / "ws"
        root.mkdir()
        (root / "package.json").write_text('{"name": "clean", "private": true}\n')
        repo = resolve(Ref(kind="benchmark", path=str(root)))
        sandbox = Sandbox(repo.root)
        node_lane.install(repo, sandbox)

        output = run_npm_audit(repo, sandbox)

        assert output.ran, output.failure
        assert output.candidates == []


class TestReadingWhatSpotBugsWrote:
    """The parser, against a real report captured from the seeded sample."""

    def test_it_finds_the_two_flows_a_pattern_cannot_see(self, tmp_path) -> None:
        """The complementarity argument, as two findings rather than a claim.

        Semgrep misses the command injection and the path traversal on this
        fixture because both need taint tracking. FindSecBugs works on
        bytecode and finds both, which is why the scanner arm is three tools
        and not one.
        """
        repo = stage_copy(resolve(Ref(kind="sample", path="java-sample")), tmp_path / "ws")

        candidates, version = parse_spotbugs(_golden("spotbugsXml.xml"), repo)

        assert version == "4.9.3", "the version that ran is part of the number's provenance"
        found = {candidate.cwe for candidate in candidates}
        assert "CWE-78" in found, "the command injection"
        assert "CWE-22" in found, "the path traversal"
        assert "CWE-89" in found

    def test_every_candidate_points_at_a_line_a_reader_can_open(self, tmp_path) -> None:
        """SpotBugs reports package relative paths, which no reader of this
        repository can find. The mapping back is what makes them evidence."""
        repo = stage_copy(resolve(Ref(kind="sample", path="java-sample")), tmp_path / "ws")

        candidates, _ = parse_spotbugs(_golden("spotbugsXml.xml"), repo)

        assert candidates
        for candidate in candidates:
            source = repo.read(candidate.path)
            assert source is not None, f"{candidate.path} is not in the repository"
            lines = source.splitlines()
            assert 1 <= candidate.start_line <= len(lines)
            assert candidate.end_line <= len(lines)

    def test_it_reports_the_sink_and_not_the_whole_class(self, tmp_path) -> None:
        """A bug instance carries the class range, the method range and the
        statement. Only the last is actionable, and the first spans forty
        lines."""
        repo = stage_copy(resolve(Ref(kind="sample", path="java-sample")), tmp_path / "ws")

        candidates, _ = parse_spotbugs(_golden("spotbugsXml.xml"), repo)
        injection = next(c for c in candidates if c.extra["bugType"] == "COMMAND_INJECTION")

        assert injection.start_line == injection.end_line
        source = (repo.read(injection.path) or "").splitlines()
        assert "exec" in source[injection.start_line - 1]

    def test_a_finding_with_no_weakness_class_is_dropped(self, tmp_path) -> None:
        """The arm is scored per weakness class. Inventing a class for a
        finding that did not carry one would be the arm asserting something
        the analyser never said."""
        repo = stage_copy(resolve(Ref(kind="sample", path="java-sample")), tmp_path / "ws")
        raw = _golden("spotbugsXml.xml").replace(' cweid="78"', "")

        candidates, _ = parse_spotbugs(raw, repo)

        assert "CWE-78" not in {candidate.cwe for candidate in candidates}

    def test_style_findings_are_not_security_findings(self, tmp_path) -> None:
        """SpotBugs also has opinions about naming. A precision number that
        counted those would be a number about something else."""
        repo = stage_copy(resolve(Ref(kind="sample", path="java-sample")), tmp_path / "ws")
        raw = _golden("spotbugsXml.xml").replace('category="SECURITY"', 'category="STYLE"')

        candidates, _ = parse_spotbugs(raw, repo)

        assert candidates == []

    def test_a_path_that_is_not_in_the_repository_yields_nothing(self, tmp_path) -> None:
        """The same refusal the pipeline applies to a model that invents a
        line number, applied to a tool that reports one this repository does
        not have."""
        repo = stage_copy(resolve(Ref(kind="sample", path="java-sample")), tmp_path / "ws")
        raw = _golden("spotbugsXml.xml").replace("com/example/records/", "com/example/absent/")

        candidates, _ = parse_spotbugs(raw, repo)

        assert candidates == []


@pytest.mark.sandbox
@needs_maven
class TestFindSecBugsAgainstTheSeededSample:
    def test_running_it_finds_what_semgrep_missed(self, tmp_path) -> None:
        """The one test that runs the build. Slow, and the only proof that the
        golden above is still what the tool writes."""
        repo = stage_copy(resolve(Ref(kind="sample", path="java-sample")), tmp_path / "ws")

        output = run_findsecbugs(repo, Sandbox(repo.root))

        assert output.ran, output.failure
        assert output.version, "the version that ran is part of every number's provenance"
        found = {candidate.cwe for candidate in output.candidates}
        print(f"\nfindsecbugs {output.version} on the seeded sample: found {sorted(found)}")
        assert {"CWE-78", "CWE-22"} <= found


class TestClassesThatAreTheSameWeaknessTwiceNamed:
    """Found by measuring, not by reading the CWE tree.

    Juliet labels its path traversal cases CWE-36 and its cross site scripting
    cases CWE-80. The scanners report CWE-22 and CWE-79. Both are right, and a
    severity that moved between them would be a severity about which arm's
    vocabulary happened to be used.
    """

    @pytest.mark.parametrize(
        ("child", "parent"),
        [("CWE-23", "CWE-22"), ("CWE-36", "CWE-22"), ("CWE-80", "CWE-79"), ("CWE-81", "CWE-79")],
    )
    def test_a_child_class_scores_what_its_parent_scores(self, child, parent) -> None:
        assert cvss_base_score(factors_for(child)[0]) == cvss_base_score(factors_for(parent)[0])

    def test_the_reasoning_says_the_score_came_from_the_parent(self) -> None:
        """A reader who sees 7.5 on a CWE-36 finding should be able to find out
        why without reading this code."""
        _, why = factors_for("CWE-36")

        assert "scored as CWE-22" in why

    def test_a_parent_is_never_scored_as_a_child(self) -> None:
        """The child is the more specific claim, and nothing here is entitled
        to make it."""
        _, why = factors_for("CWE-22")

        assert "scored as" not in why


class TestRunningTheBytecodeArmOnSomebodyElsesProject:
    """The arm was reaching its rules through the sample's own build file, so
    it worked on the one Java project in this repository and nowhere else."""

    def test_the_rules_are_found_in_the_local_cache_and_not_downloaded(self) -> None:
        """A scanner that quietly pulls a jar mid run is a scanner nobody can
        run offline."""
        from c3.detect.scanners import _findsecbugs_jar

        found = _findsecbugs_jar()

        assert found == "" or found.endswith(".jar"), found

    def test_a_cache_with_no_rules_in_it_answers_nothing_rather_than_guessing(
        self, tmp_path, monkeypatch
    ) -> None:
        from c3.detect.scanners import _findsecbugs_jar

        monkeypatch.setenv("MAVEN_HOME_REPO", str(tmp_path))

        assert _findsecbugs_jar() == ""

    def test_a_project_with_no_wrapper_and_no_maven_is_a_missing_measurement(
        self, tmp_path, monkeypatch
    ) -> None:
        """Not a clean scan. A missing tool and a clean project produce the
        same empty list, and only one of them is a result."""
        from c3.detect import run_findsecbugs
        from c3.detect import scanners as module
        from c3.harness import Sandbox, TargetRepo

        (tmp_path / "pom.xml").write_text("<project/>")
        repo = TargetRepo(root=tmp_path, kind="benchmark", stack="java")
        monkeypatch.setattr(module.shutil, "which", lambda name: None)

        output = run_findsecbugs(repo, Sandbox(repo.root))

        assert not output.ran
        assert "missing tool" in output.failure
        assert output.candidates == []


class TestTheVersionThatActuallyRan:
    """A finding count whose provenance says `Installed 66 packages in 129ms`
    cannot be compared with next month's, and that is the entire reason the
    version is captured. It happened: `uvx` prints its install chatter after
    the answer when it has to fetch semgrep first, and the first version of
    this took the last line.
    """

    class _Sandbox:
        def __init__(self, output: str, passed: bool = True) -> None:
            self.output = output
            self.passed = passed

        def run(self, step):
            from types import SimpleNamespace

            return SimpleNamespace(output=self.output, passed=self.passed)

    def test_install_chatter_after_the_answer_is_not_the_version(self) -> None:
        sandbox = self._Sandbox("1.178.0\nInstalled 66 packages in 129ms\n")

        assert semgrep_version(sandbox) == "1.178.0"

    def test_the_plain_case_still_works(self) -> None:
        assert semgrep_version(self._Sandbox("1.178.0\n")) == "1.178.0"

    def test_a_prerelease_is_still_a_version(self) -> None:
        assert semgrep_version(self._Sandbox("2.0.0rc1\n")) == "2.0.0rc1"

    def test_nothing_rather_than_a_guess(self) -> None:
        """An empty provenance field is visibly missing. A wrong one is not."""
        assert semgrep_version(self._Sandbox("Installed 66 packages in 129ms\n")) == ""

    def test_a_failed_call_records_nothing(self) -> None:
        assert semgrep_version(self._Sandbox("1.178.0\n", passed=False)) == ""


class NpmWithoutTheNetwork:
    """A sandbox that answers npm as npm 10.9.2 does, without the network.

    The shapes are npm's own, taken from npm 10.9.2 on this machine: with
    `--json`, an error is an object on stdout, and npm's own `npm error` lines
    follow it on stderr, which the sandbox appends.
    """

    def __init__(self, root: Path, *, audit: str, errors: str = "", lockfile: bool = True):
        self.root = root
        self.audit = audit
        self.errors = errors
        self.lockfile = lockfile
        self.commands: list[tuple[str, ...]] = []

    def run(self, step) -> StepResult:
        self.commands.append(tuple(step.command))
        command = " ".join(step.command)
        if step.command[:2] == ("npm", "install"):
            if not self.lockfile:
                return StepResult(
                    name=step.name,
                    command=command,
                    outcome="failed",
                    output="npm error code E404\nnpm error 404 Not Found - GET https://registry.npmjs.org/nope",
                )
            (self.root / "package-lock.json").write_text("{}\n")
            return StepResult(name=step.name, command=command, outcome="passed")
        return StepResult(
            name=step.name, command=command, outcome="failed", output=self.audit + self.errors
        )


class TestNpmAuditOnAGeneratedApp:
    """npm audit never ran on a generated app (review item C3-5).

    Every testing stage writes the workspace out of the file store again, which
    removes the lockfile the install wrote, and npm audit refuses to run without
    one. With npm's own error lines after its report, the refusal read as "the
    audit report could not be read: Extra data"; with them quiet, the error
    object parsed as a clean audit.
    """

    CLEAN = json.dumps({"auditReportVersion": 2, "vulnerabilities": {}}) + "\n"
    ENOLOCK = (
        json.dumps(
            {
                "error": {
                    "code": "ENOLOCK",
                    "summary": "This command requires an existing lockfile.",
                    "detail": "Try creating one first with: npm i --package-lock-only",
                }
            },
            indent=2,
        )
        + "\n"
    )
    NPM_LINES = (
        "npm error code ENOLOCK\n"
        "npm error A complete log of this run can be found in: /home/x/.npm/_logs/a.log\n"
    )

    def _repo(self, tmp_path, *, lockfile: bool = False) -> TargetRepo:
        root = tmp_path / "ws"
        root.mkdir()
        (root / "package.json").write_text('{"name": "app", "private": true}\n')
        if lockfile:
            (root / "package-lock.json").write_text("{}\n")
        return TargetRepo(root=root, kind="generated", stack="node")

    def test_with_no_lockfile_one_is_written_before_the_audit(self, tmp_path) -> None:
        repo = self._repo(tmp_path)
        npm = NpmWithoutTheNetwork(repo.root, audit=self.CLEAN)

        output = run_npm_audit(repo, npm)

        assert npm.commands == [
            ("npm", "install", "--package-lock-only", "--ignore-scripts"),
            ("npm", "audit", "--json"),
        ]
        assert output.ran, output.failure

    def test_a_lockfile_already_there_is_audited_as_it_is(self, tmp_path) -> None:
        repo = self._repo(tmp_path, lockfile=True)
        npm = NpmWithoutTheNetwork(repo.root, audit=self.CLEAN)

        run_npm_audit(repo, npm)

        assert npm.commands == [("npm", "audit", "--json")]

    def test_a_lockfile_npm_cannot_write_is_said_and_nothing_is_audited(self, tmp_path) -> None:
        repo = self._repo(tmp_path)
        npm = NpmWithoutTheNetwork(repo.root, audit=self.CLEAN, lockfile=False)

        output = run_npm_audit(repo, npm)

        assert not output.ran
        assert output.failure.startswith(
            "there is no lockfile to audit, and npm could not write one: npm error code E404"
        )
        assert ("npm", "audit", "--json") not in npm.commands

    def test_an_error_from_npm_is_a_failure_and_not_a_clean_audit(self, tmp_path) -> None:
        repo = self._repo(tmp_path, lockfile=True)

        output = run_npm_audit(repo, NpmWithoutTheNetwork(repo.root, audit=self.ENOLOCK))

        assert not output.ran
        assert output.failure == "npm reported ENOLOCK: This command requires an existing lockfile."

    def test_npm_s_own_lines_after_its_report_do_not_stop_it_being_read(self, tmp_path) -> None:
        repo = self._repo(tmp_path, lockfile=True)

        refused = run_npm_audit(
            repo, NpmWithoutTheNetwork(repo.root, audit=self.ENOLOCK, errors=self.NPM_LINES)
        )
        clean = run_npm_audit(
            repo, NpmWithoutTheNetwork(repo.root, audit=self.CLEAN, errors="npm warn config x\n")
        )

        assert (
            refused.failure == "npm reported ENOLOCK: This command requires an existing lockfile."
        )
        assert clean.ran, clean.failure


class TestEachToolSaysWhetherItRan:
    """A tool that failed and a tool that found nothing look the same in a list of
    zero findings. The failure reached only the stage's notes, so the Security
    step could not say npm audit never ran (review item C3-5)."""

    def test_the_scanner_arm_reports_every_tool_and_its_outcome(
        self, tmp_path, monkeypatch
    ) -> None:
        from c3.detect import ScannerArm
        from c3.detect import arm as arm_module
        from c3.detect.scanners import ScanOutput
        from sdlc_contracts import ToolOutcome

        monkeypatch.setattr(
            arm_module,
            "run_semgrep",
            lambda repo, sandbox: ScanOutput(tool="semgrep", version="1.90.0"),
        )
        monkeypatch.setattr(
            arm_module,
            "run_npm_audit",
            lambda repo, sandbox: ScanOutput(
                tool="npm audit", failure="npm reported ENOTFOUND: request failed"
            ),
        )
        repo = TargetRepo(root=tmp_path, kind="generated", stack="node")

        result = ScannerArm(repo=repo, sandbox=object()).scan_now(str(tmp_path), [])

        assert result.tools == [
            ToolOutcome(tool="semgrep", ran=True, version="1.90.0"),
            ToolOutcome(
                tool="npm audit", ran=False, detail="npm reported ENOTFOUND: request failed"
            ),
        ]

    async def test_the_report_carries_them(self, tmp_path) -> None:
        from datetime import UTC, datetime

        from c3.detection import DetectionResult
        from c3.service import C3
        from sdlc_contracts import DetectorRun, ToolOutcome

        tools = [
            ToolOutcome(tool="semgrep", ran=True, version="1.90.0"),
            ToolOutcome(
                tool="npm audit", ran=False, detail="npm reported ENOTFOUND: request failed"
            ),
        ]

        class ToolsOnly:
            async def scan(self, root, files):
                return DetectionResult(
                    candidates=[],
                    run=DetectorRun(
                        arm="scanner",
                        model_id="semgrep 1.90.0",
                        started_at=datetime.now(UTC),
                        duration_seconds=0.1,
                        offline=False,
                    ),
                    tools=tools,
                )

        answer = await C3("no model").scan(
            Ref(kind="generated", code_version=1, path=str(tmp_path)), version=1, arms=[ToolsOnly()]
        )

        assert answer.artefact.tools == tools
