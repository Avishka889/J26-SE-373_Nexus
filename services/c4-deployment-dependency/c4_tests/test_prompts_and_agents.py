"""Prompts pinned by hash, and the settings every model call is made with (NFR13)."""

import shutil
from collections.abc import Iterator

import httpx
import pytest
from c4 import prompts
from c4.agents import TEMPERATURE, model_for, recorded_settings, settings_for
from pydantic_ai import Agent, models
from pydantic_ai.exceptions import ModelHTTPError


class TestPromptsArePinned:
    def test_every_prompt_in_the_manifest_loads(self) -> None:
        for prompt_id in prompts.manifest():
            loaded = prompts.load(prompt_id)
            assert loaded.text.strip()
            assert len(loaded.sha256) == 64

    def test_every_prompt_file_is_in_the_manifest(self) -> None:
        """A prompt file nobody recorded is a prompt nobody can reproduce."""
        recorded = {entry["file"] for entry in prompts.manifest().values()}
        on_disk = {path.name for path in prompts.HERE.glob("*.md")}
        assert on_disk == recorded

    def test_an_edited_prompt_refuses_to_load(self, tmp_path, monkeypatch) -> None:
        """The teeth: change one word without recording it, and it will not load."""
        for path in prompts.HERE.iterdir():
            if path.is_file():
                shutil.copy(path, tmp_path / path.name)
        edited = tmp_path / "changelog_extract_v1.md"
        edited.write_text(edited.read_text().replace("character for character", "roughly"))
        monkeypatch.setattr(prompts, "HERE", tmp_path)

        with pytest.raises(prompts.PromptChanged, match="edited without its manifest entry"):
            prompts.load("changelog-extract/1")


class TestTheSettingsAreFixedAndRecorded:
    def test_deepseek_thinks_nothing_and_answers_the_same_way_twice(self) -> None:
        settings = settings_for("deepseek:deepseek-flash")
        assert settings["temperature"] == TEMPERATURE == 0.0
        # The ceiling travels in the body, under the name DeepSeek's API reads.
        assert settings["extra_body"] == {"thinking": {"type": "disabled"}, "max_tokens": 32768}
        assert "max_tokens" not in settings

    def test_another_provider_keeps_the_ceiling_where_pydantic_ai_maps_it(self) -> None:
        settings = settings_for("anthropic:claude-sonnet-5")
        assert settings["max_tokens"] == 16384 and "extra_body" not in settings

    def test_what_is_recorded_is_what_is_sent(self) -> None:
        assert recorded_settings("deepseek:deepseek-flash") == {
            "maxTokens": 32768,
            "thinking": "disabled",
            "temperature": 0.0,
        }

    def test_the_ceiling_can_be_pinned_for_a_run(self, monkeypatch) -> None:
        monkeypatch.setenv("C4_MAX_OUTPUT_TOKENS", "2048")
        assert settings_for("deepseek:deepseek-flash")["extra_body"]["max_tokens"] == 2048

    def test_deepseek_keeps_the_sdk_default_by_decision(self) -> None:
        assert model_for("deepseek:deepseek-flash") == "deepseek:deepseek-flash"


@pytest.fixture
def requests_allowed() -> Iterator[None]:
    before = models.ALLOW_MODEL_REQUESTS
    models.ALLOW_MODEL_REQUESTS = True
    try:
        yield
    finally:
        models.ALLOW_MODEL_REQUESTS = before


@pytest.mark.usefixtures("requests_allowed")
async def test_an_openrouter_model_asks_once_on_a_rate_limit(monkeypatch) -> None:
    """If C4_MODEL is ever pointed at OpenRouter, the rule for that lane holds."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "not-a-real-key")
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(429, json={"error": {"message": "rate limited", "code": 429}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(answer))
    with pytest.raises(ModelHTTPError):
        await Agent(model_for("openrouter:some/model:free", http_client=client)).run("hello")
    assert len(seen) == 1


@pytest.mark.usefixtures("requests_allowed")
async def test_deepseeks_ceiling_is_sent_as_the_field_its_api_reads() -> None:
    """What goes over the wire, not what the settings say: the test that would have caught it.

    pydantic-ai sends a `max_tokens` setting as `max_completion_tokens`, which
    DeepSeek's chat completion API does not read, so its default of 8K applied.
    """
    import json

    import httpx
    from pydantic_ai import Agent
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.deepseek import DeepSeekProvider

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

    assert sent["max_tokens"] == 32768
    assert "max_completion_tokens" not in sent
    assert sent["thinking"] == {"type": "disabled"}
