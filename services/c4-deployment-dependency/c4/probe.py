"""Is this provider usable by C4 at all? One call, and a verdict.

    uv run python -m c4.probe deepseek:deepseek-flash
    uv run python -m c4.probe deepseek:deepseek-flash high

C3's probe asks whether a model can point at evidence that exists. C4's asks the
same question in the shape of the changelog signal: given the release notes of
one update, can the model report what changed, quoting the notes character for
character, without reaching outside the releases it was given?

The notes are seeded. The window runs from 1.4.2 (exclusive) to 2.0.0
(inclusive). Inside it are a removal, a behaviour change, a deprecation and a
fix; below it, in 1.4.2 itself, is a second removal that is outside the window
and must not be reported. The verdict is about discipline, not about the level:

- **UNUSABLE**: a quote that is not in the notes, or a symbol its quote does not
  contain. That is the failure the signal's check exists to refuse, shown before
  any evaluation token is spent on it.
- **WORKABLE**: every quote is real, but the model reached outside the window or
  missed the removal. The check refuses the first and the rule copes with the
  second, so the model can be used and the study will show what it costs.
- **SUITABLE**: every quote is real and in the window, and the removal is found.

One call, no retry. A rate limit is reported as a reason to stop.
"""

import asyncio
import os
import sys
import time
from dataclasses import dataclass, field

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.models import Model

from . import prompts
from .agents import CEILING_VARIABLE, MALFORMED_OUTPUT_RETRIES, THINKING_LEVELS, settings_for
from .risk.changelog import changelog_agent
from .risk.claims import ChangelogAnswer, request
from .risk.notes import Section, locate, split_changelog

PROMPT_ID = "changelog-extract/1"

PACKAGE = "acme-client"
FROM_VERSION = "1.4.2"
TO_VERSION = "2.0.0"

NOTES = """\
## 2.0.0
- Removed `Client.connectLegacy()`; use `Client.connect()` instead.
- `retry` now defaults to 3 attempts instead of 0.

## 1.5.0
- Deprecated `Pool.drain()`; it will be removed in 3.0.
- Fixed a crash when the host name was empty.

## 1.4.2
- Removed the undocumented `debug` flag.
"""

#: The releases after the installed version, up to the target.
WINDOW = frozenset({"2.0.0", "1.5.0"})

#: The one change the probe insists on: a removal, in the window, by name.
REMOVED = "Client.connectLegacy"

DIAGNOSES: tuple[tuple[str, str], ...] = (
    ("429", "rate limited: stop rather than retry"),
    ("rate-limited", "rate limited: stop rather than retry"),
    ("rate_limit", "rate limited: stop rather than retry"),
    ("503", "the provider has no capacity right now, which is not a limit you can raise"),
    ("does not exist", "the model name is wrong or has been decommissioned"),
    ("model_not_found", "the model name is wrong or has been decommissioned"),
    ("tool_choice", "the model refuses a forced tool call, which every C4 agent relies on"),
    ("insufficient balance", "the account needs credit before the API will answer"),
    ("api key", "no key for this provider in the environment"),
    ("unknown provider", "pydantic-ai has no provider for this prefix"),
)


def diagnose(message: str) -> str:
    lowered = message.lower()
    for needle, meaning in DIAGNOSES:
        if needle.lower() in lowered:
            return meaning
    return "unrecognised failure, read the message above"


def sections() -> list[Section]:
    """The notes the model is shown: only the releases inside the window."""
    return [section for section in split_changelog(NOTES) if section.version in WINDOW]


def build_agent(
    model: str | Model, *, retries: int = MALFORMED_OUTPUT_RETRIES, thinking: str = "off"
) -> Agent[None, ChangelogAnswer]:
    """The signal's own agent, so the probe measures exactly what the stage will ask."""
    return changelog_agent(model, retries=retries, thinking=thinking)


def prompt() -> str:
    """The same request the signal sends, over every section including the decoy.

    The decoy is in what the model sees, so that reaching outside the window is
    something the model can do and the check can catch.
    """
    return request(PACKAGE, "npm", FROM_VERSION, TO_VERSION, split_changelog(NOTES))


@dataclass
class Findings:
    """What an answer got right and wrong, in the terms of the signal's check."""

    fabricated: list[str] = field(default_factory=list)
    outside: list[str] = field(default_factory=list)
    misattributed: list[str] = field(default_factory=list)
    found_removal: bool = False


