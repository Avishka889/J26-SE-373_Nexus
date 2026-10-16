"""The three way comparison, and the merge that turns candidates into findings.

Contribution A is a table, and every decision that shapes that table is here:
what each arm's row contains, what the combined row means, and what happens to
a finding's severity and confidence on the way from a candidate to a report.

The arms are stubs. Running the real three would take a JVM, a provider and a
GPU trained model, and would test them rather than the comparison.
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from c3.detect.findings import merge_findings, snippet_at
from c3.detection import Candidate, DetectionResult
from c3.eval import Epoch, Span, run_study
from c3.eval.tables import build as build_tables
from sdlc_contracts import DetectorRun

JAVA = """package com.example;

public class Accounts {
    public static String findByName(Connection db, String name) throws SQLException {
        Statement statement = db.createStatement();
        return statement.executeQuery("select * from users where name = '" + name + "'");
    }
}
"""

PATH = "src/main/java/com/example/Accounts.java"


@pytest.fixture
def repo(tmp_path):
    target = tmp_path / PATH
    target.parent.mkdir(parents=True)
    target.write_text(JAVA)
    return tmp_path


def _run(arm: str, model_id: str, **overrides) -> DetectorRun:
    base = {
        "arm": arm,
        "model_id": model_id,
        "started_at": datetime.now(UTC),
        "duration_seconds": 1.0,
        "offline": arm != "llm",
        "files_scanned": 1,
    }
    return DetectorRun(**{**base, **overrides})


def _candidate(cwe: str, line: int = 6, **extra) -> Candidate:
    return Candidate(
        cwe=cwe, title=f"{cwe} here", path=PATH, start_line=line, end_line=line, extra=extra
    )


class Stub:
    """An arm that answers from a list."""

    def __init__(self, arm: str, model_id: str, result: DetectionResult) -> None:
        self.arm = arm
        self.model_id = model_id
        self.offline = result.run.offline
        self.result = result

    async def scan(self, root: str, files: list[str]) -> DetectionResult:
        return self.result


class TestFromCandidateToFinding:
    def test_the_severity_comes_from_the_table_and_carries_its_reasoning(self, repo) -> None:
        """A severity nobody can argue with is a severity nobody can check."""
        results = [
            DetectionResult(candidates=[_candidate("CWE-89")], run=_run("scanner", "semgrep 1.1"))
        ]

        merged = merge_findings(str(repo), results)

        [finding] = merged.findings
        assert finding.base_score == 9.8
        assert finding.severity == "critical"
        assert "database" in finding.severity_reasoning

    def test_the_snippet_is_read_from_the_file_not_from_the_arm(self, repo) -> None:
        """An arm that quoted something slightly different would otherwise have
        its version printed in a report that is supposed to say what is
        there."""
        candidate = _candidate("CWE-89")

        snippet = snippet_at(str(repo), candidate)

        assert "executeQuery" in snippet
        assert snippet in JAVA

    def test_two_arms_agreeing_is_one_finding_that_names_both(self, repo) -> None:
        """The ensemble's own evidence, and the whole comparison: a merge that
        forgot which arms agreed would produce a tidier list and throw the
        study away."""
        results = [
            DetectionResult(candidates=[_candidate("CWE-89")], run=_run("scanner", "semgrep")),
            DetectionResult(
                candidates=[_candidate("CWE-89")], run=_run("trained", "graphcodebert")
            ),
        ]

        merged = merge_findings(str(repo), results)

        [finding] = merged.findings
        assert finding.origin == "merged"
        assert set(finding.raised_by) == {"scanner", "trained"}
        assert finding.confidence_source == "arm-agreement"
        assert finding.confidence > 0.5

    def test_one_arm_alone_is_not_credited_with_agreement(self, repo) -> None:
        results = [
            DetectionResult(candidates=[_candidate("CWE-89")], run=_run("llm", "some-model"))
        ]

        [finding] = merge_findings(str(repo), results).findings

        assert finding.origin == "llm"
        assert finding.confidence_source == "scanner-rule"

    def test_evidence_that_does_not_resolve_never_becomes_a_finding(self, repo) -> None:
        results = [
            DetectionResult(
                candidates=[
                    Candidate(
                        cwe="CWE-89", title="invented", path=PATH, start_line=900, end_line=900
                    )
                ],
                run=_run("llm", "some-model"),
            )
        ]

        merged = merge_findings(str(repo), results)

        assert merged.findings == []
        assert [refusal.reason for refusal in merged.refused] == ["span-out-of-range"]
        assert merged.refused[0].origin == "llm"

    def test_the_report_starts_with_what_matters_most(self, repo) -> None:
        results = [
            DetectionResult(
                candidates=[_candidate("CWE-328", line=3), _candidate("CWE-89", line=6)],
                run=_run("scanner", "semgrep"),
            )
        ]

        merged = merge_findings(str(repo), results)

        assert [finding.cwe for finding in merged.findings] == ["CWE-89", "CWE-328"]

    def test_a_finding_id_is_stable_across_runs(self, repo) -> None:
        """Two reports of the same repository are compared finding by finding,
        which is what the remediation stage needs to say whether a fix
        worked."""
        results = [
            DetectionResult(candidates=[_candidate("CWE-89")], run=_run("scanner", "semgrep"))
        ]

        first = merge_findings(str(repo), results).findings[0].id
        second = merge_findings(str(repo), results).findings[0].id

        assert first == second


class TestTheComparisonTable:
    def _arms(self) -> list[Stub]:
        scanner = DetectionResult(
            candidates=[_candidate("CWE-89")],
            run=_run("scanner", "semgrep 1.176.1", duration_seconds=23.0, cost_usd=0.0),
        )
        llm = DetectionResult(
            candidates=[_candidate("CWE-89"), _candidate("CWE-798", line=3)],
            run=_run(
                "llm",
                "openrouter:some-model",
                duration_seconds=91.0,
                prompt_tokens=4000,
                completion_tokens=300,
                cost_usd=None,
            ),
        )
        return [Stub("scanner", scanner.run.model_id, scanner), Stub("llm", llm.run.model_id, llm)]

    async def test_every_arm_gets_a_row_and_so_does_the_combination(self, repo) -> None:
        """The interesting question is usually not which arm wins but whether
        two cheap ones together beat an expensive one."""
        truth = [Span("CWE-89", PATH, 6, 6)]

        study = await run_study(self._arms(), str(repo), [PATH], truth, epoch=Epoch(label="test"))

        assert [arm.arm for arm in study.arms] == ["scanner", "llm", "merged"]

    async def test_the_operational_half_is_reported_beside_the_accuracy(self, repo) -> None:
        """Reporting only F1 would make the trained arm look like a worse
        language model instead of a different kind of tool."""
        truth = [Span("CWE-89", PATH, 6, 6)]

        study = await run_study(self._arms(), str(repo), [PATH], truth, epoch=Epoch(label="test"))
        scanner, llm, merged = study.arms

        assert (scanner.prompt_tokens, scanner.cost_usd, scanner.offline) == (0, 0.0, True)
        assert llm.prompt_tokens == 4000
        assert llm.offline is False
        assert merged.duration_seconds == 114.0, "the combination costs what its parts cost"
        assert merged.offline is False, "as offline as its most demanding member"

    async def test_a_cost_nobody_reported_is_not_added_up(self, repo) -> None:
        """A total that silently omits the arm that did not say is a total that
        will be quoted as though it were complete."""
        study = await run_study(
            self._arms(), str(repo), [PATH], [Span("CWE-89", PATH, 6, 6)], epoch=Epoch(label="t")
        )

        assert study.arms[-1].cost_usd is None

    async def test_the_arms_are_scored_by_the_same_rule(self, repo) -> None:
        truth = [Span("CWE-89", PATH, 6, 6)]

        study = await run_study(self._arms(), str(repo), [PATH], truth, epoch=Epoch(label="test"))
        scanner, llm, _ = study.arms

        assert scanner.scorecard.per_class["CWE-89"].true_positives == 1
        assert llm.scorecard.per_class["CWE-89"].true_positives == 1
        assert llm.scorecard.unlabelled_classes == {"CWE-798": 1}, (
            "right about something unlabelled"
        )

    async def test_the_epoch_travels_with_the_numbers(self, repo, tmp_path) -> None:
        """A table without provenance is a table nobody can defend at a viva."""
        epoch = Epoch(label="epoch-2", commit="abc1234", dataset="juliet v1.3", split_seed="c3")

        study = await run_study(self._arms(), str(repo), [PATH], [], epoch=epoch)
        study.write(tmp_path / "study.json")

        written = (tmp_path / "study.json").read_text()
        assert "abc1234" in written and "epoch-2" in written and "juliet v1.3" in written
        assert study.as_dict()["epoch"]["at"]

    async def test_it_prints_a_table_a_person_can_read_while_it_is_warm(self, repo) -> None:
        study = await run_study(
            self._arms(), str(repo), [PATH], [Span("CWE-89", PATH, 6, 6)], epoch=Epoch(label="t")
        )

        table = study.table()

        assert "scanner" in table and "llm" in table and "merged" in table
        assert "unreported" in table, "a cost nobody reported says so rather than showing 0.0000"


class TestTheSecurityStage:
    """The component's `scan`, which is what the pipeline and the gate see.

    The report is the artefact and the comparison table is a separate command:
    a table computed from one run of one project is not a result, and putting
    one in a stage output would invite it to be quoted as though it were.
    """

    def _c3(self):
        from c3.service import C3

        return C3(model="scripted:test")

    def _target(self, root):
        from .test_targets import Ref

        return Ref(kind="benchmark", path=str(root))

    async def test_it_produces_a_report_the_gate_can_read(self, repo) -> None:
        arm = Stub(
            "scanner",
            "semgrep 1.176.1",
            DetectionResult(candidates=[_candidate("CWE-89")], run=_run("scanner", "semgrep")),
        )

        answer = await self._c3().scan(self._target(repo), version=3, arms=[arm])

        report = answer.artefact
        assert report.version == 3
        assert report.open_findings == 1
        assert report.open_critical_or_high == 1
        assert report.findings[0].severity == "critical"

    def test_the_default_arm_spends_nothing_and_needs_no_key(self, repo) -> None:
        """A stage triggered by a pipeline uses the arm that costs nothing.
        Spending tokens is a decision a person makes, not one a default makes
        for them."""
        from c3.harness import TargetRepo

        chosen = self._c3().default_arms(TargetRepo(root=repo, kind="benchmark", stack="java"))

        assert [one.arm for one in chosen] == ["scanner"]

    def test_a_caller_that_supplies_a_detector_gets_the_prompted_arm_too(self, repo) -> None:
        """Supplying one is how a caller says it has decided to spend tokens.
        The scanner stays beside it, because an arm that costs money is judged
        against one that does not."""
        from c3.harness import TargetRepo
        from c3.service import C3

        service = C3(model="scripted:test", detector=object())
        chosen = service.default_arms(TargetRepo(root=repo, kind="benchmark", stack="java"))

        assert [one.arm for one in chosen] == ["scanner", "llm"]
        assert chosen[1].model_id == "scripted:test", "the study records which model answered"

    async def test_it_never_scans_somebody_elses_code(self, repo) -> None:
        """A scan of node_modules measures a dependency and costs the model
        arms a fortune to do it."""
        from c3.service import _source_files

        (repo / "node_modules" / "left-pad").mkdir(parents=True)
        (repo / "node_modules" / "left-pad" / "index.js").write_text("module.exports = 1;\n")

        found = _source_files(type("R", (), {"root": repo})())

        assert PATH in found
        assert not any("node_modules" in path for path in found)

    async def test_a_stage_with_no_test_run_reports_no_coverage_rather_than_none(
        self, repo
    ) -> None:
        """Zero coverage is a real measurement and means the tests covered
        nothing, so the stage says the tests did not run instead."""
        arm = Stub("scanner", "semgrep", DetectionResult(candidates=[], run=_run("scanner", "s")))

        answer = await self._c3().scan(self._target(repo), version=1, arms=[arm])

        assert answer.artefact.tests.run == 0
        assert answer.artefact.tests.mutation_score is None

    async def test_the_summary_says_which_arm_found_what(self, repo) -> None:
        arms = [
            Stub(
                "scanner",
                "semgrep",
                DetectionResult(candidates=[_candidate("CWE-89")], run=_run("scanner", "semgrep")),
            ),
            Stub(
                "llm",
                "some-model",
                DetectionResult(
                    candidates=[_candidate("CWE-798", line=3)], run=_run("llm", "some-model")
                ),
            ),
        ]

        answer = await self._c3().scan(self._target(repo), version=1, arms=arms)

        assert "2 findings" in answer.summary
        assert answer.notes["byOrigin"] == {"scanner": 1, "llm": 1}

    async def test_a_tool_that_did_not_run_reaches_the_notes(self, repo) -> None:
        arm = Stub(
            "scanner",
            "semgrep",
            DetectionResult(
                candidates=[], run=_run("scanner", "semgrep"), failures=["findsecbugs: no wrapper"]
            ),
        )

        answer = await self._c3().scan(self._target(repo), version=1, arms=[arm])

        assert answer.notes["failures"] == ["findsecbugs: no wrapper"]
        assert "1 tools did not run" in answer.summary


class TestScoringDetectionApartFromClassification:
    """Found by running the trained arm for the first time.

    On the seeded sample it flags all five weaknesses and names two of them
    correctly. A table that scored only the naming would report it as having
    found two, which is not what happened and is not what a reader of a
    security report cares about first.

    It also makes the comparison fair in the other direction. A pattern scanner
    that matches a rule already knows the class it matched, so class agreement
    costs it nothing; a classifier chooses from thirty three. Scoring only by
    class compares a lookup against a decision.
    """

    def _arms(self, repo) -> list[Stub]:
        # Everything found, most of it misnamed: the trained arm's real shape.
        classifier = DetectionResult(
            candidates=[_candidate("CWE-89", line=6), _candidate("CWE-90", line=3)],
            run=_run("trained", "graphcodebert fine tuned"),
        )
        return [Stub("trained", classifier.run.model_id, classifier)]

    async def test_finding_it_and_misnaming_it_is_not_the_same_as_missing_it(self, repo) -> None:
        truth = [Span("CWE-89", PATH, 6, 6), Span("CWE-798", PATH, 3, 3)]

        study = await run_study(self._arms(repo), str(repo), [PATH], truth, epoch=Epoch(label="t"))
        [arm] = study.arms

        assert arm.found_at_all.recall == 1.0, "both weaknesses were flagged"
        assert arm.scorecard.macro_f1 < 0.6, "and one of the two was misnamed"

    async def test_both_numbers_reach_the_report(self, repo) -> None:
        truth = [Span("CWE-89", PATH, 6, 6), Span("CWE-798", PATH, 3, 3)]

        study = await run_study(self._arms(repo), str(repo), [PATH], truth, epoch=Epoch(label="t"))

        row = study.arms[0].as_dict()
        assert row["detection"]["recall"] == 1.0
        assert "macroF1" in row
        assert "foundR" in study.table()

    async def test_a_miss_is_a_miss_under_both(self, repo) -> None:
        """The class blind score is not a way of being generous: a weakness
        nobody pointed at is still missed."""
        scanner = DetectionResult(candidates=[], run=_run("scanner", "semgrep"))
        arms = [Stub("scanner", "semgrep", scanner)]

        study = await run_study(
            arms, str(repo), [PATH], [Span("CWE-89", PATH, 6, 6)], epoch=Epoch(label="t")
        )

        assert study.arms[0].found_at_all.recall == 0.0
        assert study.arms[0].scorecard.macro_f1 == 0.0


class TestAnArmThatHasStoppedDiscriminating:
    """Found by running the trained arm on OWASP Benchmark.

    It returned 7,295 findings from exactly 7,295 methods: every method
    flagged, minimum confidence 0.994. Detection recall was 1.000, and without
    the denominator beside it that reads as the best result in the table. An
    arm that flags everything has perfect recall and has found nothing.
    """

    async def test_flagging_everything_is_reported_as_such(self, repo) -> None:
        everything = DetectionResult(
            candidates=[_candidate("CWE-89", line=6), _candidate("CWE-798", line=3)],
            run=_run("trained", "collapsed"),
            units_examined=2,
        )
        arms = [Stub("trained", "collapsed", everything)]
        truth = [Span("CWE-89", PATH, 6, 6)]

        study = await run_study(arms, str(repo), [PATH], truth, epoch=Epoch(label="t"))
        [arm] = study.arms

        assert arm.found_at_all.recall == 1.0, "it did find the weakness, among everything else"
        assert arm.flagged_fraction == 1.0
        assert arm.degenerate
        assert "flagged nearly everything" in study.table()

    async def test_an_arm_that_discriminates_is_not_accused(self, repo) -> None:
        selective = DetectionResult(
            candidates=[_candidate("CWE-89", line=6)],
            run=_run("scanner", "semgrep"),
            units_examined=40,
        )
        arms = [Stub("scanner", "semgrep", selective)]

        study = await run_study(
            arms, str(repo), [PATH], [Span("CWE-89", PATH, 6, 6)], epoch=Epoch(label="t")
        )

        assert not study.arms[0].degenerate
        assert "flagged nearly everything" not in study.table()

    async def test_the_denominator_reaches_the_report(self, repo) -> None:
        """A finding count means nothing without what it was counted out of."""
        result = DetectionResult(
            candidates=[_candidate("CWE-89", line=6)],
            run=_run("scanner", "semgrep"),
            units_examined=40,
        )

        study = await run_study(
            [Stub("scanner", "semgrep", result)],
            str(repo),
            [PATH],
            [Span("CWE-89", PATH, 6, 6)],
            epoch=Epoch(label="t"),
        )

        row = study.arms[0].as_dict()
        assert row["unitsExamined"] == 40
        assert row["flaggedFraction"] == 0.025
        assert row["degenerate"] is False

    async def test_an_arm_that_counts_no_units_reports_no_fraction(self, repo) -> None:
        """Null, not zero, and the first live run is why this test exists.

        The prompted arm works in files rather than methods and sets no unit
        count, so the run that found thirteen weaknesses printed `0%` flagged
        beside them. Zero there reads as an arm that flagged nothing, which is
        the opposite of what happened, and it is the same mistake the mutation
        score already refuses to make.
        """
        counted_nothing = DetectionResult(
            candidates=[_candidate("CWE-89", line=6)],
            run=_run("llm", "some-model"),
        )

        study = await run_study(
            [Stub("llm", "some-model", counted_nothing)],
            str(repo),
            [PATH],
            [Span("CWE-89", PATH, 6, 6)],
            epoch=Epoch(label="t"),
        )
        arm = study.arms[0]

        assert arm.flagged_fraction is None
        assert arm.as_dict()["flaggedFraction"] is None
        assert not arm.degenerate, "unasked is not answered, and is certainly not degenerate"
        assert "n/a" in study.table(), "the table says the question was not asked"


class TestWhatAProviderNeedsInItsBody:
    """DeepSeek's flash model is in thinking mode by default and refuses a
    forced tool choice there with a 400 saying so. Every structured output in
    this platform is a forced tool call, so all three components probed
    UNUSABLE against it until the parameter that turns thinking off travelled
    with every request.
    """

    def test_deepseek_is_told_to_stop_thinking(self) -> None:
        from c3.agents import settings_for

        settings = settings_for("deepseek:deepseek-flash")

        assert settings is not None
        assert settings["extra_body"] == {"thinking": {"type": "disabled"}}

    def test_a_provider_that_needs_nothing_is_left_alone(self) -> None:
        """None rather than an empty setting, so a provider this table says
        nothing about keeps pydantic-ai's own defaults."""
        from c3.agents import settings_for

        assert settings_for("groq:any-model") is None, "groq has neither a ceiling nor a body"

    def test_a_ceiling_and_a_body_travel_together(self) -> None:
        """Google needs a cap and nothing else; a provider needing both must
        not lose one to the other. DeepSeek reads its cap from the body, so
        both travel there (`test_output_ceiling` checks the request itself)."""
        from c3.agents import PROVIDER_BODY, PROVIDER_OUTPUT_CEILING, settings_for

        PROVIDER_OUTPUT_CEILING["deepseek"] = 4096
        try:
            settings = settings_for("deepseek:deepseek-flash")
        finally:
            del PROVIDER_OUTPUT_CEILING["deepseek"]

        assert settings is not None
        assert "max_tokens" not in settings, "DeepSeek does not read the ordinary field"
        assert settings["extra_body"] == {**PROVIDER_BODY["deepseek"], "max_tokens": 4096}

    def test_the_body_cannot_be_edited_through_the_settings(self) -> None:
        """A caller mutating what it was handed would change every later
        request on that provider."""
        from c3.agents import PROVIDER_BODY, settings_for

        settings = settings_for("deepseek:deepseek-flash")
        assert settings is not None
        settings["extra_body"]["thinking"] = {"type": "enabled"}

        assert PROVIDER_BODY["deepseek"] == {"thinking": {"type": "disabled"}}


