"""Component 1 as something the orchestrator can call, one stage at a time.

Per stage rather than one `generate_design(text)`, and the reason is what a
reader sees. Six artefact families through a model is a minute or three, and a
single call means all eight stages sit at pending and then flip to complete at
once. Per stage, each one goes generating then complete on its own, the snapshot
says so the moment it happens, and a crash costs the stage that was running
rather than the whole run.

It also puts the pipeline shape where it belongs. The orchestrator owns the
process: which stages exist, what order they run in, what happens at the gate.
This component owns the intelligence. That split is why the cross artefact checks
are not here, and why nothing in this file knows what a run is.

Agents are built once and kept, because each owns a connection to the provider.
Building one per call leaks a socket per call.

Every method returns the artefact, the sentence the thread shows, and the notes
the evaluation reads. The notes go to the audit log rather than into the
artefact: how many attempts a stage took is a fact about the run, not about the
design, and putting it in the artefact would make two runs that produced the same
design compare as different.
"""

from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Self

from pydantic_ai.models import Model
from sdlc_contracts import (
    ArchitectureGraph,
    ArchitectureRecommendation,
    ParsedRequirement,
    RequirementsArtefact,
    SprintPlan,
    UmlArtefact,
    UmlDiagram,
    UseCase,
    WireframeFlow,
    WireframesArtefact,
)

from .architecture.explain import build_explainer, explain_all
from .architecture.scoring import gather_facts, score_topologies
from .architecture.style import choose_style
from .llm.extractor import build_agent, extract_with_model
from .model_use import reports_model_use
from .naming import build_naming_agent
from .naming import name_project as run_naming
from .sag.extractor import build_graph_agent, extract_graph
from .sprint.extractor import build_sprint_agent
from .sprint.extractor import plan_sprint as plan_sprint_with
from .uml.projections import projected_diagrams, sequence_diagram
from .uml.sequence import build_sequence_agent, write_interaction
from .wireframes.extractor import build_wireframe_agent, draw_flow
from .wireframes.plan import plan_flows

#: Interactions written per run. One per journey would be a diagram nobody reads
#: and four model calls to produce it; the busiest journey is the one worth
#: drawing in full.
MAX_INTERACTIONS = 1


@dataclass(frozen=True)
class StageResult[T]:
    """What one stage produced, and what it cost."""

    artefact: T
    #: The one line posted into the thread when the stage finishes.
    summary: str
    #: Honesty metrics for the evaluation: attempts, repairs, what was refused.
    #: Recorded in the audit log, never in the artefact.
    notes: dict[str, Any] = field(default_factory=dict)


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


