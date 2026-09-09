"""What the model may return for a sprint plan, before anything is checked.

Four fields of the contract are missing here, and each one is missing because a
model producing it would be producing a number nobody can reproduce.

`id` is assigned in sequence at promotion. A model writing its own story ids
produces US-101 in one run and US-1 in the next, and occasionally the same id
twice. Assigning them removes a whole rule from the catalogue rather than adding
one, because ids allocated in sequence cannot collide.

`priority` is inherited from the requirements a story traces to. A story that
realises a must-have is a must-have, and asking a model to restate that invites
it to disagree with the requirement it came from.

`points` are counted from the design. This is the same argument the architecture
scores are built on: a model saying "5" is unreproducible, and a rule saying
"three acceptance criteria, two entities and an external system, so 8" can be
checked and argued with.

`proposed` against `backlog` is a division by the velocity assumption, which is
arithmetic once the points exist.

What the model is genuinely good at is left to it: the sentence a story is
written as, the epic it belongs under, and the acceptance criteria, which are the
one part of this artefact that is contract rather than description because C3
turns them into test cases.
"""

from pydantic import BaseModel, Field


class DraftCriterion(BaseModel):
    """One acceptance criterion, in the shape a test can be generated from."""

    given: str = Field(default="", description="The situation before, e.g. 'a signed in customer'.")
    when: str = Field(
        default="", description="The thing that happens, e.g. 'they confirm a payment'."
    )
    then: str = Field(
        default="",
        description="What must be observably true afterwards. Not a restatement of the when.",
    )


class DraftStory(BaseModel):
    """One story as the model wrote it."""

    title: str = Field(
        default="",
        description="One sentence from the reader's side, e.g. 'As a customer, I can pay with a saved card'.",
    )
    epic: str = Field(default="", description="The group of work this belongs to, e.g. 'Payments'.")
    traces: list[str] = Field(
        default_factory=list,
        description="The requirement ids this story realises, e.g. ['R-1', 'R-3'].",
    )
    acceptance: list[DraftCriterion] = Field(
        default_factory=list,
        description="At least one. How anyone can tell this story is finished.",
    )


class DraftPlan(BaseModel):
    """A sprint plan the model produced, before the rules have read it."""

    goal: str = Field(
        default="", description="One sentence saying what this sprint achieves for a user."
    )
    stories: list[DraftStory] = Field()
