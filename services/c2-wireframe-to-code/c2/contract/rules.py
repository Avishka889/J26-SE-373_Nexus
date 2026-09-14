"""The contract catalogue: nine named rules, validating either arm's output.

The same catalogue runs over the rule arm and the LLM arm, which is what makes
"findings per arm" a comparable number. Every error carries a hint written for
the repair loop, because "endpoint get-orders traces to nothing" retries far
better than "invalid".

Context matters for two of the rules: whether every scoped form and list
screen got its endpoint can only be judged against the screens, so the
validator takes the same design slice the generators read.
"""

from dataclasses import dataclass

from sdlc_contracts import ApiContract, ArchitectureGraph, SprintScope, WireframesArtefact

from ..rules.findings import Finding, Report, report
from ..rules.scope import scoped_screen_ids
from .vocab import canonical, resource_of, words_of


@dataclass(frozen=True)
class ContractContext:
    graph: ArchitectureGraph
    wireframes: WireframesArtefact
    scope: SprintScope


def _scoped_screens(context: ContractContext):
    wanted = set(scoped_screen_ids(context.scope))
    for flow in context.wireframes.flows:
        for screen in flow.screens:
            composite = f"{flow.id}/{screen.id}"
            if composite in wanted:
                yield composite, screen


def endpoint_traces(contract: ApiContract, context: ContractContext) -> list[Finding]:
    """An endpoint tracing to nothing is a finding, not a feature."""
    findings = []
    for endpoint in contract.endpoints:
        if endpoint.traces.is_empty:
            findings.append(
                Finding(
                    rule_id="endpoint-traces",
                    severity="error",
                    reason=f"{endpoint.method} {endpoint.path} traces to no screen, story or requirement",
                    hint=(
                        f"Give {endpoint.method} {endpoint.path} the screen, story or "
                        "requirement ids it exists for, or remove it."
                    ),
                    subject=endpoint.id,
                )
            )
    return findings


def traces_resolve(contract: ApiContract, context: ContractContext) -> list[Finding]:
    """Trace ids must exist in the design. Mostly the LLM arm's failure mode."""
    known_screens = {
        f"{flow.id}/{screen.id}" for flow in context.wireframes.flows for screen in flow.screens
    }
    known_stories = {story.id for story in context.scope.stories}
    findings = []
    for endpoint in contract.endpoints:
        unknown_screens = set(endpoint.traces.screen_ids) - known_screens
        unknown_stories = set(endpoint.traces.story_ids) - known_stories
        for unknown in sorted(unknown_screens):
            findings.append(
                Finding(
                    rule_id="traces-resolve",
                    severity="error",
                    reason=f"{endpoint.id} traces to screen {unknown}, which does not exist",
                    hint=(
                        f"Screen ids are composite flowId/screenId. Replace {unknown} on "
                        f"{endpoint.id} with one of the design's screens."
                    ),
                    subject=endpoint.id,
                )
            )
        for unknown in sorted(unknown_stories):
            findings.append(
                Finding(
                    rule_id="traces-resolve",
                    severity="error",
                    reason=f"{endpoint.id} traces to story {unknown}, which does not exist",
                    hint=f"Use only the sprint plan's story ids on {endpoint.id}.",
                    subject=endpoint.id,
                )
            )
    return findings


def schema_entities_known(contract: ApiContract, context: ContractContext) -> list[Finding]:
    known = {entity.name for entity in contract.entities} | {""}
    findings = []
    for endpoint in contract.endpoints:
        for side, schema in (("request", endpoint.request), ("response", endpoint.response)):
            if schema is not None and schema.entity not in known:
                findings.append(
                    Finding(
                        rule_id="schema-entity-known",
                        severity="error",
                        reason=(
                            f"{endpoint.id}'s {side} schema references entity "
                            f"'{schema.entity}', which the contract does not define"
                        ),
                        hint=(
                            f"Define entity '{schema.entity}' with its fields, or point "
                            f"{endpoint.id}'s {side} at one of: {', '.join(sorted(known - {''}))}."
                        ),
                        subject=endpoint.id,
                    )
                )
    return findings


def no_duplicate_paths(contract: ApiContract, context: ContractContext) -> list[Finding]:
    seen: dict[str, str] = {}
    findings = []
    for endpoint in contract.endpoints:
        key = canonical(endpoint.method, endpoint.path)
        if key in seen:
            findings.append(
                Finding(
                    rule_id="no-duplicate-paths",
                    severity="error",
                    reason=f"{key} is declared twice ({seen[key]} and {endpoint.id})",
                    hint=f"Merge {seen[key]} and {endpoint.id} into one endpoint.",
                    subject=endpoint.id,
                )
            )
        seen.setdefault(key, endpoint.id)
    return findings


