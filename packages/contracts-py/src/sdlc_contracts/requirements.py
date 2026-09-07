"""The requirements artefact: what the system has to do, and what we had to assume.

The honest metrics live here. Confidence is per requirement and never global,
because a single percentage over a whole analysis is a number with no referent.
Assumptions and clarifying questions are first class, because the alternative
when input is thin is to invent confident requirements instead.
"""

from typing import Literal

from pydantic import Field, model_validator

from .ids import AssumptionId, QuestionId, RequirementId, Traces
from .wire import Prose, WireDatetime, WireModel, plain_dashes

RequirementType = Literal["functional", "quality", "constraint"]
RequirementPriority = Literal["must", "should", "could"]
QualityAttribute = Literal["performance", "security", "usability", "reliability"]

#: At most three unanswered questions may be open at once. More than that is a
#: form to fill in rather than a conversation, and people stop reading them.
MAX_OPEN_QUESTIONS = 3


class ParsedRequirement(WireModel):
    id: RequirementId
    text: str = Field(min_length=1)
    type: RequirementType
    priority: RequirementPriority
    #: Computed from checkable properties of the text, never reported by the
    #: model. Capped below 100 because nothing read from prose is certain.
    confidence: int = Field(ge=0, le=100)
    #: Quality requirements only; null for the rest.
    quality_attribute: QualityAttribute | None = None
    #: The analysis decides this, so the client never picks a threshold.
    low_confidence: bool = False
    #: A human corrected the text after generation.
    adjusted: bool = False
    #: The sentence this was read from, verified against the input by slicing it
    #: at the reported offsets. Null means inferred rather than read.
    source_quote: str | None = None

    @model_validator(mode="after")
    def the_models_words_without_dashes(self) -> "ParsedRequirement":
        """The model's statement, as other model prose is; a person's correction as typed."""
        if not self.adjusted:
            self.text = plain_dashes(self.text)
        return self

    @model_validator(mode="after")
    def quality_attribute_belongs_to_quality(self) -> "ParsedRequirement":
        if self.quality_attribute is not None and self.type != "quality":
            raise ValueError(
                f"{self.id}: qualityAttribute is only meaningful on a quality requirement, "
                f"not on a {self.type} one"
            )
        return self


class Assumption(WireModel):
    id: AssumptionId
    text: str = Field(min_length=1)
    #: The requirements whose text triggered this assumption.
    traces: Traces
    dismissed: bool = False
    edited: bool = False

    @model_validator(mode="after")
    def the_models_words_without_dashes(self) -> "Assumption":
        """The model's assumption, as other model prose is; a person's edit as typed."""
        if not self.edited:
            self.text = plain_dashes(self.text)
        return self


class ClarifyingQuestion(WireModel):
    id: QuestionId
    question: Prose = Field(min_length=1)
    traces: Traces
    answer: str | None = None
    answered_at: WireDatetime | None = None

    @model_validator(mode="after")
    def answered_questions_carry_a_time(self) -> "ClarifyingQuestion":
        if self.answer is not None and self.answered_at is None:
            raise ValueError(f"{self.id}: an answered question must record when")
        return self


class RequirementsArtefact(WireModel):
    """What C1's `/requirements` endpoint produces."""

    requirements: list[ParsedRequirement] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    questions: list[ClarifyingQuestion] = Field(default_factory=list)

    @model_validator(mode="after")
    def ids_are_unique(self) -> "RequirementsArtefact":
        for label, items in (
            ("requirement", [r.id for r in self.requirements]),
            ("assumption", [a.id for a in self.assumptions]),
            ("question", [q.id for q in self.questions]),
        ):
            duplicates = sorted({i for i in items if items.count(i) > 1})
            if duplicates:
                raise ValueError(f"duplicate {label} ids: {', '.join(duplicates)}")
        return self

    @model_validator(mode="after")
    def traces_resolve(self) -> "RequirementsArtefact":
        """An assumption or question about a requirement that does not exist is
        a broken trace, and traceability is the thing this component claims."""
        known = {r.id for r in self.requirements}
        for item in (*self.assumptions, *self.questions):
            missing = sorted(set(item.traces) - known)
            if missing:
                raise ValueError(f"{item.id} traces to unknown requirements: {', '.join(missing)}")
        return self

    @model_validator(mode="after")
    def open_questions_are_capped(self) -> "RequirementsArtefact":
        """Enforced here as well as during selection, so no code path can
        produce an artefact that violates it."""
        open_count = sum(1 for q in self.questions if q.answer is None)
        if open_count > MAX_OPEN_QUESTIONS:
            raise ValueError(
                f"{open_count} unanswered questions, but at most "
                f"{MAX_OPEN_QUESTIONS} may be open at once"
            )
        return self


class RequirementChange(WireModel):
    """One requirement that reads differently than it did."""

    requirement_id: RequirementId
    field: str = Field(min_length=1)
    before: str = ""
    after: str = ""


class RequirementDiff(WireModel):
    """What moved between two requirements versions.

    The sibling of `ContractDiff`, and here for the same reason it is: the
    self healing classifier's first signal is whether the thing a failing test
    traces to changed between the two versions, and requirements are half of
    what a test traces to. Endpoints are the other half.

    A human edit counts as a change. An overlay that rewrote a requirement is
    exactly the case where a test encoding the old wording is stale rather than
    right, which is the distinction the whole loop turns on.
    """

    from_version: int = Field(ge=1)
    to_version: int = Field(ge=1)
    added: list[RequirementId] = Field(default_factory=list)
    removed: list[RequirementId] = Field(default_factory=list)
    changed: list[RequirementChange] = Field(default_factory=list)

    @property
    def touched(self) -> frozenset[str]:
        """Every requirement id that is not the same in both versions.

        Added and removed count: a test tracing to a requirement that no longer
        exists is testing something nobody asked for any more, which is as much
        a reason to look at the test as a reworded one.
        """
        return frozenset(
            [*self.added, *self.removed, *(change.requirement_id for change in self.changed)]
        )


def _comparable(requirement: ParsedRequirement) -> dict[str, str]:
    """The fields whose change could make a test stale.

    Confidence and `low_confidence` are excluded on purpose: they are computed
    from the text, so a change in them without a change in the text is a
    scoring change, not a change in what was asked for.
    """
    return {
        "text": requirement.text,
        "type": requirement.type,
        "priority": requirement.priority,
        "qualityAttribute": requirement.quality_attribute or "",
    }


def diff_requirements(
    previous: RequirementsArtefact,
    current: RequirementsArtefact,
    *,
    from_version: int,
    to_version: int,
) -> RequirementDiff:
    """A pure function, in the contracts package for `diff_contracts`'s reason:
    the orchestrator must not import the component in http mode, and comparing
    two shapes is bookkeeping rather than intelligence."""
    before = {r.id: r for r in previous.requirements}
    after = {r.id: r for r in current.requirements}

    changed: list[RequirementChange] = []
    for requirement_id in sorted(set(before) & set(after)):
        old_fields = _comparable(before[requirement_id])
        new_fields = _comparable(after[requirement_id])
        for field, old_value in old_fields.items():
            if new_fields[field] != old_value:
                changed.append(
                    RequirementChange(
                        requirement_id=requirement_id,
                        field=field,
                        before=old_value,
                        after=new_fields[field],
                    )
                )

    return RequirementDiff(
        from_version=from_version,
        to_version=to_version,
        added=sorted(set(after) - set(before)),
        removed=sorted(set(before) - set(after)),
        changed=changed,
    )
