"""Is this provider usable by C3 at all? One call, and a verdict.

    uv run python -m c3.probe openrouter:google/gemma-4-31b-it:free
    uv run python -m c3.probe deepseek:deepseek-flash high

C1 and C2 have one of these, and the reason C3 needs its own is that C3 breaks
differently. C2's probe asks whether a model can fill a nested schema under a
forced tool call. C3 assumes that much and asks the question that decides
whether a model can do this component's work at all: **can it point at
evidence that exists, and say nothing when it has none?**

So the probe hands the model a small failing test, the diff between the two
code versions, and one source file, and asks for two things at once: which of
the two the failure is (brittle or a regression), citing a line that is
actually in the diff; and any weakness in the file, citing a line span that is
actually in the file. Then it checks the citations against what it sent.

The verdict is not about whether the answers are right. A model that cites a
line it was given has demonstrated the discipline the whole component is built
on; a model that invents a line number has demonstrated exactly the failure the
guard exists to catch, before a single evaluation number is spent on it.
"""

import asyncio
import os
import sys
import time
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior

from .agents import (
    CEILING_VARIABLE,
    MALFORMED_OUTPUT_RETRIES,
    THINKING_LEVELS,
    ceiling_sent,
    model_for,
    output_for,
    settings_for,
)

# --------------------------------------------------------------- the material

#: The production file, whole, so a line number can be checked against it.
#: Seeded with one obvious weakness (a shell call built from an argument) so
#: the security half of the question has an answer that exists.
SOURCE = """\
import { exec } from "node:child_process";

export function total(items) {
  return items.reduce((sum, item) => sum + item.price, 0);
}

export function archive(name) {
  exec("tar -czf " + name + ".tar.gz ./data");
}
"""

#: What changed between the version the test was written against and the
#: version it now fails on. A rounding rule appeared; the test still expects
#: the old, unrounded answer.
DIFF = """\
--- a/src/orders.js
+++ b/src/orders.js
@@ -3,3 +3,3 @@
 export function total(items) {
-  return items.reduce((sum, item) => sum + item.price, 0);
+  return Math.round(items.reduce((sum, item) => sum + item.price, 0) * 100) / 100;
 }
"""

FAILING_TEST = """\
test("totals three prices", () => {
  expect(total([{price: 1.005}, {price: 2}, {price: 3}])).toBe(6.005);
});
"""

FAILURE = "expected 6.005, received 6.01"

INSTRUCTIONS = (
    "You are a referee, not a repairer. Two questions, and evidence for each.\n"
    "1. A test failed after the production code changed. Say whether it is "
    "`brittle` (the behaviour changed on purpose and the test encodes the old "
    "behaviour), a `regression` (the behaviour changed by accident and the "
    "test is right), or `unclear`. Quote, exactly, one line from the diff you "
    "were given that decides it. Copy the line character for character, "
    "including its leading + or -.\n"
    "2. Report any security weakness in the source file you were given. Give "
    "its CWE id and the first and last line numbers, counting from 1, of the "
    "code that is wrong.\n"
    "Cite nothing you were not given. An empty list is a correct answer when "
    "there is nothing to report, and is always better than an invented one."
)


class ProbeWeakness(BaseModel):
    cwe: str = Field(description="The CWE id, for example CWE-78.")
    start_line: int = Field(description="First line of the weakness, counting from 1.")
    end_line: int = Field(description="Last line of the weakness, counting from 1.")


class ProbeVerdict(BaseModel):
    classification: Literal["brittle", "regression", "unclear"]
    cited_line: str = Field(description="One line, copied exactly from the diff.")
    weaknesses: list[ProbeWeakness] = Field(default_factory=list)


DIAGNOSES: tuple[tuple[str, str], ...] = (
    # The two that matter operationally go first, because the standing rule on
    # this project is to stop on a rate limit rather than retry, and a probe
    # that reports "unrecognised failure" for a 429 is not telling the reader
    # the one thing they have to act on. Both of these were reported as
    # unrecognised the first time this probe met them for real.
    ("429", "rate limited: stop rather than retry, and repin if it persists"),
    ("rate-limited", "rate limited: stop rather than retry, and repin if it persists"),
    ("rate_limit", "rate limited: stop rather than retry, and repin if it persists"),
    ("503", "the provider has no capacity right now, which is not a limit you can raise"),
    ("high demand", "the provider has no capacity right now, which is not a limit you can raise"),
    ("unavailable", "the provider has no capacity right now, which is not a limit you can raise"),
    ("does not exist", "the model name is wrong or has been decommissioned"),
    ("model_not_found", "the model name is wrong or has been decommissioned"),
    ("no endpoints found", "OpenRouter has no provider serving this model right now"),
    ("tool calling` is not supported", "the model cannot call tools, so C3 cannot use it"),
    ("tool_choice", "the model refuses a forced tool call, which every C3 agent relies on"),
    ("tokens per minute", "one C3 request is larger than this tier allows per minute"),
    ("usage limits", "the account's own spend cap is reached, not a model problem"),
    ("api key", "no key for this provider in the environment"),
    ("credit", "the account needs credit before the API will answer"),
    ("unknown provider", "pydantic-ai has no provider for this prefix"),
    ("optional group", "the provider's extra is not installed: add it to C3's dependencies"),
)


