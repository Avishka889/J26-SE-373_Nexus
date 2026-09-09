"""The model writes the explanation, and only the explanation.

`score` is not a field on the output type, so the model cannot produce one. That
is the same enforcement-by-type the extraction schema uses: a field a model
cannot fill is a field it cannot get wrong, and a score it could write would be
a number nobody can reproduce sitting next to numbers that were counted.

What it can do, and does well, is turn a list of counted facts into prose a
reader understands. What it does badly, and is stopped from doing here, is invent
supporting figures. "Supports 10,000 concurrent users" is the failure mode: a
plausible number, in the right units, that nothing in the design says. An output
validator rejects any figure that is not in the facts, and pydantic-ai asks again
with the reason.

`cons` requires two entries. A candidate with only upside has not been assessed,
and the comparison is the point.
"""

import logging
import re
from dataclasses import dataclass

from pydantic import BaseModel, Field, field_validator
from pydantic_ai import Agent, ModelRetry, RunContext
from sdlc_contracts import ArchitectureRecommendation, ArchitectureStyleNote, TopologyCandidate

from ..agents import MALFORMED_OUTPUT_RETRIES, output_for, settings_for
from ..model_use import records_answers
from .scoring import CandidateScore, ScoringFacts

INSTRUCTIONS = """
You explain why a deployment shape suits a design, for someone who has to choose
between them.

You are given counted facts about the design and a shape to write about. Write:

  rationale  two or three sentences saying why this shape does or does not fit
             this design, referring to the facts you were given.
  pros       what it genuinely buys, here, for this design.
  cons       at least two. Every shape costs something, and a card with only
             upside is not an assessment.

Never state a number that is not in the facts you were given. Do not write
"handles 10,000 users" or "responds in under 200ms" or any other figure: nothing
in this design says that, and a reader will believe you. If you want to describe
scale, use the counts you were given or use words.

Do not give a score. The score is already decided by arithmetic over the design.
""".strip()


def _tidy(bullet: str) -> str:
    """A bullet as a reader should see it.

    Models occasionally emit a stray leading period or dash on a list item, and
    a real run produced ".Requires external stores for entities". Nothing about
    the meaning changes here; this only stops punctuation the model did not mean
    from reaching the card. Capitalising the first letter for the same reason.
    """
    cleaned = bullet.strip().lstrip(".-*\u2022 ").strip()
    return cleaned[:1].upper() + cleaned[1:] if cleaned else cleaned


class TopologyExplanation(BaseModel):
    """Prose about one shape. Deliberately no score field."""

    rationale: str = Field(min_length=1)
    pros: list[str] = Field(default_factory=list)
    #: Two, because every shape costs something and a card with only upside has
    #: not been assessed.
    cons: list[str] = Field(min_length=2)

    @field_validator("pros", "cons")
    @classmethod
    def tidy_bullets(cls, value: list[str]) -> list[str]:
        return [tidied for bullet in value if (tidied := _tidy(bullet))]


@dataclass(frozen=True)
class ExplanationReport:
    """How often the model tried to invent a figure, for the evaluation."""

    invented_figures_refused: int = 0


log = logging.getLogger(__name__)

#: A figure in prose: the number, then the few words it leads.
#:
#: Not one word. Real prose puts adjectives between a number and its noun, and
#: requiring adjacency refused sentences that were entirely grounded: "12
#: distinct services" when there are twelve services, "2 shared-write operations"
#: when two writes cross a service boundary. Each of those cost a retry, and a
#: stage only gets three.
#:
#: Three words is enough for "12 distinct services" and "2 shared-write
#: operations" without reaching the next clause. The number still has to meet its
#: own noun: "10,000 concurrent users" finds nothing in that window, because no
#: fact counts ten thousand of anything.
#: The trailing group takes an attached unit ("200ms", "99.5%") as well as
#: the spaced words, so a refusal quotes what the model actually wrote.
_FIGURE = re.compile(r"(\d[\d,.]*)((?:%|[A-Za-z][\w-]*)?(?:\s+[A-Za-z][\w-]*){0,3})")

