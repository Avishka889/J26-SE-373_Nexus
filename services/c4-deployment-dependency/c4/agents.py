"""Shared agent policy for C4: retries, output ceilings, settings and the provider lane.

The split C1 established and the other two inherited. The checks that refuse a
well formed answer for breaking a rule live with the stage that asks; this module
is about answers that could not be read at all, which belongs to pydantic-ai, and
about the settings every call is made with.

C4's lane is DeepSeek. The changelog step is short, structured and run once per
update, and the lane has answered every call this project has made on it.

**Settings are fixed and recorded (NFR13).** Temperature is zero, because the
same notes should yield the same claims when a study is rerun, and every call
records the settings it was made with beside the prompt's hash.
"""

import logging
import os
from typing import Any

import httpx
from pydantic_ai import PromptedOutput
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

MALFORMED_OUTPUT_RETRIES = 3

#: How much room one answer gets, per provider, because the defaults disagree.
#: A changelog answer is one short claim per sentence that names a change, so
#: its length grows with the window: on the seed set's first live pass
#: (2026-09-27) three of fourteen answers were cut off at 8192 tokens, over 10,
#: 23 and 44 releases, while the longest that fitted (145 claims) took 6882.
#: DeepSeek's flash model allows 384K; 32768 is four times what failed, and it
#: is stated rather than inherited so the probe can print it.
PROVIDER_OUTPUT_CEILING: dict[str, int] = {
    "anthropic": 16384,
    "deepseek": 32768,
    "google": 65536,
    "openrouter": 16384,
}

#: Pin the ceiling for one run. Named like `C4_MODEL`, for the same reason.
CEILING_VARIABLE = "C4_MAX_OUTPUT_TOKENS"

#: The same answer for the same notes, so a rerun study can be compared.
TEMPERATURE = 0.0

#: What a provider needs in its request body before it will do this platform's
#: work, keyed by prefix. DeepSeek's flash model thinks by default and refuses a
#: forced tool call while thinking, and every structured output here is a forced
#: tool call. Found by C3's probe; the parameter travels in the body.
PROVIDER_BODY: dict[str, dict[str, object]] = {
    "deepseek": {"thinking": {"type": "disabled"}},
}

#: Providers whose API reads the output ceiling as `max_tokens` only. pydantic-ai
#: sends the setting as OpenAI's newer `max_completion_tokens`, which DeepSeek's
#: chat completion API does not list and ignores, so its default (8K without
#: thinking) applied instead: every long answer in the 2026-09-28 pass stopped at
#: exactly 8,192 tokens with 32,768 configured. For these the ceiling travels in
#: the body, under the name the API reads.
CEILING_IN_BODY = frozenset({"deepseek"})

#: Where OpenRouter answers, the same address pydantic-ai's own provider uses.
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

log = logging.getLogger(__name__)


def _provider(model: str | Model) -> str:
    name = model if isinstance(model, str) else getattr(model, "system", "")
    return str(name).split(":", 1)[0]


def model_for(model: str | Model, *, http_client: httpx.AsyncClient | None = None) -> str | Model:
    """The model an agent is built with.

    The standing rule for the OpenRouter and Google lanes is that the first rate
    limit ends the run. C4 uses neither, but `C4_MODEL` is configuration and can
    be pointed at one, so an OpenRouter string gets a client with no retries, as
    C3's does. Google's client already makes one attempt, and DeepSeek keeps the
    SDK's default by decision (2026-09-27).
    """
    if not isinstance(model, str) or not model.startswith("openrouter:"):
        return model
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        return model

    from openai import AsyncOpenAI
    from pydantic_ai.models import create_async_http_client
    from pydantic_ai.models.openrouter import OpenRouterModel
    from pydantic_ai.providers.openrouter import OpenRouterProvider

    client = AsyncOpenAI(
        base_url=OPENROUTER_BASE_URL,
        api_key=key,
        http_client=http_client or create_async_http_client(),
        max_retries=0,
    )
    return OpenRouterModel(
        model.split(":", 1)[1], provider=OpenRouterProvider(openai_client=client)
    )


