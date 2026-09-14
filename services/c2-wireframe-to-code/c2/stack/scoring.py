"""Scoring the stacks, by arithmetic over the design. The model never scores.

Every number comes from counting things in the architecture graph and the
recommendation C1 shipped, and every adjustment names the fact that caused it,
so "why 74" has an answer. The recommendation is the arithmetic winner; the
run's default selection is the top AVAILABLE candidate, and the two can
disagree honestly when the winner's generators are not built yet.
"""

from dataclasses import dataclass

from sdlc_contracts import (
    ArchitectureGraph,
    ArchitectureRecommendation,
    CountedFact,
    ScorePart,
    StackCandidate,
    TechStackArtefact,
)

from .catalog import CATALOG


@dataclass(frozen=True)
class StackFacts:
    """What the design actually contains. Counted, never asked for."""

    n_entities: int = 0
    n_services: int = 0
    n_external: int = 0
    cross_service_writes: int = 0
    #: Constraint nodes carrying a named standard: the compliance signal.
    n_standards: int = 0
    #: The deployment shape the human selected at the design gate.
    selected_topology: str = ""

    def as_counted(self) -> list[CountedFact]:
        return [
            CountedFact(label="entities", value=self.n_entities),
            CountedFact(label="services", value=self.n_services),
            CountedFact(label="external systems", value=self.n_external),
            CountedFact(label="cross service writes", value=self.cross_service_writes),
            CountedFact(label="named standards", value=self.n_standards),
        ]

    def as_dict(self) -> dict[str, int]:
        """The facts an explanation is allowed to cite, and nothing else."""
        return {fact.label: fact.value for fact in self.as_counted()}


def gather_stack_facts(
    graph: ArchitectureGraph, recommendation: ArchitectureRecommendation | None
) -> StackFacts:
    services = [node for node in graph.nodes if node.kind == "service"]
    entities = [node for node in graph.nodes if node.kind == "entity"]
    external = [node for node in graph.nodes if node.actor_kind == "external_system"]
    standards = [node for node in graph.nodes if node.kind == "constraint" and node.standard]

    # An entity written by two services is a transaction crossing a boundary,
    # counted exactly the way C1's topology scoring counts it.
    writers: dict[str, set[str]] = {}
    for edge in graph.edges:
        if edge.kind != "data":
            continue
        writers.setdefault(edge.target, set()).add(edge.source)
    cross = sum(1 for owners in writers.values() if len(owners) > 1)

    topology = ""
    if recommendation is not None:
        chosen = recommendation.selected_candidate_id or recommendation.recommended_candidate_id
        topology = next(
            (c.name for c in recommendation.candidates if c.id == chosen),
            chosen,
        )

    return StackFacts(
        n_entities=len(entities),
        n_services=len(services),
        n_external=len(external),
        cross_service_writes=cross,
        n_standards=len(standards),
        selected_topology=topology,
    )


@dataclass(frozen=True)
class Adjustment:
    points: int
    reason: str


BASE_SCORE = 50


def _clamp(value: int) -> int:
    return max(0, min(100, value))


def _spring_adjustments(facts: StackFacts) -> list[Adjustment]:
    adjustments: list[Adjustment] = []
    if facts.n_standards:
        adjustments.append(
            Adjustment(
                12,
                f"{facts.n_standards} named standard(s): typed controllers and "
                "relational integrity carry compliance constraints into the runtime",
            )
        )
    if facts.cross_service_writes:
        adjustments.append(
            Adjustment(
                4 * min(facts.cross_service_writes, 4),
                f"{facts.cross_service_writes} cross service write(s): transactions "
                "that cross boundaries want a relational store",
            )
        )
    if facts.n_entities >= 6:
        adjustments.append(
            Adjustment(
                8,
                f"{facts.n_entities} entities: a rich model benefits from a "
                "relational schema and migrations",
            )
        )
    return adjustments


def _mern_adjustments(facts: StackFacts) -> list[Adjustment]:
    adjustments: list[Adjustment] = []
    if facts.n_entities and facts.n_entities <= 5:
        adjustments.append(
            Adjustment(
                10,
                f"{facts.n_entities} entities: a small model maps straight onto "
                "document shapes with no join pressure",
            )
        )
    if facts.cross_service_writes == 0:
        adjustments.append(
            Adjustment(
                8,
                "0 cross service writes: nothing needs a transaction across a "
                "boundary, so a document store costs nothing",
            )
        )
    if facts.n_external:
        adjustments.append(
            Adjustment(
                3 * min(facts.n_external, 3),
                f"{facts.n_external} external system(s): integration heavy work "
                "suits Node's async I/O",
            )
        )
    adjustments.append(
        Adjustment(
            5,
            "one language across the monorepo: the typed client and the handlers "
            "share the contract types with no translation",
        )
    )
    return adjustments


_ADJUSTERS = {
    "mern": _mern_adjustments,
    "react-spring-postgres": _spring_adjustments,
}


def score_stacks(facts: StackFacts) -> TechStackArtefact:
    """Every catalog entry scored, the winner recommended, the top available
    candidate selected by default."""
    candidates: list[StackCandidate] = []
    for entry in CATALOG:
        adjustments = _ADJUSTERS[entry.id](facts)
        score = _clamp(BASE_SCORE + sum(a.points for a in adjustments))
        candidates.append(
            StackCandidate(
                id=entry.id,
                name=entry.name,
                layers=list(entry.layers),
                score=score,
                score_breakdown=[
                    ScorePart(label="baseline", points=BASE_SCORE),
                    *(ScorePart(label=a.reason, points=a.points) for a in adjustments),
                ],
                available=entry.available,
                unavailable_reason=entry.unavailable_reason,
            )
        )

    recommended = max(candidates, key=lambda c: c.score)
    available = [c for c in candidates if c.available]
    default_selection = max(available, key=lambda c: c.score) if available else None

    return TechStackArtefact(
        facts=facts.as_counted(),
        candidates=candidates,
        recommended_id=recommended.id,
        selected_id=default_selection.id if default_selection else None,
        selected_by="system default" if default_selection else None,
    )
