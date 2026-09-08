"""The rule-only extraction pipeline.

No model. This is the layer the language model is later measured against, and the
layer that validates and scores whatever the model produces, so it has to work on
its own first.

What it does is read each sentence of the input as one candidate requirement,
classify it from the lexicons, verify its quote against the input, score it, and
then apply the budget by truncation. What it does not do is infer anything the
input does not contain: that is what the assumptions are for.

Its output on a thin input is deliberately unimpressive. "Build a simple
calculator app" produces one requirement at low confidence plus a handful of
assumptions, which is an honest reading of seven words. The LLM layer improves on
that; this is the floor it has to beat, and the baseline the evaluation reports.
"""

from dataclasses import dataclass, field

from sdlc_contracts import Assumption, ClarifyingQuestion, ParsedRequirement, RequirementsArtefact

from .classify import Classification, classify
from .confidence import ConfidenceScore, score
from .measure import InputMeasurement, measure
from .slots import SlotFinding, split_questions_and_assumptions, unfilled_slots
from .spans import find_span


@dataclass(frozen=True)
class ScoredRequirement:
    """One requirement with everything the rules worked out about it.

    Richer than the wire contract on purpose: the deductions and the lexicon
    evidence are what the evaluation reports, and they do not belong in a payload
    the browser renders.
    """

    id: str
    text: str
    classification: Classification
    confidence: ConfidenceScore
    quote: str | None

    def to_contract(self) -> ParsedRequirement:
        return ParsedRequirement(
            id=self.id,
            text=self.text,
            type=self.classification.type,
            priority=self.classification.priority,
            confidence=self.confidence.value,
            qualityAttribute=self.classification.quality_attribute,
            lowConfidence=self.confidence.low,
            adjusted=False,
            sourceQuote=self.quote,
        )


@dataclass(frozen=True)
class Extraction:
    """Everything one pass produced, wire payload and working alike."""

    measurement: InputMeasurement
    requirements: tuple[ScoredRequirement, ...]
    questions: tuple[SlotFinding, ...]
    assumptions: tuple[SlotFinding, ...]
    #: How many candidates the budget removed. Zero for the rule layer, which
    #: cannot exceed its own budget; non-zero when a model ignored it, which is
    #: a number worth reporting about the model.
    over_budget: int = 0
    #: Requirements dropped as near duplicates before scoring.
    duplicates_removed: int = 0
    _artefact: RequirementsArtefact | None = field(default=None, compare=False)

    def to_artefact(self) -> RequirementsArtefact:
        return RequirementsArtefact(
            requirements=[r.to_contract() for r in self.requirements],
            assumptions=[
                Assumption(
                    id=f"A-{index + 1}",
                    text=finding.slot.assumption,
                    traces=list(finding.traces),
                    dismissed=False,
                    edited=False,
                )
                for index, finding in enumerate(self.assumptions)
            ],
            questions=[
                ClarifyingQuestion(
                    id=f"Q-{index + 1}",
                    question=finding.slot.question,
                    traces=list(finding.traces),
                    answer=None,
                    answeredAt=None,
                )
                for index, finding in enumerate(self.questions)
            ],
        )


def extract(text: str) -> Extraction:
    """Read an input with rules alone."""
    measurement = measure(text)

    candidates: list[tuple[str, str | None]] = []
    for sentence in measurement.sentences:
        cleaned = sentence.strip()
        if not cleaned:
            continue
        # The rule layer quotes the input verbatim, so the span always verifies.
        # Running the check anyway keeps one code path: the model layer feeds
        # through the same function, and a quote that fails there is refused.
        check = find_span(text, cleaned)
        candidates.append((as_requirement(cleaned), check.quote))

    # Nothing readable. Say so rather than returning an empty artefact that reads
    # as "your input asked for nothing".
    if not candidates:
        candidates = [("The system does what the requirement text describes.", None)]

    scored: list[ScoredRequirement] = []
    for index, (sentence, quote) in enumerate(candidates):
        classification = classify(sentence)
        siblings = tuple(existing.text for existing in scored)
        scored.append(
            ScoredRequirement(
                id=f"R-{index + 1}",
                text=sentence,
                classification=classification,
                confidence=score(
                    text=sentence,
                    source=text,
                    quote=quote,
                    classification=classification,
                    siblings=siblings,
                ),
                quote=quote,
            )
        )

    kept, over_budget = apply_budget(scored, measurement.budget)
    findings = unfilled_slots(text, tuple(r.id for r in kept))
    questions, assumptions = split_questions_and_assumptions(findings)

    return Extraction(
        measurement=measurement,
        requirements=tuple(kept),
        questions=tuple(questions),
        assumptions=tuple(assumptions),
        over_budget=over_budget,
    )


def apply_budget(
    scored: list[ScoredRequirement], budget: int
) -> tuple[list[ScoredRequirement], int]:
    """Keep the best `budget` requirements, and report how many were dropped.

    Enforced here rather than trusted to whoever produced the list. Telling a
    model to stop at twelve is a request; truncating at twelve is a guarantee.

    Highest confidence first, because if something has to go it should be the
    reading the rules were least sure of. Ids are renumbered afterwards so the
    artefact reads R-1 upward with no gaps, and every trace elsewhere is built
    from these ids after this point.
    """
    if len(scored) <= budget:
        return scored, 0

    ranked = sorted(scored, key=lambda r: (-r.confidence.value, r.id))
    kept = ranked[:budget]
    # Back into the order they were read in, so the list still follows the input.
    kept.sort(key=lambda r: _original_index(r.id))
    renumbered = [
        ScoredRequirement(
            id=f"R-{position + 1}",
            text=requirement.text,
            classification=requirement.classification,
            confidence=requirement.confidence,
            quote=requirement.quote,
        )
        for position, requirement in enumerate(kept)
    ]
    return renumbered, len(scored) - budget


def _original_index(requirement_id: str) -> int:
    return int(requirement_id.split("-")[1])


def as_requirement(sentence: str) -> str:
    """Tidy a sentence into something that reads as a requirement.

    Deliberately minimal: capitalise, punctuate, and strip a leading connective.
    Rewriting further would put words in the reader's mouth, and the source quote
    beside it would then no longer match what the requirement claims to say.
    """
    trimmed = sentence.strip()
    for connective in ("and ", "plus ", "with ", "including "):
        if trimmed.lower().startswith(connective):
            trimmed = trimmed[len(connective) :].strip()
            break
    if not trimmed:
        return trimmed
    tidied = trimmed[0].upper() + trimmed[1:]
    return tidied if tidied.endswith((".", "!", "?")) else f"{tidied}."