def _ceiling(model: str | Model) -> int | None:
    override = os.environ.get(CEILING_VARIABLE, "").strip()
    if override:
        try:
            return int(override)
        except ValueError:
            log.warning("%s is not a number: %r, ignoring it", CEILING_VARIABLE, override)
    return PROVIDER_OUTPUT_CEILING.get(_provider(model))


#: How hard a component may ask a provider to think, off unless configured.
#:
#: Off is what every component sent before this existed: DeepSeek's thinking
#: turned off, and the answer taken as a forced tool call. The others turn it on
#: at that effort for a provider in `THINKS`, and take the answer as JSON
#: instead, because DeepSeek refuses a forced tool call while it thinks:
#: "`required` and named tool choices are not supported in thinking mode; the
#: API returns a `400` error" (its API reference). The builders default to off,
#: so the probes and the evaluations stay where they were measured.
THINKING_LEVELS = ("off", "low", "high", "max")

#: Providers whose thinking this component can turn on.
THINKS = frozenset({"deepseek"})


def _body(provider: str, thinking: str) -> dict[str, object]:
    """What the request body says about thinking, at this level."""
    if thinking not in THINKING_LEVELS:
        raise ValueError(f"thinking is one of {', '.join(THINKING_LEVELS)}, not {thinking!r}")
    if provider in THINKS and thinking != "off":
        # DeepSeek's thinking guide sends the effort at the top of the request,
        # and its API reference inside `thinking`. Both are sent, so the request
        # reads the same to either; the probe shows which one is honoured.
        return {
            "thinking": {"type": "enabled", "reasoning_effort": thinking},
            "reasoning_effort": thinking,
        }
    return dict(PROVIDER_BODY.get(provider, {}))


def thinks(model: str | Model, thinking: str) -> bool:
    """Whether an agent on this model, at this level, thinks."""
    return thinking != "off" and _provider(model) in THINKS


def output_for(output_type: Any, model: str | Model, *, thinking: str = "off") -> Any:
    """The answer an agent asks for: a forced tool call, or JSON while it thinks.

    JSON through pydantic-ai's prompted output: the schema goes into the
    instructions, with the word DeepSeek's JSON mode asks for, and the request
    carries `response_format: json_object`, so the answer is valid JSON, which
    the agent checks against the schema as it checks a tool call.
    """
    return PromptedOutput(output_type) if thinks(model, thinking) else output_type


def settings_for(model: str | Model, *, thinking: str = "off") -> ModelSettings:
    """The settings every C4 agent on this model is built with, at this thinking level."""
    settings = ModelSettings(temperature=TEMPERATURE)
    provider = _provider(model)
    ceiling = _ceiling(model)
    body = _body(provider, thinking)
    if ceiling and provider in CEILING_IN_BODY:
        body["max_tokens"] = ceiling
    elif ceiling:
        settings["max_tokens"] = ceiling
    if body:
        settings["extra_body"] = body
    return settings


def recorded_settings(model: str | Model, *, thinking: str = "off") -> dict[str, object]:
    """The same settings in the shape a `ModelCall` records them.

    Thinking as its level when it is on, so a study can tell low from max, and
    temperature as none then: DeepSeek ignores it in thinking mode without an
    error, so recording zero would claim a setting the call did not have.
    """
    asked = _body(_provider(model), thinking).get("thinking")
    kind = asked.get("type") if isinstance(asked, dict) else None
    return {
        "maxTokens": _ceiling(model),
        "thinking": thinking if kind == "enabled" else kind,
        "temperature": None if kind == "enabled" else TEMPERATURE,
    }


def log_rejected(stage: str, attempt: int, reasons: list[str]) -> None:
    """Record a draft the rules refused, so a give up is explicable."""
    log.warning(
        "c4 %s rejected draft on attempt %s: %s",
        stage,
        attempt,
        "; ".join(reasons[:3]) or "no reason recorded",
    )