class TestTheTablesSayWhatCannotBeQuoted:
    """The formatter's whole job beyond layout. Epoch 9's prompted arm read 39
    of 108 chunks, scored worst of three, and produced the conclusion that the
    free scanner was the most accurate arm; epoch 10 gave the same arm the
    whole corpus and it scored best. The row carried a warning in prose and
    still misled, so the mark has to travel with the number.
    """

    @staticmethod
    def _study(tmp_path, arm: dict) -> Path:
        body = {
            "epoch": {"label": "t", "commit": "abc1234", "note": "10 of 100", "at": "2026-09-26"},
            "target": "a corpus",
            "groundTruthCount": 5,
            "arms": [
                {
                    "arm": "llm",
                    "modelId": "some:model",
                    "durationSeconds": 1.5,
                    "promptTokens": 10,
                    "completionTokens": 2,
                    "costUsd": None,
                    "offline": False,
                    "filesScanned": 10,
                    "found": 3,
                    "refused": 0,
                    "unitsExamined": 0,
                    "flaggedFraction": None,
                    "degenerate": False,
                    "macroF1": 0.5,
                    "detection": {"precision": 1.0, "recall": 0.5, "f1": 0.67},
                    "failures": [],
                    "perClass": [],
                    **arm,
                }
            ],
        }
        path = tmp_path / "study.json"
        path.write_text(json.dumps(body))
        return path

    @staticmethod
    def _row(written: str, arm: str) -> str:
        """The table row for one arm, which is what a reader's eye lands on.

        Asserting against the whole document was the first version of this and
        it passed with the row mark removed, because the footnote below the
        table says the same word. A mark that is only in a footnote is the
        arrangement epoch 9 already proved insufficient.
        """
        return next(line for line in written.splitlines() if line.startswith(f"| {arm} |"))

    def test_an_arm_that_did_not_finish_is_marked_in_its_row(self, tmp_path) -> None:
        self._study(tmp_path, {"failures": ["chunk 39 of 108: 429 quota exceeded"]})

        written = build_tables(tmp_path)

        assert "**incomplete**" in self._row(written, "llm"), "in the row, not only below it"
        assert "did not finish its pass" in written
        assert "429" in written, "the reason travels with the mark"

    def test_an_arm_that_flagged_everything_is_marked_too(self, tmp_path) -> None:
        self._study(tmp_path, {"degenerate": True, "unitsExamined": 3, "found": 3})

        written = build_tables(tmp_path)

        assert "**degenerate**" in self._row(written, "llm"), "in the row, not only below it"
        assert "is not a result" in written

    def test_a_clean_arm_carries_no_mark(self, tmp_path) -> None:
        self._study(tmp_path, {})

        written = build_tables(tmp_path)

        assert "**incomplete**" not in written
        assert "**degenerate**" not in written

    def test_a_cost_nobody_reported_is_not_a_zero(self, tmp_path) -> None:
        """A free tier is charged nothing, an arm that makes no call spends
        nothing, and neither is a price nobody published."""
        self._study(tmp_path, {})

        written = build_tables(tmp_path)

        assert "not reported" in written

    def test_two_epochs_never_share_a_table(self, tmp_path) -> None:
        """A rule, a model or a corpus changed between them, and a reader has
        to see that before comparing."""
        for name, label in (("a.json", "epoch-one"), ("b.json", "epoch-two")):
            body = json.loads(self._study(tmp_path, {}).read_text())
            body["epoch"]["label"] = label
            (tmp_path / name).write_text(json.dumps(body))
        (tmp_path / "study.json").unlink()

        written = build_tables(tmp_path)

        assert written.count("| arm | model |") == 2, "one header per epoch"
        assert "### epoch-one" in written and "### epoch-two" in written

    def test_a_file_that_is_not_a_study_is_skipped(self, tmp_path) -> None:
        """The same directory holds heal reports and label files, and reading
        one as the other would put a number in a table that means something
        else."""
        (tmp_path / "labels.json").write_text(json.dumps({"a::b": "brittle"}))
        self._study(tmp_path, {})

        written = build_tables(tmp_path)

        assert "brittle" not in written
