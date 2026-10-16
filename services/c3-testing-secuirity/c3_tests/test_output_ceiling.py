"""The output ceiling, read from what a request carries rather than from the settings.

DeepSeek is the lane every component runs on by default, and it reads its
ceiling from `max_tokens`. pydantic-ai sends a `max_tokens` setting as
`max_completion_tokens`, which it ignores, so `C3_MAX_OUTPUT_TOKENS` set for a
DeepSeek run never arrived. Worse, the override replaced the whole settings and
with them the body that turns thinking off, and in thinking mode DeepSeek
refuses every forced tool call. A test on the settings object could not see
either, which is how the same trap got through C4: these read the request body
a mock transport receives.
"""

import json
from collections.abc import Iterator

import httpx
import pytest
from c3.agents import CEILING_VARIABLE, ceiling_sent, settings_for
from pydantic_ai import Agent, models
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider


@pytest.fixture
def requests_allowed() -> Iterator[None]:
    """C1's and C2's conftests block model requests for the whole session.

    Every request here lands on a mock transport, so the block is lifted for
    the one test and put back after.
    """
    before = models.ALLOW_MODEL_REQUESTS
    models.ALLOW_MODEL_REQUESTS = True
    try:
        yield
    finally:
        models.ALLOW_MODEL_REQUESTS = before


async def _sent_to_deepseek() -> dict:
    """The body of the one request an agent on DeepSeek sends, answered with "ok"."""
    sent: dict = {}

    def answer(request: httpx.Request) -> httpx.Response:
        sent.update(json.loads(request.content))
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
                        "message": {"role": "assistant", "content": "ok"},
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    provider = DeepSeekProvider(
        api_key="not-a-key", http_client=httpx.AsyncClient(transport=httpx.MockTransport(answer))
    )
    agent = Agent(
        OpenAIChatModel("deepseek-flash", provider=provider),
        model_settings=settings_for("deepseek:deepseek-flash"),
    )
    await agent.run("hello")
    return sent


@pytest.mark.usefixtures("requests_allowed")
async def test_the_override_reaches_deepseek_as_the_field_its_api_reads(monkeypatch) -> None:
    monkeypatch.setenv(CEILING_VARIABLE, "12000")

    sent = await _sent_to_deepseek()

    assert sent["max_tokens"] == 12000
    assert "max_completion_tokens" not in sent


@pytest.mark.usefixtures("requests_allowed")
async def test_the_override_keeps_thinking_off(monkeypatch) -> None:
    monkeypatch.setenv(CEILING_VARIABLE, "12000")

    sent = await _sent_to_deepseek()

    assert sent["thinking"] == {"type": "disabled"}


@pytest.mark.usefixtures("requests_allowed")
async def test_without_the_override_deepseek_keeps_its_own_default(monkeypatch) -> None:
    """C3's table gives DeepSeek no ceiling, so nothing is sent and its 8K applies."""
    monkeypatch.delenv(CEILING_VARIABLE, raising=False)

    sent = await _sent_to_deepseek()

    assert "max_tokens" not in sent and "max_completion_tokens" not in sent
    assert sent["thinking"] == {"type": "disabled"}


def test_on_another_provider_the_override_is_the_ordinary_setting(monkeypatch) -> None:
    monkeypatch.setenv(CEILING_VARIABLE, "12000")

    settings = settings_for("openrouter:google/gemma-4-31b-it:free")

    assert settings == {"max_tokens": 12000}


def test_an_override_that_is_not_a_number_leaves_the_table_in_force(monkeypatch) -> None:
    monkeypatch.setenv(CEILING_VARIABLE, "plenty")

    assert settings_for("openrouter:google/gemma-4-31b-it:free") == {"max_tokens": 16384}


def test_the_probe_prints_the_ceiling_the_request_carries(monkeypatch) -> None:
    monkeypatch.setenv(CEILING_VARIABLE, "12000")
    assert ceiling_sent(settings_for("deepseek:deepseek-flash")) == 12000
    assert ceiling_sent(settings_for("openrouter:any/model")) == 12000

    monkeypatch.delenv(CEILING_VARIABLE)
    assert ceiling_sent(settings_for("deepseek:deepseek-flash")) is None
    assert ceiling_sent(settings_for("groq:any-model")) is None
