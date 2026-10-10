"""Thinking, behind a switch that is off by default.

DeepSeek refuses a forced tool call while it thinks: "`required` and named tool
choices are not supported in thinking mode; the API returns a `400` error" (its
API reference). A component that thinks therefore asks for its answer as JSON,
through DeepSeek's JSON mode, and one that does not sends exactly what it always
sent. These read the request body a mock transport receives, as the output
ceiling tests do; no request leaves the process.
"""

import json
from collections.abc import Callable, Iterator

import httpx
import pytest
from c1.agents import output_for, settings_for
from c1.architecture.explain import build_explainer
from c1.llm.extractor import build_agent
from c1.model_use import model_use, recording, records_answers
from c1.naming import build_naming_agent
from c1.sag.extractor import build_graph_agent
from c1.service import C1
from c1.sprint.extractor import build_sprint_agent
from c1.uml.sequence import build_sequence_agent
from c1.wireframes.extractor import build_wireframe_agent
from pydantic import BaseModel
from pydantic_ai import Agent, PromptedOutput, models
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider

#: The builders the stages use. Naming is a builder too, and never thinks.
STAGE_BUILDERS = (
    ("requirements", build_agent),
    ("graph", build_graph_agent),
    ("explainer", build_explainer),
    ("sequence", build_sequence_agent),
    ("wireframes", build_wireframe_agent),
    ("sprint", build_sprint_agent),
)


class Title(BaseModel):
    title: str


@pytest.fixture
def requests_allowed() -> Iterator[None]:
    """The conftest blocks model requests; these land on a mock transport."""
    before = models.ALLOW_MODEL_REQUESTS
    models.ALLOW_MODEL_REQUESTS = True
    try:
        yield
    finally:
        models.ALLOW_MODEL_REQUESTS = before


def _deepseek(answer: Callable[[httpx.Request], httpx.Response]) -> tuple[OpenAIChatModel, list]:
    """DeepSeek's chat model on a mock transport, and the bodies it is sent."""
    sent: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return answer(request)

    provider = DeepSeekProvider(
        api_key="not-a-key", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
    )
    return OpenAIChatModel("deepseek-flash", provider=provider), sent


def _refuse(request: httpx.Request) -> httpx.Response:
    """Stops the run at its first request, which is all a body test needs."""
    return httpx.Response(400, json={"error": {"message": "stop", "type": "invalid_request_error"}})


def _answering(content: str, *, reasoning: str = "", reasoning_tokens: int = 0):
    def answer(request: httpx.Request) -> httpx.Response:
        message: dict = {"role": "assistant", "content": content}
        if reasoning:
            message["reasoning_content"] = reasoning
        usage: dict = {"prompt_tokens": 40, "completion_tokens": 60, "total_tokens": 100}
        if reasoning_tokens:
            usage["completion_tokens_details"] = {"reasoning_tokens": reasoning_tokens}
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": "deepseek-flash",
                "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
                "usage": usage,
            },
        )

    return answer


async def _first_body(build, thinking: str) -> dict:
    model, sent = _deepseek(_refuse)
    with pytest.raises(ModelHTTPError):
        await build(model, thinking=thinking).run("anything")
    return sent[0]


@pytest.mark.usefixtures("requests_allowed")
class TestWhatAStageSends:
    @pytest.mark.parametrize(("name", "build"), STAGE_BUILDERS, ids=[n for n, _ in STAGE_BUILDERS])
    async def test_off_sends_what_was_always_sent(self, name: str, build) -> None:
        body = await _first_body(build, "off")

        assert body["tool_choice"] == "required", f"{name} stopped forcing its tool call"
        assert body["thinking"] == {"type": "disabled"}
        assert "response_format" not in body and "reasoning_effort" not in body

    @pytest.mark.parametrize(("name", "build"), STAGE_BUILDERS, ids=[n for n, _ in STAGE_BUILDERS])
    async def test_thinking_asks_for_json_and_forces_no_tool(self, name: str, build) -> None:
        body = await _first_body(build, "high")

        assert "tools" not in body and "tool_choice" not in body, f"{name} still forces a tool"
        assert body["response_format"] == {"type": "json_object"}
        assert body["thinking"] == {"type": "enabled", "reasoning_effort": "high"}
        assert body["reasoning_effort"] == "high"
        # DeepSeek's JSON mode asks for the word in the prompt, with the shape.
        instructions = " ".join(
            m.get("content") or "" for m in body["messages"] if m["role"] in {"system", "developer"}
        )
        assert "JSON" in instructions and "properties" in instructions

    async def test_a_json_answer_is_read_into_the_shape_and_its_level_recorded(self) -> None:
        model, _ = _deepseek(
            _answering('{"title": "Ledger"}', reasoning="A short title.", reasoning_tokens=45)
        )
        agent = Agent(
            model,
            output_type=output_for(Title, model, thinking="max"),
            model_settings=settings_for(model, thinking="max"),
            capabilities=[records_answers()],
        )

        with recording() as answers:
            result = await agent.run("name it")

        assert result.output == Title(title="Ledger")
        use = model_use(answers)
        assert use is not None
        assert use["thinking"] == ["max"] and use["reasoning_tokens"] == 45


