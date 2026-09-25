"""The model, for the failures the rules cannot reach, on a short leash.

The rules decide from traceability, and they decide most of it. What is left is
a failing test whose traces point at nothing, or at a mixture of things that
moved and things that did not, and that is a judgement rather than a lookup. So
a model is asked, under two conditions that make the answer checkable.

**It must quote a change it was given.** Every verdict carries a cited diff
span, the check is that the citation is one of the lines actually supplied, and
a verdict that cites something else is refused and the failure stays undecided.
That is the same discipline `c3.probe` measures a provider against before any
of this runs, and it exists because a classification that cannot point at
evidence is a guess with a confident tone.

**It cannot decide alone that a test is stale.** A refused citation, a malformed
answer, or an exhausted attempt budget all leave the classification `undecided`,
which reaches a human rather than the repair loop. The dangerous direction here
is one way: calling a regression brittle sends a real bug to be papered over,
while calling brittleness a regression only costs a person a look.
"""

import logging
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models import Model
from sdlc_contracts import ClassificationEvidence, ContractDiff, RequirementDiff, TestCase

from ..agents import MALFORMED_OUTPUT_RETRIES, log_rejected, model_for, output_for, settings_for
from ..model_use import records_answers
from .classify import Verdict, traced_to

log = logging.getLogger(__name__)

#: One retry with the reason, then the failure stays undecided. C1's number and
#: C1's reason: a second refusal is a model that cannot satisfy the rule, and a
#: third attempt spends tokens to learn that again.
REFEREE_ATTEMPTS = 2

INSTRUCTIONS = (
    "You referee one failing test that a rule could not classify. Decide "
    "whether it is `brittle` (the behaviour changed on purpose and the test "
    "encodes the old behaviour, so the test is stale) or a `regression` (the "
    "behaviour changed by accident and the test is right). Answer `undecided` "
    "when the changes you were given do not settle it.\n"
    "Quote, exactly, one of the numbered change lines you were given as your "
    "evidence. Copy it character for character. A verdict citing anything else "
    "is refused.\n"
    "Saying `undecided` is a correct answer and is better than a guess: an "
    "undecided failure reaches a person, and a wrong `brittle` sends a real "
    "bug to be papered over."
)


class RefereeAnswer(BaseModel):
    """The only shape the referee may produce."""

    classification: Literal["brittle", "regression", "undecided"]
    cited_change: str = Field(description="One change line, copied exactly.")
    reasoning: str = Field(default="", description="One sentence, for the reader.")


@dataclass(frozen=True)
class Change:
    """One change, as the model is shown it and as it must quote it back."""

    label: str
    text: str

    @property
    def line(self) -> str:
        return f"[{self.label}] {self.text}"


def changes_for(
    contracts: ContractDiff | None, requirements: RequirementDiff | None
) -> list[Change]:
    """Everything that moved between the two versions, one labelled line each.

    Labelled so a citation can be checked exactly. Asking a model to quote a
    rendered JSON schema back character for character would fail on whitespace
    and prove nothing about whether it looked.
    """
    found: list[Change] = []
    if contracts is not None:
        for endpoint_id in contracts.added:
            found.append(Change(f"E{len(found) + 1}", f"endpoint {endpoint_id} was added"))
        for endpoint_id in contracts.removed:
            found.append(Change(f"E{len(found) + 1}", f"endpoint {endpoint_id} was removed"))
        for change in contracts.changed:
            found.append(
                Change(
                    f"E{len(found) + 1}",
                    f"endpoint {change.endpoint_id} changed its {change.field}",
                )
            )
    if requirements is not None:
        for requirement_id in requirements.added:
            found.append(Change(f"R{len(found) + 1}", f"requirement {requirement_id} was added"))
        for requirement_id in requirements.removed:
            found.append(Change(f"R{len(found) + 1}", f"requirement {requirement_id} was removed"))
        for change in requirements.changed:
            found.append(
                Change(
                    f"R{len(found) + 1}",
                    f"requirement {change.requirement_id} changed its {change.field} "
                    f"from {change.before!r} to {change.after!r}",
                )
            )
    return found