def check(answer: ChangelogAnswer) -> Findings:
    """Every claim against the notes: real, in the window, naming what it quotes."""
    every = split_changelog(NOTES)
    findings = Findings()
    for claim in answer.claims:
        home = locate(claim.quote, every)
        if home is None:
            findings.fabricated.append(claim.quote)
            continue
        if home.version not in WINDOW:
            findings.outside.append(f"{claim.quote} (under {home.version})")
            continue
        missing = [symbol for symbol in claim.symbols if symbol not in claim.quote]
        if missing:
            findings.misattributed.append(f"{claim.quote} names {missing}")
            continue
        if claim.kind in ("removal", "breaking") and any(REMOVED in s for s in claim.symbols):
            findings.found_removal = True
    return findings


async def probe(model: str, *, agent_model: Model | None = None, thinking: str = "off") -> int:
    """Ask the provider about one update's notes, at a thinking level. Returns an exit code."""
    print(f"model      {model}")
    print(f"thinking   {thinking}")
    settings = settings_for(model, thinking=thinking)
    source = f" (from {CEILING_VARIABLE})" if os.environ.get(CEILING_VARIABLE) else ""
    # Where the ceiling travels depends on the provider (`agents.CEILING_IN_BODY`); print
    # what the request carries, in the name the provider reads.
    sent = settings.get("max_tokens") or (settings.get("extra_body") or {}).get("max_tokens")
    print(f"ceiling    {sent or 'provider default'}{source}")
    print(f"prompt     {PROMPT_ID} {prompts.load(PROMPT_ID).sha256[:12]}")

    try:
        agent = build_agent(agent_model or model, thinking=thinking)
    except Exception as error:
        print(f"build      FAILED: {type(error).__name__}: {error}")
        print(f"verdict    UNUSABLE ({diagnose(str(error))})")
        return 2

    started = time.monotonic()
    try:
        async with agent:
            result = await agent.run(prompt())
    except ModelHTTPError as error:
        print(f"call       FAILED after {time.monotonic() - started:.1f}s")
        print(f"           HTTP {error.status_code}: {error.body}")
        print(f"verdict    UNUSABLE ({diagnose(f'{error.status_code} {error.body} {error}')})")
        return 2
    except UnexpectedModelBehavior as error:
        print(f"call       answered but never in the required shape ({error})")
        print("verdict    UNUSABLE (cannot satisfy the schema in the shape asked for)")
        return 2
    except Exception as error:
        print(f"call       FAILED: {type(error).__name__}: {error}")
        print(f"verdict    UNUSABLE ({diagnose(str(error))})")
        return 2

    usage = result.usage
    answer = result.output
    found = check(answer)
    print(f"call       ok in {time.monotonic() - started:.1f}s")
    reasoning = usage.details.get("reasoning_tokens", 0)
    print(
        f"tokens     {usage.input_tokens or 0} in / {usage.output_tokens or 0} out, "
        f"{reasoning} of them reasoning; {usage.requests} request(s)"
    )
    print(f"claims     {len(answer.claims)}, stated level {answer.stated_level}")
    for quote in found.fabricated:
        print(f"           not in the notes: {quote!r}")
    for quote in found.misattributed:
        print(f"           symbol not in its quote: {quote}")
    for quote in found.outside:
        print(f"           outside the window: {quote!r}")
    print(f"removal    {'found' if found.found_removal else 'missed'} ({REMOVED})")

    if found.fabricated or found.misattributed:
        print("verdict    UNUSABLE (invented evidence: a quote or a symbol that is not there)")
        return 1
    if found.outside or not found.found_removal:
        print(
            "verdict    WORKABLE (every quote is real, but it reached outside the window or "
            "missed the removal; the check refuses the first and the rule copes with the second)"
        )
        return 0
    print("verdict    SUITABLE (every quote is real and in the window, and the removal is found)")
    return 0


def main() -> int:
    level = sys.argv[2] if len(sys.argv) == 3 else "off"
    if len(sys.argv) not in (2, 3) or level not in THINKING_LEVELS:
        print(__doc__)
        print("give one model string, for example: deepseek:deepseek-flash")
        print(f"and optionally a thinking level: {', '.join(THINKING_LEVELS)}")
        return 64
    return asyncio.run(probe(sys.argv[1], thinking=level))


if __name__ == "__main__":
    raise SystemExit(main())
