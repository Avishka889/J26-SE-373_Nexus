"""The scanner arm as one detector: the baseline the other two have to beat.

The tools themselves are tested where they are parsed. What is tested here is
the arm's arithmetic, which is where the three way comparison can quietly
become unfair: which tools are asked, what counts as one weakness, what is
refused, and whether the cost the arm reports is the cost it actually has.
"""

import asyncio

import pytest
from c3.detect import ScannerArm, tools_for
from c3.detect.scanners import ScanOutput
from c3.detection import Candidate
from c3.harness import resolve, stage_copy

from . import jdk
from .test_targets import Ref


def _sample(tmp_path):
    return stage_copy(resolve(Ref(kind="sample", path="java-sample")), tmp_path / "ws")


def _fake(monkeypatch, **outputs: ScanOutput) -> None:
    """Answer for the tools without running them.

    The tools are proven against the real fixture elsewhere; running them again
    here would buy ninety seconds of the same evidence.
    """
    for name, output in outputs.items():
        monkeypatch.setattr(f"c3.detect.arm.run_{name}", lambda *a, _o=output, **k: _o)


def _run(arm: ScannerArm, root: str, files: list[str] | None = None):
    return asyncio.run(arm.scan(root, files or []))


class TestWhichToolsAreAsked:
    def test_a_java_target_gets_the_bytecode_analyser_and_not_npm(self, tmp_path) -> None:
        assert tools_for(_sample(tmp_path)) == ("semgrep", "findsecbugs")

    def test_a_node_target_gets_the_advisory_check_and_not_the_jvm(self, tmp_path) -> None:
        """Running a Java analyser at a React app and counting its silence as a
        clean result would make the arm look precise on a target it never
        examined."""
        repo = stage_copy(resolve(Ref(kind="sample", path="node-sample")), tmp_path / "ws")

        assert tools_for(repo) == ("semgrep", "npm audit")


class TestCountingOneWeaknessOnce:
    def test_two_rules_on_the_same_sink_are_one_candidate(self, tmp_path, monkeypatch) -> None:
        """SpotBugs reports the sample's SQL injection under two rule names.
        Counting them separately would halve the arm's measured precision for
        a reason about rule packs rather than about the code."""
        repo = _sample(tmp_path)
        path = "src/main/java/com/example/records/Accounts.java"
        both = ScanOutput(
            tool="findsecbugs",
            version="4.9.3",
            candidates=[
                Candidate(
                    cwe="CWE-89",
                    title="Potential JDBC Injection",
                    path=path,
                    start_line=36,
                    end_line=36,
                ),
                Candidate(
                    cwe="CWE-89",
                    title="Non constant string passed to execute",
                    path=path,
                    start_line=36,
                    end_line=36,
                ),
            ],
        )
        _fake(monkeypatch, semgrep=ScanOutput(tool="semgrep", version="1.176.1"), findsecbugs=both)

        result = _run(ScannerArm(repo=repo), str(repo.root))

        assert len(result.candidates) == 1
        assert result.candidates[0].extra["tools"] == ["findsecbugs"]

    def test_two_tools_agreeing_is_recorded_rather_than_counted_twice(
        self, tmp_path, monkeypatch
    ) -> None:
        """Agreement between independent tools is information the merge and the
        confidence rule both use, so it is kept."""
        repo = _sample(tmp_path)
        path = "src/main/java/com/example/records/Accounts.java"
        one = Candidate(cwe="CWE-89", title="sql injection", path=path, start_line=36, end_line=36)
        _fake(
            monkeypatch,
            semgrep=ScanOutput(tool="semgrep", version="1.176.1", candidates=[one]),
            findsecbugs=ScanOutput(tool="findsecbugs", version="4.9.3", candidates=[one]),
        )

        result = _run(ScannerArm(repo=repo), str(repo.root))

        assert len(result.candidates) == 1
        assert result.candidates[0].extra["tools"] == ["semgrep", "findsecbugs"]


class TestWhatTheArmRefuses:
    def test_a_location_that_is_not_in_the_repository_is_refused_and_counted(
        self, tmp_path, monkeypatch
    ) -> None:
        repo = _sample(tmp_path)
        _fake(
            monkeypatch,
            semgrep=ScanOutput(
                tool="semgrep",
                version="1.176.1",
                candidates=[
                    Candidate(
                        cwe="CWE-89",
                        title="invented",
                        path="src/main/java/Nowhere.java",
                        start_line=3,
                        end_line=3,
                    )
                ],
            ),
            findsecbugs=ScanOutput(tool="findsecbugs", version="4.9.3"),
        )

        result = _run(ScannerArm(repo=repo), str(repo.root))

        assert result.candidates == []
        assert [r.reason for r in result.refused] == ["file-not-found"]
        assert result.refused[0].claimed_path == "src/main/java/Nowhere.java"

    def test_a_weakness_with_no_line_is_refused_rather_than_pointed_at_line_one(
        self, tmp_path, monkeypatch
    ) -> None:
        """What npm audit produces for a transitive package. There is no line
        zero in any file, and evidence that resolves and is wrong is worse than
        evidence that does not resolve."""
        repo = _sample(tmp_path)
        _fake(
            monkeypatch,
            semgrep=ScanOutput(
                tool="semgrep",
                version="1.176.1",
                candidates=[
                    Candidate(
                        cwe="CWE-1321",
                        title="prototype pollution",
                        path="pom.xml",
                        start_line=0,
                        end_line=0,
                    )
                ],
            ),
            findsecbugs=ScanOutput(tool="findsecbugs", version="4.9.3"),
        )

        result = _run(ScannerArm(repo=repo), str(repo.root))

        assert result.candidates == []
        assert [r.reason for r in result.refused] == ["no-evidence"]


