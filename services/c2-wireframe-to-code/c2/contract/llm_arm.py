"""The LLM contract generator: the same output shape, the same catalogue.

The draft the model may return is permissive in its fields and strict about
its lists, C1's hardest lesson: with everything defaulted, a forced tool call
is satisfied by an empty object and the stage stores nothing shaped like an
answer. `entities` and `endpoints` are required; everything inside them keeps
defaults so the repair loop can read a malformed answer instead of losing it.

The model has no field for confidence, origin or endpoint ids: all three are
computed after the fact, exactly as the rule arm computes its own.
"""

import logging
from dataclasses import dataclass

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models import Model
from sdlc_contracts import (
    ApiContract,
    ApiEndpoint,
    ArchitectureGraph,
    EndpointSchema,
    EndpointTraces,
    EntityModel,
    SchemaField,
    SprintScope,
    WireframesArtefact,
)

from ..agents import MALFORMED_OUTPUT_RETRIES, log_rejected, output_for, settings_for
from ..model_use import records_answers
from ..rules.scope import scoped_actions, scoped_screen_ids
from .rules import ContractContext, validate_contract
from .vocab import slug

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 2

_FIELD_TYPES = {"string", "number", "boolean", "date", "id", "object", "array"}
_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


class DraftField(BaseModel):
    name: str = ""
    type: str = "string"
    required: bool = True


class DraftSchema(BaseModel):
    entity: str = ""
    fields: list[DraftField] = Field(default_factory=list)


class DraftEntity(BaseModel):
    name: str = ""
    fields: list[DraftField] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)


class DraftEndpoint(BaseModel):
    method: str = "GET"
    path: str = ""
    summary: str = ""
    auth_actors: list[str] = Field(default_factory=list)
    request: DraftSchema | None = None
    response: DraftSchema | None = None
    validation: list[str] = Field(default_factory=list)
    screen_ids: list[str] = Field(default_factory=list)
    action_ids: list[str] = Field(default_factory=list)
    story_ids: list[str] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)


class DraftContract(BaseModel):
    entities: list[DraftEntity] = Field(
        description="Every entity the endpoints reference. Required: answer with the list."
    )
    endpoints: list[DraftEndpoint] = Field(
        description=(
            "Every endpoint the scoped screens need. Required: a contract with "
            "entities and no endpoints is not an answer."
        )
    )


INSTRUCTIONS = (
    "You infer a REST API contract from a designed UI: the wireframe screens "
    "are the specification, grounded in the architecture graph. Rules:\n"
    "1. Work only from the screens, actions, entities and stories you are "
    "given. Invent no resource the design does not contain.\n"
    "2. Every endpoint carries its traces: the screen ids (composite "
    "flowId/screenId), the link or block ids that are its UI, the story ids "
    "and the requirement ids it exists for. Use only ids that appear in the "
    "input.\n"
    "3. Paths are kebab case plural resources (/purchase-orders/{id}). PATCH "
    "and DELETE address one item. A domain action that is not CRUD is a POST "
    "subaction (/orders/{id}/dispatch).\n"
    "4. Request and response schemas name the entity they derive from and "
    "list their fields with types from: string, number, boolean, date, id, "
    "object, array.\n"
    "5. auth_actors are the design's actor labels allowed to call the "
    "endpoint.\n"
    "6. Every field you cannot ground, leave empty rather than invent."
)


def build_contract_agent(
    model: str | Model, *, retries: int = MALFORMED_OUTPUT_RETRIES, thinking: str = "off"
) -> Agent[None, DraftContract]:
    return Agent(
        model,
        output_type=output_for(DraftContract, model, thinking=thinking),
        instructions=INSTRUCTIONS,
        retries=retries,
        model_settings=settings_for(model, thinking=thinking),
        capabilities=[records_answers()],
    )


def _render_design(
    graph: ArchitectureGraph, wireframes: WireframesArtefact, scope: SprintScope
) -> str:
    lines: list[str] = []
    lines.append("Actors:")
    for node in graph.nodes:
        if node.kind == "actor":
            lines.append(f"- {node.label} ({node.actor_kind})")
    lines.append("Entities:")
    for node in graph.nodes:
        if node.kind == "entity":
            attributes = ", ".join(f"{a.name}: {a.type}" for a in node.attributes) or "none"
            lines.append(
                f"- {node.label} [traces {', '.join(node.traces)}] attributes: {attributes}"
            )
    lines.append("Constraints:")
    for node in graph.nodes:
        if node.kind == "constraint":
            lines.append(f"- {node.label} (applies to {', '.join(node.applies_to)})")
    lines.append("Actions (actor, verb, target entity):")
    entity_labels = {n.id: n.label for n in graph.nodes if n.kind == "entity"}
    actor_labels = {n.id: n.label for n in graph.nodes if n.kind == "actor"}
    for edge in scoped_actions(graph.edges, scope):
        if edge.source in actor_labels and edge.target in entity_labels:
            lines.append(
                f"- {actor_labels[edge.source]} {edge.verb} {entity_labels[edge.target]} "
                f"[traces {', '.join(edge.traces)}]"
            )
    in_scope = set(scoped_screen_ids(scope))
    lines.append("Scoped screens:")
    for flow in wireframes.flows:
        for screen in flow.screens:
            composite = f"{flow.id}/{screen.id}"
            if composite not in in_scope:
                continue
            lines.append(f"- screen {composite}: {screen.name}")
            for block in screen.blocks:
                lines.append(f"  - block {block.id} ({block.kind}): {block.label}")
            for link in screen.links:
                lines.append(f"  - action {link.id}: {link.label} -> {link.target_id}")
    lines.append("Stories in scope:")
    for story in scope.stories:
        if story.in_scope:
            lines.append(
                f"- {story.id}: {story.title} [requirements {', '.join(story.traces.requirement_ids)}]"
            )
    return "\n".join(lines)


