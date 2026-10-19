"""The prompted arm, and the checks that make its answers usable.

No model is called anywhere in this file. Every answer below is written out,
because what is under test is what the pipeline does with an answer, not
whether a provider happens to produce one. The arm's real behaviour against a
real provider is a measurement and belongs to the study, under an epoch.

The cases are chosen from what models actually do wrong. They invent a file.
They quote code that is nowhere in it. They find something real and get the
line number wrong by two, which a line based check would report as the same
failure as inventing it, and which is not the same failure at all.
"""

import json

import pytest
from c3.detect import ProposedFinding, build_detector, check_no_self_scoring, chunks, find_quote
from c3.detect.llm import CONTEXT_LINES, LlmArm, build_triager, context_for, readable, triage
from c3.detection import Candidate
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel

SOURCE = """\
import { exec } from "node:child_process";

export function report(name) {
  const command = `wc -l ${name}`;
  return exec(command);
}
"""


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "reports.js").write_text(SOURCE)
    return tmp_path


class Scripted:
    """A model that answers from a list, and keeps every prompt it was given."""

    def __init__(self, answers: list[dict]) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    def as_function(self) -> FunctionModel:
        def respond(messages, info):
            texts = [
                part.content
                for message in messages
                for part in getattr(message, "parts", [])
                if getattr(part, "part_kind", "") == "user-prompt"
            ]
            self.prompts.append(texts[-1] if texts else "")
            answer = self.answers.pop(0) if self.answers else {"findings": []}
            return ModelResponse(
                parts=[ToolCallPart(info.output_tools[0].name, json.dumps(answer))]
            )

        return FunctionModel(respond)


def _arm(scripted: Scripted) -> LlmArm:
    return LlmArm(agent=build_detector(scripted.as_function()), model_id="scripted:test")


def _finding(**overrides) -> dict:
    """One well formed claim, with the part under test overridden.

    The overrides are checked against the real field names, because an
    override that misses silently leaves the default in place and the test
    then passes while proving nothing.
    """
    unknown = set(overrides) - set(ProposedFinding.model_fields)
    assert not unknown, f"not fields of a proposed finding: {sorted(unknown)}"
    base = {
        "cwe": "CWE-78",
        "title": "command injection",
        "path": "src/reports.js",
        "start_line": 5,
        "end_line": 5,
        "quoted_code": "  return exec(command);",
        "explanation": "The name reaches a shell.",
        "remediation": "Use execFile with an argument list.",
    }
    return {**base, **overrides}


class TestWhatTheModelIsShown:
    def test_the_source_is_numbered_so_a_location_can_be_checked(self, repo) -> None:
        [block] = chunks(str(repo), ["src/reports.js"])

        assert "--- src/reports.js ---" in block.body
        assert "    1 import { exec }" in block.body
        assert block.paths == ("src/reports.js",), "the body travels with what went into it"

    def test_a_lock_file_is_never_worth_a_token(self) -> None:
        assert readable(["src/a.js", "package-lock.json", "dist/app.min.js"]) == ["src/a.js"]

    def test_a_file_larger_than_the_budget_travels_whole(self, tmp_path) -> None:
        """A weakness split across two calls is a weakness neither call can
        see, so the budget batches files and never cuts one."""
        (tmp_path / "big.js").write_text("const x = 1;\n" * 4000)
        (tmp_path / "small.js").write_text("const y = 2;\n")

        blocks = chunks(str(tmp_path), ["big.js", "small.js"], budget=1000)

        assert len(blocks) == 2
        assert blocks[0].body.count("--- ") == 1
        assert [block.paths for block in blocks] == [("big.js",), ("small.js",)]


class TestFindingWhereTheQuoteReallyIs:
    def test_an_exact_quote_is_located_at_its_line(self) -> None:
        found = find_quote(SOURCE, "  return exec(command);", claimed=5)

        assert (found.start_line, found.drift) == (5, 0)

    def test_a_re_indented_quote_still_counts_as_copied(self) -> None:
        """Refusing this would measure transcription rather than detection."""
        found = find_quote(SOURCE, "return exec(command);", claimed=5)

        assert found.start_line == 5

    def test_a_quote_that_is_not_there_is_not_found(self) -> None:
        assert find_quote(SOURCE, "eval(userInput)", claimed=2) is None

    def test_a_repeated_quote_resolves_to_the_one_nearest_the_claim(self) -> None:
        source = "a();\nb();\na();\n"

        assert find_quote(source, "a();", claimed=3).start_line == 3
        assert find_quote(source, "a();", claimed=1).start_line == 1


