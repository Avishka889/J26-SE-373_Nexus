"""Thinking, behind a switch that is off by default, in this component.

C1 holds the mechanism; these hold C4 to it through its two model stages, the
changelog reading and the explanation, reading the request body a mock
transport receives. A thinking call asks for JSON with no forced tool, and its
call record says the level it ran at, with temperature as none: DeepSeek
ignores temperature while it thinks, so recording zero would claim a setting
the call did not have.
"""

import json
from collections.abc import Callable, Iterator

import httpx
import pytest
from c4.agents import recorded_settings
from c4.risk import assess
from c4.risk.changelog import changelog_agent
from c4.risk.explain import explain, explanation_agent
from c4.service import C4
from pydantic_ai import models
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider
from sdlc_contracts import ChangedSymbol, RiskReport

from .test_assessment import _changelog, _impact
from .test_assessment import _update as _assessed_update
from .test_assessment import _updates as _assessed_updates
from .test_changelog_signal import MODEL, _texts, _update, _updates
from .test_explanation import GOOD

BUILDERS = (("changelog", changelog_agent), ("explanation", explanation_agent))


@pytest.fixture
def requests_allowed() -> Iterator[None]:
    """C4's conftest blocks model requests; these land on a mock transport."""
    before = models.ALLOW_MODEL_REQUESTS
    models.ALLOW_MODEL_REQUESTS = True
    try:
        yield
    finally:
        models.ALLOW_MODEL_REQUESTS = before


@pytest.fixture
async def risk() -> RiskReport:
    """`test_explanation`'s report: one update whose removed symbol the project uses."""
    update = _assessed_update("acme")
    changelog = _changelog((update, "fix", "low"))
    removed = ChangedSymbol(
        update_id=update.id, symbol="thing", kind="removed", source="api-diff", tool="test"
    )
    files = {"src/a.ts": 'import { thing } from "acme";\nthing(); // the call itself\n'}
    impact = await _impact(files, _assessed_updates(update), changelog, symbols=[removed])
    return assess.report(_assessed_updates(update), changelog, impact, version=1)


def _deepseek(answer: Callable[[httpx.Request], httpx.Response]) -> tuple[OpenAIChatModel, list]:
    sent: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return answer(request)

    provider = DeepSeekProvider(
        api_key="not-a-key", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
    )
    return OpenAIChatModel("deepseek-flash", provider=provider), sent


def _answering(content: str) -> Callable[[httpx.Request], httpx.Response]:
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "x",
                "object": "chat.completion",
                "created": 0,
                "model": "deepseek-flash",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": content},
                    }
                ],
                "usage": {"prompt_tokens": 40, "completion_tokens": 60, "total_tokens": 100},
            },
        )

    return answer


def _refuse(request: httpx.Request) -> httpx.Response:
    return httpx.Response(400, json={"error": {"message": "stop"}})


@pytest.mark.usefixtures("requests_allowed")
@pytest.mark.parametrize(("name", "build"), BUILDERS, ids=[n for n, _ in BUILDERS])
@pytest.mark.parametrize("thinking", ["off", "max"])
async def test_what_each_agent_sends_at_each_end_of_the_switch(
    name: str, build, thinking: str
) -> None:
    model, sent = _deepseek(_refuse)
    with pytest.raises(ModelHTTPError):
        await build(model, thinking=thinking).run("anything")
    body = sent[0]

    if thinking == "off":
        assert body["tool_choice"] == "required", f"{name} stopped forcing its tool call"
        assert body["thinking"] == {"type": "disabled"}
        assert "response_format" not in body
    else:
        assert "tools" not in body and "tool_choice" not in body, f"{name} still forces a tool"
        assert body["response_format"] == {"type": "json_object"}
        assert body["thinking"] == {"type": "enabled", "reasoning_effort": "max"}


@pytest.mark.usefixtures("requests_allowed")
async def test_a_thinking_changelog_reading_is_asked_in_json_and_recorded_at_its_level() -> None:
    model, sent = _deepseek(_answering('{"claims": [], "stated_level": "low"}'))
    update = _update()

    answer = await C4(MODEL, agent_model=model, thinking="high").analyse_changelogs(
        _updates(update), _texts(update), version=1
    )

    assert sent[0]["response_format"] == {"type": "json_object"}
    assert sent[0]["thinking"] == {"type": "enabled", "reasoning_effort": "high"}
    call = answer.artefact.per_update[0].model
    assert call.settings.thinking == "high"
    assert call.settings.temperature is None


@pytest.mark.usefixtures("requests_allowed")
async def test_a_thinking_explanation_is_asked_in_json_and_recorded_at_its_level(
    risk: RiskReport,
) -> None:
    model, sent = _deepseek(_answering(json.dumps({"level": "high", "text": GOOD})))

    explained = await explain(risk, model=MODEL, agent_model=model, thinking="low")

    assert sent[0]["response_format"] == {"type": "json_object"}
    [item] = explained.assessments
    assert item.explanation_call is not None
    assert item.explanation_call.settings.thinking == "low"


def test_off_records_what_it_always_recorded() -> None:
    assert recorded_settings(MODEL) == {
        "maxTokens": 32768,
        "thinking": "disabled",
        "temperature": 0.0,
    }


class TestTheProbe:
    """The probe asks at the level it is given, so step 4 measures what a run would send."""

    def test_the_level_is_read_from_the_command_line_and_defaults_to_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from c4 import probe as module

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
        from c4 import probe as module

        monkeypatch.setattr("sys.argv", ["probe", "deepseek:deepseek-flash", "medium"])

        assert module.main() == 64
        assert "off, low, high, max" in capsys.readouterr().out

    @pytest.mark.usefixtures("requests_allowed")
    async def test_it_asks_at_the_level_it_is_given(self) -> None:
        from c4 import probe as module

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
        assert (
            await module.probe("deepseek:deepseek-flash", agent_model=model, thinking="high") == 2
        )
        assert sent[0]["response_format"] == {"type": "json_object"}
        assert sent[0]["thinking"] == {"type": "enabled", "reasoning_effort": "high"}
