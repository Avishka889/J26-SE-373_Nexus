"""The API contract: the C2 to C3 seam, and the research core's artefact.

The contract is inferred from the wireframe screens together with the
architecture graph, by two arms whose outputs share this exact shape: a
deterministic rule generator and an LLM generator. The stored artefact carries
both arms, the comparison between them, and the effective contract the human
chose, because comparing the arms is the point and a stored artefact that kept
only the winner would destroy the evidence.

Traceability is by construction: every endpoint carries the screens, actions,
stories and requirements it exists for. An endpoint tracing to nothing is a
finding, not a feature.
"""

from typing import Literal

from pydantic import Field, model_validator

from .ids import RequirementId, StoryId, Traces
from .wire import WireModel

Method = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]
Origin = Literal["rule", "llm", "merged"]

#: The primitive field types the generators emit. Deliberately small: a type
#: outside this set is a generator bug, and the code generators map each of
#: these onto the stack's own type system.
FieldType = Literal["string", "number", "boolean", "date", "id", "object", "array"]


class SchemaField(WireModel):
    name: str = Field(min_length=1)
    type: FieldType = "string"
    required: bool = True
    #: For arrays and objects: what the items or the value refer to, usually an
    #: entity name. Empty for primitives.
    item_ref: str = ""
    #: The bounds the design's constraints and the sprint's acceptance criteria
    #: state for this field, read by a rule (C2's `field_rules`), so a generated
    #: handler refuses a value outside them and the tests generated from the
    #: contract assert it. They were words in a comment, and the generated app
    #: took any value: the Movie Tracker took release years 1999 and 2027.
    minimum: int | float | None = None
    maximum: int | float | None = None
    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=0)
    one_of: list[str] = Field(default_factory=list)
    #: The words each bound was read from.
    rules: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def bounds_that_can_hold(self) -> "SchemaField":
        name = self.name
        if (self.minimum is not None or self.maximum is not None) and self.type != "number":
            raise ValueError(f"a numeric bound on {name}, but {name} is a {self.type}")
        lengths = self.min_length is not None or self.max_length is not None
        if (lengths or self.one_of) and self.type != "string":
            raise ValueError(f"a length or a choice on {name}, but {name} is a {self.type}")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError(
                f"{name}'s minimum {_number(self.minimum)} is above its maximum "
                f"{_number(self.maximum)}"
            )
        if (
            self.min_length is not None
            and self.max_length is not None
            and self.min_length > self.max_length
        ):
            raise ValueError(
                f"{name}'s minimum length {self.min_length} is above its maximum {self.max_length}"
            )
        return self


def _number(value: int | float) -> str:
    """A bound as a person writes it: 2000, not 2000.0."""
    return str(int(value)) if float(value).is_integer() else str(value)


class EntityModel(WireModel):
    """A data shape the schemas reference, derived from a graph entity."""

    name: str = Field(min_length=1)
    fields: list[SchemaField] = Field(default_factory=list)
    traces: Traces


class EndpointSchema(WireModel):
    """A request or response body, as fields plus the entity it derives from."""

    #: The graph entity this schema is a view of, or empty when it is composed.
    entity: str = ""
    fields: list[SchemaField] = Field(default_factory=list)


class EndpointTraces(WireModel):
    """Where an endpoint comes from. The unit of inference is the user action
    on a screen, so screens and actions lead; stories and requirements ground
    them in the plan and the brief."""

    screen_ids: list[str] = Field(default_factory=list)
    #: Link and actionable block ids on those screens.
    action_ids: list[str] = Field(default_factory=list)
    story_ids: list[StoryId] = Field(default_factory=list)
    requirement_ids: list[RequirementId] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.screen_ids or self.action_ids or self.story_ids or self.requirement_ids)


class ApiEndpoint(WireModel):
    #: Deterministic slug of method and path ("get-orders-id"), never a
    #: sequence number: a human decision recorded against an endpoint must
    #: still attach to it after a regeneration.
    id: str = Field(min_length=1)
    method: Method
    path: str = Field(min_length=1, pattern=r"^/")
    summary: str = ""
    #: Actor labels allowed to call this. Empty means unauthenticated.
    auth_actors: list[str] = Field(default_factory=list)
    request: EndpointSchema | None = None
    response: EndpointSchema | None = None
    #: Constraint derived validation rules, in words, for the handler.
    validation: list[str] = Field(default_factory=list)
    traces: EndpointTraces = Field(default_factory=EndpointTraces)
    origin: Origin = "rule"
    #: Computed from checkable properties, exactly as C1's requirement
    #: confidence is; the generating model has no field to invent one in.
    confidence: int = Field(default=0, ge=0, le=98)


class ApiContract(WireModel):
    """The effective contract one arm produced, or the human's merge."""

    version: int = Field(ge=1)
    entities: list[EntityModel] = Field(default_factory=list)
    endpoints: list[ApiEndpoint] = Field(default_factory=list)


