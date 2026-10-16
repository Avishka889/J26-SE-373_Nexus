"""The api-contract as OpenAPI 3.1.

A pure translation, and it lives beside the contracts rather than in one
service because two of them need it: the orchestrator serves it on a route, and
C3 reads it to derive API test skeletons. A translation implemented twice is
the drift this package exists to prevent, and the same argument that put
`cvss_base_score` here puts this here.

Two things it deliberately does. The status codes describe what the generated
server actually answers, taken from the code generator rather than from
convention: 201 on a create, 204 on a delete, 404 wherever a path carries a
parameter that might not resolve. An OpenAPI that says 200 where the server
says 201 would produce API tests that fail against a correct implementation,
which is worse than no OpenAPI at all.

And traceability survives the translation. Every operation carries `x-traces`
with the screens, actions, stories and requirements the endpoint exists for, so
a test generated from this document can still say which acceptance criterion it
came from. Dropping them here would mean recovering them later by matching
paths, which is guesswork.
"""

from typing import Any

from .api_contract import ApiContract, ApiEndpoint, EndpointSchema, EntityModel, SchemaField

#: The contract's small type vocabulary, as JSON Schema. `id` is a string
#: rather than an integer because the generators emit string ids everywhere.
_PRIMITIVES: dict[str, dict[str, Any]] = {
    "string": {"type": "string"},
    "number": {"type": "number"},
    "boolean": {"type": "boolean"},
    "date": {"type": "string", "format": "date-time"},
    "id": {"type": "string"},
}


def _schema_name(entity: str) -> str:
    """A component name from an entity name: "Calculation State" -> "CalculationState"."""
    return "".join(part[:1].upper() + part[1:] for part in entity.replace("-", " ").split())


def _field_schema(field: SchemaField) -> dict[str, Any]:
    if field.type == "array":
        items = (
            {"$ref": f"#/components/schemas/{_schema_name(field.item_ref)}"}
            if field.item_ref
            else {}
        )
        return {"type": "array", "items": items}
    if field.type == "object":
        if field.item_ref:
            return {"$ref": f"#/components/schemas/{_schema_name(field.item_ref)}"}
        return {"type": "object", "additionalProperties": True}
    schema = dict(_PRIMITIVES[field.type])
    # The bounds as the standard keywords, so what reads the document sees them.
    for keyword, value in (
        ("minimum", field.minimum),
        ("maximum", field.maximum),
        ("minLength", field.min_length),
        ("maxLength", field.max_length),
    ):
        if value is not None:
            schema[keyword] = value
    if field.one_of:
        schema["enum"] = list(field.one_of)
    if field.rules:
        schema["description"] = "; ".join(field.rules)
    return schema


def _fields_schema(fields: list[SchemaField]) -> dict[str, Any]:
    properties = {field.name: _field_schema(field) for field in fields}
    required = [field.name for field in fields if field.required]
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _entity_schema(entity: EntityModel) -> dict[str, Any]:
    return _fields_schema(entity.fields)


def _body_schema(body: EndpointSchema) -> dict[str, Any]:
    """A request or response body.

    Explicit fields win over the entity reference: a request that omits the id
    is a different shape from the entity it derives from, and saying `$ref`
    there would describe the wrong thing.
    """
    if body.fields:
        return _fields_schema(body.fields)
    if body.entity:
        return {"$ref": f"#/components/schemas/{_schema_name(body.entity)}"}
    return {"type": "object", "additionalProperties": True}


def path_parameters(path: str) -> list[str]:
    """The `{name}` segments of a path, in order.

    Every one of them, not just the first. The single parameter assumption is
    what broke C2's generated contract tests when the LLM arm produced
    `/routes/{id}/stops/{stop_id}`.
    """
    found: list[str] = []
    for segment in path.split("/"):
        if segment.startswith("{") and segment.endswith("}") and len(segment) > 2:
            found.append(segment[1:-1])
    return found


def _is_collection(endpoint: ApiEndpoint) -> bool:
    return endpoint.method == "GET" and "{" not in endpoint.path


