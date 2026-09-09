"""Promoting a draft flow the rules accepted into the contract type.

Two fields are decided here rather than carried over, because the model was never
allowed to set them.

`terminal` comes from `reads_as_an_ending`, the same function the dead end rule
consults. One source, so the flag on the artefact and the warning about the
artefact cannot disagree: a screen exempted from the warning is exactly a screen
marked terminal, and a reader looking at a flow with no dead end warnings can be
sure the endings are the marked ones.

`covers_story_ids` is left empty. Flows are generated without being shown the
sprint plan, so a flow claiming to cover a story would be claiming something
nothing checked. The next step computes coverage from traces and writes it there.

One field goes the other way and is deliberately dropped. The draft carries
traces on every screen and two rules check them, and none of that reaches the
artefact, which looks like a bug until you ask what would read it. Coverage is
computed per flow, not per screen: a story is covered by a flow and the row then
lists that flow's screens. So the per screen trace is a constraint on generation
rather than a fact about the design. It earns its place by making the model say
which requirement each screen serves, which is what stops it drawing screens
nobody asked for, and it has done that job by the time this function runs.
Persisting it would add a field to the contract that nothing reads.
"""

from sdlc_contracts import FlowLink, FlowScreen, ScreenBlock, WireframeFlow

from ..rules.findings import Report
from .rules import reads_as_an_ending
from .schema import DraftFlow, DraftScreen


def _block(block, /) -> ScreenBlock:
    return ScreenBlock(
        id=block.id,
        kind=block.kind,  # type: ignore[arg-type]
        label=block.label,
        value=block.value or None,
        tone=block.tone or None,  # type: ignore[arg-type]
        linkId=block.link_id or None,
    )


def _screen(screen: DraftScreen) -> FlowScreen:
    return FlowScreen(
        id=screen.id,
        name=screen.name,
        crumbs=list(screen.crumbs),
        blocks=[_block(block) for block in screen.blocks],
        links=[
            FlowLink(
                id=link.id,
                label=link.label,
                targetId=link.target_id,
                variant=link.variant,  # type: ignore[arg-type]
            )
            for link in screen.links
        ],
        # Decided by rule from the name, never by the model. See rules.py.
        terminal=reads_as_an_ending(screen.name),
    )


def to_contract(
    draft: DraftFlow,
    _report: Report,
    *,
    flow_id: str,
    version: str,
    traces: list[str],
) -> WireframeFlow:
    """The flow as the artefact stores it.

    `traces` comes from the brief the flow was planned from rather than from the
    screens, so the flow's own traceability is the journey's, not the union of
    whatever the model happened to write on each screen.
    """
    return WireframeFlow(
        id=flow_id,
        name=draft.name,
        version=version,
        screens=[_screen(screen) for screen in draft.screens],
        traces=list(traces),
        # Computed against the sprint plan in the consistency step, never here.
        coversStoryIds=[],
        pendingRefinement=False,
        refinementNote=None,
    )
