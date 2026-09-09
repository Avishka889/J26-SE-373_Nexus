"""Story points, counted from the design rather than guessed by a model.

Story points are judgement, and that is exactly why a model must not produce
them. A model writing "5" gives a number that changes between two runs over
identical input and that nobody can argue with, sitting in a column next to other
numbers that look equally solid. The same argument that keeps `score` off the
architecture explanation type keeps `points` off the story type.

What can be counted is how much of the design a story touches: how many distinct
behaviours have to hold, how many things it stores, how many boundaries it
crosses, whether somebody else's system is involved, and whether it carries a
quality requirement or a rule the design has to obey. Those are all readable off
the graph and the requirements, and the deductions are kept so the evaluation can
say why a story landed where it did.

The result is snapped to the planning scale teams actually use. An unsnapped 7
looks like it was measured, and nothing here was measured.
"""

from dataclasses import dataclass, field

from sdlc_contracts import ArchitectureGraph, ParsedRequirement

from .schema import DraftStory

#: The cards on the table. Anything bigger than the last one is a story that
#: should be split rather than estimated, which is reported as a warning.
SCALE = (1, 2, 3, 5, 8, 13, 21)

_PRIORITY_RANK = {"must": 0, "should": 1, "could": 2}


@dataclass(frozen=True)
class Estimate:
    """A story's size, and everything that went into it."""

    points: int
    raw: int
    #: Reads "two entities: +2", one per signal that moved the number.
    because: tuple[str, ...] = field(default=())

    @property
    def too_big_to_plan(self) -> bool:
        """Bigger than the largest card, so it needs splitting rather than sizing."""
        return self.raw > SCALE[-1]


def _touching(graph: ArchitectureGraph, traces: set[str], kinds: set[str]) -> list[str]:
    """Nodes of these kinds that came from any requirement this story realises."""
    return [node.id for node in graph.nodes if node.kind in kinds and traces & set(node.traces)]


def estimate_story(
    story: DraftStory,
    *,
    graph: ArchitectureGraph,
    requirements: list[ParsedRequirement],
) -> Estimate:
    """How big this story is, and why."""
    traces = set(story.traces)
    mine = [r for r in requirements if r.id in traces]

    entities = _touching(graph, traces, {"entity"})
    services = _touching(graph, traces, {"service"})
    constraints = _touching(graph, traces, {"constraint"})
    externals = [
        node.id
        for node in graph.nodes
        if node.kind == "actor"
        and node.actor_kind == "external_system"
        and traces & set(node.traces)
    ]
    quality = [r.id for r in mine if r.type == "quality"]

    raw = 1
    because: list[str] = ["a story is at least one point"]

    extra_behaviours = max(0, len(story.acceptance) - 1)
    if extra_behaviours:
        raw += extra_behaviours
        because.append(f"{extra_behaviours} more behaviour(s) to satisfy: +{extra_behaviours}")
    if entities:
        raw += len(entities)
        because.append(f"{len(entities)} entity(s) to store: +{len(entities)}")
    if services:
        raw += len(services)
        because.append(f"{len(services)} service boundary(s): +{len(services)}")
    if externals:
        # The expensive part of most stories. Somebody else's system fails in
        # ways this design does not control, and every one of them needs
        # handling.
        raw += 2 * len(externals)
        because.append(f"{len(externals)} external system(s) to integrate: +{2 * len(externals)}")
    if quality:
        # Non-functional work is chronically underestimated, and the honest
        # response is to weight it rather than to hope.
        raw += 3
        because.append(f"a quality requirement ({', '.join(quality)}): +3")
    if constraints:
        raw += len(constraints)
        because.append(f"{len(constraints)} rule(s) to prove compliance with: +{len(constraints)}")

    return Estimate(points=snap(raw), raw=raw, because=tuple(because))


def snap(raw: int) -> int:
    """The nearest card, rounding up when it falls exactly between two.

    Rounding up on a tie rather than down, because a plan that is slightly too
    pessimistic disappoints nobody and one that is slightly too optimistic is how
    a sprint is missed.
    """
    if raw >= SCALE[-1]:
        return SCALE[-1]
    return min(SCALE, key=lambda card: (abs(card - raw), -card))


def priority_of(story: DraftStory, requirements: list[ParsedRequirement]) -> str:
    """The highest priority among the requirements this story realises.

    Inherited rather than asked for. A story that realises a must-have is a
    must-have, and a model given the chance to restate that will sometimes
    contradict the requirement the story came from.
    """
    traces = set(story.traces)
    priorities = [r.priority for r in requirements if r.id in traces]
    if not priorities:
        # No trace resolves, which is an error the rules already report. Ranking
        # it last keeps ordering total instead of raising here.
        return "could"
    return min(priorities, key=lambda p: _PRIORITY_RANK[p])