class TestWhatSurvivesVerification:
    async def test_a_real_finding_quoted_exactly_becomes_a_candidate(self, repo) -> None:
        scripted = Scripted([{"findings": [_finding()]}])

        result = await _arm(scripted).scan(str(repo), ["src/reports.js"])

        assert result.refused == []
        [candidate] = result.candidates
        assert (candidate.cwe, candidate.start_line) == ("CWE-78", 5)

    async def test_an_invented_file_is_refused_and_counted(self, repo) -> None:
        scripted = Scripted([{"findings": [_finding(path="src/nowhere.js")]}])

        result = await _arm(scripted).scan(str(repo), ["src/reports.js"])

        assert result.candidates == []
        assert [r.reason for r in result.refused] == ["file-not-found"]
        assert result.refused[0].origin == "llm"

    async def test_quoted_code_that_is_not_in_the_file_is_a_fabrication(self, repo) -> None:
        """The refusal rate per arm is a result. An arm whose evidence does not
        resolve is an arm inventing locations, and the study cannot report that
        if the pipeline quietly repairs it."""
        scripted = Scripted([{"findings": [_finding(quoted_code="eval(request.body.cmd)")]}])

        result = await _arm(scripted).scan(str(repo), ["src/reports.js"])

        assert result.candidates == []
        assert [r.reason for r in result.refused] == ["snippet-does-not-match"]

    async def test_a_true_finding_with_a_wrong_line_number_is_corrected_not_discarded(
        self, repo
    ) -> None:
        """The distinction the whole arm turns on. A model that found a real
        weakness and counted lines badly has not fabricated anything, and
        throwing its finding away would measure arithmetic instead of
        detection. The drift is reported instead."""
        scripted = Scripted([{"findings": [_finding(start_line=2, end_line=2)]}])
        arm = _arm(scripted)

        result = await arm.scan(str(repo), ["src/reports.js"])

        [candidate] = result.candidates
        assert candidate.start_line == 5, "located by its quote, not by its claim"
        assert candidate.extra["claimedStartLine"] == 2
        assert candidate.extra["lineDrift"] == 3
        assert arm.drifted == 1

    async def test_a_weakness_class_it_made_up_is_refused(self, repo) -> None:
        scripted = Scripted([{"findings": [_finding(cwe="probably bad")]}])

        result = await _arm(scripted).scan(str(repo), ["src/reports.js"])

        assert [r.reason for r in result.refused] == ["malformed-cwe"]

    async def test_a_finding_with_no_quote_at_all_is_refused(self, repo) -> None:
        scripted = Scripted([{"findings": [_finding(quoted_code="   ")]}])

        result = await _arm(scripted).scan(str(repo), ["src/reports.js"])

        assert [r.reason for r in result.refused] == ["no-evidence"]


class TestTheModelMayNotScoreItsOwnFinding:
    def test_the_output_type_has_no_severity_and_no_confidence(self) -> None:
        """The strongest form of the rule: it is not that the arm is asked not
        to score, it is that there is nowhere for a score to go."""
        fields = set(ProposedFinding.model_fields)

        assert not fields & {"severity", "confidence", "score", "cvss", "risk"}

    @pytest.mark.parametrize(
        "prose",
        [
            "This is a critical issue.",
            "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
            "A high-risk injection.",
            "Severity: 9.8",
        ],
    )
    def test_a_severity_in_prose_is_caught(self, prose) -> None:
        """The output type cannot hold a score, but a sentence can."""
        assert check_no_self_scoring(prose)

    def test_ordinary_prose_is_left_alone(self) -> None:
        assert check_no_self_scoring("User input reaches a shell command unescaped.") == []

    async def test_the_finding_survives_and_the_claim_does_not(self, repo) -> None:
        """Throwing away a real weakness because its sentence was badly worded
        would cost recall to enforce a rule about wording."""
        scripted = Scripted([{"findings": [_finding(explanation="A critical hole here.")]}])
        arm = _arm(scripted)

        result = await arm.scan(str(repo), ["src/reports.js"])

        [candidate] = result.candidates
        assert "critical" not in candidate.message
        assert "[severity claim removed]" in candidate.message
        assert arm.scoring_refused == 1