class TestTheSwitch:
    def test_only_the_four_levels_are_taken(self) -> None:
        with pytest.raises(ValueError, match="thinking is one of"):
            settings_for("deepseek:deepseek-flash", thinking="medium")

    def test_a_provider_whose_thinking_this_does_not_turn_on_is_left_as_it_was(self) -> None:
        assert settings_for("anthropic:claude-sonnet-5", thinking="high") == settings_for(
            "anthropic:claude-sonnet-5"
        )
        assert output_for(Title, "anthropic:claude-sonnet-5", thinking="high") is Title

    def test_the_component_builds_its_stages_at_its_level_and_naming_never_thinks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "placeholder")

        thinking = C1("deepseek:deepseek-flash", thinking="high")
        plain = C1("deepseek:deepseek-flash")

        stages = [a for a in thinking._agents() if a is not thinking._naming]
        assert all(isinstance(agent.output_type, PromptedOutput) for agent in stages)
        assert not isinstance(thinking._naming.output_type, PromptedOutput)
        assert not any(isinstance(agent.output_type, PromptedOutput) for agent in plain._agents())

    def test_the_naming_builder_would_think_so_the_component_is_what_keeps_it_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Which is why the test above holds the component to it, not the builder.
        monkeypatch.setenv("DEEPSEEK_API_KEY", "placeholder")
        assert isinstance(
            build_naming_agent("deepseek:deepseek-flash", thinking="high").output_type,
            PromptedOutput,
        )


class TestTheProbe:
    """The probe asks at the level it is given, so step 4 measures what a run would send."""

    def test_the_level_is_read_from_the_command_line_and_defaults_to_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from c1 import probe as module

        asked: list[str] = []

        async def fake(model: str, *, thinking: str = "off") -> int:
            asked.append(thinking)
            return 0

        monkeypatch.setattr(module, "probe", fake)
        monkeypatch.setattr("sys.argv", ["probe", "deepseek:deepseek-flash", "high"])
        assert module.main() == 0
        monkeypatch.setattr("sys.argv", ["probe", "deepseek:deepseek-flash"])
        assert module.main() == 0

        assert asked == ["high", "off"]

    def test_a_level_that_is_not_one_of_the_four_is_refused(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from c1 import probe as module

        monkeypatch.setattr("sys.argv", ["probe", "deepseek:deepseek-flash", "medium"])

        assert module.main() == 64
        assert "off, low, high, max" in capsys.readouterr().out

    @pytest.mark.usefixtures("requests_allowed")
    async def test_it_asks_at_the_level_it_is_given(self) -> None:
        from c1 import probe as module

        sent: list[dict] = []

        def refuse(request: httpx.Request) -> httpx.Response:
            sent.append(json.loads(request.content))
            return httpx.Response(400, json={"error": {"message": "stop"}})

        provider = DeepSeekProvider(
            api_key="not-a-key",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(refuse)),
        )
        model = OpenAIChatModel("deepseek-flash", provider=provider)

        # The refusal reads as unusable; what matters is what was asked.
        assert await module.probe(model, thinking="high") == 2
        assert sent[0]["response_format"] == {"type": "json_object"}
        assert sent[0]["thinking"] == {"type": "enabled", "reasoning_effort": "high"}
