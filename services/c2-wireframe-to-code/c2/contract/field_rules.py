"""Field rules: the bounds a sentence states, read by a rule and put on the contract.

The design's constraint nodes and the sprint's acceptance criteria say what a
field may hold ("release years run from 2000 to 2026"). The contract carried
them only as words, which the generated handler wrote as a `// validation:`
comment, so the app took any value: the Movie Tracker accepted release years
1999 and 2027. This reads the common ways a bound is said, attaches each to the
field named nearest before it in the same sentence (or, with none before it, the
nearest after), and leaves anything else as words. A bound that cannot be read
is not guessed.

Read the same way over both arms' contracts, so neither is held to bounds the
other is not, and recorded on each field with the words it was read from.
"""

import re
from collections.abc import Sequence

from pydantic import BaseModel
from sdlc_contracts import ApiContract, SchemaField

_NUMBER = r"-?\d+(?:\.\d+)?"
#: The dashes a range may be written with, by code point so this file stays
#: plain: a hyphen, an en dash and an em dash.
_DASHES = "-" + chr(0x2013) + chr(0x2014)

#: Two numbers that close a range. A dash counts only with spaces around it: a
#: bare hyphen is a date's ("2026-01-01"), not a range.
_RANGE = re.compile(
    rf"\bbetween\s+(?P<a>{_NUMBER})\s+and\s+(?P<b>{_NUMBER})"
    rf"|\b(?P<c>{_NUMBER})\s+(?:to|through)\s+(?P<d>{_NUMBER})"
    rf"|\b(?P<e>{_NUMBER})\s+[{_DASHES}]\s+(?P<f>{_NUMBER})",
    re.IGNORECASE,
)
_AT_LEAST = re.compile(
    r"\b(?:at\s+least|no\s+(?:less|fewer)\s+than|not\s+less\s+than|no\s+earlier\s+than"
    rf"|not\s+before|(?:a\s+)?minimum(?:\s+of)?)\s+(?P<n>{_NUMBER})"
    rf"|\b(?P<m>{_NUMBER})\s+or\s+(?:more|above|greater|higher|later|after)\b",
    re.IGNORECASE,
)
_AT_MOST = re.compile(
    r"\b(?:at\s+most|no\s+more\s+than|not\s+more\s+than|no\s+later\s+than|not\s+after"
    rf"|up\s+to|(?:a\s+)?maximum(?:\s+of)?)\s+(?P<n>{_NUMBER})"
    rf"|\b(?P<m>{_NUMBER})\s+or\s+(?:less|fewer|below|lower|earlier|before)\b",
    re.IGNORECASE,
)
#: What turns a number bound into a length bound, read right after it.
_CHARACTERS = re.compile(r"\s*(?:characters?|chars|letters)\b", re.IGNORECASE)
_ONE_OF = re.compile(r"\bone\s+of\s+(?P<values>[^.;]+)", re.IGNORECASE)
_SENTENCE = re.compile(r"(?<=[.;!?])\s+|\n+")
#: The types a bound can hold for: a number's range, a string's length or choice.
_BOUNDABLE = {"number", "string"}


class FieldRule(BaseModel):
    """What one sentence says one field may hold."""

    minimum: int | float | None = None
    maximum: int | float | None = None
    min_length: int | None = None
    max_length: int | None = None
    one_of: list[str] = []
    #: The sentence it was read from.
    source: str = ""


def rules_in(text: str, fields: Sequence[SchemaField]) -> dict[str, FieldRule]:
    """The bounds one text states, by the name of the field each is for."""
    candidates = [
        field for field in fields if field.type in _BOUNDABLE and field.name.lower() != "id"
    ]
    found: dict[str, FieldRule] = {}
    for sentence in _SENTENCE.split(text):
        mentions = sorted(
            (match.start(), field)
            for field in candidates
            for match in _mention(field.name).finditer(sentence)
        )
        if not mentions:
            continue
        for start, end, bound in _bounds(sentence):
            field = _nearest(mentions, start, end)
            rule = _rule_for(field, bound, characters=bool(_CHARACTERS.match(sentence, end)))
            if rule is not None:
                rule.source = text
                found[field.name] = _tighter(found.get(field.name), rule) or found.get(
                    field.name, rule
                )
    return found


def with_field_rules(contract: ApiContract, texts: Sequence[str]) -> ApiContract:
    """The contract with every bound the texts state on the fields they name.

    On the entities and on each request that spells its fields out; a request
    that names its entity instead is bounded through the entity.
    """
    if not texts:
        return contract
    entities = [
        entity.model_copy(update={"fields": _bounded(entity.fields, texts)})
        for entity in contract.entities
    ]
    endpoints = [
        endpoint.model_copy(
            update={
                "request": endpoint.request.model_copy(
                    update={"fields": _bounded(endpoint.request.fields, texts)}
                )
            }
        )
        if endpoint.request is not None and endpoint.request.fields
        else endpoint
        for endpoint in contract.endpoints
    ]
    return contract.model_copy(update={"entities": entities, "endpoints": endpoints})