class TestWhatTheArmReportsAboutItself:
    async def test_it_records_the_tokens_it_spent(self, repo) -> None:
        scripted = Scripted([{"findings": [_finding()]}])

        run = (await _arm(scripted).scan(str(repo), ["src/reports.js"])).run

        assert run.arm == "llm"
        assert run.model_id == "scripted:test"
        assert run.prompt_tokens > 0
        assert run.offline is False

    async def test_a_free_run_reports_no_cost_rather_than_a_cost_of_nothing(self, repo) -> None:
        """Null because nobody said. Zero is what the scanner arm reports for
        making no API call, and the study exists to tell those apart."""
        scripted = Scripted([{"findings": []}])

        run = (await _arm(scripted).scan(str(repo), ["src/reports.js"])).run

        assert run.cost_usd is None

    @pytest.mark.parametrize(
        ("hour", "dollars"),
        [(12, "0.75"), (2, "1.50")],
        ids=["off peak", "peak"],
    )
    def test_a_deepseek_flash_answer_is_priced(self, hour: int, dollars: str) -> None:
        """Every DeepSeek run recorded its cost as null.

        The arm reads its cost from pydantic-ai, which prices each answer from
        `genai-prices` by the model name the answer carries, and the platform's
        answers say `deepseek-flash`, a name the bundled table did not know. A
        million tokens in and a million out, at DeepSeek's list prices of
        2026-10-18: $0.15 and $0.60 off peak, twice that from 01:00 to 04:00 UTC.
        """
        from datetime import UTC, datetime
        from decimal import Decimal

        from pydantic_ai.messages import TextPart
        from pydantic_ai.usage import RequestUsage

        answer = ModelResponse(
            parts=[TextPart("ok")],
            usage=RequestUsage(input_tokens=1_000_000, output_tokens=1_000_000),
            model_name="deepseek-flash",
            provider_name="deepseek",
            provider_url="https://api.deepseek.com",
            timestamp=datetime(2026, 10, 19, hour, 0, tzinfo=UTC),
        )

        assert answer.cost().total_price == Decimal(dollars)

    async def test_a_chunk_that_failed_is_not_a_chunk_that_was_clean(self, repo) -> None:
        def explode(messages, info):
            raise RuntimeError("the provider returned something unreadable")

        arm = LlmArm(agent=build_detector(FunctionModel(explode)), model_id="scripted:test")

        result = await arm.scan(str(repo), ["src/reports.js"])

        assert result.candidates == []
        assert len(result.failures) == 1
        assert "unreadable" in result.failures[0]

    async def test_a_rate_limit_stops_the_pass(self, tmp_path) -> None:
        """The standing rule, and the reason for it: the quota is spent, every
        call after it is refused too, and a pass that ploughs on turns one
        refusal into a hundred while still measuring nothing. The first live
        three arm run did exactly that, 69 chunks of it.
        """
        for name in ("a.js", "b.js", "c.js"):
            (tmp_path / name).write_text("const x = 1;\n" * 500)
        calls = []

        def refuse(messages, info):
            calls.append(1)
            raise RuntimeError("status_code: 429, quota exceeded")

        arm = LlmArm(agent=build_detector(FunctionModel(refuse)), model_id="scripted:test")

        result = await arm.scan(str(tmp_path), ["a.js", "b.js", "c.js"])

        assert len(calls) == 1, "it asked once and stopped"
        assert any("never attempted" in failure for failure in result.failures)
        assert result.run.files_scanned == 0, "it read nothing, and says so"

    async def test_it_counts_the_files_it_read_rather_than_the_files_it_meant_to(
        self, tmp_path
    ) -> None:
        """A denominator nothing measured is how a partial pass comes to look
        like a poor one."""
        for name in ("a.js", "b.js", "c.js"):
            (tmp_path / name).write_text("const x = 1;\n" * 500)
        answered = []

        def once_then_refuse(messages, info):
            if not answered:
                answered.append(1)
                return ModelResponse(
                    parts=[ToolCallPart(info.output_tools[0].name, json.dumps({"findings": []}))]
                )
            raise RuntimeError("status_code: 429, quota exceeded")

        arm = LlmArm(
            agent=build_detector(FunctionModel(once_then_refuse)), model_id="scripted:test"
        )

        result = await arm.scan(str(tmp_path), ["a.js", "b.js", "c.js"])

        assert result.run.files_scanned == 1, "one chunk answered, and it held one file"


class TestTriageAsASeparateCapability:
    def _candidate(self) -> Candidate:
        return Candidate(
            cwe="CWE-78",
            title="command injection",
            path="src/reports.js",
            start_line=5,
            end_line=5,
            message="a shell command built from a parameter",
        )

    def test_the_triager_sees_the_guard_clause_above_and_the_sanitiser_below(self, repo) -> None:
        context = context_for(str(repo), self._candidate(), around=CONTEXT_LINES)

        assert "--- src/reports.js ---" in context
        assert "import { exec }" in context, "the whole function, not one line"

    async def test_a_dismissal_labels_the_finding_and_never_deletes_it(self, repo) -> None:
        """The study measures how often the triager was right, which it cannot
        do if the triager's mistakes are thrown away."""
        scripted = Scripted(
            [
                {
                    "verdict": "false-positive",
                    "cited_line": "const command = `wc -l ${name}`;",
                    "reasoning": "the name is a constant here",
                }
            ]
        )
        candidate = self._candidate()

        [judged] = await triage(build_triager(scripted.as_function()), str(repo), [candidate])

        assert judged.dismissed
        assert judged.candidate is candidate
        assert judged.reasoning

    async def test_a_verdict_citing_something_it_was_not_shown_becomes_unsure(self, repo) -> None:
        """The referee's discipline, applied where the cost of believing a
        confident tone is a real weakness deleted from the report."""
        scripted = Scripted(
            [{"verdict": "false-positive", "cited_line": "escapeShellArg(name)", "reasoning": ""}]
        )

        [judged] = await triage(
            build_triager(scripted.as_function()), str(repo), [self._candidate()]
        )

        assert judged.verdict == "unsure"
        assert "cited a line it was not shown" in judged.reasoning

    async def test_a_triager_that_does_not_answer_leaves_the_finding_standing(self, repo) -> None:
        def explode(messages, info):
            raise RuntimeError("the provider said 503")

        [judged] = await triage(
            build_triager(FunctionModel(explode)), str(repo), [self._candidate()]
        )

        assert judged.verdict == "unsure"
        assert not judged.dismissed
