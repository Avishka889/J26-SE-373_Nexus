"""The explanation: a model's prose about a decision it did not make, checked before it is shown.

The assessment explained is Low, Low, High (SemVer and the changelog say Low; the
code uses a removed export), so the final level is High and Medium was voted by
nobody. Each scripted answer breaks one check; the one that breaks none is used.

What passes is shown without em or en dashes, and every call is on the record
with what it cost. The dash cases are the patterns Epoch 4's explain/1 answers
used (17 of 26 had at least one), each with the reading it is replaced by.
"""

from typing import Any

import pytest
from c4.agents import MALFORMED_OUTPUT_RETRIES
from c4.risk import assess
from c4.risk.explain import explain, plain, shown, summary
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sdlc_contracts import ChangedSymbol, RiskReport

from .test_assessment import _changelog, _impact, _update, _updates

MODEL = "deepseek:deepseek-flash"


@pytest.fixture
async def risk() -> RiskReport:
    update = _update("acme")
    changelog = _changelog((update, "fix", "low"))
    removed = ChangedSymbol(
        update_id=update.id, symbol="thing", kind="removed", source="api-diff", tool="test"
    )
    files = {"src/a.ts": 'import { thing } from "acme";\nthing(); // the call itself\n'}
    impact = await _impact(files, _updates(update), changelog, symbols=[removed])
    return assess.report(_updates(update), changelog, impact, version=1)


def _answering(level: str, text: str, calls: list[int] | None = None) -> FunctionModel:
    def respond(_: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if calls is not None:
            calls.append(1)
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"level": level, "text": text})]
        )

    return FunctionModel(respond)


GOOD = (
    "High, decided by usage: the project uses `thing`, which the new release removed, at "
    "src/a.ts:2. SemVer and the changelog say Low. Review it and keep the rollback ready."
)


async def _explained_by(risk: RiskReport, model: FunctionModel) -> Any:
    [item] = (await explain(risk, model=MODEL, agent_model=model)).assessments
    return item


async def _explained(risk: RiskReport, level: str, text: str) -> Any:
    return await _explained_by(risk, _answering(level, text))


class TestWhatIsShown:
    def test_the_model_is_shown_the_decision_and_never_the_code(self, risk) -> None:
        request = shown(risk.assessments[0])
        assert "Final level: High" in request and "usage: High" in request
        assert "src/a.ts:2" in request
        assert "the call itself" not in request


class TestTheCheck:
    async def test_an_answer_that_passes_every_check_is_what_the_developer_reads(
        self, risk
    ) -> None:
        item = await _explained(risk, "high", GOOD)
        assert (item.explanation, item.explanation_source) == (GOOD, "model")
        assert item.explanation_refusal == "" and item.explanation_unavailable == ""

    async def test_a_different_level_is_refused(self, risk) -> None:
        item = await _explained(risk, "medium", GOOD)
        assert item.explanation_refusal == "it states medium, and the final level is high"
        assert item.explanation_source == "rule" and item.explanation == summary(item)

    async def test_a_level_nobody_voted_is_refused_even_in_passing(self, risk) -> None:
        item = await _explained(risk, "high", "High overall, though it could be seen as Medium.")
        assert item.explanation_refusal.startswith("it names medium")

    async def test_a_quote_that_was_not_shown_is_refused(self, risk) -> None:
        item = await _explained(risk, "high", 'High: the notes say "thing() is gone for good".')
        assert "is not in what it was shown" in item.explanation_refusal

    async def test_a_file_the_evidence_never_named_is_refused(self, risk) -> None:
        item = await _explained(risk, "high", "High: it is used in src/b.ts as well.")
        assert item.explanation_refusal == "it names src/b.ts, which the evidence does not"

    async def test_the_report_counts_refusals_and_names_the_model_and_prompt(self, risk) -> None:
        refused = await explain(risk, model=MODEL, agent_model=_answering("low", GOOD))
        assert refused.explanations_refused == 1
        assert (refused.explanation_model_id, refused.explanation_prompt_id) == (
            MODEL,
            "explain-assessment/2",
        )