def _mention(name: str) -> re.Pattern[str]:
    """A field named in words: `releaseYear` and `release_year` as "release year"."""
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name).replace("_", " ").lower().split()
    return re.compile(r"\b" + r"\s+".join(map(re.escape, words)) + r"(?:s|es)?\b", re.IGNORECASE)


def _bounds(sentence: str) -> list[tuple[int, int, tuple[str, object]]]:
    """Every bound a sentence states, where it stands, and what it says."""
    found: list[tuple[int, int, tuple[str, object]]] = []
    for match in _RANGE.finditer(sentence):
        low, high = (
            next(group for group in pair if group is not None)
            for pair in (match.group("a", "c", "e"), match.group("b", "d", "f"))
        )
        found.append((match.start(), match.end(), ("range", (_value(low), _value(high)))))
    for kind, pattern in (("minimum", _AT_LEAST), ("maximum", _AT_MOST)):
        for match in pattern.finditer(sentence):
            number = match.group("n") or match.group("m")
            found.append((match.start(), match.end(), (kind, _value(number))))
    for match in _ONE_OF.finditer(sentence):
        values = [
            value.strip(" '\"")
            for value in re.split(r",\s*(?:or\s+|and\s+)?|\s+or\s+|\s+and\s+", match["values"])
        ]
        found.append((match.start(), match.end(), ("one_of", [v for v in values if v])))
    return sorted(found, key=lambda item: item[0])


def _nearest(mentions: list[tuple[int, SchemaField]], start: int, end: int) -> SchemaField:
    """The field named nearest before a bound, or with none before it, nearest after."""
    before = [field for position, field in mentions if position < start]
    if before:
        return before[-1]
    after = [field for position, field in mentions if position >= end]
    return after[0] if after else mentions[-1][1]


def _rule_for(
    field: SchemaField, bound: tuple[str, object], *, characters: bool
) -> FieldRule | None:
    """A bound on the field it can hold for, or None: a number's range, a string's length."""
    kind, value = bound
    if kind == "one_of":
        return FieldRule(one_of=list(value)) if field.type == "string" and value else None  # type: ignore[arg-type]
    low, high = value if kind == "range" else (value, None) if kind == "minimum" else (None, value)  # type: ignore[misc]
    if low is not None and high is not None and low > high:
        return None
    if characters:
        if field.type != "string" or not _whole(low, high):
            return None
        return FieldRule(min_length=low, max_length=high)
    if field.type != "number":
        return None
    return FieldRule(minimum=low, maximum=high)


def _bounded(fields: list[SchemaField], texts: Sequence[str]) -> list[SchemaField]:
    """Each field with what every text says of it, the tighter bound winning."""
    rules: dict[str, FieldRule] = {}
    sources: dict[str, list[str]] = {}
    for text in texts:
        for name, rule in rules_in(text, fields).items():
            merged = _tighter(rules.get(name), rule)
            if merged is None:
                continue
            rules[name] = merged
            sources.setdefault(name, [])
            if text not in sources[name]:
                sources[name].append(text)
    bounded = []
    for field in fields:
        rule = rules.get(field.name)
        if rule is None:
            bounded.append(field)
            continue
        current = FieldRule(
            minimum=field.minimum,
            maximum=field.maximum,
            min_length=field.min_length,
            max_length=field.max_length,
            one_of=list(field.one_of),
        )
        rule = _tighter(current, rule) or current
        words = list(field.rules) + [
            text for text in sources[field.name] if text not in field.rules
        ]
        bounded.append(
            SchemaField(
                **{
                    **field.model_dump(),
                    "minimum": rule.minimum,
                    "maximum": rule.maximum,
                    "min_length": rule.min_length,
                    "max_length": rule.max_length,
                    "one_of": rule.one_of,
                    "rules": words,
                }
            )
        )
    return bounded


def _tighter(current: FieldRule | None, new: FieldRule) -> FieldRule | None:
    """Both rules at once, or None when the new one cannot hold with the current."""
    if current is None:
        return new.model_copy()

    def pick(a, b, choose):
        return b if a is None else a if b is None else choose(a, b)

    merged = FieldRule(
        minimum=pick(current.minimum, new.minimum, max),
        maximum=pick(current.maximum, new.maximum, min),
        min_length=pick(current.min_length, new.min_length, max),
        max_length=pick(current.max_length, new.max_length, min),
        one_of=(
            [value for value in current.one_of if value in new.one_of]
            if current.one_of and new.one_of
            else current.one_of or new.one_of
        ),
        source=current.source,
    )
    if (
        (
            merged.minimum is not None
            and merged.maximum is not None
            and merged.minimum > merged.maximum
        )
        or (
            merged.min_length is not None
            and merged.max_length is not None
            and merged.min_length > merged.max_length
        )
        or (current.one_of and new.one_of and not merged.one_of)
    ):
        return None
    return merged


def _value(number: str) -> int | float:
    value = float(number)
    return int(value) if value.is_integer() else value


def _whole(*values: object) -> bool:
    return all(value is None or isinstance(value, int) for value in values)
