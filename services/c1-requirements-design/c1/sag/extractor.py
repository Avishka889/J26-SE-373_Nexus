"""Building the graph, and giving the model a second chance with real reasons.

The loop is short and bounded: build, validate, and if the rules found errors,
ask again with those errors written out as instructions. Two attempts, not more.

Bounded because an unbounded loop against a model that cannot satisfy a rule is
an expensive way to fail, and because a third attempt in practice repeats the
second. What makes the second attempt worth having is not that it is a retry: it
is that the prompt changes. The rules produced sentences saying which node broke
which rule and what to do instead, and those go back in. A loop that re-sends the
same prompt and hopes is not repair, and this module has a test asserting the
hints really travel.

If the second attempt still has errors, this raises rather than promoting a graph
the rules refused, and rather than quietly deleting the offending parts. The
design is the generative source for everything downstream, so a broken one is a
failed stage with reasons attached, not a smaller graph nobody asked for.
"""

from dataclasses import dataclass, field

from pydantic_ai import Agent
from sdlc_contracts import ArchitectureGraph, ParsedRequirement

from ..agents import MALFORMED_OUTPUT_RETRIES, log_rejected, output_for, settings_for
from ..model_use import records_answers
from .build import to_contract
from .layout import layout
from .rules import SagFinding, ValidationReport, validate_sag
from .schema import DraftGraph

#: Attempts in total, so one repair. The plan's own bound.
MAX_ATTEMPTS = 2

INSTRUCTIONS = """
You turn a list of requirements into one typed graph of the system.

The graph has four kinds of node:

  actor       a person, or another system this one talks to. Never a screen,
              a page or a form: those are interface, not someone who acts.
              Always set actor_kind: "primary" for a person, "external_system"
              for another system.
  entity      something the system keeps. Always list its fields in attributes,
              even if only an id and one more, and only an entity has fields.
  service     something the system runs.
  constraint  a rule the design has to obey. It must name the node ids it binds
              in applies_to, and name the standard it comes from.

And four kinds of edge:

  action      who does what to what, with a present tense verb, so it reads
              "Customer makes Payment"
  data        which service owns which entity
  dependency  which service calls what
  constraint  which rule binds what

Every node has to be wired, and each kind is wired differently. This is the part
most often got wrong: the nodes come out right and the edges are forgotten, which
leaves things drawn on the design that nothing uses.

  an actor       needs an action edge to an entity: who does what to what
  an entity      needs a data edge from the service that owns it
  a service      needs a data edge to an entity it owns, or a dependency edge to
                 something it calls
  a constraint   needs a constraint edge to each node id it binds

A worked example. Two nodes and one service is three nodes and two edges, never
three nodes and no edges:

  nodes  a1 actor "Customer", e1 entity "Order", m1 service "Order Service"
  edges  x1 action a1 -> e1 "places",  x2 data m1 -> e1 "owns"

Rules you must follow:

1. Every node and every edge names the requirement ids it came from, in traces.
   Use only ids from the list you are given. Do not invent one to justify a node.
2. Before you answer, read your own edge list and check that every node id you
   created appears in it. A node with no edge is worse than a missing node.
3. Ids are short and unique: a1, e1, m1, c1, x1.
4. Build only what the requirements ask for. A graph with things nobody asked for
   is worse than a small one. Three or four nodes is usually right for something
   described in a sentence.
""".strip()


class CouldNotBuildGraph(RuntimeError):
    """Every attempt was refused by the rules.

    Carries the findings, so the caller can fail the stage with reasons a reader
    understands rather than with a stack trace.
    """

    def __init__(self, report: ValidationReport, attempts: int) -> None:
        self.report = report
        self.attempts = attempts
        reasons = "; ".join(finding.reason for finding in report.errors[:3])
        super().__init__(
            f"the graph still broke {len(report.errors)} rule(s) after {attempts} attempts: {reasons}"
        )