_CONTEXT_WORDS = 3

#: Trailing punctuation on the context word.
_TRIM = " .,;:!?)('\""


def _singular(word: str) -> str:
    """Enough of a singular to compare two words that mean the same unit.

    Not a stemmer, and not trying to be. It exists because the facts are named
    in the plural ("entities", "external systems") and prose is written in
    whichever number reads better, so "8 entity" and "8 entities" would otherwise
    be different claims. A crude rstrip("s") is what made "entities" into
    "entitie" and refused a sentence that was quoting a count.
    """
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("ses", "xes", "zes", "ches", "shes")):
        return word[:-2]
    if len(word) <= 2:
        # "ms", "s". Stripping these leaves nothing to compare.
        return word
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _context_of(trailing: str) -> list[str]:
    """The words a number leads, hyphens split, singularised.

    "shared-write" becomes "shared" and "write", because a fact named "cross
    service writes" is written in prose as a hyphenated compound as often as not.
    """
    words: list[str] = []
    # "%" is how prose writes what a brief spells out, and a hyphen is how it
    # writes a compound the facts name as separate words ("cross service
    # writes" against "2 shared-write operations").
    for token in trailing.replace("-", " ").replace("%", " percent ").split():
        cleaned = token.strip(_TRIM).lower()
        if cleaned:
            words.append(_singular(cleaned))
    return words[:_CONTEXT_WORDS]


def _normalise(number: str) -> str:
    """The number, as both sides of the comparison write it."""
    return number.rstrip(".,").replace(",", "")


def _figures_in(text: str) -> set[tuple[str, str]]:
    """Every (number, context word) pair a text offers, for the allowed set."""
    found: set[tuple[str, str]] = set()
    for match in _FIGURE.finditer(text):
        number = _normalise(match.group(1))
        for word in _context_of(match.group(2)) or [""]:
            found.add((number, word))
    return found


def _allowed_figures(facts: ScoringFacts) -> set[tuple[str, str]]:
    """Every figure an explanation may cite, as (number, context word) pairs.

    Two sources, and both are grounded in something checkable. The counts are
    what this design contains, so "6 services" is citable when there are six.
    The source figures are what the requirements themselves state, so "99.5
    percent" is citable when the brief says it.

    A count is offered under each word of its name, so both "6 services" and, for
    "external systems", either half of the phrase will do.
    """
    allowed: set[tuple[str, str]] = set()
    for name, value in facts.as_dict().items():
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        for word in name.split():
            allowed.add((str(value), _singular(word)))
    allowed |= {(number, _singular(word)) for number, word in facts.source_figures}
    return allowed


def check_no_invented_figures(text: str, facts: ScoringFacts) -> list[str]:
    """Figures in the prose that neither the counts nor the requirements support.

    Refuses the claim, not the arithmetic. "10,000 concurrent users" appears in
    no count and in no requirement, so it is an invention. "99.5 percent" is
    quoted from the input, and refusing it once cost a whole stage.

    A figure is supported when the number meets one of its own words within the
    few it leads. Requiring the very next word refused "12 distinct services" on
    a design with twelve services, which is grounded prose and cost a retry.
    """
    allowed = _allowed_figures(facts)
    invented: list[str] = []
    for match in _FIGURE.finditer(text):
        number = _normalise(match.group(1))
        context = _context_of(match.group(2))
        if any((number, word) in allowed for word in context or [""]):
            continue
        invented.append(match.group(0).strip(_TRIM) or match.group(1))
    return sorted(set(invented))


def _citable(facts: ScoringFacts) -> str:
    """The figures an explanation may use, written the way a reader would say them.

    Built from the fact names, not from the pairs the guard compares against.
    Those are exploded into single words so that "8 entities" and "8 entity"
    match, and printing them back produced "1 cross, 1 service, 1 write, 11
    service" as advice: fragments, and two different counts for the same word.
    A retry message that misleads is worse than none, because it is spent on
    every attempt.
    """
    counted = ", ".join(
        f"{value} {name}"
        for name, value in facts.as_dict().items()
        if isinstance(value, int) and not isinstance(value, bool)
    )
    quoted = ", ".join(f"{number} {word}" for number, word in sorted(facts.source_figures))
    return f"{counted}; and from the requirements: {quoted}" if quoted else counted


