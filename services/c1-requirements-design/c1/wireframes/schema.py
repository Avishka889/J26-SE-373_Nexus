"""What the model may return for a flow, before anything is checked.

Permissive for the same reason the graph draft is: `WireframeFlow` refuses a link
to a screen that does not exist by raising at construction, which is right on the
wire and useless in a repair loop. An exception says something is wrong without
saying what, and hands nothing structured back to the model. So the model answers
in this shape, the rules read it and produce findings with hints, and only a
draft that passes is promoted to the strict type.

Two fields of the contract are missing here on purpose.

`terminal` is absent because a model must not be able to set it. It is the flag
that silences the dead end warning, and a model given a flag that silences a
warning about its own output will set the flag. A rule assigns it from the
screen's name, where the reasoning is inspectable and the same input gives the
same answer.

`covers_story_ids` is absent because flows are generated from the graph without
being shown the sprint plan. If a flow were told which story to satisfy, it would
claim to satisfy it, and the coverage figure in the next step would measure
nothing but the model's willingness to agree. The two artefacts are produced
independently so that whether they line up is a finding rather than an assumption.
"""

from pydantic import BaseModel, Field


class DraftBlock(BaseModel):
    """One piece of a screen as the model described it."""

    id: str = Field(default="", description="Short and unique within the screen, e.g. 'b1'.")
    kind: str = Field(
        default="",
        description=(
            "One of: field, row, summary, banner, text, list, button, display. Nothing else."
        ),
    )
    label: str = Field(default="", description="What the reader sees on this line.")
    value: str = Field(default="", description="Example content, when a value would be shown.")
    tone: str = Field(default="", description="Optional: neutral, positive, or muted.")
    link_id: str = Field(
        default="",
        description="Optional: the id of a link on this screen that this line activates.",
    )


class DraftLink(BaseModel):
    """One way out of a screen."""

    id: str = Field(default="", description="Short and unique within the screen, e.g. 'l1'.")
    label: str = Field(default="", description="What the control says, e.g. 'Continue'.")
    target_id: str = Field(default="", description="The id of the screen this goes to.")
    variant: str = Field(
        default="",
        description="One of: primary, secondary, row, text.",
    )


class DraftScreen(BaseModel):
    """One screen as the model described it."""

    id: str = Field(default="", description="Short and unique within the flow, e.g. 's1'.")
    name: str = Field(default="", description="What this screen is called.")
    crumbs: list[str] = Field(
        default_factory=list,
        description="The path to this screen, without the product name.",
    )
    traces: list[str] = Field(
        default_factory=list,
        description="The requirement ids this screen serves, e.g. ['R-1', 'R-3'].",
    )
    blocks: list[DraftBlock] = Field(default_factory=list)
    links: list[DraftLink] = Field(default_factory=list)


class DraftFlow(BaseModel):
    """A flow the model produced, before the rules have read it."""

    name: str = Field(default="", description="What this journey is called, in plain words.")
    screens: list[DraftScreen] = Field(
        description="The screens, entry point first. Every other screen must be reachable from it.",
    )