@dataclass(frozen=True)
class GraphExtractionReport:
    """What it took to get a graph, for the evaluation."""

    attempts: int = 0
    #: The rule ids that fired on each attempt, oldest first. The interesting
    #: number is whether the second attempt fixed what the first got wrong.
    errors_per_attempt: tuple[tuple[str, ...], ...] = field(default=())
    #: Warnings on the attempt that succeeded. Not errors: these travel with the
    #: graph and the reader sees them on the canvas.
    warnings: tuple[SagFinding, ...] = field(default=())

    @property
    def repaired(self) -> bool:
        """True when the first attempt failed and a later one succeeded."""
        return (
            self.attempts > 1 and bool(self.errors_per_attempt) and bool(self.errors_per_attempt[0])
        )

    @property
    def clean_first_time(self) -> bool:
        return self.attempts == 1 and not any(self.errors_per_attempt)


def build_graph_agent(
    model: str, *, retries: int = MALFORMED_OUTPUT_RETRIES, thinking: str = "off"
) -> Agent[None, DraftGraph]:
    """The graph building agent. Build one and keep it; it owns a connection.

    The retry budget is shared and explained in `c1.agents`. It absorbs an answer
    that could not be read: against Groq the model sometimes returns this output as
    text wrapped in `<function=final_result({...})</function>` instead of as a tool
    call, which does not parse as a graph.

    Separate from the repair loop below, which is for a well formed graph that
    breaks a rule. Confusing the two leads to raising this number when the real
    problem is that the model is answering wrongly rather than unreadably.
    """
    return Agent(
        model,
        output_type=output_for(DraftGraph, model, thinking=thinking),
        instructions=INSTRUCTIONS,
        retries=retries,
        model_settings=settings_for(model, thinking=thinking),
        capabilities=[records_answers()],
    )


def prompt_for(requirements: list[ParsedRequirement]) -> str:
    """The requirements, as the only thing the graph may be built from."""
    lines = [f"{r.id}: {r.text}" for r in requirements]
    return "Build the graph for these requirements. Use only these ids in traces.\n\n" + "\n".join(
        lines
    )


def repair_prompt(previous: str, report: ValidationReport) -> str:
    """The same request, plus exactly what was wrong with the last answer.

    The hints, not the reasons: the reasons are written for a person reading the
    design, and the hints name ids and say what to do. Sending the reader-facing
    wording here would be polite and useless.
    """
    return (
        f"{previous}\n\n"
        "Your previous graph broke these rules. Fix each one and return the whole "
        "graph again:\n\n"
        f"{report.hints()}"
    )


async def extract_graph(
    requirements: list[ParsedRequirement],
    *,
    agent: Agent[None, DraftGraph],
    requirements_text: str = "",
    max_attempts: int = MAX_ATTEMPTS,
) -> tuple[ArchitectureGraph, GraphExtractionReport]:
    """Build a graph, validate it, and repair it once if the rules refuse it."""
    ids = frozenset(requirement.id for requirement in requirements)
    prompt = prompt_for(requirements)

    errors_per_attempt: list[tuple[str, ...]] = []
    report = ValidationReport()
    draft = DraftGraph(nodes=[], edges=[])

    for attempt in range(1, max_attempts + 1):
        result = await agent.run(prompt)
        draft = result.output
        report = validate_sag(draft, requirement_ids=ids, requirements_text=requirements_text)
        errors_per_attempt.append(tuple(sorted({f.rule_id for f in report.errors})))

        if report.ok:
            # Positions are computed here rather than asked of the model. A model
            # has no idea where anything should sit, and its guesses differ
            # between two runs over identical requirements, which is exactly what
            # makes the impact highlight unreadable.
            return to_contract(
                draft,
                report,
                # In the order the brief reads, so the canvas and the
                # requirements page agree about what comes first. Requirement
                # ids are identities carried across design versions, so the
                # number inside one no longer says where it sits.
                positions=layout(draft.nodes, requirement_ids=[one.id for one in requirements]),
            ), GraphExtractionReport(
                attempts=attempt,
                errors_per_attempt=tuple(errors_per_attempt),
                warnings=report.warnings,
            )

        if attempt < max_attempts:
            prompt = repair_prompt(prompt_for(requirements), report)

    log_rejected("architecture-graph", draft, attempts=max_attempts, rules=report.rule_ids())
    raise CouldNotBuildGraph(report, max_attempts)
