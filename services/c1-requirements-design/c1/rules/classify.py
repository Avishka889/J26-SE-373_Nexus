"""What kind of requirement this is, and how strongly it is asked for.

The rule decides type, priority and quality attribute. The model never does.

That split is the point. A language model asked to label a requirement will
produce a label, and nothing about the label can be checked afterwards. A lexicon
match can be shown: the classification carries the word that triggered it, so the
evaluation can report how often the rule fired on evidence and how often it fell
back to a default.

Falling back is not hidden either. A sentence with no modal verb gets the default
priority and says so, and the confidence rule takes points off for it.
"""

import re
from dataclasses import dataclass, field
from typing import Literal

from .lexicons import (
    ACTION_VERBS,
    ALL_MODALS,
    CONSTRAINT_MARKERS,
    COULD_WORDS,
    MUST_WORDS,
    QUALITY_MARKERS,
    QUALITY_SIGNALS,
    SHOULD_WORDS,
    verb_stem,
)

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'-]*")

RequirementType = Literal["functional", "quality", "constraint"]
RequirementPriority = Literal["must", "should", "could"]
QualityAttribute = Literal["performance", "security", "usability", "reliability"]

#: What a sentence with no modality is taken to be asking for.
#:
#: "should" rather than "must": a requirement nobody marked as mandatory should
#: not be promoted to mandatory by a tool. Understating is recoverable in review;
#: overstating quietly turns a suggestion into a commitment.
DEFAULT_PRIORITY: RequirementPriority = "should"


@dataclass(frozen=True)
class Classification:
    """A label, and the word that produced it."""

    type: RequirementType
    priority: RequirementPriority
    quality_attribute: QualityAttribute | None = None
    #: The lexicon words that fired, so a reader can check the rule's working.
    evidence: tuple[str, ...] = field(default=())
    #: True when no modal appeared and the priority is therefore a default.
    priority_is_default: bool = False
    #: True when the sentence names no action, no prohibition and no quality, so
    #: nothing positively identified what kind of requirement it is.
    type_is_default: bool = False


def _matches(haystack: str, words: frozenset[str]) -> list[str]:
    """Which of these words appear. Multi-word entries are matched as phrases."""
    return sorted(word for word in words if word in haystack)


def classify(text: str) -> Classification:
    """Read a requirement sentence and label it from the lexicons."""
    haystack = f" {text.lower().strip()} "

    priority, priority_words, priority_defaulted = _priority(haystack)
    requirement_type, type_words, type_defaulted = _type(haystack)

    attribute: QualityAttribute | None = None
    attribute_words: list[str] = []
    if requirement_type == "quality":
        attribute, attribute_words = _quality_attribute(haystack)
        # A quality requirement the lexicons cannot attribute is not a quality
        # requirement we can say anything useful about, so it stays functional
        # rather than carrying an attribute nobody chose.
        if attribute is None:
            requirement_type = "functional"
            type_defaulted = True

    return Classification(
        type=requirement_type,
        priority=priority,
        quality_attribute=attribute,
        evidence=tuple(dict.fromkeys(priority_words + type_words + attribute_words)),
        priority_is_default=priority_defaulted,
        type_is_default=type_defaulted,
    )


def _priority(haystack: str) -> tuple[RequirementPriority, list[str], bool]:
    """Strongest modality wins, because that is how the sentence reads.

    "may be exported, but must be audited" is a must: the weaker clause does not
    soften the stronger one.
    """
    for words, priority in (
        (MUST_WORDS, "must"),
        (SHOULD_WORDS, "should"),
        (COULD_WORDS, "could"),
    ):
        found = _matches(haystack, words)
        if found:
            return priority, found, False  # type: ignore[return-value]

    assert not _matches(haystack, ALL_MODALS)
    return DEFAULT_PRIORITY, [], True


def _type(haystack: str) -> tuple[RequirementType, list[str], bool]:
    """Constraint, then quality, then functional.

    Order matters and is not arbitrary. A prohibition is a constraint even when
    it mentions a quality word: "card data must never be stored" restricts the
    solution rather than describing how well it performs.

    Functional is not merely the leftover box. A sentence naming an action the
    system takes is positively functional, and the verb is the evidence for it.
    Only a sentence with no prohibition, no quality marker and no action at all
    is genuinely unclassified, and that is the case worth taking points off for.
    """
    constraint_words = _matches(haystack, CONSTRAINT_MARKERS)
    if constraint_words:
        return "constraint", constraint_words, False

    quality_words = _matches(haystack, QUALITY_MARKERS)
    if quality_words:
        return "quality", quality_words, False

    actions = sorted({verb_stem(token) for token in _WORD.findall(haystack)} & ACTION_VERBS)
    if actions:
        return "functional", actions[:2], False

    return "functional", [], True


def _quality_attribute(haystack: str) -> tuple[QualityAttribute | None, list[str]]:
    """Which of the four attributes this is about.

    Scored by how many signals fire rather than by first match, so a sentence
    mentioning one performance word and three security words is security. Ties
    resolve alphabetically, which is arbitrary but stable: an unstable tie break
    would make the same input classify differently between runs.
    """
    scored: list[tuple[int, str, list[str]]] = []
    for attribute, signals in QUALITY_SIGNALS.items():
        found = _matches(haystack, signals)
        if found:
            scored.append((len(found), attribute, found))

    if not scored:
        return None, []

    scored.sort(key=lambda item: (-item[0], item[1]))
    _, attribute, words = scored[0]
    return attribute, words  # type: ignore[return-value]
