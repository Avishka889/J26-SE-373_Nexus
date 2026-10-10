"""Drawing one flow, and giving the model a second chance with real reasons.

The same bounded loop the graph uses: draw, validate, and if the rules found
errors, ask again with those errors written out as instructions. Two attempts,
because a third repeats the second.

What travels back is the hints, not the reasons. "Screen s4 targets s9, which is
not a screen here; point it at one of s1, s2, s3" is a repairable instruction.
"This journey has a broken link" is a sentence for a person.

Warnings do not trigger a repair and are not sent back. A dead end the model
chose is a decision a reader should see and judge, and asking the model to remove
every warning would teach it to link confirmation screens back to the start just
to silence the check, which is a worse prototype than an honest dead end.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field

from pydantic_ai import Agent
from sdlc_contracts import ArchitectureGraph, WireframeFlow

from ..agents import MALFORMED_OUTPUT_RETRIES, log_rejected, output_for, settings_for
from ..model_use import records_answers
from ..rules.findings import Finding, Report
from .build import to_contract
from .plan import FlowBrief
from .rules import validate_flow
from .schema import DraftFlow

#: Attempts in total, so one repair.
MAX_ATTEMPTS = 2

INSTRUCTIONS = """
You lay out the screens of one journey through a system, as a clickable
prototype: what the reader sees on each screen, and what each control leads to.

A screen is a list of lines. Each line has a kind:

  field    something the reader types or chooses
  row      one item in a list, usually pressable
  summary  a read-only fact, like a total
  banner   a short message across the top
  text     a sentence of explanation
  list     the heading of a group of rows
  button   a control used on this screen, like a calculator key: pressing it
           enters its value into the screen's first field, a value of "" clears
           that field, and with a linkId it goes where that link goes instead
  display  a large read-out of the screen's first field, like a calculator's
           result, or of its own value on a screen with no field

Draw what the screen is for. A screen that is used rather than filled in, a
calculator, a counter, a timer, is a display and its buttons, not a form.

And a screen has links: the controls that lead somewhere. Each names the id of
the screen it goes to.

Rules you must follow:

1. Every screen has at least one line on it. A screen where the journey ends is
   still a screen the reader looks at: give it a banner saying what happened, and
   the facts they came for. A name on its own draws as an empty box.
2. The first screen is where the reader starts. Every other screen must be
   reachable by following links from it.
3. Every link goes to a screen in this journey. Never link a screen to itself.
4. Every screen names the requirement ids it serves, in traces. Use only ids from
   the list you are given. Do not invent one to justify a screen.
5. A line that is pressable sets linkId to a link on its own screen.
6. Draw only the screens this journey needs. Three to six is usually right.
7. Where a journey ends, say so in the name: "Payment Confirmed", "Booking
   Receipt", "Card Declined". A screen with no way out and an ordinary name reads
   as an accident.
