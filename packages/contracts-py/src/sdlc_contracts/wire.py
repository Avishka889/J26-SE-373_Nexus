"""The base every artefact model is built on.

Two things live here and nowhere else: the camelCase mapping, and the timestamp
format. Both exist because the browser is the consumer, and both are the kind of
detail that goes wrong quietly if each model decides for itself.
"""

import re
from datetime import UTC, datetime
from functools import cache
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, PlainSerializer, model_validator
from pydantic.alias_generators import to_camel


def _wire_time(value: datetime) -> str:
    """UTC in ISO 8601, with its zone: "2026-10-03T09:12:00Z".

    It was "2026-10-03 09:12", UTC with the zone dropped, and the pages showed
    that string as it came: five and a half hours early to a reader in Colombo.
    The browser now shows every time in its reader's zone through one formatter
    (`shared/utils/time.ts`), which also reads the older shape, still inside
    stored artefacts, as the UTC it always was. A naive value is UTC too: every
    time the platform writes is.
    """
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# One serializer, applied by the type, means no model can forget it.
WireDatetime = Annotated[datetime, PlainSerializer(_wire_time, return_type=str)]

_RANGE = re.compile(r"(\d)\s*[\u2013\u2014]\s*(\d)")
_DASH = re.compile(r"\s*[\u2013\u2014]+\s*")


def plain_dashes(text: str) -> str:
    """Prose without em or en dashes, which nothing this platform writes uses.

    Models write them freely, and they reached the page as written: seven of
    Book Tracker's architecture options carried one. A dash between numbers is
    a range and becomes a hyphen; anywhere else it becomes a comma, and one
    that leads or trails the text goes. The words stay the model's.
    """
    if "\u2013" not in text and "\u2014" not in text:
        return text
    text = _RANGE.sub(r"\1-\2", text)
    text = _DASH.sub(", ", text)
    text = re.sub(r",\s*(?=[,.;:!?)])", "", text)
    return text.strip().strip(",").strip()


#: Prose a model wrote, normalised once where every artefact passes: on the way
#: in, and on the way out of the store, so text written before this reads the
#: same. Never for a quote, which is checked against its source letter for
#: letter and stays plain `str`.
Prose = Annotated[str, AfterValidator(plain_dashes)]


class WireModel(BaseModel):
    """A model that serializes to what the browser expects.

    Python stays snake_case and the wire stays camelCase. `populate_by_name`
    means either spelling parses, which is what lets a JSONB row written by an
    older version still load.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        # A field the contract does not declare is a contract violation, not
        # something to carry along silently.
        extra="forbid",
        # Enum members serialize as their values, which is what the schema says.
        use_enum_values=True,
        str_strip_whitespace=True,
        # A field with a default is still always present in serialized output,
        # so the schema marks it required. Without this every defaulted field
        # generated an optional TypeScript property, and the frontend's
        # hand written types disagreed with the generated ones on exactly the
        # fields readers index without a guard.
        json_schema_serialization_defaults_required=True,
    )

    @model_validator(mode="before")
    @classmethod
    def _discard_derived_values(cls, data: Any) -> Any:
        """Drop a derived key on the way in, so an artefact can be read back.

        Every derived number in the C3 contracts is a `@computed_field`: it is
        written into the stored body and into the TypeScript type, and it has
        no setter. That combination means a stored artefact cannot be validated
        as it stands, because `extra="forbid"` refuses the very keys the dump
        just produced. Found by the testing spine: the quality stage read back
        the report the run stage wrote and got eleven "Extra inputs are not
        permitted" errors, one per derived count.

        Dropping rather than accepting keeps the guarantee that matters. A
        producer still cannot author a derived value: whatever it sends is
        discarded and the number is recomputed from the evidence underneath it.
        The weaker consequence, and it is deliberate, is that offering one is
        no longer an error. A key the contract does not declare at all is still
        refused, which is what `extra="forbid"` was for.
        """
        derived = _derived_keys(cls)
        if not derived or not isinstance(data, dict):
            return data
        if not derived & data.keys():
            return data
        return {key: value for key, value in data.items() if key not in derived}


@cache
def _derived_keys(model: type[BaseModel]) -> frozenset[str]:
    """Both spellings of every computed field on a model, or nothing.

    Cached per class because this runs on every validation of every model, and
    for the great majority (which have no computed fields at all) the answer is
    an empty set that early-returns.
    """
    keys: set[str] = set()
    for name, info in model.model_computed_fields.items():
        keys.add(name)
        keys.add(info.alias or to_camel(name))
    return frozenset(keys)
