"""Is this provider usable by C1 at all? One call, and a verdict.

    uv run python -m c1.probe anthropic:claude-haiku-4-5
    uv run python -m c1.probe deepseek:deepseek-flash high

Written after a day spent finding out the hard way. Four candidate models were
rejected by four different mechanisms, none of which showed up until a run was
several stages in:

    llama-3.3-70b-versatile   404, decommissioned
    qwen                      exhausted its output retries on the requirements
    openai/gpt-oss-120b       413, one request needs more tokens than the tier
                              allows per minute, so it can never succeed
    groq/compound             400, tool calling not supported at all

Each of those cost a real run to discover. This asks the same question in one
call, before a provider is wired into anything.

It deliberately uses C1's own graph agent and its own rule catalogue rather than
a simplified stand in. The shape that breaks models is the real one: a nested
object with lists of objects inside it, under a forced tool call. An
approximation would pass where the component fails.
"""

import asyncio
import sys
import time

from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior
from sdlc_contracts import ParsedRequirement

from .agents import THINKING_LEVELS
from .sag.extractor import build_graph_agent, prompt_for
from .sag.rules import validate_sag

#: Three requirements, because the probe is about whether the shape can be
#: filled at all, not about design quality. Small enough that the call is cheap
#: and that a token limit failure means the tier cannot serve C1 at any size.
REQUIREMENTS = [
    ParsedRequirement(
        id="R-1",
        text="A customer places an order.",
        type="functional",
        priority="must",
        confidence=80,
    ),
    ParsedRequirement(
        id="R-2",
        text="The store keeps a record of every order.",
        type="functional",
        priority="must",
        confidence=80,
    ),
    ParsedRequirement(
        id="R-3",
        text="A customer pays for an order.",
        type="functional",
        priority="must",
        confidence=80,
    ),
]

#: What each failure means for this component, since the raw error rarely says.
#: Matched on substrings of the provider's own message.
DIAGNOSES: tuple[tuple[str, str], ...] = (
    ("does not exist", "the model name is wrong or has been decommissioned"),
    ("model_not_found", "the model name is wrong or has been decommissioned"),
    ("tool calling` is not supported", "the model cannot call tools, so C1 cannot use it"),
    ("tool_choice", "the model refuses a forced tool call, which all seven agents rely on"),
    ("tokens per minute", "one C1 request is larger than this tier allows per minute"),
    ("rate_limit", "rate limited: check whether the limit is per request or per minute"),
    ("usage limits", "the account's own spend cap is reached, not a model problem"),
    ("api key", "no key for this provider in the environment"),
    ("credit", "the account needs credit before the API will answer"),
    ("unknown provider", "pydantic-ai has no provider for this prefix"),
    ("optional group", "the provider's extra is not installed: add it to C1's dependencies"),
)


def diagnose(message: str) -> str:
    lowered = message.lower()
    for needle, meaning in DIAGNOSES:
        if needle.lower() in lowered:
            return meaning
    return "unrecognised failure, read the message above"


async def probe(model: str, *, thinking: str = "off") -> int:
    """Ask the provider for one graph, at a thinking level. Returns a process exit code."""
    print(f"model      {model}")
    print(f"thinking   {thinking}")
    try:
        agent = build_graph_agent(model, thinking=thinking)
    except Exception as error:
        # Three different types reach here and all mean "not usable": UserError
        # for a missing key, ImportError for a provider whose extra is not
        # installed, ValueError for a prefix pydantic-ai does not know.
        print(f"build      FAILED: {type(error).__name__}: {error}")
        print(f"verdict    UNUSABLE ({diagnose(str(error))})")
        return 2

    started = time.monotonic()
    try:
        result = await agent.run(prompt_for(REQUIREMENTS))
    except ModelHTTPError as error:
        print(f"call       FAILED after {time.monotonic() - started:.1f}s")
        print(f"           HTTP {error.status_code}: {error.body}")
        print(f"verdict    UNUSABLE ({diagnose(str(error.body) + str(error))})")
        return 2
    except UnexpectedModelBehavior as error:
        # The interesting one: it answered, repeatedly, and never in the shape.
        print(f"call       answered but never in the required shape ({error})")
        print("verdict    UNUSABLE (cannot satisfy a nested schema in the shape asked for)")
        return 2
    except Exception as error:
        print(f"call       FAILED: {type(error).__name__}: {error}")
        print(f"verdict    UNUSABLE ({diagnose(str(error))})")
        return 2

    draft = result.output
    usage = result.usage
    print(f"call       ok in {time.monotonic() - started:.1f}s")
    reasoning = usage.details.get("reasoning_tokens", 0)
    print(
        f"tokens     {usage.input_tokens or 0} in / {usage.output_tokens or 0} out, "
        f"{reasoning} of them reasoning; {usage.requests} request(s)"
    )

    # The failure that produced an empty graph twice: both keys are required, so
    # arriving here at all means the provider honoured them.
    print(f"shape      nodes and edges both returned ({len(draft.nodes)} / {len(draft.edges)})")
    if not draft.nodes or not draft.edges:
        print("verdict    UNUSABLE (returned the keys empty, which is not a graph)")
        return 1

    report = validate_sag(
        draft,
        requirement_ids=frozenset(r.id for r in REQUIREMENTS),
        requirements_text=" ".join(r.text for r in REQUIREMENTS),
    )
    print(f"rules      {len(report.errors)} errors, {len(report.warnings)} warnings")
    for finding in report.errors[:5]:
        print(f"           error [{finding.rule_id}] {finding.reason}")

    if report.ok:
        print("verdict    SUITABLE (first attempt passed every rule)")
        return 0
    # Not fatal. The repair loop exists for exactly this, and one attempt is not
    # evidence it cannot recover. But it is worth knowing before a paid run.
    print("verdict    WORKABLE (shape is fine, first attempt broke rules; repair loop would run)")
    return 0


def main() -> int:
    level = sys.argv[2] if len(sys.argv) == 3 else "off"
    if len(sys.argv) not in (2, 3) or level not in THINKING_LEVELS:
        print(__doc__)
        print("give one model string, for example: anthropic:claude-haiku-4-5")
        print(f"and optionally a thinking level: {', '.join(THINKING_LEVELS)}")
        return 64
    return asyncio.run(probe(sys.argv[1], thinking=level))


if __name__ == "__main__":
    raise SystemExit(main())