def method_path_shape(contract: ApiContract, context: ContractContext) -> list[Finding]:
    """PATCH and DELETE address one thing; a bare POST addresses a collection."""
    findings = []
    for endpoint in contract.endpoints:
        has_id = "{id}" in canonical(endpoint.method, endpoint.path)
        if endpoint.method in ("PATCH", "PUT", "DELETE") and not has_id:
            findings.append(
                Finding(
                    rule_id="method-path-shape",
                    severity="error",
                    reason=f"{endpoint.method} {endpoint.path} does not address one item",
                    hint=(
                        f"{endpoint.method} needs an {{id}} in the path, or should be a "
                        "POST on the collection."
                    ),
                    subject=endpoint.id,
                )
            )
    return findings


def resource_from_an_entity(contract: ApiContract, context: ContractContext) -> list[Finding]:
    """An endpoint whose resource matches no entity is an orphan."""
    known_resources = {resource_of(entity.name) for entity in contract.entities}
    graph_resources = {
        resource_of(node.label) for node in context.graph.nodes if node.kind == "entity"
    }
    findings = []
    for endpoint in contract.endpoints:
        first_segment = endpoint.path.strip("/").split("/", 1)[0]
        if first_segment not in known_resources:
            nearest = (
                "define its entity in the contract"
                if first_segment in graph_resources
                else f"use a resource derived from an entity: {', '.join(sorted(known_resources))}"
            )
            findings.append(
                Finding(
                    rule_id="resource-from-an-entity",
                    severity="error",
                    reason=(
                        f"{endpoint.method} {endpoint.path} serves resource "
                        f"'{first_segment}', which no contract entity produces"
                    ),
                    hint=f"For {endpoint.id}: {nearest}.",
                    subject=endpoint.id,
                )
            )
    return findings


def form_screens_have_a_write(contract: ApiContract, context: ContractContext) -> list[Finding]:
    """Every scoped form must submit somewhere: the inference's whole point."""
    write_screens: set[str] = set()
    for endpoint in contract.endpoints:
        if endpoint.method in ("POST", "PATCH", "PUT", "DELETE"):
            write_screens.update(endpoint.traces.screen_ids)
    findings = []
    for composite, screen in _scoped_screens(context):
        fields = [block for block in screen.blocks if block.kind == "field"]
        if len(fields) >= 2 and composite not in write_screens:
            findings.append(
                Finding(
                    rule_id="screen-action-has-an-endpoint",
                    severity="error",
                    reason=(
                        f"screen {composite} ('{screen.name}') is a form with "
                        f"{len(fields)} fields and no write endpoint traces to it"
                    ),
                    hint=(
                        f"Add the POST or PATCH endpoint that screen {composite}'s form "
                        "submits to, tracing back to it."
                    ),
                    subject=composite,
                )
            )
    return findings


def list_screens_have_a_read(contract: ApiContract, context: ContractContext) -> list[Finding]:
    read_screens: set[str] = set()
    for endpoint in contract.endpoints:
        if endpoint.method == "GET":
            read_screens.update(endpoint.traces.screen_ids)
    findings = []
    for composite, screen in _scoped_screens(context):
        lists = [block for block in screen.blocks if block.kind == "list"]
        if lists and composite not in read_screens:
            findings.append(
                Finding(
                    rule_id="list-screen-has-a-read",
                    severity="error",
                    reason=(
                        f"screen {composite} ('{screen.name}') renders a list and no "
                        "GET endpoint traces to it"
                    ),
                    hint=(
                        f"Add the GET endpoint that fills screen {composite}'s list, "
                        "tracing back to it."
                    ),
                    subject=composite,
                )
            )
    return findings


def auth_actors_known(contract: ApiContract, context: ContractContext) -> list[Finding]:
    known = {node.label for node in context.graph.nodes if node.kind == "actor"}
    known_words = {word for label in known for word in words_of(label)}
    findings = []
    for endpoint in contract.endpoints:
        for actor in endpoint.auth_actors:
            if actor not in known and not (words_of(actor) & known_words):
                findings.append(
                    Finding(
                        rule_id="auth-actor-known",
                        severity="warning",
                        reason=f"{endpoint.id} requires '{actor}', who is not an actor in the design",
                        hint=f"Use one of the design's actors on {endpoint.id}: {', '.join(sorted(known))}.",
                        subject=endpoint.id,
                    )
                )
    return findings


ALL_RULES = (
    endpoint_traces,
    traces_resolve,
    schema_entities_known,
    no_duplicate_paths,
    method_path_shape,
    resource_from_an_entity,
    form_screens_have_a_write,
    list_screens_have_a_read,
    auth_actors_known,
)

#: Pinned, because a consistency rate is only reproducible if the denominator is.
RULE_IDS = (
    "endpoint-traces",
    "traces-resolve",
    "schema-entity-known",
    "no-duplicate-paths",
    "method-path-shape",
    "resource-from-an-entity",
    "screen-action-has-an-endpoint",
    "list-screen-has-a-read",
    "auth-actor-known",
)


def validate_contract(contract: ApiContract, context: ContractContext) -> Report:
    findings: list[Finding] = []
    for rule in ALL_RULES:
        findings.extend(rule(contract, context))
    return report(findings)
