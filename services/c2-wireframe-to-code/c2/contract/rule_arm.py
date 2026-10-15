"""The deterministic contract generator: the baseline arm, and the novelty.

The contract is inferred FROM the designed UI, grounded in the architecture
graph, for the scoped slice only:

- graph entities become resources and entity models;
- SAG action edges (actor performs verb on entity) become endpoints, method
  and path by the verb convention, the acting actor becoming the auth
  requirement;
- scoped screens' list and form blocks become the read endpoints and the
  request schemas, and their ids become the endpoint's screen and action
  traces;
- constraint nodes that apply to an entity become validation rules on its
  write endpoints.

No model is involved anywhere in this file, and it must stay that way: this
arm is the baseline the LLM arm is measured against, and a baseline that
quietly consulted a model would be measuring itself.

Confidence is computed from checkable properties, the same policy as C1:
grounding in a screen action, in a story, in real entity attributes. There is
no field for a generator to invent one in.
"""

from dataclasses import dataclass, field

from sdlc_contracts import (
    ApiContract,
    ApiEndpoint,
    ArchitectureGraph,
    EndpointSchema,
    EndpointTraces,
    EntityModel,
    GraphNode,
    SchemaField,
    SprintScope,
    WireframesArtefact,
)

from ..rules.scope import scoped_actions, scoped_screen_ids
from .vocab import canonical, classify_verb, head_noun, mentions, resource_of, slug, verb_slug

#: Attribute type words onto the contract's small field type set.
_TYPE_MAP = {
    "string": "string",
    "text": "string",
    "str": "string",
    "name": "string",
    "email": "string",
    "enum": "string",
    "status": "string",
    "int": "number",
    "integer": "number",
    "number": "number",
    "float": "number",
    "decimal": "number",
    "money": "number",
    "count": "number",
    "quantity": "number",
    "bool": "boolean",
    "boolean": "boolean",
    "flag": "boolean",
    "date": "date",
    "datetime": "date",
    "time": "date",
    "timestamp": "date",
    "id": "id",
    "uuid": "id",
    "reference": "id",
    "ref": "id",
}


def _field_type(attribute_type: str) -> str:
    return _TYPE_MAP.get(attribute_type.strip().lower(), "string")


def _entity_model(node: GraphNode) -> EntityModel:
    fields = [SchemaField(name="id", type="id")]
    for attribute in node.attributes:
        if attribute.name.lower() == "id":
            continue
        fields.append(SchemaField(name=attribute.name, type=_field_type(attribute.type)))
    return EntityModel(name=node.label, fields=fields, traces=list(node.traces))


@dataclass
class _Draft:
    """One endpoint being assembled, before dedup and confidence."""

    method: str
    path: str
    summary: str
    entity: GraphNode | None
    auth_actors: set[str] = field(default_factory=set)
    screen_ids: set[str] = field(default_factory=set)
    action_ids: set[str] = field(default_factory=set)
    requirement_ids: set[str] = field(default_factory=set)
    validation: list[str] = field(default_factory=list)
    request: EndpointSchema | None = None
    response: EndpointSchema | None = None
    verb_classified: bool = True


def _confidence(draft: _Draft, story_ids: list[str]) -> int:
    score = 55
    if draft.screen_ids or draft.action_ids:
        score += 15
    if story_ids:
        score += 10
    if draft.entity is not None and draft.entity.attributes:
        score += 10
    if draft.verb_classified:
        score += 8
    return min(score, 98)


