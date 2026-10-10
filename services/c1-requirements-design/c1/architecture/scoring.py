"""Scoring the deployment shapes, by arithmetic over the design.

The model never produces a score. Every number here comes from counting things in
the requirements and the graph, and every adjustment carries the fact that caused
it, so a reader can ask "why 82" and get an answer rather than a shrug.

The candidates are deployment shapes, and only deployment shapes. A code
organisation style is a different axis: "Clean Architecture 71 versus
Microservices 68" compares a way of arranging modules with a way of deploying
them, and a viva panel will say so. The style is recorded beside the comparison
as a note, not scored against it.

Three shapes rather than five, for the same reason.
"""

from dataclasses import dataclass, field
from typing import Final

from sdlc_contracts import ArchitectureGraph, ParsedRequirement


@dataclass(frozen=True)
class ScoringFacts:
    """What the design actually contains. Counted, never asked for."""

    n_requirements: int = 0
    n_services: int = 0
    n_entities: int = 0
    n_external: int = 0
    #: Entities written by more than one service. Each one is a transaction that
    #: crosses a boundary, which is what makes splitting expensive.
    cross_service_writes: int = 0
    #: A requirement asking for one part to scale without the others.
    independent_scaling: bool = False
    #: A named standard or a security constraint the design has to satisfy.
    compliance_signal: bool = False
    #: Figures the requirements themselves state, each as the number and the word
    #: that follows it: ("99.5", "percent"), ("30", "seconds").
    #:
    #: Carried here so an explanation may quote the brief. A figure the input
    #: states is not one the model invented, and refusing it made the stage fail
    #: on the most relevant numbers there were. The pair is the point: the number
    #: alone is not evidence, because a brief saying "under 2 seconds" would
    #: otherwise license "a team of 2 engineers".
    #:
    #: Deliberately outside `as_dict`, which is the prompt and the scoring input.
    #: These are permitted to appear, not facts to reason from.
    source_figures: frozenset[tuple[str, str]] = frozenset()

    def as_dict(self) -> dict[str, int | bool]:
        """The facts an explanation is allowed to cite, and nothing else."""
        return {
            "requirements": self.n_requirements,
            "services": self.n_services,
            "entities": self.n_entities,
            "external systems": self.n_external,
            "cross service writes": self.cross_service_writes,
            "independent scaling": self.independent_scaling,
            "compliance": self.compliance_signal,
        }


#: Words in a requirement that mean one part has to scale apart from the rest.
_SCALING_WORDS: Final = (
    "scale",
    "scaling",
    "concurrent",
    "throughput",
    "traffic",
    "load",
    "independently",
    "without affecting",
    "degrade",
    "spike",
    "peak",
)
_COMPLIANCE_WORDS: Final = (
    "pci",
    "gdpr",
    "hipaa",
    "iso",
    "soc 2",
    "wcag",
    "hl7",
    "fhir",
    "compliance",
    "comply",
    "regulation",
    "audit trail",
    "retention",
)


def source_figures_in(text: str) -> frozenset[tuple[str, str]]:
    """The figures the requirements state, as (number, following word) pairs.

    Imported from the explanation module rather than written twice: the pair the
    guard looks for and the pair recorded here have to be built the same way, or
    a figure quoted verbatim from the brief fails to match itself.
    """
    from .explain import _figures_in

    return frozenset(_figures_in(text))


def gather_facts(requirements: list[ParsedRequirement], graph: ArchitectureGraph) -> ScoringFacts:
    """Count what the design contains."""
    text = " ".join(requirement.text.lower() for requirement in requirements)

    services = [node for node in graph.nodes if node.kind == "service"]
    entities = [node for node in graph.nodes if node.kind == "entity"]
    external = [node for node in graph.nodes if node.actor_kind == "external_system"]

    # An entity written by two services is a transaction that crosses a boundary.
    writers: dict[str, set[str]] = {}
    for edge in graph.edges:
        if edge.kind != "data":
            continue
        writers.setdefault(edge.target, set()).add(edge.source)
    cross = sum(1 for owners in writers.values() if len(owners) > 1)

    compliance = any(word in text for word in _COMPLIANCE_WORDS) or any(
        node.standard for node in graph.nodes if node.kind == "constraint"
    )

    return ScoringFacts(
        source_figures=source_figures_in(text),
        n_requirements=len(requirements),
        n_services=len(services),
        n_entities=len(entities),
        n_external=len(external),
        cross_service_writes=cross,
        independent_scaling=any(word in text for word in _SCALING_WORDS),
        compliance_signal=compliance,
    )


@dataclass(frozen=True)
class Adjustment:
    """One reason a shape scored what it did."""

    factor: str
    points: int
    reason: str


@dataclass(frozen=True)
class CandidateScore:
    id: str
    name: str
    score: int
    adjustments: tuple[Adjustment, ...] = field(default=())

    @property
    def why(self) -> str:
        return " ".join(adjustment.reason for adjustment in self.adjustments)


