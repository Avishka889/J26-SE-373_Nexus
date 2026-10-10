"""The settings every agent in the component shares.

These exist because the failure they guard against is silent. An answer that does
not fit the output ceiling is not refused: it arrives shorter. Every draft type
here defaults its fields to empty so the repair loop can read a malformed answer,
which means a truncated graph validates as a graph with fewer nodes, or none.
"""

import json
from collections.abc import Iterator

import httpx
import pytest
from c1.agents import CEILING_VARIABLE, PROVIDER_OUTPUT_CEILING, settings_for
from c1.architecture.explain import build_explainer
from c1.llm.extractor import build_agent
from c1.naming import build_naming_agent
from c1.sag.extractor import build_graph_agent
from c1.sprint.extractor import build_sprint_agent
from c1.uml.sequence import build_sequence_agent
from c1.wireframes.extractor import build_wireframe_agent
from pydantic_ai import Agent, models
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider

#: Every agent the component builds. A new one belongs here on the day it is
#: written, which is the point of listing them rather than globbing.
BUILDERS = (
    ("requirements", build_agent),
    ("graph", build_graph_agent),
    ("wireframes", build_wireframe_agent),
    ("sprint", build_sprint_agent),
    ("sequence", build_sequence_agent),
    ("explainer", build_explainer),
    ("naming", build_naming_agent),
)

ANTHROPIC = "anthropic:claude-sonnet-5"
#: Any Groq string does: the point is a provider the ceiling table says
#: nothing about. Deliberately not a real model name, so this test does not
#: have to be revisited every time a provider retires one.
GROQ = "groq:any-model"