def generate_rule_contract(
    version: int,
    graph: ArchitectureGraph,
    wireframes: WireframesArtefact,
    scope: SprintScope,
) -> ApiContract:
    entities = [node for node in graph.nodes if node.kind == "entity"]
    actors = {node.id: node for node in graph.nodes if node.kind == "actor"}
    constraints = [node for node in graph.nodes if node.kind == "constraint"]

    in_scope_screens = set(scoped_screen_ids(scope))
    scoped_requirements = {
        rid for story in scope.stories if story.in_scope for rid in story.traces.requirement_ids
    }
    actions = [edge for edge in scoped_actions(graph.edges, scope) if edge.source in actors]

    # Screens in scope, keyed by their composite id, with their flow kept.
    screens: dict[str, tuple[str, object]] = {}
    for flow in wireframes.flows:
        for screen in flow.screens:
            composite = f"{flow.id}/{screen.id}"
            if composite in in_scope_screens:
                screens[composite] = (flow.id, screen)

    def entity_in_scope(entity: GraphNode) -> bool:
        if any(mentions(screen.name, entity.label) for _, screen in screens.values()):
            return True
        if any(
            mentions(block.label, entity.label)
            for _, screen in screens.values()
            for block in screen.blocks
        ):
            return True
        # An action this sprint's stories trace brings its entity, even when
        # no screen names it; an action no story traces does not.
        if any(
            edge.target == entity.id and set(edge.traces) & scoped_requirements for edge in actions
        ):
            return True
        return bool(set(entity.traces) & scoped_requirements)

    scoped_entities = [entity for entity in entities if entity_in_scope(entity)]

    def screens_about(entity: GraphNode) -> list[tuple[str, object]]:
        """Screens that talk about the entity: by name, by a block, or by a
        link ("Record calculation" makes the keypad a Calculation screen even
        though its only block is an expression field)."""
        return [
            (composite, screen)
            for composite, (_, screen) in screens.items()
            if mentions(screen.name, entity.label)
            or any(mentions(block.label, entity.label) for block in screen.blocks)
            or any(mentions(link.label, entity.label) for link in screen.links)
        ]

    def validation_for(entity: GraphNode) -> list[str]:
        rules: list[str] = []
        for constraint in constraints:
            if entity.id in constraint.applies_to:
                rules.append(constraint.label)
        return rules

    drafts: dict[str, _Draft] = {}

    def add(draft: _Draft) -> _Draft:
        key = canonical(draft.method, draft.path)
        existing = drafts.get(key)
        if existing is None:
            drafts[key] = draft
            return draft
        existing.auth_actors |= draft.auth_actors
        existing.screen_ids |= draft.screen_ids
        existing.action_ids |= draft.action_ids
        existing.requirement_ids |= draft.requirement_ids
        for rule in draft.validation:
            if rule not in existing.validation:
                existing.validation.append(rule)
        return existing

    # Read endpoints, from the screens themselves: a list block about an
    # entity is a collection read; a screen named after the entity carrying
    # summary or field blocks is a detail read.
    for entity in scoped_entities:
        resource = resource_of(entity.label)
        response = EndpointSchema(entity=entity.label)
        for composite, screen in screens_about(entity):
            list_blocks = [
                block
                for block in screen.blocks
                if block.kind == "list" and mentions(block.label, entity.label)
            ] + [
                block
                for block in screen.blocks
                if block.kind == "row" and mentions(block.label, entity.label)
            ]
            if list_blocks:
                draft = add(
                    _Draft(
                        method="GET",
                        path=f"/{resource}",
                        summary=f"List {resource_of(entity.label).replace('-', ' ')}",
                        entity=entity,
                        response=response,
                    )
                )
                draft.screen_ids.add(composite)
                draft.action_ids.update(block.id for block in list_blocks)
                draft.requirement_ids.update(entity.traces)
            summary_blocks = [block for block in screen.blocks if block.kind in ("summary", "text")]
            if summary_blocks and mentions(screen.name, entity.label):
                draft = add(
                    _Draft(
                        method="GET",
                        path=f"/{resource}/{{id}}",
                        summary=f"Read one {head_noun(entity.label)}",
                        entity=entity,
                        response=response,
                    )
                )
                draft.screen_ids.add(composite)
                draft.requirement_ids.update(entity.traces)

    # Write endpoints, from the action edges this build may take: actor performs
    # verb on entity.
    entity_by_id = {entity.id: entity for entity in entities}
    for edge in actions:
        actor = actors[edge.source]
        entity = entity_by_id.get(edge.target)
        if entity is None or entity not in scoped_entities:
            continue

        resource = resource_of(entity.label)
        verb_kind = classify_verb(edge.verb)
        request = EndpointSchema(
            entity=entity.label,
            fields=[f for f in _entity_model(entity).fields if f.name != "id"],
        )
        response = EndpointSchema(entity=entity.label)

        if verb_kind == "create":
            draft = _Draft(
                method="POST",
                path=f"/{resource}",
                summary=f"{edge.verb.capitalize()} a {head_noun(entity.label)}",
                entity=entity,
                request=request,
                response=response,
            )
        elif verb_kind == "update":
            draft = _Draft(
                method="PATCH",
                path=f"/{resource}/{{id}}",
                summary=f"{edge.verb.capitalize()} a {head_noun(entity.label)}",
                entity=entity,
                request=request,
                response=response,
            )
        elif verb_kind == "delete":
            draft = _Draft(
                method="DELETE",
                path=f"/{resource}/{{id}}",
                summary=f"{edge.verb.capitalize()} a {head_noun(entity.label)}",
                entity=entity,
            )
        elif verb_kind == "read":
            draft = _Draft(
                method="GET",
                path=f"/{resource}",
                summary=f"List {resource.replace('-', ' ')}",
                entity=entity,
                response=response,
            )
        else:
            # A domain verb: the REST convention for an action that is not
            # CRUD is a POST subaction, which keeps the verb visible instead
            # of mislabelling it an update.
            draft = _Draft(
                method="POST",
                path=f"/{resource}/{{id}}/{verb_slug(edge.verb)}",
                summary=f"{edge.verb.capitalize()} a {head_noun(entity.label)}",
                entity=entity,
                request=None,
                response=response,
                verb_classified=False,
            )

        draft.auth_actors.add(actor.label)
        # The action's own requirements, not the entity's: those include the
        # backlog's, which this endpoint does not serve.
        draft.requirement_ids.update(edge.traces)
        if verb_kind in ("create", "update", "delete"):
            draft.validation.extend(
                rule for rule in validation_for(entity) if rule not in draft.validation
            )
        merged = add(draft)

        # Ground the action in the screens: a link whose label carries the
        # verb or the entity's noun, on a scoped screen, is this action's UI.
        for composite, screen in screens_about(entity):
            for link in screen.links:
                if mentions(link.label, edge.verb) or mentions(link.label, entity.label):
                    merged.screen_ids.add(composite)
                    merged.action_ids.add(link.id)

    # Stories attach by shared requirements or shared screens.
    endpoints: list[ApiEndpoint] = []
    for key in sorted(drafts):
        draft = drafts[key]
        story_ids = [
            story.id
            for story in scope.stories
            if story.in_scope
            and (
                set(story.traces.requirement_ids) & draft.requirement_ids
                or set(story.traces.screen_ids) & draft.screen_ids
            )
        ]
        endpoints.append(
            ApiEndpoint(
                id=slug(draft.method, draft.path),
                method=draft.method,  # type: ignore[arg-type]
                path=draft.path,
                summary=draft.summary,
                auth_actors=sorted(draft.auth_actors),
                request=draft.request,
                response=draft.response,
                validation=list(draft.validation),
                traces=EndpointTraces(
                    screen_ids=sorted(draft.screen_ids),
                    action_ids=sorted(draft.action_ids),
                    story_ids=sorted(story_ids),
                    requirement_ids=sorted(draft.requirement_ids),
                ),
                origin="rule",
                confidence=_confidence(draft, story_ids),
            )
        )

    return ApiContract(
        version=version,
        entities=[_entity_model(entity) for entity in scoped_entities],
        endpoints=endpoints,
    )
