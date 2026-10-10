"""How many malformed answers to absorb before giving up on a stage.

There are two loops in this component and they are easy to confuse, so this
constant is only about one of them.

The repair loop is about a well formed answer that breaks a rule: an actor that is
really a screen, a link to a screen that does not exist. That is bounded at two
attempts and the second attempt is worth having because the prompt changes, since
the rules produce sentences saying what to fix.

This is the other one. It counts answers that could not be read at all, and it
belongs to pydantic-ai rather than to us: output that arrives as text instead of a
tool call, or a tool call missing a required field. Retrying is worth it because
the model is told precisely what was wrong with the shape, and it usually gets it
right on the next turn.

Three, from measurement rather than caution. Two was enough for Llama and is not
enough for a reasoning model: switching to gpt-oss-120b, the requirements stage
died on "Exceeded maximum output retries (2)" and the graph stage had already
needed a third earlier the same day. These retries only ever happen when something
has already gone wrong, so the cost of a spare one is nothing on a healthy run and
a whole stage on an unhealthy one.

Raising this is not a fix for a model that answers badly. A wrong answer is the
rules' problem and they say so in words. This is only for an answer nobody can
parse.
"""

import logging
import os
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel
from pydantic_ai import PromptedOutput
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings

MALFORMED_OUTPUT_RETRIES = 3


#: How much room one answer gets, per provider, because the defaults disagree.
#:
#: pydantic-ai gives Anthropic 4096 output tokens when nothing is said and passes
#: NOT_GIVEN for Groq, so the same component had two ceilings depending on which
#: model string it was handed. That asymmetry is worth removing on its own.
#:
#: This is headroom, not a fix for anything observed. It was added believing 4096
#: had truncated a graph, and the measurement says otherwise: the largest artefact
#: this component has ever stored is the requirements list at roughly 3000 tokens,
#: and a full graph is around 1600. What actually made a graph come back empty,
#: and then come back with its edges missing, is not established. The likeliest
#: remaining explanation is that nothing in the draft schema is required, so a
#: forced tool call is satisfied by an almost empty object.
#:
#: The margin is still worth having: 3000 against 4096 is close enough that a
#: denser brief would sit on the ceiling, and output is billed by what is
#: produced rather than by the cap.
#:
#: Only providers whose library default is low enough to matter appear here. A
#: provider that is absent gets no `max_tokens` at all, which is what it had
#: before this existed: capping a provider that was not capped would risk
#: truncating the one that works, and nothing in pydantic-ai exposes a model's
#: real limit. 16384 is well under what any current Anthropic model will produce,
#: so it bounds a runaway without being reachable in normal use.
PROVIDER_OUTPUT_CEILING: dict[str, int] = {"anthropic": 16384}

#: Pin the ceiling for one run, for an evaluation that needs it fixed across
#: providers. Named like `C1_MODEL`, and for the same reason: a number that
#: decides what a run can produce belongs in configuration, not in a literal.
CEILING_VARIABLE = "C1_MAX_OUTPUT_TOKENS"

#: Providers whose API reads the ceiling as `max_tokens` in the request body.
#:
#: pydantic-ai sends a `max_tokens` setting to an OpenAI compatible chat API as
#: `max_completion_tokens`, and DeepSeek's reference names `max_tokens` only, so
#: a ceiling set the ordinary way never reaches it and its default applies: 8K
#: tokens with thinking off. C4 found it on a pass where every long answer
#: stopped at exactly 8,192 (2026-09-28). For these providers the ceiling
#: travels in the body under the name the API reads.
CEILING_IN_BODY = frozenset({"deepseek"})


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
    return model.split(":", 1)[0] if isinstance(model, str) else model.system


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

    Takes what the builders take. Every builder here accepts a model string or a
    built model, because the tests drive them with `TestModel` and `FunctionModel`
    instances, and a provider read off the front of a string would have raised on
    every one of them.

    `Model.system` is the provider either way: "anthropic" for a model string and
    for an `AnthropicModel` built by hand, "test" for the doubles, which this
    table says nothing about.

    None rather than an empty `ModelSettings`, so a provider this module says
    nothing about is left exactly as pydantic-ai would have it. Silence is the
    correct answer for most of them.

    The override replaces the table's ceiling and nothing else. It used to
    replace the whole settings, so on DeepSeek it also dropped the body that
    turns thinking off, and the provider refuses every forced tool call in
    thinking mode: setting the variable made the component unusable. C3 had the
    same trap until 2026-09-28.

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


log = logging.getLogger(__name__)


def _ceiling(provider: str) -> int | None:
    """The override when it is a number, otherwise the table's ceiling for this provider."""
    override = os.environ.get(CEILING_VARIABLE, "").strip()
    if override:
        try:
            return int(override)
        except ValueError:
            log.warning("%s is not a number: %r, ignoring it", CEILING_VARIABLE, override)
    return PROVIDER_OUTPUT_CEILING.get(provider)


def log_rejected(stage: str, draft: BaseModel, *, attempts: int, rules: Sequence[str]) -> None:
    """Write down the answer that was refused, before the exception loses it.

    The repair loops discard their last draft when they give up, so a failed
    stage reaches the console as a list of rule names with nothing to read them
    against. Working out that one rejected graph had contained nodes and no edges
    meant inferring it from the order the rules happen to run in, which is not a
    thing anyone should have to do twice.

    ERROR rather than DEBUG because a stage failing is an error and this is the
    only record of why: the draft is not stored anywhere. It goes to the console
    log beside the traceback, which is where a failure is actually read.

    The whole draft, not a summary. A summary is a guess about which field will
    matter next time, and the two failures this exists for differed in a field no
    summary would have thought to include.
    """
    log.error(
        "%s rejected after %d attempt(s), broke %s. The refused answer was: %s",
        stage,
        attempts,
        ", ".join(rules) or "nothing, which should not happen",
        draft.model_dump_json(),
    )
