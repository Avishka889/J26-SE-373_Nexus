"""Naming a project, and refusing the answers that are not titles.

The rules are a plain function, so most of this file needs no model at all. That
is the same shape `check_no_invented_figures` has in test_architecture.py, and
for the same reason: a rule tested through a model is a rule tested slowly and
flakily.
"""

import json

import pytest
from c1.naming import PROMPT_CHARS, build_naming_agent, check_is_a_title, name_project, prompt_for
from pydantic_ai.messages import ModelMessage, ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

BRIEF = (
    "Build a web application for FOMMP (Farmer Organizations Management and "
    "Monitoring Platform) as specified in the attached BRD. Core modules: AC "
    "Profile Management, Business Plan Management, Asset Management."
)


class TestTheRules:
    def test_a_good_title_passes(self) -> None:
        assert check_is_a_title("FOMMP Platform", BRIEF) == "FOMMP Platform"

    def test_trailing_punctuation_is_removed_rather_than_refused(self) -> None:
        assert check_is_a_title("FOMMP Platform.", BRIEF) == "FOMMP Platform"

    @pytest.mark.parametrize(
        "said", ["> FOMMP Platform", "## FOMMP Platform", '"FOMMP Platform"', "**FOMMP Platform**"]
    )
    def test_markdown_and_quotes_around_a_title_are_removed(self, said: str) -> None:
        # One came back as "> Community Library Reservation System" and named
        # the project, quote marker and all.
        assert check_is_a_title(said, BRIEF) == "FOMMP Platform"

    def test_one_word_is_refused(self) -> None:
        with pytest.raises(ValueError, match="words"):
            check_is_a_title("FOMMP", BRIEF)

    def test_a_sentence_is_refused(self) -> None:
        with pytest.raises(ValueError, match="words"):
            check_is_a_title("Build a web application for FOMMP as specified", BRIEF)

    def test_the_opening_of_the_text_is_refused(self) -> None:
        """A model returning the first words has copied, not summarised.

        That is the exact failure this agent exists to fix, so it has to be
        caught rather than accepted as a plausible looking answer.
        """
        with pytest.raises(ValueError, match="opening of the text"):
            check_is_a_title("Build a web", BRIEF)

    def test_a_title_sharing_no_word_with_the_text_is_refused(self) -> None:
        with pytest.raises(ValueError, match="shares no word"):
            check_is_a_title("Enterprise Logistics Suite", BRIEF)

    def test_a_title_of_only_category_words_is_refused(self) -> None:
        """ "Web Application Platform" names a category, not this system."""
        with pytest.raises(ValueError, match="shares no word"):
            check_is_a_title("Web Application Platform", BRIEF)

    def test_one_grounded_word_is_enough_even_if_another_is_not(self) -> None:
        """The check is an intersection, not a subset test.

        "fommp" is in BRIEF and "dashboard" is not. A policy requiring every
        title word to be grounded would refuse this title; the shipped check
        only asks for one shared content word, so it passes.
        """
        assert check_is_a_title("FOMMP Dashboard", BRIEF) == "FOMMP Dashboard"


class TestThePrompt:
    def test_only_the_opening_of_a_long_input_is_sent(self) -> None:
        """A title comes from the opening of a brief, not from its appendices."""
        huge = BRIEF + ("\n\nAppendix. " * 5000)
        assert len(huge) > PROMPT_CHARS

        prompt = prompt_for(huge)
        assert len(prompt) < PROMPT_CHARS + 200
        assert "FOMMP" in prompt


def agent_returning(payload: dict, *, then: dict | None = None):
    """A model that returns this title, then optionally a second one."""
    calls: list[int] = []

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        calls.append(1)
        body = payload if (len(calls) == 1 or then is None) else then
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, json.dumps(body))])

    return build_naming_agent(FunctionModel(respond)), calls


class TestTheAgent:
    async def test_a_good_title_comes_back(self) -> None:
        agent, calls = agent_returning({"title": "FOMMP Platform"})
        assert await name_project(BRIEF, agent=agent) == "FOMMP Platform"
        assert len(calls) == 1

    async def test_a_refused_title_is_asked_for_again(self) -> None:
        """One word is refused, and the second attempt is accepted.

        A loop that re-sent the same prompt and hoped would pass a call count
        test, so what this proves is that the refusal reached the model and a
        different answer came back.
        """
        agent, calls = agent_returning({"title": "FOMMP"}, then={"title": "FOMMP Platform"})

        assert await name_project(BRIEF, agent=agent) == "FOMMP Platform"
        assert len(calls) == 2
