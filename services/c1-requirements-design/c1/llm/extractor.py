"""LLM extraction, under the budget the rules computed and checked by them.

The division of labour, stated once:

    the model reads       -> text, and where in the input it came from
    the rules decide      -> type, priority, quality attribute, confidence
    the rules verify      -> that the quoted span is really in the input
    the rules enforce     -> the budget, by truncation

Nothing the model returns is trusted on its own. The budget appears in the
instructions because a model that knows the target usually respects it, and it is
applied again by truncation afterwards because sometimes it does not. The gap
between the two is recorded rather than smoothed over: how often a model ignores
its budget is a number worth publishing about the model.

The model string is configuration and is never hardcoded here. Which provider
answers is a deployment decision, and an evaluation run pins one.
"""

from dataclasses import dataclass, replace

from pydantic_ai import Agent

from ..agents import MALFORMED_OUTPUT_RETRIES, output_for, settings_for
from ..model_use import records_answers
from ..rules.classify import classify
from ..rules.confidence import score
from ..rules.extract import Extraction, ScoredRequirement, apply_budget, as_requirement
from ..rules.measure import measure
from ..rules.slots import (
    SlotFinding,
    rank,
    slot_for_gap,
    split_questions_and_assumptions,
    unfilled_slots,
)
from ..rules.spans import find_span, verify_span
from .schema import ExtractedRequirement, ExtractionResult

INSTRUCTIONS = """
You read a short software brief and list the requirements it contains.

The brief is somebody asking for a system to be built. Requirements describe what
that system does once it exists, never the act of asking for it or of building it.
"Build a simple calculator app" is a request for a calculator: the requirement is
that someone works out a calculation, and there is no developer and no build in
the design. Getting this wrong produces a design about the wrong subject, which is
the worst thing this step can do.

Rules you must follow:

1. Read what is written. Do not add requirements the brief does not ask for, and
   do not expand one requirement into several to reach a number.
2. One sentence each, present tense, naming who does what: "A customer pays with
   a saved card", not "The system should probably support payments". The who is
   someone who uses the system, not the person who commissioned it.
3. For each requirement, give the character offsets of the sentence in the brief
   it came from, and copy that sentence exactly into sourceQuote. The offsets are
   checked against the brief, so a quote that is not there will be discarded.
4. If a requirement follows from the brief without any sentence saying it
   directly, set rationaleKind to "inferred" and leave sourceQuote empty. This is
   allowed and is better than pointing at a sentence that does not say it.
5. Do not classify anything. Do not say whether a requirement is functional,
   mandatory, or high priority, and do not give a confidence score. Those are
   decided elsewhere from the words you quote.

A brief with little in it should produce few requirements. Returning three
well-read requirements is a better answer than twelve invented ones.

Separately from the requirements, list the decisions this brief leaves open that
a designer would have to settle before drawing anything. Rules for those:

6. Name the specific missing thing, not the category. "What is the permitted
   temperature range, and in what units?" is useful; "What are the thresholds?"
   is not.
7. Only raise a gap that this brief actually creates. Point at the sentence that
   raises it with offsets and an exact quote, the same way as a requirement, and
   a gap whose quote is not there will be discarded.
8. Give each gap the assumption a designer would fall back on if nobody answers,
   written as a statement a reader can correct. Gaps that are not asked are
   recorded as assumptions, so one without an assumption is one that gets lost.
9. Do not raise gaps about sign in, storage, platform, scale, error handling or
   audit trails. Those are checked separately and you will be duplicating them.
   Raise what is specific to this brief and its subject.
""".strip()


@dataclass(frozen=True)
class ExtractionReport:
    """What happened on one pass, for the evaluation rather than the browser."""

    #: What the model returned, before any rule touched it.
    returned: int = 0
    #: How many the budget removed. Non-zero means the model ignored its target.
    over_budget: int = 0
    #: Quotes that did not survive being checked against the input.
    spans_refused: int = 0
    #: Requirements the model itself said it inferred.
    self_declared_inferred: int = 0
    #: Gaps the model raised, before any were checked.
    gaps_returned: int = 0
    #: Gaps discarded because their quote was not in the brief. Reported rather
    #: than hidden: how often a model invents the evidence for its own question
    #: is a number about the model.
    gaps_refused: int = 0
    #: Gaps kept because their quote is the brief's own words, although their
    #: offsets missed: the recovery a requirement's quote already had.
    gaps_recovered: int = 0

    @property
    def span_failure_rate(self) -> float:
        return self.spans_refused / self.returned if self.returned else 0.0


