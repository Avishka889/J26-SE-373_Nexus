"""What a component asks its provider about thinking, and at which level a run asks it.

A run thinks at the level its account chose for the phase, or as the platform
is configured where it chose nothing (3B). The level travels from the runner to
the component in `RUN_THINKING`, a per task context: the runner sets it around
the graph it drives, LangGraph runs the nodes in tasks that copy it, and two
runs on two workers never see each other's. Each in-process client keeps one
component per level (`Levelled`), so nothing between the runner and the
component has to carry the level by hand.
"""

import asyncio
from collections.abc import Callable, Mapping
from contextlib import AsyncExitStack
from contextvars import ContextVar
from typing import Any

#: The component sent nothing about thinking, so the provider's own default applies.
PROVIDER_DEFAULT = "default"

#: The levels a run can be asked at (`ThinkingLevel` in the contracts).
LEVELS = ("off", "low", "high", "max")

#: The level of the run this task is driving; None outside a run, where a
#: client uses its configured level.
RUN_THINKING: ContextVar[str | None] = ContextVar("run_thinking", default=None)


def thinking_sent(settings: Mapping[str, Any] | None) -> str:
    """Read from the settings the component's agents are built with, never assumed.

    "disabled" where the request body turns thinking off, as every component
    does for DeepSeek, whose thinking mode refuses the forced tool calls the
    platform's structured answers depend on; "default" where the body says
    nothing about it and the provider decides.
    """
    body = (settings or {}).get("extra_body")
    thinking = body.get("thinking") if isinstance(body, Mapping) else None
    kind = thinking.get("type") if isinstance(thinking, Mapping) else None
    if kind == "enabled":
        # The effort it was asked at, so a run's record tells low from max.
        return str(thinking.get("reasoning_effort") or kind)  # type: ignore[union-attr]
    return str(kind) if kind else PROVIDER_DEFAULT


def level_recorded(thinking: str | None) -> str:
    """The level a run was asked at, read back from what its record says it sent.

    A regeneration resumes the run it belongs to, at the level the run began
    at; what a run records is what its requests said, so a level is the record
    itself and anything else ("disabled", "default", none) was off.
    """
    return thinking if thinking in LEVELS else "off"


class Levelled:
    """One component per thinking level, built on first use and closed with the client.

    `opens` says whether the component is an async context to be entered while
    the client is, as C1's and C2's are. A lock keeps two runs on two workers
    from building the same level twice.
    """

    def __init__(self, build: Callable[[str], Any], default: str, *, opens: bool) -> None:
        self._build = build
        self.default = default
        self._at: dict[str, Any] = {default: build(default)}
        self._opens = opens
        self._stack: AsyncExitStack | None = None
        self._lock = asyncio.Lock()

    @property
    def configured(self) -> Any:
        """The component at the configured level, which is what outside a run means."""
        return self._at[self.default]

    async def open(self) -> None:
        self._stack = AsyncExitStack()
        if self._opens:
            for component in self._at.values():
                await self._stack.enter_async_context(component)

    async def close(self, *args: Any) -> None:
        stack, self._stack = self._stack, None
        if stack is not None:
            await stack.__aexit__(*(args or (None, None, None)))

    async def current(self) -> Any:
        """The component for the run this task is driving."""
        level = RUN_THINKING.get() or self.default
        component = self._at.get(level)
        if component is not None:
            return component
        async with self._lock:
            component = self._at.get(level)
            if component is None:
                component = self._build(level)
                if self._opens and self._stack is not None:
                    await self._stack.enter_async_context(component)
                self._at[level] = component
        return component
