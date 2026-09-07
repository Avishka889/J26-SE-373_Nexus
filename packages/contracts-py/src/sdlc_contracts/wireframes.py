"""Wireframes as declarative blocks.

A screen is a list of blocks rather than authored markup, which is what lets the
same screen render at full size in the clickable prototype and scaled down as a
card thumbnail without a special case per screen.
"""

from typing import Literal

from pydantic import Field, model_validator

from .ids import StoryId, Traces
from .wire import WireModel

#: `button` and `display` are what a screen that is used rather than filled in
#: needs: a calculator's keys and the read-out above them, a counter, a timer.
#: With only fields, rows and lists every screen was a form or a table, whatever
#: it was for. A button with a `link_id` goes where that link goes; without one
#: it enters its `value` into the screen's first field, and a value of "" clears
#: it. A display reads out that field, or its own `value` on a screen with none.
ScreenBlockKind = Literal["field", "row", "summary", "banner", "text", "list", "button", "display"]
LinkVariant = Literal["primary", "secondary", "row", "text"]


class ScreenBlock(WireModel):
    id: str = Field(min_length=1)
    kind: ScreenBlockKind
    label: str = Field(min_length=1)
    value: str | None = None
    tone: Literal["neutral", "positive", "muted"] | None = None
    #: Ties a row or banner to the link it activates.
    link_id: str | None = None


class FlowLink(WireModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    variant: LinkVariant


class FlowScreen(WireModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    #: Without the product name: the player prefixes the project's own name, so
    #: a fixture can never bake in a brand.
    crumbs: list[str] = Field(default_factory=list)
    blocks: list[ScreenBlock] = Field(default_factory=list)
    links: list[FlowLink] = Field(default_factory=list)
    terminal: bool = Field(
        default=False,
        description=(
            "True when this screen is meant to be the end of the journey, such as "
            "a confirmation or an error. A screen with no outgoing links is "
            "otherwise reported as a dead end, and this is how a flow says the "
            "dead end was the point. Assigned by rule from the screen's name and "
            "correctable by a human, never written by a generating model: a flag "
            "that silences a warning is a flag a model will set to silence the "
            "warning."
        ),
    )

    @model_validator(mode="after")
    def blocks_point_at_real_links(self) -> "FlowScreen":
        known = {link.id for link in self.links}
        for block in self.blocks:
            if block.link_id is not None and block.link_id not in known:
                raise ValueError(f"block {block.id} activates an unknown link: {block.link_id}")
        return self


class WireframeFlow(WireModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    screens: list[FlowScreen] = Field(
        min_length=1,
        description=(
            "The screens of this flow. The first is the entry point: the player "
            "opens there and the card thumbnail shows it, so ordering is meaning "
            "rather than presentation. Every other screen has to be reachable "
            "from it by following links."
        ),
    )
    traces: Traces
    covers_story_ids: list[StoryId] = Field(default_factory=list)
    pending_refinement: bool = False
    refinement_note: str | None = None

    @model_validator(mode="after")
    def links_stay_inside_the_flow(self) -> "WireframeFlow":
        """A link to a screen that does not exist is a dead end in the
        prototype, which is exactly what a clickable prototype is for finding."""
        known = {screen.id for screen in self.screens}
        for screen in self.screens:
            for link in screen.links:
                if link.target_id not in known:
                    raise ValueError(
                        f"{self.id}/{screen.id}: link {link.id} goes to {link.target_id}, "
                        f"which is not a screen in this flow"
                    )
        return self


class WireframeCoverageRow(WireModel):
    story_id: StoryId
    story_title: str
    #: Composite `flowId/screenId` references.
    screen_ids: list[str] = Field(default_factory=list)
    covered: bool
    #: Whether a screen is the right thing to expect for this story at all.
    #:
    #: False for work no person performs: ingesting telemetry, syncing an ERP,
    #: staying available. Scoring those against screens made a real plan report
    #: fourteen of twenty four stories uncovered when six of them could not have
    #: a screen, which is a number that reads as a gap in the design and is not.
    #:
    #: The row is kept rather than dropped, because a machine decided this and a
    #: reader has to be able to disagree with it. A table that quietly omits what
    #: it could not classify is the same failure as one listing only what it
    #: covered.
    needs_screen: bool = True


class WireframesArtefact(WireModel):
    flows: list[WireframeFlow] = Field(default_factory=list)
    #: Derived, never authored: recomputed from flows against the sprint plan.
    coverage: list[WireframeCoverageRow] = Field(default_factory=list)
