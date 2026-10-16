"""Thinking, behind a switch that is off by default, in this component.

C1 holds the mechanism; these hold C3 to it. Every builder is read through the
request body a mock transport receives. C3 builds its agents on first use, deep
inside its stages, so the component's own builds are held by reading its
source: each passes the component's level.
"""

import ast
import json
from collections.abc import Iterator
from functools import partial
from pathlib import Path

import c3.service
import httpx
import pytest
from c3.detect.llm import build_detector, build_triager
from c3.generate.fill import build_filler
from c3.heal.referee import build_referee
from c3.heal.repair import build_repairer
from c3.remediate.patch import build_patcher
from pydantic_ai import models
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider

BUILDERS = (
    ("test filler", build_filler),
    ("detector", build_detector),
    ("triager", build_triager),
    ("repairer, whole file", build_repairer),
    ("repairer, minimal", partial(build_repairer, shape="minimal")),
    ("referee", build_referee),
    ("patcher", build_patcher),
)

#: The builders the component calls on first use.
LAZY = {"build_filler", "build_repairer", "build_patcher", "build_referee"}


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
    body = await _first_body(build, "high")

    assert "tools" not in body and "tool_choice" not in body, f"{name} still forces a tool"
    assert body["response_format"] == {"type": "json_object"}
    assert body["thinking"] == {"type": "enabled", "reasoning_effort": "high"}


def test_every_agent_the_component_builds_on_first_use_takes_its_level() -> None:
    tree = ast.parse(Path(c3.service.__file__).read_text())
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in LAZY
    ]

    assert {call.func.id for call in calls} == LAZY  # type: ignore[union-attr]
    for call in calls:
        level = next((k.value for k in call.keywords if k.arg == "thinking"), None)
        assert level is not None, f"{call.func.id} is built without the level"  # type: ignore[union-attr]
        assert ast.unparse(level) == "self.thinking"


def test_the_component_keeps_its_level() -> None:
    assert c3.service.C3("deepseek:deepseek-flash", thinking="max").thinking == "max"
    assert c3.service.C3("deepseek:deepseek-flash").thinking == "off"


class TestTheProbe:
    """The probe asks at the level it is given, so step 4 measures what a run would send."""

    def test_the_level_is_read_from_the_command_line_and_defaults_to_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from c3 import probe as module

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
        from c3 import probe as module

        monkeypatch.setattr("sys.argv", ["probe", "deepseek:deepseek-flash", "medium"])

        assert module.main() == 64
        assert "off, low, high, max" in capsys.readouterr().out

    @pytest.mark.usefixtures("requests_allowed")
    async def test_it_asks_at_the_level_it_is_given(self) -> None:
        from c3 import probe as module

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
