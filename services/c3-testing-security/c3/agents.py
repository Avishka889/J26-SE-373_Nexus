"""Shared agent policy for C3: retries, output ceilings, and the provider lane.

The same split C1 established and C2 inherited. The repair loop is about a well
formed answer that breaks a rule and is bounded per stage. This module is about
answers that could not be read at all, which belongs to pydantic-ai: text
instead of a tool call, a tool call missing a required field.

C3's lane is OpenRouter, and the reason is arithmetic rather than preference:
free tier limits are per provider, this component makes more calls than the
other three together once the benchmark sweeps start, and sharing a lane with
the design phase would mean one evaluation run spending the quota a demo needs.
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
#:
#: Anthropic's library default of 4096 was already found silently low by C1.
#: Google counts hidden thinking against max_output_tokens, so a tight cap
#: surfaces as "exceeded maximum output retries" rather than as truncation.
#: OpenRouter fronts many models with many defaults, so this component states
#: one rather than inheriting whichever the routed model happens to carry.
#: A provider absent from this table gets no max_tokens at all, exactly as
#: pydantic-ai would have it.
PROVIDER_OUTPUT_CEILING: dict[str, int] = {
    "anthropic": 16384,
    "google": 65536,
    "openrouter": 16384,
}

#: Pin the ceiling for one run, for an evaluation that needs it fixed across
#: providers. Named like `C3_MODEL`, for the same reason.
CEILING_VARIABLE = "C3_MAX_OUTPUT_TOKENS"

#: Providers whose API reads the ceiling as `max_tokens` in the request body.
#:
#: pydantic-ai sends a `max_tokens` setting to an OpenAI compatible chat API as
#: `max_completion_tokens`, and DeepSeek's reference names `max_tokens` only, so
#: a ceiling set the ordinary way never reached it and its default applied: 8K
#: tokens with thinking off. C4 found it on a pass where every long answer
#: stopped at exactly 8,192 (2026-09-28). For these providers the ceiling
#: travels in the body under the name the API reads.
CEILING_IN_BODY = frozenset({"deepseek"})

log = logging.getLogger(__name__)


#: What a provider needs in its request body before it will do this platform's
#: work, keyed by prefix.
#:
#: DeepSeek's flash model is in thinking mode by default and refuses a forced
#: tool choice there, with a 400 that says exactly that. Every structured
#: output in this platform is a forced tool call, so without this the provider
#: is unusable and the probe reports it as such. `ModelSettings(thinking=False)`
#: does not reach it, which was the first thing tried: the parameter travels in
#: the body under the provider's own name.
PROVIDER_BODY: dict[str, dict[str, object]] = {
    "deepseek": {"thinking": {"type": "disabled"}},
}


#: Where OpenRouter answers, the same address pydantic-ai's own provider uses.
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def model_for(model: str | Model, *, http_client: httpx.AsyncClient | None = None) -> str | Model:
    """The model an agent is built with, so that the free lanes stop on a 429.

    The standing rule for the OpenRouter and Google lanes is that the first rate
    limit ends the run, with no retry, because a retry spends the free quota
    the next run needs. pydantic-ai builds OpenRouter's client with the OpenAI
    SDK's default of two retries, so a 429 was asked three times before
    anything here saw it and the rule held only on paper. Here the client is
    built with none. Google's client makes one attempt unless it is given retry
    options, and nothing gives it any, so a Google string passes through; the
    tests pin both. DeepSeek keeps the SDK default, by decision (2026-09-27).

    A string without a key also passes through unchanged, so pydantic-ai still
    says what is missing in its own words.
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


def _provider(model: str | Model) -> str:
    name = model if isinstance(model, str) else getattr(model, "system", "")
    return str(name).split(":", 1)[0]


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


def settings_for(model: str | Model, *, thinking: str = "off") -> ModelSettings | None:
    """The settings an agent on this model should carry, or none.

    None rather than an empty dict when nothing applies, so a provider this
    table does not know keeps pydantic-ai's own defaults instead of being
    handed a cap this component invented for it.

    The override replaces the table's ceiling and nothing else. It used to
    replace the whole settings, so on DeepSeek it also dropped the body that
    turns thinking off, and the provider refuses every forced tool call in
    thinking mode: setting the variable made the lane unusable.

    `thinking` is the component's level (`THINKING_LEVELS`); off sends what was
    always sent.
    """
    provider = _provider(model)
    ceiling = _ceiling(provider)
    body = _body(provider, thinking)
    settings = ModelSettings()
    if ceiling and provider in CEILING_IN_BODY:
        body["max_tokens"] = ceiling
    elif ceiling:
        settings["max_tokens"] = ceiling
    if body:
        settings["extra_body"] = body
    return settings or None


def _ceiling(provider: str) -> int | None:
    """The override when it is a number, otherwise the table's ceiling for this provider."""
    override = os.environ.get(CEILING_VARIABLE, "").strip()
    if override:
        try:
            return int(override)
        except ValueError:
            log.warning("%s is not a number: %r, ignoring it", CEILING_VARIABLE, override)
    return PROVIDER_OUTPUT_CEILING.get(provider)


def ceiling_sent(settings: ModelSettings | None) -> int | None:
    """The ceiling a request made with these settings carries, wherever it travels."""
    if not settings:
        return None
    body = settings.get("extra_body")
    in_body = body.get("max_tokens") if isinstance(body, dict) else None
    return settings.get("max_tokens") or in_body


def log_rejected(stage: str, attempt: int, reasons: list[str]) -> None:
    """Record a draft the rules refused, so a give up is explicable.

    C1's convention, carried forward: the run that gave up should be able to
    say what it saw, and the evaluation counts these to report how often the
    repair loop converged.
    """
    log.warning(
        "c3 %s rejected draft on attempt %s: %s",
        stage,
        attempt,
        "; ".join(reasons[:3]) or "no reason recorded",
    )
