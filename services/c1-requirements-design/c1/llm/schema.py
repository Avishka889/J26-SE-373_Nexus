"""What the model is allowed to return, and nothing more.

The shape of this type is the argument. A language model asked to produce a
requirement will happily also produce its type, its priority and a confidence
score, and none of those can be checked afterwards. So the type does not have
fields for them: the model reports what it read and where it read it, and the
rule layer decides everything else.

That is not a stylistic preference. A field the model cannot fill is a field the
model cannot get wrong, and every field removed here is one fewer unverifiable
claim in the artefact.
"""

from pydantic import BaseModel, Field


class ExtractedRequirement(BaseModel):
    """One requirement the model claims to have read from the input."""

    text: str = Field(
        min_length=1,
        description=(
            "The requirement as one clear sentence, in the present tense, naming who "
            "does what. Do not invent detail the input does not contain."
        ),
    )
    #: Offsets, not a quote. A quote can be written from memory; offsets have to
    #: point at something, and the pipeline slices the input at them and compares.
    source_start: int = Field(
        ge=0,
        description="Character offset in the input where the sentence this came from starts.",
    )
    source_end: int = Field(
        ge=0,
        description="Character offset where that sentence ends.",
    )
    source_quote: str = Field(
        default="",
        description=(
            "The exact text of the input between those offsets. Copy it, do not "
            "rewrite it. Leave empty if this requirement was inferred rather than "
            "read from a specific sentence."
        ),
    )
    #: Whether the model claims to have read this or worked it out. Checked
    #: against the span, so a claim of "read" with a quote that does not verify
    #: is treated as inferred and loses the confidence that goes with it.
    rationale_kind: str = Field(
        default="read",
        description=(
            "Either 'read' when a sentence in the input says this directly, or "
            "'inferred' when it follows from the input without being stated."
        ),
    )


class ExtractedGap(BaseModel):
    """A decision this brief leaves open that the slot table cannot know about.

    The table in `rules/slots.py` holds the decisions every project faces and can
    default honestly: sign in, persistence, platform, scale. It cannot hold the
    ones that belong to a domain. A cold chain brief that never states its
    permitted temperature range has a hole in it that no generic slot describes,
    and the table asked about currency conversion instead.

    So the model is allowed to name gaps, under the same discipline as a
    requirement: offsets into the brief that are checked, and no score of its own.
    How consequential a gap is stays out of this type, because a model asked to
    rank its own findings will rank them all highly.

    The assumption is required rather than optional. Every gap that does not make
    the question cap is written down as a stated assumption instead, and a gap
    with nothing honest to assume would break that: it would be silently dropped.
    """

    question: str = Field(
        min_length=1,
        description=(
            "The question to ask, in one plain sentence, about something this "
            "brief genuinely does not say. Name the specific thing: 'What is the "
            "permitted temperature range, and in what units?', not 'What are the "
            "thresholds?'."
        ),
    )
    assumption: str = Field(
        min_length=1,
        description=(
            "What a designer would reasonably assume if nobody answers, written "
            "as a statement a reader can correct: 'Assumed the permitted range is "
            "supplied as configuration rather than fixed in the design.'"
        ),
    )
    #: The same evidence rule as a requirement. A gap has to arise from somewhere
    #: in the brief, and pointing at where is what stops it being invented.
    source_start: int = Field(
        ge=0,
        description="Character offset where the sentence that raises this gap starts.",
    )
    source_end: int = Field(ge=0, description="Character offset where that sentence ends.")
    source_quote: str = Field(
        min_length=1,
        description=(
            "The exact text of the brief between those offsets. Copy it. A gap "
            "whose quote is not there is discarded."
        ),
    )


class ExtractionResult(BaseModel):
    """Everything one extraction pass produced.

    Deliberately flat. Nesting invites the model to organise, and organising is
    where it starts inventing structure the input does not have.
    """

    requirements: list[ExtractedRequirement] = Field(
        description="The requirements read from the input, in the order they appear.",
    )
    gaps: list[ExtractedGap] = Field(
        default_factory=list,
        description=(
            "Decisions this brief leaves open that a reader would need answered "
            "before designing. At most three matter, so return the ones that would "
            "change the design if answered differently, not everything unstated."
        ),
    )