def _clamp(value: int) -> int:
    return max(0, min(100, value))


def _monolith(facts: ScoringFacts) -> list[Adjustment]:
    out: list[Adjustment] = []
    if facts.n_services <= 3:
        out.append(
            Adjustment("small-scope", 12, f"Only {facts.n_services} services in the design.")
        )
    if facts.cross_service_writes:
        out.append(
            Adjustment(
                "one-transaction",
                10,
                f"{facts.cross_service_writes} thing(s) written by more than one service, "
                f"which stays a single transaction here.",
            )
        )
    if facts.independent_scaling:
        out.append(
            Adjustment(
                "scales-together",
                -15,
                "A requirement asks for one part to scale apart from the rest, and "
                "everything here scales together.",
            )
        )
    if facts.n_services >= 6:
        out.append(
            Adjustment("many-services", -12, f"{facts.n_services} services in one deployment.")
        )
    return out


def _microservices(facts: ScoringFacts) -> list[Adjustment]:
    out: list[Adjustment] = []
    if facts.n_services >= 4:
        out.append(
            Adjustment(
                "real-boundaries",
                12,
                f"The graph already separates {facts.n_services} services.",
            )
        )
    if facts.independent_scaling:
        out.append(
            Adjustment(
                "scales-apart",
                18,
                "A requirement asks for one part to scale without the others.",
            )
        )
    if facts.cross_service_writes:
        out.append(
            Adjustment(
                "distributed-write",
                -15,
                f"{facts.cross_service_writes} write(s) cross a service boundary and would "
                f"need a saga.",
            )
        )
    if facts.n_services <= 2:
        out.append(
            Adjustment(
                "nothing-to-split",
                -20,
                f"With {facts.n_services} service(s) there is nothing to split along.",
            )
        )
    if facts.n_external >= 2:
        out.append(
            Adjustment("external-seams", 6, f"{facts.n_external} external systems to isolate.")
        )
    return out


def _serverless(facts: ScoringFacts) -> list[Adjustment]:
    out: list[Adjustment] = []
    if facts.n_requirements <= 4:
        out.append(
            Adjustment(
                "small-surface",
                10,
                f"{facts.n_requirements} requirement(s), so there is little to host.",
            )
        )
    if facts.n_entities <= 1:
        out.append(
            Adjustment(
                "little-state",
                10,
                f"{facts.n_entities} thing(s) kept, so almost nothing needs a running store.",
            )
        )
    if facts.n_entities >= 4:
        out.append(
            Adjustment(
                "stateful",
                -12,
                f"{facts.n_entities} things kept, each needing a store outside the function.",
            )
        )
    if facts.cross_service_writes:
        out.append(
            Adjustment(
                "distributed-write",
                -10,
                "Writes that cross a boundary are awkward without a long lived process.",
            )
        )
    if facts.independent_scaling:
        out.append(Adjustment("scales-per-request", 8, "Scaling per request is the default here."))
    if facts.compliance_signal:
        out.append(
            Adjustment(
                "compliance-surface",
                -6,
                "A named standard is more work to evidence across many small functions.",
            )
        )
    return out


#: The three shapes, their starting point, and the rule that adjusts each.
#:
#: Bases differ because the shapes are not equally likely before any evidence: a
#: single deployment is the default a team gets right, and the others have to
#: earn their cost. Starting all three at the same number would be neutral and
#: wrong.
CANDIDATES: Final = (
    ("modular-monolith", "Modular Monolith", 70, _monolith),
    ("microservices", "Microservices", 45, _microservices),
    ("serverless", "Serverless functions", 35, _serverless),
)


def score_topologies(facts: ScoringFacts) -> list[CandidateScore]:
    """Score every shape, highest first.

    Ties break on the candidate order above, which puts the cheaper shape first.
    Arbitrary but stable: an unstable tie break would recommend a different shape
    on two runs over the same design.
    """
    scored: list[CandidateScore] = []
    for identifier, name, base, rule in CANDIDATES:
        adjustments = rule(facts)
        scored.append(
            CandidateScore(
                id=identifier,
                name=name,
                score=_clamp(base + sum(a.points for a in adjustments)),
                adjustments=tuple(adjustments),
            )
        )
    order = {identifier: index for index, (identifier, *_rest) in enumerate(CANDIDATES)}
    scored.sort(key=lambda candidate: (-candidate.score, order[candidate.id]))
    return scored


def recommended(facts: ScoringFacts) -> CandidateScore:
    return score_topologies(facts)[0]


def margin(facts: ScoringFacts) -> int:
    """How far ahead the winner is. A recommendation nobody can argue with is
    either obvious or a rubber stamp, and this is what tells the two apart."""
    scored = score_topologies(facts)
    return scored[0].score - scored[1].score