class TestTheOutputCeiling:
    """Stated per provider, because the library defaults disagree with each other."""

    def test_anthropic_gets_more_room_than_the_library_default(self) -> None:
        # 4096 is what pydantic-ai gives Anthropic when nothing is said, and the
        # run that proved it too small returned a graph with no edges at all.
        settings = settings_for(ANTHROPIC)
        assert settings is not None
        assert settings["max_tokens"] > 4096

    def test_a_provider_this_module_says_nothing_about_is_left_alone(self) -> None:
        # Groq is passed NOT_GIVEN by pydantic-ai, so its own default applies.
        # Capping it here would recreate the truncation bug on the provider that
        # was working, and nothing in the library exposes its real limit.
        assert settings_for(GROQ) is None
        assert "groq" not in PROVIDER_OUTPUT_CEILING

    def test_the_ceiling_can_be_pinned_for_a_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # An evaluation comparing two providers wants one number for both, and a
        # number that decides what a run can produce belongs in configuration.
        monkeypatch.setenv(CEILING_VARIABLE, "8192")
        assert settings_for(ANTHROPIC) == {"max_tokens": 8192}
        assert settings_for(GROQ) == {"max_tokens": 8192}

    def test_a_built_model_is_read_the_same_way_as_a_string(self) -> None:
        # The builders take either, and the whole test suite passes instances.
        # A provider read off the front of a string raises on every one of them.
        from pydantic_ai.models.test import TestModel

        assert settings_for(TestModel()) is None

    def test_a_blank_setting_is_not_a_ceiling_of_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # An unset variable in a .env arrives as an empty string, and int("")
        # raises. The provider table has to answer instead.
        monkeypatch.setenv(CEILING_VARIABLE, "")
        assert settings_for(ANTHROPIC) == {"max_tokens": PROVIDER_OUTPUT_CEILING["anthropic"]}
        assert settings_for(GROQ) is None

    def test_an_override_that_is_not_a_number_leaves_the_table_in_force(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # It used to raise from int() as soon as an agent was built, so a typo
        # in a .env stopped the component instead of being reported.
        monkeypatch.setenv(CEILING_VARIABLE, "plenty")
        assert settings_for(ANTHROPIC) == {"max_tokens": PROVIDER_OUTPUT_CEILING["anthropic"]}
        assert settings_for(GROQ) is None


@pytest.fixture
def requests_allowed() -> Iterator[None]:
    """The conftest blocks model requests for the whole session.

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
class TestWhatDeepSeekReceives:
    """Read from the request body a mock transport receives, not from the settings.

    DeepSeek is the lane every phase runs on, and both of its traps were
    invisible to a test on the settings object. pydantic-ai sends a `max_tokens`
    setting as `max_completion_tokens`, which DeepSeek ignores. And the override
    replaced the whole settings, dropping the body that turns thinking off, so
    pinning a ceiling for an evaluation made every forced tool call a 400.
    """

    async def test_the_override_reaches_deepseek_as_the_field_its_api_reads(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv(CEILING_VARIABLE, "12000")

        sent = await _sent_to_deepseek()

        assert sent["max_tokens"] == 12000
        assert "max_completion_tokens" not in sent

    async def test_the_override_keeps_thinking_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(CEILING_VARIABLE, "12000")

        sent = await _sent_to_deepseek()

        assert sent["thinking"] == {"type": "disabled"}

    async def test_without_the_override_deepseek_keeps_its_own_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The table gives DeepSeek no ceiling, so nothing is sent and its 8K applies.
        monkeypatch.delenv(CEILING_VARIABLE, raising=False)

        sent = await _sent_to_deepseek()

        assert "max_tokens" not in sent and "max_completion_tokens" not in sent
        assert sent["thinking"] == {"type": "disabled"}


class TestEveryAgentAsksForThem:
    """The table is worthless if a builder forgets to consult it."""

    @pytest.mark.parametrize(("name", "build"), BUILDERS, ids=[n for n, _ in BUILDERS])
    def test_the_builder_passes_the_settings_through(
        self, name: str, build, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Pinned rather than provider derived, so this works on the `test` model
        # string and proves the builder called `settings_for` at all.
        monkeypatch.setenv(CEILING_VARIABLE, "12345")
        assert (build("test").model_settings or {}).get("max_tokens") == 12345, (
            f"the {name} agent ignores the shared settings"
        )

    @pytest.mark.parametrize(("name", "build"), BUILDERS, ids=[n for n, _ in BUILDERS])
    def test_the_builder_adds_nothing_when_there_is_nothing_to_add(self, name: str, build) -> None:
        assert not build("test").model_settings, f"the {name} agent invents a setting"

    @pytest.mark.parametrize(("name", "build"), BUILDERS, ids=[n for n, _ in BUILDERS])
    def test_the_builder_survives_a_built_model(self, name: str, build) -> None:
        # How every other test in this package builds these agents. Reading a
        # provider off the front of a string broke all of them at once.
        from pydantic_ai.models.test import TestModel

        assert build(TestModel()) is not None, f"the {name} agent refuses a built model"

    @pytest.mark.parametrize(("name", "build"), BUILDERS, ids=[n for n, _ in BUILDERS])
    async def test_every_response_it_gets_is_recorded(self, name: str, build) -> None:
        # A stage can say what answered only if every agent it uses reports
        # every response. A model that only ever answers in prose is refused
        # until the agent gives up, and each refused answer still counts.
        from c1.model_use import recording
        from pydantic_ai.exceptions import UnexpectedModelBehavior
        from pydantic_ai.messages import ModelResponse, TextPart
        from pydantic_ai.models.function import FunctionModel

        def prose(messages, info) -> ModelResponse:
            return ModelResponse(parts=[TextPart("An answer in words, not in the shape asked.")])

        agent = build(FunctionModel(prose))
        with recording() as answers, pytest.raises(UnexpectedModelBehavior):
            await agent.run("anything")

        assert answers, f"the {name} agent's responses are not recorded"


class TestTheRejectedDraftIsWrittenDown:
    """What a stage produced before it was refused, since nothing else keeps it.

    The repair loops discard their last draft when they give up. Diagnosing a
    graph that came back with nodes and no edges meant inferring its shape from
    the order the rules run in, because the answer itself was gone by the time
    anyone looked.
    """

    async def test_a_refused_graph_reaches_the_log(self, caplog: pytest.LogCaptureFixture) -> None:
        from c1.sag.extractor import CouldNotBuildGraph, extract_graph
        from pydantic_ai.models.test import TestModel
        from sdlc_contracts import ParsedRequirement

        # The exact failure this exists for: nodes, and no edges.
        agent = build_graph_agent(
            TestModel(
                custom_output_args={
                    # Two nodes, because `no-isolated-node` deliberately
                    # exempts a graph of one: a lone node has nothing to
                    # connect to.
                    "nodes": [
                        {
                            "id": "a1",
                            "kind": "actor",
                            "label": "Driver",
                            "traces": ["R-1"],
                            "actor_kind": "primary",
                        },
                        {
                            "id": "e1",
                            "kind": "entity",
                            "label": "Consignment",
                            "traces": ["R-1"],
                            "attributes": [{"name": "id", "type": "string"}],
                        },
                    ],
                    "edges": [],
                }
            )
        )
        requirement = ParsedRequirement(
            id="R-1",
            text="A driver collects a consignment.",
            type="functional",
            priority="must",
            confidence=80,
        )

        with caplog.at_level("ERROR"), pytest.raises(CouldNotBuildGraph):
            await extract_graph([requirement], agent=agent, requirements_text="A driver collects.")

        written = "\n".join(r.getMessage() for r in caplog.records)
        assert "architecture-graph rejected" in written
        # The draft itself, not a summary: the node is there and so is the empty
        # edge list, which is the whole diagnosis in one line.
        assert '"edges":[]' in written.replace(" ", "")
        assert "Driver" in written
        assert "no-isolated-node" in written