class ArmCounts(WireModel):
    endpoints: int = Field(default=0, ge=0)
    errors: int = Field(default=0, ge=0)
    warnings: int = Field(default=0, ge=0)
    attempts: int = Field(default=0, ge=0)


class ContractConflict(WireModel):
    """The same endpoint, said differently by the two arms. Surfaced as a
    finding and decided item by item when the human picks merged."""

    endpoint_key: str = Field(min_length=1, description='Canonical "METHOD /path".')
    field: str = Field(min_length=1)
    rule_value: str = ""
    llm_value: str = ""


class ArmComparison(WireModel):
    """The ablation data, one run's worth."""

    rule: ArmCounts = Field(default_factory=ArmCounts)
    llm: ArmCounts = Field(default_factory=ArmCounts)
    agreed: list[str] = Field(
        default_factory=list, description="Canonical keys both arms produced."
    )
    rule_only: list[str] = Field(default_factory=list)
    llm_only: list[str] = Field(default_factory=list)
    conflicts: list[ContractConflict] = Field(default_factory=list)
    #: |agreed| / |union|, 1.0 when both arms say exactly the same endpoints.
    agreement_rate: float = Field(default=0.0, ge=0.0, le=1.0)


class ContractRuleFinding(WireModel):
    """One of the rule catalogue's findings about an arm's contract."""

    rule_id: str = Field(min_length=1)
    severity: Literal["error", "warning"]
    reason: str = Field(min_length=1)
    #: What it is about: an endpoint id, a screen id.
    subject: str = ""


class ApiContractArtefact(WireModel):
    """The stored artefact: both arms, the comparison, and the choice.

    `contract` is the effective one downstream stages generate from. It equals
    the chosen arm's output, or the recorded merge. The losing arm is kept
    whole, because the evaluation compares arms and an artefact that kept only
    the winner would have destroyed its own denominator.
    """

    version: int = Field(ge=1)
    rule_arm: ApiContract
    #: None when the LLM arm failed; the failure text is beside it.
    llm_arm: ApiContract | None = None
    llm_failure: str | None = None
    chosen: Origin = "rule"
    contract: ApiContract
    comparison: ArmComparison | None = None
    #: The rule arm's own findings, kept whatever the model arm did. They lived
    #: only in the comparison, which a failed model arm leaves out, so the rule
    #: arm read as having no violations (review item C2-3).
    rule_findings: list[ContractRuleFinding] = Field(default_factory=list)

    @model_validator(mode="after")
    def a_failed_arm_says_why(self) -> "ApiContractArtefact":
        if self.llm_arm is None and not self.llm_failure:
            raise ValueError("the llm arm is absent without a recorded failure")
        if self.chosen == "llm" and self.llm_arm is None:
            raise ValueError("the llm arm cannot be chosen when it failed")
        return self


class EndpointChange(WireModel):
    endpoint_id: str = Field(min_length=1)
    field: str = Field(min_length=1)
    before: str = ""
    after: str = ""


class ContractDiff(WireModel):
    """What moved between two contract versions: the agile mechanic's receipt."""

    from_version: int = Field(ge=1)
    to_version: int = Field(ge=1)
    added: list[str] = Field(default_factory=list, description="Endpoint ids new in `to`.")
    removed: list[str] = Field(default_factory=list)
    changed: list[EndpointChange] = Field(default_factory=list)


def _rendered(endpoint: ApiEndpoint) -> dict[str, str]:
    """The comparable fields of an endpoint, rendered stably."""
    return {
        "method": endpoint.method,
        "path": endpoint.path,
        "summary": endpoint.summary,
        "auth": ", ".join(sorted(endpoint.auth_actors)),
        "request": endpoint.request.model_dump_json() if endpoint.request else "",
        "response": endpoint.response.model_dump_json() if endpoint.response else "",
        "validation": "; ".join(endpoint.validation),
    }


def diff_contracts(previous: ApiContract, current: ApiContract) -> ContractDiff:
    """A pure function, in the contracts package on purpose: the orchestrator
    must not import the component in http mode, and comparing two shapes is
    bookkeeping, not intelligence."""
    before = {endpoint.id: endpoint for endpoint in previous.endpoints}
    after = {endpoint.id: endpoint for endpoint in current.endpoints}

    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed: list[EndpointChange] = []
    for endpoint_id in sorted(set(before) & set(after)):
        old_fields = _rendered(before[endpoint_id])
        new_fields = _rendered(after[endpoint_id])
        for field, old_value in old_fields.items():
            if new_fields[field] != old_value:
                changed.append(
                    EndpointChange(
                        endpoint_id=endpoint_id,
                        field=field,
                        before=old_value,
                        after=new_fields[field],
                    )
                )

    return ContractDiff(
        from_version=previous.version,
        to_version=current.version,
        added=added,
        removed=removed,
        changed=changed,
    )