def diagnose(message: str) -> str:
    lowered = message.lower()
    for needle, meaning in DIAGNOSES:
        if needle.lower() in lowered:
            return meaning
    return "unrecognised failure, read the message above"


def build_referee_agent(
    model: str, *, retries: int = MALFORMED_OUTPUT_RETRIES, thinking: str = "off"
) -> Agent[None, ProbeVerdict]:
    return Agent(
        model_for(model),
        output_type=output_for(ProbeVerdict, model, thinking=thinking),
        instructions=INSTRUCTIONS,
        retries=retries,
        model_settings=settings_for(model, thinking=thinking),
    )


def prompt() -> str:
    return (
        f"The failing test:\n{FAILING_TEST}\nIt failed with: {FAILURE}\n\n"
        f"What changed in the production code:\n{DIFF}\n"
        f"The source file src/orders.js, in full:\n{SOURCE}"
    )


def _bare(line: str) -> str:
    """A diff line without its marker or its indentation.

    So that quoting `return Math.round(...)` rather than
    `+  return Math.round(...)` counts as a citation. The probe is about
    inventing evidence, not about transcribing it perfectly.
    """
    return line.lstrip().lstrip("+-").strip()


def check_citation(cited: str) -> tuple[bool, str]:
    """Is the quoted line actually in the diff we sent?

    Whitespace insensitive, because a model reformatting its own quote is a
    transcription difference rather than a fabrication, and this probe is
    about fabrication.
    """
    quoted = _bare(cited)
    if not quoted:
        return False, "cited nothing"
    # The file headers and the hunk marker are not code, and a model quoting
    # `a/src/orders.js` has cited a path rather than a change.
    lines = {_bare(line) for line in DIFF.splitlines() if not line.startswith(("---", "+++", "@@"))}
    if quoted in lines - {""}:
        return True, ""
    return False, f"cited a line that is not in the diff: {cited.strip()!r}"


def check_span(weakness: ProbeWeakness) -> tuple[bool, str]:
    """Does the span it named exist in the file we sent?"""
    length = len(SOURCE.splitlines())
    if weakness.start_line < 1 or weakness.end_line > length:
        return False, (
            f"{weakness.cwe} at lines {weakness.start_line}-{weakness.end_line}, "
            f"but the file has {length} lines"
        )
    if weakness.end_line < weakness.start_line:
        return False, f"{weakness.cwe} ends at {weakness.end_line} before it starts"
    return True, ""


async def probe(model: str, *, thinking: str = "off") -> int:
    """Ask the provider to referee one failure, at a thinking level. Returns an exit code."""
    print(f"model      {model}")
    print(f"thinking   {thinking}")
    ceiling = ceiling_sent(settings_for(model, thinking=thinking))
    source = f" (from {CEILING_VARIABLE})" if os.environ.get(CEILING_VARIABLE) else ""
    print(f"ceiling    {ceiling if ceiling else 'provider default'}{source}")

    try:
        agent = build_referee_agent(model, thinking=thinking)
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
        print(f"verdict    UNUSABLE ({diagnose(str(error.body) + str(error))})")
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
    verdict = result.output
    print(f"call       ok in {time.monotonic() - started:.1f}s")
    reasoning = usage.details.get("reasoning_tokens", 0)
    print(
        f"tokens     {usage.input_tokens or 0} in / {usage.output_tokens or 0} out, "
        f"{reasoning} of them reasoning; {usage.requests} request(s)"
    )
    print(f"classified {verdict.classification} (the honest answer here is brittle)")

    cited_ok, why = check_citation(verdict.cited_line)
    print(f"citation   {'resolves' if cited_ok else why}")

    spans = [check_span(weakness) for weakness in verdict.weaknesses]
    resolved = sum(1 for ok, _ in spans if ok)
    print(f"weaknesses {len(verdict.weaknesses)} reported, {resolved} with a span in the file")
    for ok, reason in spans:
        if not ok:
            print(f"           fabricated: {reason}")

    fabricated = len(spans) - resolved
    if not cited_ok and fabricated:
        print("verdict    UNUSABLE (invented evidence on both halves)")
        return 1
    if not cited_ok or fabricated:
        print(
            "verdict    WORKABLE (answered in shape, but invented evidence once; "
            "the span checks would refuse that finding and the run would count it)"
        )
        return 0
    if verdict.classification == "brittle":
        print("verdict    SUITABLE (right call, and every citation resolves)")
        return 0
    print(
        f"verdict    WORKABLE (evidence resolves, but it called a rounding change "
        f"{verdict.classification}; the rules classify first and the model only "
        "referees the ambiguous middle)"
    )
    return 0


def main() -> int:
    level = sys.argv[2] if len(sys.argv) == 3 else "off"
    if len(sys.argv) not in (2, 3) or level not in THINKING_LEVELS:
        print(__doc__)
        print("give one model string, for example: openrouter:google/gemma-4-31b-it:free")
        print(f"and optionally a thinking level: {', '.join(THINKING_LEVELS)}")
        return 64
    return asyncio.run(probe(sys.argv[1], thinking=level))


if __name__ == "__main__":
    raise SystemExit(main())
