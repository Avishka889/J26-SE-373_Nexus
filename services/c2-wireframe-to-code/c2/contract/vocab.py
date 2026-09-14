"""Naming conventions: how design vocabulary becomes REST vocabulary.

Deterministic and dull on purpose. Endpoint ids are slugs of method and path
so a human decision recorded against one survives a regeneration; resources
are kebab case plurals of entity labels; verbs classify into methods by a
fixed table, and a verb the table does not know becomes a POST subaction,
which is the REST convention for a domain action rather than a guess at CRUD.
"""

import re
from typing import Final, Literal

Method = Literal["GET", "POST", "PUT", "PATCH", "DELETE"]

_NON_WORD = re.compile(r"[^a-z0-9]+")


def kebab(text: str) -> str:
    return _NON_WORD.sub("-", text.lower()).strip("-")


_US_NOUNS = frozenset(["status", "bus", "virus", "bonus", "campus", "radius", "census", "surplus"])


def singular(word: str) -> str:
    word = word.lower()
    if word.endswith("ies") and len(word) > 3:
        return word[:-3] + "y"
    # Strip "es" only when the stem is one that takes -es ("statuses",
    # "classes", "boxes"); "browses" and "houses" are plain -s words whose
    # stems happen to end in "se". The -us nouns are a closed list because
    # letters alone cannot separate "status(es)" from "hous(es)".
    if word.endswith("es"):
        stem = word[:-2]
        if stem.endswith(("ss", "x", "z", "ch", "sh")) or stem in _US_NOUNS:
            return stem
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def plural(word: str) -> str:
    word = word.lower()
    if word.endswith("y") and word[-2:-1] not in "aeiou":
        return word[:-1] + "ies"
    if word.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    return word + "s"


def verb_slug(verb: str) -> str:
    """ "Submits For Review" -> "submit-for-review": kebab, words singular."""
    return "-".join(singular(word) for word in kebab(verb).split("-") if word)


def resource_of(entity_label: str) -> str:
    """ "Purchase Order" -> "purchase-orders": kebab, last word pluralised."""
    parts = kebab(entity_label).split("-")
    if not parts or not parts[0]:
        return ""
    parts[-1] = plural(parts[-1])
    return "-".join(parts)


def slug(method: str, path: str) -> str:
    """ "GET /orders/{id}" -> "get-orders-id". Deterministic by construction."""
    cleaned = re.sub(r"[{}]", "", path)
    return kebab(f"{method} {cleaned}")


def canonical(method: str, path: str) -> str:
    """The comparison key both arms and the agreement checker share.

    Path parameters normalise to {id} whatever they were called, so an Express
    route with :orderId and a contract path with {id} compare as equal.
    """
    normalised = re.sub(r"\{[^}]+\}|:[A-Za-z_][\w]*", "{id}", path)
    return f"{method.upper()} {normalised}"


#: Verb classification. Word match on the edge's verb, first hit wins.
CREATE_VERBS: Final = frozenset(
    [
        "create",
        "add",
        "place",
        "submit",
        "register",
        "record",
        "upload",
        "send",
        "start",
        "request",
        "book",
        "schedule",
        "pack",
        "open",
        "raise",
    ]
)
UPDATE_VERBS: Final = frozenset(
    [
        "update",
        "edit",
        "change",
        "assign",
        "correct",
        "mark",
        "confirm",
        "approve",
        "resolve",
        "complete",
        "acknowledge",
        "adjust",
        "set",
        "reschedule",
    ]
)
DELETE_VERBS: Final = frozenset(["delete", "remove", "cancel", "revoke"])
READ_VERBS: Final = frozenset(
    [
        "view",
        "see",
        "browse",
        "track",
        "monitor",
        "review",
        "check",
        "look",
        "search",
        "filter",
        "watch",
        "read",
        "list",
        "inspect",
        "audit",
        "compare",
        "receive",
    ]
)

VerbKind = Literal["create", "update", "delete", "read", "domain"]


def classify_verb(verb: str) -> VerbKind:
    words = [singular(w) for w in kebab(verb).split("-") if w]
    for word in words:
        if word in CREATE_VERBS:
            return "create"
        if word in UPDATE_VERBS:
            return "update"
        if word in DELETE_VERBS:
            return "delete"
        if word in READ_VERBS:
            return "read"
    return "domain"


def words_of(text: str) -> set[str]:
    """The singular word set of a label, for vocabulary matching."""
    return {singular(word) for word in kebab(text).split("-") if word}


def head_noun(label: str) -> str:
    """The last word of a label, singular: "Purchase Order" -> "order"."""
    parts = kebab(label).split("-")
    return singular(parts[-1]) if parts and parts[-1] else ""


def mentions(text: str, entity_label: str) -> bool:
    """Whether a screen or block name speaks about this entity.

    The entity's head noun must appear as a word of the text, in the singular.
    Word match, never substring: C1 paid for a substring match with a money
    question on a temperature threshold.
    """
    noun = head_noun(entity_label)
    return bool(noun) and noun in words_of(text)