class C1:
    """Component 1, in process.

    One instance per orchestrator process, built at startup. The HTTP client on
    the other side of the boundary calls the same methods over the wire.
    """

    def __init__(self, model: str | Model, *, thinking: str = "off") -> None:
        # A model object as well as a name, because the golden corpus case
        # drives this exact construction path with a scripted model. Taking
        # only a string would have forced the test to reach in and replace
        # the agents, which is the one part of the wiring worth exercising.
        self.model = model
        #: How hard the stages ask the model to think (`agents.THINKING_LEVELS`).
        self.thinking = thinking
        self._requirements = build_agent(model, thinking=thinking)
        self._graph = build_graph_agent(model, thinking=thinking)
        self._explainer = build_explainer(model, thinking=thinking)
        self._sequence = build_sequence_agent(model, thinking=thinking)
        self._wireframes = build_wireframe_agent(model, thinking=thinking)
        self._sprint = build_sprint_agent(model, thinking=thinking)
        # Never thinks: a title is worth a second or two, and the run waits on
        # it under a 20 second bound that thinking would spend.
        self._naming = build_naming_agent(model)

    def _agents(self) -> tuple[Any, ...]:
        return (
            self._requirements,
            self._graph,
            self._explainer,
            self._sequence,
            self._wireframes,
            self._sprint,
            self._naming,
        )

    async def __aenter__(self) -> Self:
        """Open every agent, so something closes them again.

        Each holds an HTTP client to the provider and owns it. Nothing closed
        them: the process leaked one socket per agent, as many as `_agents()`
        returns, until the interpreter exited, and in a test that surfaces as
        a ResourceWarning pytest turns into a failure after the results are
        printed. Entering the agent is how pydantic-ai exposes that lifecycle.
        """
        self._stack = AsyncExitStack()
        await self._stack.__aenter__()
        for agent in self._agents():
            await self._stack.enter_async_context(agent)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        stack = getattr(self, "_stack", None)
        if stack is not None:
            await stack.__aexit__(exc_type, exc, tb)
            self._stack = None

    @reports_model_use
    async def parse_requirements(self, text: str) -> StageResult[RequirementsArtefact]:
        """Read the input into requirements, assumptions and questions."""
        extraction, report = await extract_with_model(text, agent=self._requirements)
        artefact = extraction.to_artefact()

        parts = [
            _plural(len(artefact.requirements), "requirement"),
            _plural(len(artefact.assumptions), "assumption"),
        ]
        if artefact.questions:
            parts.append(_plural(len(artefact.questions), "open question"))

        return StageResult(
            artefact=artefact,
            summary=f"Requirements analysed: {', '.join(parts)}",
            notes={
                "returned": report.returned,
                "over_budget": report.over_budget,
                "spans_refused": report.spans_refused,
                "self_declared_inferred": report.self_declared_inferred,
                # How many of the model's own questions survived, so a live run
                # says whether the questions it asked were about this brief.
                "gaps_returned": report.gaps_returned,
                "gaps_recovered": report.gaps_recovered,
                "gaps_refused": report.gaps_refused,
            },
        )

    @reports_model_use
    async def build_graph(
        self, requirements: list[ParsedRequirement], *, text: str
    ) -> StageResult[ArchitectureGraph]:
        """Turn the requirements into the one graph everything else reads."""
        graph, report = await extract_graph(requirements, agent=self._graph, requirements_text=text)
        unconfirmed = sum(1 for node in graph.nodes if node.unconfirmed)
        summary = (
            f"Architecture graph ready: {_plural(len(graph.nodes), 'node')}, "
            f"{_plural(len(graph.edges), 'edge')}"
        )
        if unconfirmed:
            summary += f", {unconfirmed} needing a closer look"

        return StageResult(
            artefact=graph,
            summary=summary,
            notes={
                "attempts": report.attempts,
                "repaired": report.repaired,
                "rules_fired": [r for attempt in report.errors_per_attempt for r in attempt],
                "warnings": [f.rule_id for f in report.warnings],
            },
        )

    @reports_model_use
    async def recommend(
        self, requirements: list[ParsedRequirement], graph: ArchitectureGraph
    ) -> StageResult[ArchitectureRecommendation]:
        """Score the deployment shapes, and choose the code organisation style.

        The scores are arithmetic over the design and the model only writes the
        prose. Nothing here can change a number.
        """
        facts = gather_facts(requirements, graph)
        scored = score_topologies(facts)
        recommendation, _ = await explain_all(
            scored, facts, agent=self._explainer, style=choose_style(facts)
        )
        winner = next(c for c in recommendation.candidates if c.id == scored[0].id)

        return StageResult(
            artefact=recommendation,
            summary=(
                f"{_plural(len(scored), 'deployment shape')} scored, "
                f"{winner.name} recommended at {winner.score}"
            ),
            notes={
                "scores": {c.id: c.score for c in recommendation.candidates},
                "margin": scored[0].score - scored[1].score,
                "style": recommendation.style.id,
                "facts": facts.as_dict(),
            },
        )

    @reports_model_use
    async def write_uml(self, graph: ArchitectureGraph) -> StageResult[UmlArtefact]:
        """Project the class and entity diagrams, and write one interaction.

        Class and entity relationship diagrams need no model: the entities and
        the services that own them are already in the graph. The interaction does,
        because a request, a check, a persist and a response cannot be read off
        an actor-verb-entity triple.
        """
        diagrams: list[UmlDiagram] = list(projected_diagrams(graph))
        use_cases: list[UseCase] = []
        tokenised: list[str] = []

        briefs = plan_flows(graph)[:MAX_INTERACTIONS]
        for index, brief in enumerate(briefs, start=1):
            story = brief.actions[0] if brief.actions else f"what {brief.actor_label} does"
            use_case, report = await write_interaction(
                graph,
                story,
                agent=self._sequence,
                use_case_id=f"uc{index}",
                traces=list(brief.traces),
            )
            use_cases.append(use_case)
            diagrams.append(sequence_diagram(graph, use_case.id, list(brief.traces)))
            tokenised.extend(report.names_tokenised)

        return StageResult(
            artefact=UmlArtefact(useCases=use_cases, diagrams=diagrams),
            summary=(
                f"{_plural(len(diagrams), 'diagram')} generated, "
                f"{_plural(len(use_cases), 'interaction')} written"
            ),
            notes={"names_tokenised": sorted(set(tokenised))},
        )

    @reports_model_use
    async def draw_wireframes(
        self,
        graph: ArchitectureGraph,
        *,
        requirement_ids: list[str],
        version: str,
        requirements: list[ParsedRequirement] | None = None,
    ) -> StageResult[WireframesArtefact]:
        """One journey per primary actor that does something, drawn from what the
        requirements say as well as from the graph."""
        flows: list[WireframeFlow] = []
        attempts = 0
        warnings: list[str] = []

        for brief in plan_flows(graph):
            flow, report = await draw_flow(
                brief,
                graph,
                agent=self._wireframes,
                requirement_ids=requirement_ids,
                version=version,
                requirements=[(one.id, one.text) for one in requirements or []],
            )
            flows.append(flow)
            attempts += report.attempts
            warnings.extend(f.rule_id for f in report.warnings)

        screens = sum(len(flow.screens) for flow in flows)
        return StageResult(
            # Coverage is left empty on purpose: it is derived by the read model
            # against the sprint plan, which does not exist yet at this point.
            artefact=WireframesArtefact(flows=flows, coverage=[]),
            summary=f"{_plural(len(flows), 'flow')} generated, {_plural(screens, 'screen')}",
            notes={"attempts": attempts, "warnings": warnings},
        )

    @reports_model_use
    async def plan_sprint(
        self, requirements: list[ParsedRequirement], graph: ArchitectureGraph
    ) -> StageResult[SprintPlan]:
        """Stories from the model, every number from arithmetic."""
        plan, report = await plan_sprint_with(requirements, graph, agent=self._sprint)
        return StageResult(
            artefact=plan,
            summary=(
                f"{plan.sprint_name} proposed: "
                f"{_plural(len(plan.proposed), 'story', 'stories')}, "
                f"{plan.estimated_points} points estimated"
            ),
            notes={
                "attempts": report.attempts,
                "warnings": [f.rule_id for f in report.warnings],
                "backlog": len(plan.backlog),
            },
        )

    async def name_project(self, text: str) -> str:
        """A short title for this brief. Not a stage: nothing is stored."""
        return await run_naming(text, agent=self._naming)
