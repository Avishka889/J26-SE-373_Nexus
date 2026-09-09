"""What answered a stage: every response seen, per stage, and nothing outside one.

A run recorded the model it was configured with and nothing about what
answered. DeepSeek serves some names with another model, and a stage that
retries a malformed answer makes more than one request, so neither the model
behind a stage nor what it used could be read from the record.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest
from c1.model_use import model_use, recording, records_answers, reports_model_use
from c1.service import C1
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.settings import ModelSettings
from pydantic_ai.usage import RequestUsage


class Title(BaseModel):
    title: str


def prose_then_tool(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    """Prose first, which the agent refuses and asks again for, then the tool call."""
    if len(messages) == 1:
        return ModelResponse(parts=[TextPart("A title, in words.")])
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"title": "Ledger"})])


def thinking(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    """One answer whose usage says part of what it produced was reasoning."""
    return ModelResponse(
        parts=[ToolCallPart(info.output_tools[0].name, {"title": "Ledger"})],
        usage=RequestUsage(input_tokens=120, output_tokens=900, details={"reasoning_tokens": 700}),
    )


def _agent(answer: Any = prose_then_tool) -> Agent[None, Title]:
    return Agent(
        FunctionModel(answer), output_type=Title, retries=3, capabilities=[records_answers()]
    )


@dataclass
class _Result:
    notes: dict[str, Any] = field(default_factory=dict)


class TestWhatAStageRecords:
    async def test_every_response_counts_the_refused_one_included(self) -> None:
        with recording() as answers:
            await _agent().run("name it")

        assert [answer.model for answer in answers] == ["function:prose_then_tool:"] * 2

    async def test_nothing_is_kept_outside_a_stage(self) -> None:
        agent = _agent()
        await agent.run("name it")

        with recording() as answers:
            pass

        assert answers == []

    async def test_two_stages_at_once_never_see_each_other(self) -> None:
        # The orchestrator runs two workers against one component, and both
        # can be inside a stage on the same agents at the same moment.
        agent = _agent()

        async def stage() -> int:
            with recording() as answers:
                await asyncio.gather(agent.run("a"), agent.run("b"))
            return len(answers)

        assert await asyncio.gather(stage(), stage()) == [4, 4]

    async def test_reasoning_is_read_where_the_provider_reports_it(self) -> None:
        with recording() as answers:
            await _agent(thinking).run("name it")

        assert model_use(answers) == {
            "answered_by": ["function:thinking:"],
            # The agent sent nothing about thinking, so the provider decided.
            "thinking": ["default"],
            "requests": 1,
            "tokens_in": 120,
            "tokens_out": 900,
            "reasoning_tokens": 700,
        }

    async def test_what_a_request_asked_about_thinking_is_read_from_its_settings(self) -> None:
        # What every component sends DeepSeek, read from the request itself, so
        # a stage's record says it without borrowing its run's.
        agent = Agent(
            FunctionModel(thinking),
            output_type=Title,
            model_settings=ModelSettings(extra_body={"thinking": {"type": "disabled"}}),
            capabilities=[records_answers()],
        )

        with recording() as answers:
            await agent.run("name it")

        assert model_use(answers)["thinking"] == ["disabled"]  # type: ignore[index]

    def test_a_stage_that_asked_no_model_says_nothing(self) -> None:
        assert model_use([]) is None


#: Every stage this component runs that asks a model. Naming a project is not a
#: stage: it answers with a title and has no notes to carry this.
MODEL_STAGES = (
    "parse_requirements",
    "build_graph",
    "recommend",
    "write_uml",
    "draw_wireframes",
    "plan_sprint",
)


@pytest.mark.parametrize("stage", MODEL_STAGES)
def test_every_stage_that_asks_a_model_reports_what_answered(stage: str) -> None:
    assert getattr(getattr(C1, stage), "reports_model_use", False), f"{stage} does not report"


class TestAStageMethodReportsIt:
    async def test_its_notes_carry_what_answered_beside_its_own(self) -> None:
        agent = _agent()

        @reports_model_use
        async def stage() -> _Result:
            await agent.run("name it")
            return _Result(notes={"returned": 1})

        result = await stage()

        assert result.notes["returned"] == 1
        assert result.notes["model_use"]["requests"] == 2

    async def test_a_stage_that_asked_no_model_gets_nothing_added(self) -> None:
        @reports_model_use
        async def stage() -> _Result:
            return _Result(notes={"returned": 0})

        assert (await stage()).notes == {"returned": 0}