class TestWhatTheArmReportsAboutItself:
    def test_a_tool_that_fell_over_is_not_a_tool_that_found_nothing(
        self, tmp_path, monkeypatch
    ) -> None:
        repo = _sample(tmp_path)
        _fake(
            monkeypatch,
            semgrep=ScanOutput(tool="semgrep", version="1.176.1"),
            findsecbugs=ScanOutput(tool="findsecbugs", failure="the build did not compile"),
        )

        result = _run(ScannerArm(repo=repo), str(repo.root))

        assert result.failures == ["findsecbugs: the build did not compile"]
        assert "findsecbugs" not in result.run.model_id

    def test_the_provenance_names_every_version_that_ran(self, tmp_path, monkeypatch) -> None:
        """A number in a dissertation that cannot name what produced it is not
        a number anybody can use, and this arm is three tools."""
        repo = _sample(tmp_path)
        _fake(
            monkeypatch,
            semgrep=ScanOutput(tool="semgrep", version="1.176.1", files=("a.java", "b.java")),
            findsecbugs=ScanOutput(tool="findsecbugs", version="4.9.3", files=("b.java", "c.java")),
        )

        result = _run(ScannerArm(repo=repo), str(repo.root))

        assert result.run.model_id == "semgrep 1.176.1 + findsecbugs 4.9.3"
        assert result.run.files_scanned == 3, "the union of what the tools read, not the sum"
        assert result.run.duration_seconds >= 0

    def test_it_does_not_claim_to_work_offline(self, tmp_path) -> None:
        """Semgrep fetches its rules and npm audit asks a service. Offline
        operation is the trained arm's headline claim, and it is worthless if
        the baseline claims it untruthfully."""
        assert ScannerArm(repo=_sample(tmp_path)).offline is False

    def test_its_zero_cost_is_a_measurement_rather_than_a_silence(
        self, tmp_path, monkeypatch
    ) -> None:
        """Null means nobody said and zero means it was free. Every model arm
        in this study runs on a free tier, so without the distinction their
        costs would read as the same zero this arm reports for making no API
        call at all."""
        repo = _sample(tmp_path)
        _fake(
            monkeypatch,
            semgrep=ScanOutput(tool="semgrep", version="1.176.1"),
            findsecbugs=ScanOutput(tool="findsecbugs", version="4.9.3"),
        )

        run = _run(ScannerArm(repo=repo), str(repo.root)).run

        assert (run.cost_usd, run.prompt_tokens, run.completion_tokens) == (0.0, 0, 0)


class TestNarrowingToTheSameInputAsTheOtherArms:
    def test_a_file_the_other_arms_were_not_given_is_left_out(self, tmp_path, monkeypatch) -> None:
        """The LLM arm is priced per token and reads slices. A comparison where
        one arm saw the whole repository is not a comparison."""
        repo = _sample(tmp_path)
        accounts = "src/main/java/com/example/records/Accounts.java"
        reports = "src/main/java/com/example/records/Reports.java"
        _fake(
            monkeypatch,
            semgrep=ScanOutput(
                tool="semgrep",
                version="1.176.1",
                candidates=[
                    Candidate(cwe="CWE-89", title="a", path=accounts, start_line=36, end_line=36),
                    Candidate(cwe="CWE-78", title="b", path=reports, start_line=26, end_line=26),
                ],
            ),
            findsecbugs=ScanOutput(tool="findsecbugs", version="4.9.3"),
        )

        result = _run(ScannerArm(repo=repo), str(repo.root), [accounts])

        assert [candidate.path for candidate in result.candidates] == [accounts]

    def test_a_dependency_advisory_survives_the_narrowing(self, tmp_path, monkeypatch) -> None:
        """It is about what the project depends on, not about a file anyone
        touched, so dropping it would be dropping it for a reason that has
        nothing to do with whether it is true."""
        repo = _sample(tmp_path)
        _fake(
            monkeypatch,
            semgrep=ScanOutput(tool="semgrep", version="1.176.1"),
            findsecbugs=ScanOutput(
                tool="findsecbugs",
                version="4.9.3",
                candidates=[
                    Candidate(
                        cwe="CWE-1035",
                        title="an advisory",
                        path="pom.xml",
                        start_line=9,
                        end_line=9,
                        extra={"scope": "project"},
                    )
                ],
            ),
        )

        result = _run(ScannerArm(repo=repo), str(repo.root), ["src/main/java/nothing.java"])

        assert [candidate.path for candidate in result.candidates] == ["pom.xml"]


@pytest.mark.sandbox
class TestTheRealArmOnTheSeededSample:
    """FindSecBugs reads bytecode, so this needs the sample to compile.

    It carried no guard at all until 2026-09-27, which is why it failed in CI
    rather than skipping: the runner's JDK was older than the release the sample
    is compiled at, nothing was built, and the arm reported that spotbugs left
    no report. That reads as a broken arm and was a missing compiler.
    """

    @jdk.needs_jdk
    def test_it_finds_four_of_the_five_seeded_weaknesses(self, tmp_path) -> None:
        """The arm end to end, both tools, against the fixture. The one it
        misses is the hardcoded credential, which is the gap the LLM and
        trained arms have to close to earn their cost."""
        repo = _sample(tmp_path)

        result = _run(ScannerArm(repo=repo), str(repo.root))

        assert not result.failures, result.failures
        found = {candidate.cwe for candidate in result.candidates}
        print(f"\nscanner arm ({result.run.model_id}) in {result.run.duration_seconds}s")
        print(f"  found {sorted(found)} over {result.run.files_scanned} files")
        print(f"  refused {len(result.refused)}")
        assert {"CWE-89", "CWE-78", "CWE-22"} <= found
        assert "CWE-798" not in found, "the credential is missed by both tools, and that is the gap"
