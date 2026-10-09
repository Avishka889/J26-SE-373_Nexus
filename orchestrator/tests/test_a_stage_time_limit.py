"""An in-process design stage is held to a time limit, as the HTTP client's request is.

A provider request that hangs held a stage, and the run behind it, for as long as
the provider client waits and retries: half an hour, with nothing to cancel it.
The HTTP client gave up after five minutes; the in-process one never did.
"""

import asyncio

import pytest
from orchestrator.clients import c1 as c1_client
from orchestrator.clients.c1 import InProcessC1
from orchestrator.errors import readable_failure
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models.function import AgentInfo, FunctionModel

from .calculator_script import calculator_model


async def _hangs(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    await asyncio.sleep(30)
    raise AssertionError("the stage should have been stopped before this answered")


async def test_a_stage_whose_model_call_hangs_is_stopped_and_says_so(monkeypatch) -> None:
    monkeypatch.setattr(c1_client, "IN_PROCESS_STAGE_SECONDS", 0.2)

    async with InProcessC1(FunctionModel(_hangs)) as component:
        with pytest.raises(TimeoutError) as stopped:
            await component.parse_requirements("A person keeps a list of tasks to do.")

    said = readable_failure(stopped.value)
    assert "took longer than" in said and "Try it again" in said


async def test_a_stage_that_answers_in_time_is_not_touched(monkeypatch) -> None:
    monkeypatch.setattr(c1_client, "IN_PROCESS_STAGE_SECONDS", 30)

    async with InProcessC1(calculator_model()) as component:
        outcome = await component.parse_requirements(
            "A person adds two numbers and sees the total."
        )

    assert outcome.artefact is not None


async def test_a_timeout_the_stage_raises_itself_is_left_as_it_was(monkeypatch) -> None:
    """Only the limit's own expiry is reworded; a stage's own timeout keeps its words."""

    async def times_out() -> None:
        raise TimeoutError("the registry did not answer")

    with pytest.raises(TimeoutError, match="the registry did not answer"):
        await c1_client._within(times_out())