def _success_code(endpoint: ApiEndpoint) -> str:
    """What the generated server answers, not what a style guide prefers."""
    if endpoint.method == "POST":
        return "201"
    if endpoint.method == "DELETE":
        return "204"
    return "200"


def _responses(endpoint: ApiEndpoint) -> dict[str, Any]:
    code = _success_code(endpoint)
    responses: dict[str, Any] = {}

    if code == "204":
        responses[code] = {"description": "Deleted."}
    else:
        schema = _body_schema(endpoint.response) if endpoint.response else {"type": "object"}
        if _is_collection(endpoint) and endpoint.response and endpoint.response.entity:
            schema = {"type": "array", "items": schema}
        responses[code] = {
            "description": endpoint.summary or "The request succeeded.",
            "content": {"application/json": {"schema": schema}},
        }

    # A body or a declared rule means there is something to reject.
    if endpoint.request is not None or endpoint.validation:
        responses["400"] = {"description": "The request did not satisfy the declared rules."}
    if endpoint.auth_actors:
        responses["401"] = {
            "description": "The caller is not one of: " + ", ".join(endpoint.auth_actors)
        }
    if path_parameters(endpoint.path):
        responses["404"] = {"description": "No such resource."}
    return responses


def _operation(endpoint: ApiEndpoint) -> dict[str, Any]:
    operation: dict[str, Any] = {
        # The contract's own id, so a test, a finding and an operation all name
        # the endpoint the same way.
        "operationId": endpoint.id,
        "responses": _responses(endpoint),
    }
    if endpoint.summary:
        operation["summary"] = endpoint.summary

    parameters = [
        {
            "name": name,
            "in": "path",
            "required": True,
            "schema": {"type": "string"},
        }
        for name in path_parameters(endpoint.path)
    ]
    if parameters:
        operation["parameters"] = parameters

    if endpoint.request is not None:
        operation["requestBody"] = {
            "required": True,
            "content": {"application/json": {"schema": _body_schema(endpoint.request)}},
        }

    if endpoint.auth_actors:
        operation["security"] = [{"bearerAuth": []}]

    # Extensions, so the translation is lossless in the direction that matters.
    # A test generated from this document can still name the story and the
    # requirement it came from, rather than having them matched back by path.
    traces = endpoint.traces
    if not traces.is_empty:
        operation["x-traces"] = {
            "screenIds": traces.screen_ids,
            "actionIds": traces.action_ids,
            "storyIds": traces.story_ids,
            "requirementIds": traces.requirement_ids,
        }
    if endpoint.validation:
        # The declared invariants, kept as written. These are the third tier of
        # the oracle: status class, then schema conformance, then these.
        operation["x-validation"] = list(endpoint.validation)
    if endpoint.auth_actors:
        operation["x-auth-actors"] = list(endpoint.auth_actors)
    return operation


def to_openapi(contract: ApiContract, *, title: str, version: str | None = None) -> dict[str, Any]:
    """The contract as an OpenAPI 3.1 document.

    Deterministic: the same contract produces the same document, byte for byte,
    because the paths and the schemas are built in the contract's own order.
    That matters for a diff between two code versions, which is one of the
    inputs the self healing classifier reads.
    """
    paths: dict[str, dict[str, Any]] = {}
    for endpoint in contract.endpoints:
        paths.setdefault(endpoint.path, {})[endpoint.method.lower()] = _operation(endpoint)

    document: dict[str, Any] = {
        "openapi": "3.1.0",
        "info": {
            "title": title,
            "version": version or f"{contract.version}.0.0",
            "description": (
                "Generated from the platform's api-contract artefact. "
                "Every operation carries the screens, stories and requirements "
                "it was inferred from under x-traces."
            ),
        },
        "paths": paths,
    }

    components: dict[str, Any] = {}
    if contract.entities:
        components["schemas"] = {
            _schema_name(entity.name): _entity_schema(entity) for entity in contract.entities
        }
    if any(endpoint.auth_actors for endpoint in contract.endpoints):
        components["securitySchemes"] = {
            "bearerAuth": {"type": "http", "scheme": "bearer"},
        }
    if components:
        document["components"] = components
    return document
