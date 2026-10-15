"""Is this provider usable by C2 at all? One call, and a verdict.

    uv run python -m c2.probe google:gemini-2.5-pro
    uv run python -m c2.probe deepseek:deepseek-flash high

C1's probe, aimed at C2's breaking shape: a nested contract draft (entities
with typed fields, endpoints with schemas and trace lists) under a forced
tool call. The design slice is deliberately tiny, so a token failure means
the tier cannot serve C2 at any size, and it reports the output ceiling the
call carried, because Gemini counts hidden thinking against it and a silent
cap surfaces as retries, not truncation.
"""

import asyncio
import os
import sys
import time

from pydantic_ai.exceptions import ModelHTTPError, UnexpectedModelBehavior
from sdlc_contracts import (
    ArchitectureGraph,
    EntityAttribute,
    FlowLink,
    FlowScreen,
    GraphEdge,
    GraphNode,
    ScopeStory,
    ScopeStoryTraces,
    ScreenBlock,
    SprintScope,
    WireframeCoverageRow,
    WireframeFlow,
    WireframesArtefact,
)

from .agents import CEILING_VARIABLE, THINKING_LEVELS, ceiling_sent, settings_for
from .contract.llm_arm import build_contract_agent, prompt_for, to_contract
from .contract.rules import ContractContext, validate_contract

#: One actor, one entity, one action, two screens, one story: whether the
#: shape can be filled at all, not whether the design is good.
GRAPH = ArchitectureGraph(
    nodes=[
        GraphNode(
            id="a1",
            kind="actor",
            label="Member",
            actor_kind="primary",
            traces=["R-1"],
            position={"x": 0, "y": 0},
        ),
        GraphNode(
            id="e1",
            kind="entity",
            label="Booking",
            traces=["R-1"],
            position={"x": 0, "y": 0},
            attributes=[EntityAttribute(name="startsAt", type="datetime")],
        ),
    ],
    edges=[
        GraphEdge(id="ed1", source="a1", target="e1", kind="action", verb="books", traces=["R-1"])
    ],
)

WIREFRAMES = WireframesArtefact(
    flows=[
        WireframeFlow(
            id="book",
            name="Book a slot",
            version="v1",
            coversStoryIds=["US-1"],
            screens=[
                FlowScreen(
                    id="pick",
                    name="Pick a slot",
                    blocks=[ScreenBlock(id="b1", kind="field", label="Starts at")],
                    links=[FlowLink(id="l1", label="Book", target_id="done", variant="primary")],
                ),
                FlowScreen(
                    id="done",
                    name="Booking confirmed",
                    terminal=True,
                    blocks=[ScreenBlock(id="b2", kind="summary", label="Booking summary")],
                    links=[],
                ),
            ],
        )
    ],
    coverage=[
        WireframeCoverageRow(
            story_id="US-1",
            story_title="Book a slot",
            screen_ids=["book/pick", "book/done"],
            covered=True,
        )
    ],
)

SCOPE = SprintScope(
    sprint_name="Sprint 1 (proposed)",
    stories=[
        ScopeStory(
            id="US-1",
            title="Book a slot",
            points=3,
            in_scope=True,
            traces=ScopeStoryTraces(requirement_ids=["R-1"], screen_ids=["book/pick", "book/done"]),
        )
    ],
)

DIAGNOSES: tuple[tuple[str, str], ...] = (
    ("does not exist", "the model name is wrong or has been decommissioned"),
    ("model_not_found", "the model name is wrong or has been decommissioned"),
    ("tool calling` is not supported", "the model cannot call tools, so C2 cannot use it"),
    ("tool_choice", "the model refuses a forced tool call, which every C2 agent relies on"),
    ("tokens per minute", "one C2 request is larger than this tier allows per minute"),
    ("rate_limit", "rate limited: check whether the limit is per request or per minute"),
    ("usage limits", "the account's own spend cap is reached, not a model problem"),
    ("api key", "no key for this provider in the environment"),
    ("credit", "the account needs credit before the API will answer"),
    ("unknown provider", "pydantic-ai has no provider for this prefix"),
    ("optional group", "the provider's extra is not installed: add it to C2's dependencies"),
)


