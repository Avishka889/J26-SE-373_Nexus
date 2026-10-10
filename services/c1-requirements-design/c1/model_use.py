"""What answered a stage: the model each response named, and what it used.

Every agent this component builds carries `records_answers()`, so every
response it receives is seen, output retries included, without a call site
having to keep its result. A stage method runs inside `recording()`: the
responses its own task gets land in that stage's list, and two stages running
at once (the orchestrator runs two workers against one component) never see
each other's. Outside a stage nothing is kept.

The model is the one the response names, which is what the provider says
answered rather than the string this component was configured with: DeepSeek
serves some names with another model, and a configured string cannot show it.
"""

import functools
from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from pydantic_ai.capabilities import Hooks
from pydantic_ai.messages import ModelResponse


@dataclass(frozen=True)
class Answer:
    """One response a stage received, and what its request asked about thinking."""

    model: str
    #: "disabled" where the request body turned thinking off, "default" where
    #: it said nothing and the provider decided: the words a run records.
    thinking: str
    tokens_in: int
    tokens_out: int
    #: Part of `tokens_out` where the provider reports it (DeepSeek's thinking).
    reasoning_tokens: int


_ANSWERS: ContextVar[list[Answer] | None] = ContextVar("c1_answers", default=None)


def _thinking_asked(settings: Mapping[str, Any] | None) -> str:
    """What a request's settings said about thinking, read rather than assumed."""
    body = (settings or {}).get("extra_body")
    thinking = body.get("thinking") if isinstance(body, Mapping) else None
    kind = thinking.get("type") if isinstance(thinking, Mapping) else None
    if kind == "enabled":
        # The effort it was asked at, so a record tells low from max.
        return str(thinking.get("reasoning_effort") or kind)  # type: ignore[union-attr]
    return str(kind) if kind else "default"


def _seen(ctx: Any, /, *, request_context: Any, response: ModelResponse) -> ModelResponse:
    answers = _ANSWERS.get()
    if answers is not None:
        usage = response.usage
        answers.append(
            Answer(
                model=response.model_name or "not named by the provider",
                thinking=_thinking_asked(request_context.model_settings),
                tokens_in=usage.input_tokens or 0,
                tokens_out=usage.output_tokens or 0,
                reasoning_tokens=int(usage.details.get("reasoning_tokens", 0)),
            )
        )
    return response


def records_answers() -> Hooks[Any]:
    """The capability every agent here is built with, one per agent."""
    return Hooks(after_model_request=_seen)


@contextmanager
def recording() -> Iterator[list[Answer]]:
    """Collect the responses this task's agents receive until the block ends."""
    answers: list[Answer] = []
    token = _ANSWERS.set(answers)
    try:
        yield answers
    finally:
        _ANSWERS.reset(token)


def model_use(answers: list[Answer]) -> dict[str, Any] | None:
    """A stage's model use as its notes carry it, or None when it asked no model."""
    if not answers:
        return None
    return {
        "answered_by": sorted({answer.model for answer in answers}),
        "thinking": sorted({answer.thinking for answer in answers}),
        "requests": len(answers),
        "tokens_in": sum(answer.tokens_in for answer in answers),
        "tokens_out": sum(answer.tokens_out for answer in answers),
        "reasoning_tokens": sum(answer.reasoning_tokens for answer in answers),
    }


def reports_model_use[**P, R](method: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
    """Run a stage method inside `recording()` and add what answered to its notes.

    Under `model_use`, one key, so it never meets a stage's own notes. A stage
    that asked no model gets nothing added. A stage that raises records its
    error and not what it used: the exception carries no notes.
    """

    @functools.wraps(method)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        with recording() as answers:
            result = await method(*args, **kwargs)
        use = model_use(answers)
        if use is not None:
            result.notes["model_use"] = use  # type: ignore[attr-defined]
        return result

    # So a test can ask every stage that calls a model whether it reports.
    wrapped.reports_model_use = True  # type: ignore[attr-defined]
    return wrapped
