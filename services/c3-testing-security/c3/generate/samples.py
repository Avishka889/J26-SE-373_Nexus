"""A request body the contract would accept, built from the contract.

Every value here is derived from a declared field type, so the sample changes
when the contract changes and cannot drift into being a fixture somebody has to
maintain. Deterministic on purpose: two runs over one contract produce the same
body, because a test that sends a different payload each time cannot be
compared with the one before it.

C2 builds samples too, for the per endpoint tests it ships with the generated
repository. These are not shared code and should not be: they are on opposite
sides of the component seam, and this one has to work against a target C2 never
wrote. Both derive from the same contract, which is the thing that keeps them
agreeing.
"""

import json
from typing import Any

from sdlc_contracts import EndpointSchema, EntityModel, SchemaField

#: One value per declared type. Recognisable in a failure message, which is why
#: they are words rather than "x": a test that fails saying `expected "sample
#: name"` tells a reader where the value came from.
_BY_TYPE: dict[str, Any] = {
    "string": "a sample value",
    "number": 42,
    "boolean": True,
    "date": "2026-01-31",
    "id": "sample-id",
    "object": {},
    "array": [],
}


def sample_value(field: SchemaField, entities: dict[str, EntityModel], *, depth: int = 0) -> Any:
    """What to send for one field.

    An object or an array of a known entity is filled from that entity, once.
    The recursion stops at one level: an entity that refers to itself would
    otherwise build a sample of infinite depth, and a second level buys nothing
    a test asserts on.
    """
    if field.type in ("object", "array") and field.item_ref and depth == 0:
        entity = entities.get(field.item_ref)
        if entity is not None:
            nested = sample_body_from_fields(entity.fields, entities, depth=depth + 1)
            return [nested] if field.type == "array" else nested
    return _inside_bounds(field, _BY_TYPE.get(field.type, "a sample value"))


def _inside_bounds(field: SchemaField, value: Any) -> Any:
    """The type's sample, moved inside the bounds the contract states.

    The type's own value when it is inside them, so an unbounded contract's
    samples stay what they were: a create that sent 42 for a total bounded to
    100 would be refused for a reason the test is not about.
    """
    if field.one_of:
        return field.one_of[0]
    if field.type == "number":
        if field.minimum is not None and value < field.minimum:
            value = field.minimum
        if field.maximum is not None and value > field.maximum:
            value = field.maximum
    if field.type == "string":
        if field.max_length is not None and len(value) > field.max_length:
            value = value[: field.max_length]
        if field.min_length is not None and len(value) < field.min_length:
            value = value + "s" * (field.min_length - len(value))
    return value


def out_of_bounds(field: SchemaField) -> list[tuple[Any, str]]:
    """Values a bounded field must be refused, each with the words that say why.

    Just past each bound: the bounds are inclusive, so one past is the nearest
    value outside, and a refusal of it says the bound is where the contract
    puts it.
    """
    found: list[tuple[Any, str]] = []
    if field.minimum is not None:
        found.append((field.minimum - 1, f"below its minimum {_number(field.minimum)}"))
    if field.maximum is not None:
        found.append((field.maximum + 1, f"above its maximum {_number(field.maximum)}"))
    if field.min_length:
        found.append(("s" * (field.min_length - 1), f"shorter than {field.min_length} characters"))
    if field.max_length is not None:
        found.append(("s" * (field.max_length + 1), f"longer than {field.max_length} characters"))
    if field.one_of:
        outside = next(
            value
            for value in ("not one of them", "none of these", "another value")
            if value not in field.one_of
        )
        found.append((outside, f"not one of {', '.join(field.one_of)}"))
    return found


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


def sample_body_from_fields(
    fields: list[SchemaField], entities: dict[str, EntityModel], *, depth: int = 0
) -> dict[str, Any]:
    """Every required field, and nothing else.

    Optional fields are left out on purpose: the happy path should send the
    smallest body the contract accepts, so a handler that quietly depends on an
    optional field is caught rather than accommodated.
    """
    return {
        field.name: sample_value(field, entities, depth=depth) for field in fields if field.required
    }


def sample_body(schema: EndpointSchema | None, entities: dict[str, EntityModel]) -> dict[str, Any]:
    return sample_body_from_fields(schema.fields, entities) if schema else {}


def incomplete_body(
    schema: EndpointSchema | None, entities: dict[str, EntityModel]
) -> tuple[dict[str, Any], str] | None:
    """A body missing exactly one required field, and which one.

    For the validation tier. None when the schema has no required fields, in
    which case there is no such thing as an incomplete request and the tier
    does not apply rather than being asserted vacuously.
    """
    if schema is None:
        return None
    required = [field for field in schema.fields if field.required]
    if not required:
        return None
    dropped = required[0]
    body = {
        field.name: sample_value(field, entities)
        for field in required
        if field.name != dropped.name
    }
    return body, dropped.name


def as_literal(value: Any) -> str:
    """A Python value as the TypeScript literal for it.

    JSON, because the subset of TypeScript a test body needs here is JSON, and
    the escaping is somebody else's solved problem.
    """
    return json.dumps(value, sort_keys=True)