def diagnose(message: str) -> str:
    lowered = message.lower()
    for needle, meaning in DIAGNOSES:
        if needle.lower() in lowered:
            return meaning
    return "unrecognised failure, read the message above"


async def probe(model: str, *, thinking: str = "off") -> int:
    """Ask the provider for one small contract, at a thinking level. Returns an exit code."""
    print(f"model      {model}")
    print(f"thinking   {thinking}")
    # What the request carries, not the setting: on DeepSeek the ceiling travels
    # in the body, where the ordinary setting would have said "provider default".
    ceiling = ceiling_sent(settings_for(model, thinking=thinking))
    source = f" (from {CEILING_VARIABLE})" if os.environ.get(CEILING_VARIABLE) else ""
    print(f"ceiling    {ceiling if ceiling else 'provider default'}{source}")

    try:
        agent = build_contract_agent(model, thinking=thinking)
    except Exception as error:
        print(f"build      FAILED: {type(error).__name__}: {error}")
        print(f"verdict    UNUSABLE ({diagnose(str(error))})")
        return 2

    context = ContractContext(graph=GRAPH, wireframes=WIREFRAMES, scope=SCOPE)
    started = time.monotonic()
    try:
        async with agent:
            result = await agent.run(prompt_for(GRAPH, WIREFRAMES, SCOPE))
    except ModelHTTPError as error:
        print(f"call       FAILED after {time.monotonic() - started:.1f}s")
        print(f"           HTTP {error.status_code}: {error.body}")
        print(f"verdict    UNUSABLE ({diagnose(str(error.body) + str(error))})")
        return 2
    except UnexpectedModelBehavior as error:
        print(f"call       answered but never in the required shape ({error})")
        print("verdict    UNUSABLE (cannot satisfy a nested schema in the shape asked for)")
        return 2
    except Exception as error:
        print(f"call       FAILED: {type(error).__name__}: {error}")
        print(f"verdict    UNUSABLE ({diagnose(str(error))})")
        return 2

    usage = result.usage
    print(f"call       ok in {time.monotonic() - started:.1f}s")
    reasoning = usage.details.get("reasoning_tokens", 0)
    print(
        f"tokens     {usage.input_tokens or 0} in / {usage.output_tokens or 0} out, "
        f"{reasoning} of them reasoning; {usage.requests} request(s)"
    )

    draft = result.output
    print(f"shape      {len(draft.entities)} entities / {len(draft.endpoints)} endpoints")
    if not draft.entities or not draft.endpoints:
        print("verdict    UNUSABLE (returned the keys empty, which is not a contract)")
        return 1

    contract = to_contract(draft, 1, context)
    report = validate_contract(contract, context)
    print(f"rules      {len(report.errors)} errors, {len(report.warnings)} warnings")
    for finding in report.errors[:5]:
        print(f"           error [{finding.rule_id}] {finding.reason}")

    if report.ok:
        print("verdict    SUITABLE (first attempt passed every rule)")
        return 0
    print("verdict    WORKABLE (shape is fine, first attempt broke rules; repair loop would run)")
    return 0


def main() -> int:
    level = sys.argv[2] if len(sys.argv) == 3 else "off"
    if len(sys.argv) not in (2, 3) or level not in THINKING_LEVELS:
        print(__doc__)
        print("give one model string, for example: google:gemini-2.5-pro")
        print(f"and optionally a thinking level: {', '.join(THINKING_LEVELS)}")
        return 64
    return asyncio.run(probe(sys.argv[1], thinking=level))


if __name__ == "__main__":
    raise SystemExit(main())