class TestNoDashesReachTheDeveloper:
    @pytest.mark.parametrize(
        ("written", "shown_as"),
        [
            (
                "The signals disagree \u2014 the changelog abstained.",
                "The signals disagree: the changelog abstained.",
            ),
            (
                "decided by all three signals \u2014 semver, changelog, and usage \u2014 which "
                "each voted high.",
                "decided by all three signals (semver, changelog, and usage) which each voted "
                "high.",
            ),
            (
                "none of its changed symbols is used \u2014 so the most cautious level was taken.",
                "none of its changed symbols is used, so the most cautious level was taken.",
            ),
            (
                "Medium: the signals disagree \u2014 the changelog abstained.",
                "Medium: the signals disagree; the changelog abstained.",
            ),
            ("It moves from 2.7.3\u20132.7.21 at once.", "It moves from 2.7.3 to 2.7.21 at once."),
            ("High\u2014the usage signal found it.", "High: the usage signal found it."),
            ("The change is minor \u2014, oddly.", "The change is minor, oddly."),
            ("No dash at all.", "No dash at all."),
        ],
    )
    def test_each_dash_is_replaced_by_the_punctuation_its_sentence_needs(
        self, written: str, shown_as: str
    ) -> None:
        cleaned, replaced = plain(written)
        assert cleaned == shown_as
        assert replaced == written.count("\u2014") + written.count("\u2013")

    def test_a_quote_keeps_its_dashes_because_it_is_someone_elses_words(self) -> None:
        written = 'The notes say "Removed \u2014 use bar()" \u2014 and `a\u2013b` stays too.'
        cleaned, replaced = plain(written)
        assert cleaned == 'The notes say "Removed \u2014 use bar()", and `a\u2013b` stays too.'
        assert replaced == 1

    async def test_what_passes_the_check_is_shown_without_dashes_and_counted(self, risk) -> None:
        written = GOOD.replace("Review it and keep", "Review it \u2014 keep")
        item = await _explained(risk, "high", written)
        assert item.explanation_source == "model"
        assert "\u2014" not in item.explanation and "\u2013" not in item.explanation
        assert item.explanation == GOOD.replace("Review it and keep", "Review it: keep")
        assert item.explanation_dashes_replaced == 1


class TestEveryCallIsOnTheRecord:
    async def test_an_answered_call_records_its_prompt_and_what_it_cost(self, risk) -> None:
        item = await _explained(risk, "high", GOOD)
        call = item.explanation_call
        assert call is not None
        assert (call.model_id, call.prompt_id, call.outcome) == (
            MODEL,
            "explain-assessment/2",
            "answered",
        )
        assert call.requests == 1 and call.prompt_tokens > 0 and call.completion_tokens > 0
        assert call.stated_level == "high"
        assert call.settings.max_tokens == 32768 and call.settings.thinking == "disabled"

    async def test_a_malformed_answer_records_every_retry_it_was_billed_for(self, risk) -> None:
        calls: list[int] = []
        item = await _explained_by(risk, _answering("extreme", GOOD, calls))
        assert item.explanation_source == "rule"
        assert item.explanation_unavailable == "the model never answered in the required shape"
        call = item.explanation_call
        assert call is not None and call.outcome == "malformed"
        assert call.requests == len(calls) == 1 + MALFORMED_OUTPUT_RETRIES
        assert call.completion_tokens > 0

    async def test_a_refused_answer_was_still_paid_for(self, risk) -> None:
        item = await _explained(risk, "medium", GOOD)
        assert item.explanation_source == "rule"
        assert item.explanation_call is not None
        assert item.explanation_call.outcome == "answered"
        assert item.explanation_call.requests == 1
        assert item.explanation_call.stated_level == "medium"
        assert item.explanation_dashes_replaced == 0


class TestNoAnswer:
    async def test_a_rate_limit_stops_the_explanations_and_asks_no_more(self, risk) -> None:
        calls: list[int] = []

        def limited(_: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            calls.append(1)
            raise ModelHTTPError(status_code=429, model_name="scripted", body="slow down")

        twice = risk.model_copy(
            update={
                "assessments": [
                    risk.assessments[0],
                    risk.assessments[0].model_copy(update={"update_id": _update("beta").id}),
                ]
            }
        )
        explained = await explain(twice, model=MODEL, agent_model=FunctionModel(limited))
        first, second = explained.assessments
        assert len(calls) == 1
        assert first.explanation_unavailable.startswith("rate-limited")
        assert first.explanation_call is not None
        assert first.explanation_call.outcome == "rate-limited"
        assert first.explanation_call.requests == 0
        assert second.explanation_unavailable.startswith("not asked")
        assert second.explanation_call is None
        assert explained.explanations_refused == 0

    async def test_a_model_that_cannot_be_built_leaves_the_rule_summary(
        self, risk, monkeypatch
    ) -> None:
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        [item] = (await explain(risk, model=MODEL)).assessments
        assert item.explanation_source == "rule"
        assert item.explanation_unavailable.startswith("no model could be built")
        assert item.explanation.startswith("High, decided by usage")
