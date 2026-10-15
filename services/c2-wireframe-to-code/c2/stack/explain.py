"""The stack explanation: the one model written part, guarded against figures.

C2's citable set is smaller than C1's on purpose: this component never sees
the brief, only artefacts, so the only numbers an explanation may use are the
counted facts. The matching semantics mirror C1's hard won ones exactly: a
figure is the number plus the few words it leads, the number has to meet one
of its own fact words inside that window, and unit words compare in the
singular so "6 entities" matches the "entities" fact.
"""

import logging
import re
from dataclasses import dataclass

from pydantic import BaseModel, Field
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.models import Model

from ..agents import MALFORMED_OUTPUT_RETRIES, output_for, settings_for
from ..model_use import records_answers
from .scoring import StackFacts

log = logging.getLogger(__name__)

#: A figure in prose: the number, then the few words it leads. Three words,
#: because real prose puts adjectives between a number and its noun, and
#: requiring adjacency refused grounded sentences in C1's live runs.
_FIGURE = re.compile(r"(\d[\d,.]*)((?:%|[A-Za-z][\w-]*)?(?:\s+[A-Za-z][\w-]*){0,3})")
_TRIM = " .,;:!?)('\""


def _singular(word: str) -> str:
    word = word.strip(_TRIM).lower()
    if word.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _context_of(trailing: str) -> list[str]:
    return [_singular(word) for word in trailing.strip().split()[:3] if word.strip(_TRIM)]


def _normalise(number: str) -> str:
    return number.replace(",", "").rstrip(".")


def _allowed(facts: StackFacts) -> set[tuple[str, str]]:
    allowed: set[tuple[str, str]] = set()
    for name, value in facts.as_dict().items():
        for word in name.split():
            allowed.add((str(value), _singular(word)))
    return allowed


def check_no_invented_figures(text: str, facts: StackFacts) -> list[str]:
    """Figures in the prose the counted facts do not support."""
    allowed = _allowed(facts)
    invented: list[str] = []
    for match in _FIGURE.finditer(text):
        number = _normalise(match.group(1))
        context = _context_of(match.group(2))
        if any((number, word) in allowed for word in context or [""]):
            continue
        invented.append(match.group(0).strip(_TRIM) or match.group(1))
    return sorted(set(invented))


def _citable(facts: StackFacts) -> str:
    return ", ".join(f"{value} {name}" for name, value in facts.as_dict().items())


class StackExplanation(BaseModel):
    """Prose about one stack. Deliberately no score field."""

    rationale: str = Field(min_length=1)


@dataclass(frozen=True)
class ExplanationReport:
    invented_figures_refused: int = 0


INSTRUCTIONS = (
    "You explain why a technology stack fits or does not fit a design, for a "
    "reader deciding which to build with. Ground every claim in the counted "
    "facts you are given. Never state a number the facts do not contain: no "
    "invented user counts, latencies, or team sizes. Two to four sentences, "
    "plain words, no headings."
)


def build_stack_explainer(
    model: str | Model, *, retries: int = MALFORMED_OUTPUT_RETRIES, thinking: str = "off"
) -> Agent[StackFacts, StackExplanation]:
    agent: Agent[StackFacts, StackExplanation] = Agent(
        model,
        deps_type=StackFacts,
        output_type=output_for(StackExplanation, model, thinking=thinking),
        instructions=INSTRUCTIONS,
        retries=retries,
        model_settings=settings_for(model, thinking=thinking),
        capabilities=[records_answers()],
    )

    @agent.output_validator
    def no_invented_figures(
        ctx: RunContext[StackFacts], output: StackExplanation
    ) -> StackExplanation:
        invented = check_no_invented_figures(output.rationale, ctx.deps)
        if invented:
            log.error(
                "stack explanation refused: cited %s; citable facts are %s",
                ", ".join(invented),
                _citable(ctx.deps),
            )
            raise ModelRetry(
                f"The design does not support these figures: {', '.join(invented)}. "
                f"You may cite: {_citable(ctx.deps)}. Remove the rest, or reword "
                "without numbers."
            )
        return output

    return agent


def prompt_for(stack_name: str, facts: StackFacts, score_reasons: list[str]) -> str:
    reasons = "\n".join(f"- {reason}" for reason in score_reasons) or "- (baseline only)"
    topology = facts.selected_topology or "not selected"
    return (
        f"The stack: {stack_name}.\n"
        f"The selected deployment shape: {topology}.\n"
        f"The counted facts: {_citable(facts)}.\n"
        f"What the arithmetic rewarded:\n{reasons}\n\n"
        "Explain, for the reader deciding, why this stack fits or does not fit "
        "this design."
    )