""".strip()


class CouldNotDrawFlow(RuntimeError):
    """Every attempt was refused by the rules.

    Carries the findings, so the caller can fail the stage with reasons a reader
    understands rather than with a stack trace.
    """

    def __init__(self, report: Report, attempts: int, flow_id: str) -> None:
        self.report = report
        self.attempts = attempts
        self.flow_id = flow_id
        reasons = "; ".join(finding.reason for finding in report.errors[:3])
        super().__init__(
            f"{flow_id} still broke {len(report.errors)} rule(s) after {attempts} attempts: {reasons}"
        )


@dataclass(frozen=True)
class FlowExtractionReport:
    """What it took to draw one flow, for the evaluation."""

    flow_id: str = ""
    attempts: int = 0
    #: The rule ids that fired on each attempt, oldest first.
    errors_per_attempt: tuple[tuple[str, ...], ...] = field(default=())
    #: Warnings on the attempt that succeeded. These travel with the flow and a
    #: reader sees them, which is the whole reason they are not errors.
    warnings: tuple[Finding, ...] = field(default=())
    screens: int = 0

    @property
    def repaired(self) -> bool:
        return (
            self.attempts > 1 and bool(self.errors_per_attempt) and bool(self.errors_per_attempt[0])
        )

    @property
    def clean_first_time(self) -> bool:
        return self.attempts == 1 and not any(self.errors_per_attempt)


def build_wireframe_agent(
    model: str, *, retries: int = MALFORMED_OUTPUT_RETRIES, thinking: str = "off"
) -> Agent[None, DraftFlow]:
    """The flow drawing agent. Build one and keep it; it owns a connection.

    The retry budget is shared and explained in `c1.agents`. It absorbs answers
    that could not be read; the loop below is for a well formed flow that breaks a
    rule, and the two must not be confused.
    """
    return Agent(
        model,
        output_type=output_for(DraftFlow, model, thinking=thinking),
        instructions=INSTRUCTIONS,
        retries=retries,
        model_settings=settings_for(model, thinking=thinking),
        capabilities=[records_answers()],
    )


def prompt_for(
    brief: FlowBrief,
    graph: ArchitectureGraph,
    requirement_ids: list[str],
    requirements: Sequence[tuple[str, str]] = (),
) -> str:
    """The journey to draw, and the only vocabulary it may be drawn from.

    `requirements` is each requirement's id and what it says. The drawer was
    given only the actor, "verb Entity" actions and the entities' field names,
    never what anybody asked for, so every journey came out as the same forms
    and lists whatever the subject was. What the requirements say (the answers a
    person gave included, since answering regenerates them) is what a screen is
    for, so it is offered for the journey's own requirements, or all of them when
    the journey names none.
    """
    entities = [
        f"  {node.label}: {', '.join(a.name for a in node.attributes) or 'no fields listed'}"
        for node in graph.nodes
        if node.id in brief.entity_ids
    ]
    parts = [f"The journey: what {brief.actor_label} does with this system."]
    if brief.actions:
        parts.append("What they do:\n" + "\n".join(f"  {action}" for action in brief.actions))
    if entities:
        parts.append("The things involved:\n" + "\n".join(entities))
    wanted = set(brief.traces)
    said = [(rid, text) for rid, text in requirements if not wanted or rid in wanted]
    if said:
        parts.append(
            "What the requirements say, which is what these screens are for:\n"
            + "\n".join(f"  {rid}: {text}" for rid, text in said)
        )
    parts.append("Requirement ids you may use in traces:\n  " + ", ".join(requirement_ids))
    parts.append("Draw the screens for this journey.")
    return "\n\n".join(parts)


def repair_prompt(previous: str, report: Report) -> str:
    """The same request, plus exactly what was wrong with the last answer."""
    return (
        f"{previous}\n\n"
        "Your previous screens broke these rules. Fix each one and return the whole "
        "journey again:\n\n"
        f"{report.hints()}"
    )


async def draw_flow(
    brief: FlowBrief,
    graph: ArchitectureGraph,
    *,
    agent: Agent[None, DraftFlow],
    requirement_ids: list[str],
    version: str,
    requirements: Sequence[tuple[str, str]] = (),
    max_attempts: int = MAX_ATTEMPTS,
) -> tuple[WireframeFlow, FlowExtractionReport]:
    """Draw one flow, validate it, and repair it once if the rules refuse it."""
    known = frozenset(requirement_ids)
    prompt = prompt_for(brief, graph, requirement_ids, requirements)

    errors_per_attempt: list[tuple[str, ...]] = []
    report = Report()
    draft = DraftFlow(name="", screens=[])

    for attempt in range(1, max_attempts + 1):
        result = await agent.run(prompt)
        draft = result.output
        report = validate_flow(draft, requirement_ids=known)
        errors_per_attempt.append(tuple(sorted({f.rule_id for f in report.errors})))

        if report.ok:
            flow = to_contract(
                draft,
                report,
                flow_id=brief.id,
                version=version,
                traces=list(brief.traces),
            )
            return flow, FlowExtractionReport(
                flow_id=brief.id,
                attempts=attempt,
                errors_per_attempt=tuple(errors_per_attempt),
                warnings=report.warnings,
                screens=len(flow.screens),
            )

        if attempt < max_attempts:
            prompt = repair_prompt(prompt_for(brief, graph, requirement_ids, requirements), report)

    log_rejected(
        f"wireframe flow {brief.id}", draft, attempts=max_attempts, rules=report.rule_ids()
    )
    raise CouldNotDrawFlow(report, max_attempts, brief.id)
