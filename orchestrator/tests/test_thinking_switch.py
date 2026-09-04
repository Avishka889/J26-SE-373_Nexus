"""Each phase's thinking switch, from the configuration to the component and the record.

Off unless configured. The components hold what a level sends; these hold the
orchestrator to reading the switch, refusing a level that is not one of the
four, building each phase's component at its level, and saying the level in
the run's record, in Activity and on the AI Model tab.
"""

from typing import Any

import pytest
from orchestrator.clients.thinking import thinking_sent
from orchestrator.components import spec_for
from orchestrator.config import Settings
from orchestrator.wording import run_setup_words
from pydantic import ValidationError
from pydantic_ai import PromptedOutput

DEEPSEEK = "deepseek:deepseek-flash"


def _component(client: Any) -> Any:
    """The component inside an in-process client."""
    return getattr(client, "_c1", None) or getattr(client, "_c2", None) or client._component


class TestTheSwitch:
    def test_every_phase_is_off_unless_configured(self, settings: Settings) -> None:
        assert {settings.c1_thinking, settings.c2_thinking, settings.c3_thinking} == {"off"}
        assert settings.c4_thinking == "off"

    def test_a_level_that_is_not_one_of_the_four_is_refused(self, settings: Settings) -> None:
        with pytest.raises(ValidationError):
            Settings.model_validate({**settings.model_dump(), "c1_thinking": "medium"})

    @pytest.mark.parametrize("component", ["c1", "c2", "c3", "c4"])
    def test_each_phase_is_built_at_its_level_and_records_it(
        self, component: str, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Building a client builds its agents, and a provider refuses to
        # construct without a key. Nothing here calls one.
        monkeypatch.setenv("DEEPSEEK_API_KEY", "placeholder")
        configured = settings.model_copy(
            update={f"{component}_model": DEEPSEEK, f"{component}_thinking": "high"}
        )

        client = spec_for(component).make_client(configured)

        assert client.thinking == "high", "the run would record another level than it ran at"
        assert _component(client).thinking == "high"

    def test_the_detection_arm_thinks_at_testings_level_too(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "placeholder")
        from orchestrator.clients.c3 import InProcessC3

        client = InProcessC3(DEEPSEEK, arms="scanner,llm", thinking="max")

        assert isinstance(client._component._detector.output_type, PromptedOutput)


class TestTheRecord:
    def test_a_body_that_turns_thinking_on_records_its_effort(self) -> None:
        body = {
            "thinking": {"type": "enabled", "reasoning_effort": "max"},
            "reasoning_effort": "max",
        }

        assert thinking_sent({"extra_body": body}) == "max"

    @pytest.mark.parametrize(
        ("level", "words"),
        [
            ("low", "thinking on, low effort"),
            ("high", "thinking on, high effort"),
            ("max", "thinking on, max effort"),
        ],
    )
    def test_activity_says_the_level_in_words(self, level: str, words: str) -> None:
        assert run_setup_words(DEEPSEEK, level) == f"{DEEPSEEK}, {words}"
