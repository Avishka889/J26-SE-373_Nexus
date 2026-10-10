"""Writing the sprint plan, and giving the model a second chance with real reasons.

The same bounded loop as the graph and the wireframes. Two attempts, hints back
on the second, warnings never sent back.

The prompt is deliberately shown the graph as well as the requirements. A story
is a slice of delivered behaviour, and a model given only a list of requirements
writes one story per requirement, which is a restatement rather than a plan. The
entities and services say what has to exist for a story to be finished.
"""

from dataclasses import dataclass, field

from pydantic_ai import Agent
from sdlc_contracts import ArchitectureGraph, ParsedRequirement, SprintPlan

from ..agents import MALFORMED_OUTPUT_RETRIES, log_rejected, output_for, settings_for
from ..model_use import records_answers
from ..rules.findings import Finding, Report
from .build import to_contract
from .rules import validate_plan
from .schema import DraftPlan

#: Attempts in total, so one repair.
MAX_ATTEMPTS = 2

INSTRUCTIONS = """
You turn a set of requirements into the user stories that would deliver them.

For each story, write:

  title       one sentence from the reader's side, such as
              "As a customer, I can pay with a saved card"
  epic        the group of work it belongs under, such as "Payments"
  traces      the requirement ids this story realises
  acceptance  at least one given/when/then saying how anyone can tell it works

Rules you must follow:

1. Acceptance criteria are the important part. They are turned into test cases
   later, so each one has to be checkable: `given` the situation, `when` the
   thing that happens, `then` what is observably true afterwards. The `then`
   must never restate the `when`, or the test asserts nothing.
2. Every story names the requirement ids it realises, in traces. Use only ids
   from the list you are given. Do not invent one to justify a story.
3. Write a story for every requirement that describes something a user can do.
   A requirement covered by no story is a gap somebody has to see.
4. One story per slice of behaviour a user would recognise, not one per
   requirement. Two requirements about the same action are one story.
5. Never say the same thing twice.

Do not give points, priorities or story ids. Those are worked out from the
design, not written here.
""".strip()


class CouldNotPlanSprint(RuntimeError):
    """Every attempt was refused by the rules."""

    def __init__(self, report: Report, attempts: int) -> None:
        self.report = report
        self.attempts = attempts
        reasons = "; ".join(finding.reason for finding in report.errors[:3])
        super().__init__(
            f"the plan still broke {len(report.errors)} rule(s) after {attempts} attempts: {reasons}"
        )


@dataclass(frozen=True)
class SprintReport:
    """What it took to get a plan, for the evaluation."""

    attempts: int = 0
    errors_per_attempt: tuple[tuple[str, ...], ...] = field(default=())
    #: Warnings on the attempt that succeeded. Requirement coverage lives here,
    #: which is the traceability figure the evaluation reports.
    warnings: tuple[Finding, ...] = field(default=())
    stories: int = 0

    @property
    def repaired(self) -> bool:
        return (
            self.attempts > 1 and bool(self.errors_per_attempt) and bool(self.errors_per_attempt[0])
        )

    @property
    def clean_first_time(self) -> bool:
        return self.attempts == 1 and not any(self.errors_per_attempt)


def build_sprint_agent(
    model: str, *, retries: int = MALFORMED_OUTPUT_RETRIES, thinking: str = "off"
) -> Agent[None, DraftPlan]:
    """The planning agent. Build one and keep it; it owns a connection."""
    return Agent(
        model,
        output_type=output_for(DraftPlan, model, thinking=thinking),
        instructions=INSTRUCTIONS,
        retries=retries,
        model_settings=settings_for(model, thinking=thinking),
        capabilities=[records_answers()],
    )


def prompt_for(requirements: list[ParsedRequirement], graph: ArchitectureGraph) -> str:
    """The requirements, and what the design says has to exist to satisfy them."""
    lines = [f"  {r.id} ({r.priority}, {r.type}): {r.text}" for r in requirements]
    entities = [f"  {n.label}" for n in graph.nodes if n.kind == "entity"]
    services = [f"  {n.label}" for n in graph.nodes if n.kind == "service"]

    parts = ["The requirements:\n" + "\n".join(lines)]
    if entities:
        parts.append("What the system keeps:\n" + "\n".join(entities))
    if services:
        parts.append("What the system runs:\n" + "\n".join(services))
    parts.append("Write the user stories that would deliver these.")
    return "\n\n".join(parts)


def repair_prompt(previous: str, report: Report) -> str:
    """The same request, plus exactly what was wrong with the last answer."""
    return (
        f"{previous}\n\n"
        "Your previous plan broke these rules. Fix each one and return the whole "
        "plan again:\n\n"
        f"{report.hints()}"
    )


async def plan_sprint(
    requirements: list[ParsedRequirement],
    graph: ArchitectureGraph,
    *,
    agent: Agent[None, DraftPlan],
    max_attempts: int = MAX_ATTEMPTS,
) -> tuple[SprintPlan, SprintReport]:
    """Write a plan, validate it, and repair it once if the rules refuse it."""
    prompt = prompt_for(requirements, graph)

    errors_per_attempt: list[tuple[str, ...]] = []
    report = Report()
    draft = DraftPlan(goal="", stories=[])

    for attempt in range(1, max_attempts + 1):
        result = await agent.run(prompt)
        draft = result.output
        report = validate_plan(draft, requirements=requirements, graph=graph)
        errors_per_attempt.append(tuple(sorted({f.rule_id for f in report.errors})))

        if report.ok:
            plan = to_contract(draft, requirements=requirements, graph=graph)
            return plan, SprintReport(
                attempts=attempt,
                errors_per_attempt=tuple(errors_per_attempt),
                warnings=report.warnings,
                stories=len(plan.proposed) + len(plan.backlog),
            )

        if attempt < max_attempts:
            prompt = repair_prompt(prompt_for(requirements, graph), report)

    log_rejected("sprint-plan", draft, attempts=max_attempts, rules=report.rule_ids())
    raise CouldNotPlanSprint(report, max_attempts)