def build_explainer(
    model: str, *, retries: int = MALFORMED_OUTPUT_RETRIES, thinking: str = "off"
) -> Agent[ScoringFacts, TopologyExplanation]:
    """The explanation agent, with the invented figure guard attached.

    The guard is an output validator rather than a check afterwards, so a refused
    explanation is retried with the reason instead of reaching a reader.
    """
    agent: Agent[ScoringFacts, TopologyExplanation] = Agent(
        model,
        output_type=output_for(TopologyExplanation, model, thinking=thinking),
        deps_type=ScoringFacts,
        instructions=INSTRUCTIONS,
        retries=retries,
        model_settings=settings_for(model, thinking=thinking),
        capabilities=[records_answers()],
    )

    @agent.output_validator
    def no_invented_figures(
        ctx: RunContext[ScoringFacts], output: TopologyExplanation
    ) -> TopologyExplanation:
        prose = " ".join([output.rationale, *output.pros, *output.cons])
        invented = check_no_invented_figures(prose, ctx.deps)
        if invented:
            # The prose, not just the verdict. A stage that dies here has spent
            # its whole retry budget, and knowing which figures were refused
            # without seeing the sentence they were in leaves the next reader
            # guessing at what the model was trying to say.
            log.error(
                "explanation refused on attempt %d: %s. It wrote: %r. It may cite: %s",
                ctx.run_step,
                ", ".join(invented),
                " ".join([output.rationale, *output.pros, *output.cons])[:400],
                _citable(ctx.deps),
            )
            raise ModelRetry(
                "These figures are not supported by anything you were given: "
                f"{', '.join(invented)}. A figure is only usable if the design was "
                "counted that way or the requirements say it, with the same unit. "
                f"You may cite: {_citable(ctx.deps)}. Remove the rest, or reword "
                "without numbers."
            )
        return output

    return agent


def prompt_for(candidate: CandidateScore, facts: ScoringFacts) -> str:
    """One shape, and the counted facts about the design it is being judged for."""
    lines = [f"  {name}: {value}" for name, value in facts.as_dict().items()]
    reasons = [f"  {a.reason}" for a in candidate.adjustments] or ["  Nothing stood out."]
    return (
        f"Shape: {candidate.name}\n\n"
        f"Facts about this design:\n" + "\n".join(lines) + "\n\n"
        "What the scoring noticed:\n" + "\n".join(reasons) + "\n\n"
        "Write the explanation for this shape."
    )


async def explain_all(
    scored: list[CandidateScore],
    facts: ScoringFacts,
    *,
    agent: Agent[ScoringFacts, TopologyExplanation],
    style: ArchitectureStyleNote,
) -> tuple[ArchitectureRecommendation, ExplanationReport]:
    """Explain every shape and assemble the recommendation.

    The scores come from `scored` and are never touched here: this function only
    attaches words to numbers that were already decided.
    """
    candidates: list[TopologyCandidate] = []
    for candidate in scored:
        result = await agent.run(prompt_for(candidate, facts), deps=facts)
        explanation = result.output
        candidates.append(
            TopologyCandidate(
                id=candidate.id,
                name=candidate.name,
                score=candidate.score,
                rationale=explanation.rationale,
                pros=explanation.pros,
                cons=explanation.cons,
            )
        )

    return (
        ArchitectureRecommendation(
            candidates=candidates,
            recommendedCandidateId=scored[0].id,
            # Nobody has chosen yet. The recommendation is an argument, and the
            # gate is where a human answers it.
            selectedCandidateId=None,
            selectedAt=None,
            selectedBy=None,
            style=style,
        ),
        ExplanationReport(),
    )