def build_agent(
    model: str, *, retries: int = MALFORMED_OUTPUT_RETRIES, thinking: str = "off"
) -> Agent[None, ExtractionResult]:
    """The extraction agent.

    Build one and keep it. The agent owns an HTTP client to the provider, so one
    per request leaks a connection per request; the service builds this at
    startup and `extract_with_model` takes it as an argument for exactly that
    reason.

    `instructions` rather than `system_prompt`, which is what pydantic-ai
    recommends: instructions belong to this agent and are dropped when message
    history is carried into another one, and nothing here should leak into a
    later conversation.
    """
    return Agent(
        model,
        output_type=output_for(ExtractionResult, model, thinking=thinking),
        instructions=INSTRUCTIONS,
        retries=retries,
        model_settings=settings_for(model, thinking=thinking),
        capabilities=[records_answers()],
    )


def prompt_for(text: str, budget: int) -> str:
    """The brief, with its budget stated as a target the model can see."""
    return (
        f"Read this brief and list the requirements in it. "
        f"There is roughly enough here for about {budget} requirements; "
        f"fewer is fine, and more than {budget} will be discarded.\n\n"
        f"---\n{text}\n---"
    )


async def extract_with_model(
    text: str, *, agent: Agent[None, ExtractionResult]
) -> tuple[Extraction, ExtractionReport]:
    """Read an input with the model, then check everything it said.

    Returns the same `Extraction` the rule-only path returns, so the caller
    cannot tell which produced it and the two can be compared directly. That is
    the point: the evaluation runs both over the same corpus.
    """
    measurement = measure(text)
    result = await agent.run(prompt_for(text, measurement.budget))
    returned = result.output.requirements

    scored: list[ScoredRequirement] = []
    spans_refused = 0
    self_declared_inferred = 0

    for index, candidate in enumerate(returned):
        if candidate.rationale_kind.strip().lower() == "inferred":
            self_declared_inferred += 1

        quote = _verified_quote(text, candidate)
        if quote is None and candidate.source_quote.strip():
            # It claimed a sentence and the input does not contain it there.
            # Not an error to raise: it is a fact about this run, and the
            # requirement survives as inferred with the confidence that implies.
            spans_refused += 1

        sentence = as_requirement(candidate.text)
        classification = classify(sentence)
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
                    siblings=tuple(existing.text for existing in scored),
                ),
                quote=quote,
            )
        )

    kept, over_budget = apply_budget(scored, measurement.budget)
    requirement_ids = tuple(r.id for r in kept)

    # A gap has to point at the brief, exactly as a requirement does, including
    # the recovery a requirement has when its offsets miss but its quote is the
    # brief's own words. One that points at nothing is discarded rather than
    # downgraded: an unverified quote costs a requirement its confidence, but a
    # gap has no confidence to lose, and a question about something the brief
    # never said is worse than no question.
    #
    # Without the recovery a question about this brief was discarded for its
    # arithmetic alone, and the generic slot table filled its place: which is
    # how every project was asked the same three questions.
    gap_findings: list[SlotFinding] = []
    gaps_refused = 0
    gaps_recovered = 0
    for gap in result.output.gaps:
        if not verify_span(text, gap.source_start, gap.source_end, gap.source_quote).verified:
            if not find_span(text, gap.source_quote.strip()).verified:
                gaps_refused += 1
                continue
            gaps_recovered += 1
        slot = slot_for_gap(len(gap_findings), gap.question.strip(), gap.assumption.strip())
        gap_findings.append(SlotFinding(slot, requirement_ids))

    findings = rank(gap_findings + unfilled_slots(text, requirement_ids))
    questions, assumptions = split_questions_and_assumptions(findings)

    extraction = Extraction(
        measurement=measurement,
        requirements=tuple(kept),
        questions=tuple(questions),
        assumptions=tuple(assumptions),
        over_budget=over_budget,
    )
    report = ExtractionReport(
        returned=len(returned),
        over_budget=over_budget,
        spans_refused=spans_refused,
        self_declared_inferred=self_declared_inferred,
        gaps_returned=len(result.output.gaps),
        gaps_refused=gaps_refused,
        gaps_recovered=gaps_recovered,
    )
    return extraction, report


def _verified_quote(source: str, candidate: ExtractedRequirement) -> str | None:
    """The input's own words, or nothing.

    Offsets first, because they are the claim that can be wrong in a way a quote
    cannot: a model reproducing a sentence it read is easy, pointing at where it
    sits is not. When the offsets miss but the sentence really is in the brief,
    the quote is recovered by searching, because the requirement is still read
    rather than inferred and should not be punished for arithmetic.
    """
    claimed = candidate.source_quote.strip()
    if not claimed:
        return None

    check = verify_span(source, candidate.source_start, candidate.source_end, claimed)
    if check.verified:
        return check.quote

    recovered = find_span(source, claimed)
    return recovered.quote if recovered.verified else None


def with_ids_renumbered(extraction: Extraction) -> Extraction:
    """Ids as R-1 upward with no gaps, after anything that removed a member."""
    return replace(
        extraction,
        requirements=tuple(
            replace(requirement, id=f"R-{position + 1}")
            for position, requirement in enumerate(extraction.requirements)
        ),
    )
