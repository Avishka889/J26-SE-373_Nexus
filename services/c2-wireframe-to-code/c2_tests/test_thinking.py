"""Thinking, behind a switch that is off by default, in this component.

C1 holds the mechanism; these hold C2 to it, reading the request body a mock
transport receives: off sends what it always sent, and a thinking agent asks for
JSON with no forced tool, because DeepSeek refuses one while it thinks.
"""

import json
from collections.abc import Iterator

import httpx
import pytest
from c2.codegen.fill import build_handler_filler, build_page_filler
from c2.contract.llm_arm import build_contract_agent
from c2.service import C2
from c2.stack.explain import build_stack_explainer
from pydantic_ai import PromptedOutput, models
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider

BUILDERS = (
    ("contract", build_contract_agent),
    ("stack explainer", build_stack_explainer),
    ("page filler", build_page_filler),
    ("handler filler", build_handler_filler),
)


@pytest.fixture
def requests_allowed() -> Iterator[None]:
    """The conftest blocks model requests; these land on a mock transport."""
    before = models.ALLOW_MODEL_REQUESTS
    models.ALLOW_MODEL_REQUESTS = True
    try:
        yield
    finally:
        models.ALLOW_MODEL_REQUESTS = before


async def _first_body(build, thinking: str) -> dict:
    """The body of an agent's first request, stopped there with a refusal."""
    sent: list[dict] = []

    def refuse(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(400, json={"error": {"message": "stop"}})

    provider = DeepSeekProvider(
        api_key="not-a-key", http_client=httpx.AsyncClient(transport=httpx.MockTransport(refuse))
    )
    model = OpenAIChatModel("deepseek-flash", provider=provider)
    with pytest.raises(ModelHTTPError):
        await build(model, thinking=thinking).run("anything")
    return sent[0]


@pytest.mark.usefixtures("requests_allowed")
@pytest.mark.parametrize(("name", "build"), BUILDERS, ids=[n for n, _ in BUILDERS])
async def test_off_sends_what_was_always_sent(name: str, build) -> None:
    body = await _first_body(build, "off")

    assert body["tool_choice"] == "required", f"{name} stopped forcing its tool call"
    assert body["thinking"] == {"type": "disabled"}
    assert "response_format" not in body


@pytest.mark.usefixtures("requests_allowed")
@pytest.mark.parametrize(("name", "build"), BUILDERS, ids=[n for n, _ in BUILDERS])
async def test_thinking_asks_for_json_and_forces_no_tool(name: str, build) -> None:
    body = await _first_body(build, "low")

    assert "tools" not in body and "tool_choice" not in body, f"{name} still forces a tool"
    assert body["response_format"] == {"type": "json_object"}
    assert body["thinking"] == {"type": "enabled", "reasoning_effort": "low"}


def test_the_component_builds_every_agent_at_its_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "placeholder")

    thinking = C2("deepseek:deepseek-flash", thinking="high")
    plain = C2("deepseek:deepseek-flash")

    def agents(component: C2) -> list:
        return [
            component._contract_agent,
            component._explainer,
            component._page_filler,
            component._handler_filler,
        ]

    assert all(isinstance(agent.output_type, PromptedOutput) for agent in agents(thinking))
    assert not any(isinstance(agent.output_type, PromptedOutput) for agent in agents(plain))


class TestTheProbe:
    """The probe asks at the level it is given, so step 4 measures what a run would send."""

    def test_the_level_is_read_from_the_command_line_and_defaults_to_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from c2 import probe as module

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
        from c2 import probe as module

        monkeypatch.setattr("sys.argv", ["probe", "deepseek:deepseek-flash", "medium"])

        assert module.main() == 64
        assert "off, low, high, max" in capsys.readouterr().out

    @pytest.mark.usefixtures("requests_allowed")
    async def test_it_asks_at_the_level_it_is_given(self) -> None:
        from c2 import probe as module

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