def prompt_for(graph: ArchitectureGraph, wireframes: WireframesArtefact, scope: SprintScope) -> str:
    return (
        "Infer the API contract this design needs.\n\n"
        f"{_render_design(graph, wireframes, scope)}\n\n"
        "Answer with the full contract: entities and endpoints, every element "
        "traced to the ids above."
    )


def repair_prompt(base_prompt: str, hints: str) -> str:
    return (
        f"{base_prompt}\n\n"
        "Your previous contract broke these rules. Fix exactly these and keep "
        f"everything that was right:\n{hints}"
    )


def _normalise_type(value: str) -> str:
    value = value.strip().lower()
    return value if value in _FIELD_TYPES else "string"


def _schema(draft: DraftSchema | None) -> EndpointSchema | None:
    if draft is None:
        return None
    return EndpointSchema(
        entity=draft.entity.strip(),
        fields=[
            SchemaField(name=f.name.strip(), type=_normalise_type(f.type), required=f.required)
            for f in draft.fields
            if f.name.strip()
        ],
    )


def _confidence(endpoint: ApiEndpoint, context: ContractContext) -> int:
    """Computed from what resolves, never reported: an id that exists in the
    design is evidence, an id that does not is nothing."""
    known_screens = {
        f"{flow.id}/{screen.id}" for flow in context.wireframes.flows for screen in flow.screens
    }
    known_stories = {story.id for story in context.scope.stories}
    score = 50
    if set(endpoint.traces.screen_ids) & known_screens:
        score += 18
    if set(endpoint.traces.story_ids) & known_stories:
        score += 10
    if endpoint.request is not None or endpoint.response is not None:
        score += 8
    if endpoint.auth_actors:
        score += 4
    return min(score, 98)


def to_contract(draft: DraftContract, version: int, context: ContractContext) -> ApiContract:
    entities = [
        EntityModel(
            name=entity.name.strip(),
            fields=[
                SchemaField(name=f.name.strip(), type=_normalise_type(f.type), required=f.required)
                for f in entity.fields
                if f.name.strip()
            ],
            traces=[rid for rid in entity.requirement_ids if rid.strip()],
        )
        for entity in draft.entities
        if entity.name.strip()
    ]
    endpoints: list[ApiEndpoint] = []
    for item in draft.endpoints:
        method = item.method.strip().upper()
        path = item.path.strip()
        if method not in _METHODS or not path.startswith("/"):
            # Unreadable enough that no rule can name it usefully; skip it and
            # let the coverage rules report the hole it leaves.
            continue
        endpoint = ApiEndpoint(
            id=slug(method, path),
            method=method,  # type: ignore[arg-type]
            path=path,
            summary=item.summary.strip(),
            auth_actors=sorted({actor.strip() for actor in item.auth_actors if actor.strip()}),
            request=_schema(item.request),
            response=_schema(item.response),
            validation=[rule.strip() for rule in item.validation if rule.strip()],
            traces=EndpointTraces(
                screen_ids=sorted({s for s in item.screen_ids if s.strip()}),
                action_ids=sorted({a for a in item.action_ids if a.strip()}),
                story_ids=sorted({s for s in item.story_ids if s.strip()}),
                requirement_ids=sorted({r for r in item.requirement_ids if r.strip()}),
            ),
            origin="llm",
        )
        endpoints.append(endpoint.model_copy(update={"confidence": _confidence(endpoint, context)}))
    return ApiContract(version=version, entities=entities, endpoints=endpoints)


class CouldNotInferContract(RuntimeError):
    def __init__(self, reasons: list[str], attempts: int) -> None:
        super().__init__(
            f"the contract still broke {len(reasons)} rule(s) after {attempts} attempts: "
            + "; ".join(reasons[:3])
        )
        self.reasons = reasons
        self.attempts = attempts


@dataclass(frozen=True)
class LlmContractReport:
    attempts: int
    errors_per_attempt: tuple[tuple[str, ...], ...]

    @property
    def repaired(self) -> bool:
        return self.attempts > 1


async def infer_llm_contract(
    agent: Agent[None, DraftContract],
    *,
    version: int,
    context: ContractContext,
    max_attempts: int = MAX_ATTEMPTS,
) -> tuple[ApiContract, LlmContractReport]:
    """The repair loop, C1's shape: fresh prompt plus hints, bounded, logged."""
    base = prompt_for(context.graph, context.wireframes, context.scope)
    prompt = base
    errors_per_attempt: list[tuple[str, ...]] = []
    contract: ApiContract | None = None
    report = None

    for attempt in range(1, max_attempts + 1):
        result = await agent.run(prompt)
        contract = to_contract(result.output, version, context)
        report = validate_contract(contract, context)
        errors_per_attempt.append(report.rule_ids())
        if report.ok:
            return contract, LlmContractReport(
                attempts=attempt, errors_per_attempt=tuple(errors_per_attempt)
            )
        if attempt < max_attempts:
            prompt = repair_prompt(base, report.hints())

    assert contract is not None and report is not None
    log_rejected(
        "api-contract (llm arm)",
        contract,
        attempts=max_attempts,
        rules=report.rule_ids(),
    )
    raise CouldNotInferContract([finding.reason for finding in report.errors], max_attempts)