def check_citation(cited: str, changes: list[Change]) -> tuple[bool, str]:
    """Is the quoted change one of the ones we supplied?

    Accepts the label alone or the whole line, and ignores surrounding
    whitespace, because the question is whether the model looked at what it was
    given rather than whether it can transcribe.
    """
    quoted = cited.strip()
    if not quoted:
        return False, "cited nothing"
    for change in changes:
        if quoted in (change.label, change.line, change.text, f"[{change.label}]"):
            return True, ""
    return False, f"cited a change that was not supplied: {quoted!r}"


def build_referee(
    model: str | Model, *, retries: int = MALFORMED_OUTPUT_RETRIES, thinking: str = "off"
):
    return Agent(
        model_for(model),
        output_type=output_for(RefereeAnswer, model, thinking=thinking),
        instructions=INSTRUCTIONS,
        retries=retries,
        model_settings=settings_for(model, thinking=thinking),
        capabilities=[records_answers()],
    )


def prompt_for(case: TestCase, changes: list[Change]) -> str:
    traces = traced_to(case)
    lines = [
        f"The failing test: {case.name}",
        f"It failed with: {case.message.strip().splitlines()[0] if case.message.strip() else 'no message'}",
        f"It was written from: {', '.join(traces) or 'nothing recorded'}",
        "",
        "What changed between the version it was written against and the version",
        "it now runs against:",
    ]
    lines.extend(f"  {change.line}" for change in changes)
    if not changes:
        lines.append("  nothing changed in the contract or the requirements")
    return "\n".join(lines)


async def referee(
    agent: Agent[None, RefereeAnswer],
    case: TestCase,
    *,
    contracts: ContractDiff | None = None,
    requirements: RequirementDiff | None = None,
    attempts: int = REFEREE_ATTEMPTS,
) -> Verdict:
    """Ask the model, and believe it only if it points at something real.

    Returns a verdict either way. A refused citation leaves the classification
    undecided with the reason on it, which is the outcome that reaches a person.
    """
    changes = changes_for(contracts, requirements)
    traces = traced_to(case)
    if not changes:
        return Verdict(
            classification="undecided",
            classified_by="unclassified",
            evidence=ClassificationEvidence(
                traced_to=traces,
                referee_reasoning=(
                    "nothing changed between the two versions, so there was nothing for a "
                    "referee to look at"
                ),
            ),
        )

    prompt = prompt_for(case, changes)
    refused: list[str] = []
    for attempt in range(1, attempts + 1):
        answer = (await agent.run(prompt)).output
        ok, why = check_citation(answer.cited_change, changes)
        if ok:
            return Verdict(
                classification=answer.classification,
                # `model-referee` even when it answers undecided: a model was
                # asked, and the evaluation counts how often that happened
                # rather than how often it helped.
                classified_by="model-referee",
                evidence=ClassificationEvidence(
                    traced_to=traces,
                    changed_artefacts=[
                        trace for trace in traces if any(trace in change.text for change in changes)
                    ],
                    cited_diff_span=answer.cited_change.strip(),
                    referee_reasoning=answer.reasoning.strip(),
                ),
            )
        refused.append(why)
        log_rejected("self-healing referee", attempt, [why])
        prompt = f"{prompt}\n\nYour previous answer was refused: {why}"

    return Verdict(
        classification="undecided",
        classified_by="unclassified",
        evidence=ClassificationEvidence(
            traced_to=traces,
            referee_reasoning=(
                f"the referee cited evidence it was not given {len(refused)} times, so its "
                "verdict was not used: " + "; ".join(refused[:2])
            ),
        ),
    )


_LABEL = re.compile(r"^\[([ER]\d+)\]")


def label_of(line: str) -> str:
    """The label out of a rendered change line, for a reader following a
    citation back to what was shown."""
    match = _LABEL.match(line.strip())
    return match.group(1) if match else ""
