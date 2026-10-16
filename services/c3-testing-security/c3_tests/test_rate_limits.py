"""The free lanes stop on the first rate limit, and these count the requests.

The standing rule for the OpenRouter and Google lanes is that a 429 ends the
run with no retry, because a retry spends the free quota the next run needs.
The rule was written down long before anything checked it. pydantic-ai builds
OpenRouter's client with the OpenAI SDK's default of two retries, so a 429 was
asked three times before C3 saw it; nothing here noticed because no run had hit
a rate limit on that lane since the client was built that way.

Both tests answer every request with a 429 and count what arrives. One request
is the rule; three is the SDK's default coming back.
"""

from collections.abc import Iterator

import httpx
import pytest
from c3.agents import model_for
from pydantic_ai import Agent, models
from pydantic_ai.exceptions import ModelHTTPError


@pytest.fixture
def requests_allowed() -> Iterator[None]:
    """C1's and C2's conftests block model requests for the whole session.

    Nothing here leaves the machine, since every request lands on a mock
    transport, so the block is lifted for the one test and put back after.
    """
    before = models.ALLOW_MODEL_REQUESTS
    models.ALLOW_MODEL_REQUESTS = True
    try:
        yield
    finally:
        models.ALLOW_MODEL_REQUESTS = before


def _rate_limited(seen: list[httpx.Request]) -> httpx.AsyncClient:
    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(429, json={"error": {"message": "rate limited", "code": 429}})

    return httpx.AsyncClient(transport=httpx.MockTransport(answer))


@pytest.mark.usefixtures("requests_allowed")
async def test_the_openrouter_lane_asks_once_and_stops(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "not-a-real-key")
    seen: list[httpx.Request] = []

    model = model_for("openrouter:google/gemma-4-31b-it:free", http_client=_rate_limited(seen))
    with pytest.raises(ModelHTTPError) as raised:
        await Agent(model).run("hello")

    assert raised.value.status_code == 429
    assert len(seen) == 1, f"a 429 was asked {len(seen)} times"


@pytest.mark.usefixtures("requests_allowed")
async def test_the_google_lane_asks_once_and_stops() -> None:
    """Google's client is not rebuilt by `model_for`, because it already makes
    one attempt unless it is handed retry options. This pins that default, so
    an upgrade that starts retrying fails here rather than on a quota."""
    from pydantic_ai.models.google import GoogleModel
    from pydantic_ai.providers.google import GoogleProvider

    seen: list[httpx.Request] = []
    provider = GoogleProvider(api_key="not-a-real-key", http_client=_rate_limited(seen))

    with pytest.raises(ModelHTTPError) as raised:
        await Agent(GoogleModel("gemini-3.5-flash-lite", provider=provider)).run("hello")

    assert raised.value.status_code == 429
    assert len(seen) == 1, f"a 429 was asked {len(seen)} times"


def test_other_lanes_pass_through_unchanged() -> None:
    """DeepSeek keeps the SDK's default retries by decision, and a model
    object a test built is already what it should be."""
    assert model_for("deepseek:deepseek-flash") == "deepseek:deepseek-flash"
    assert model_for("google:gemini-3.5-flash-lite") == "google:gemini-3.5-flash-lite"
    marker = object()
    assert model_for(marker) is marker  # type: ignore[arg-type]
