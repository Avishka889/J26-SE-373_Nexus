"""Test setup for C1.

The important line is the first one: real model requests are blocked at import,
so a test that forgets to override the model fails loudly instead of quietly
calling a provider and spending money. Tests that genuinely want a live model opt
back in explicitly, and are marked `live` so the ordinary suite never runs them.
"""

import os
from contextlib import AsyncExitStack

import pytest
from pydantic_ai import models

#: Blocked before any test module is imported. pydantic-ai raises rather than
#: calling out, which is the behaviour we want: an accidental live call in CI is
#: a bill and a flake, and a forgotten override is easy to write.
models.ALLOW_MODEL_REQUESTS = False


@pytest.fixture
def allow_live_requests():
    """Opt one test back into calling a real provider.

    Used only by tests marked `live`. It restores the block afterwards even if
    the test fails, so one live test cannot leave the door open for the rest of
    the session.
    """
    models.ALLOW_MODEL_REQUESTS = True
    try:
        yield
    finally:
        models.ALLOW_MODEL_REQUESTS = False


@pytest.fixture
async def live(live_model_name: str):
    """Build a live agent and close its HTTP client when the test ends.

    An agent constructed from a model string makes its own httpx client and owns
    it. Nothing closes it when the test finishes, so the socket is reclaimed by
    the garbage collector during interpreter shutdown, which raises a
    ResourceWarning that pytest turns into an unraisable-exception error. The
    tests all passed and the process still exited 1, which makes "the live suite
    is green" a thing no script can check and a person has to read.

    pydantic-ai already handles this: entering the agent enters its provider, and
    leaving closes the client the provider owns.
    """
    async with AsyncExitStack() as stack:

        async def enter(agent):
            return await stack.enter_async_context(agent)

        yield enter


@pytest.fixture
async def live_agent(live, live_model_name: str):
    """The requirement extraction agent, opened and closed around one test."""
    from c1.llm.extractor import build_agent

    return await live(build_agent(live_model_name))


@pytest.fixture(scope="session")
def live_model_name() -> str:
    """The model a live run pins, from configuration.

    Never a literal in a test. Which model answered is part of a result, and a
    hardcoded name makes a recorded number impossible to reproduce.
    """
    return os.environ.get("C1_MODEL", "anthropic:claude-sonnet-5")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip live tests unless they were asked for by name.

    `-m live` runs them. Anything else, including a bare `pytest`, does not, so
    the suite stays offline, free and deterministic by default.
    """
    if config.getoption("-m") == "live":
        return
    skip = pytest.mark.skip(reason="needs a real provider; run with -m live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
