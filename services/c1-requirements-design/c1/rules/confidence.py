"""How confidently a requirement was read, computed from checkable properties.

Never reported by a model. That is the whole rule.

A model asked "how confident are you" returns a number with no referent: it
cannot be reproduced, it cannot be audited, and it correlates with fluency rather
than with evidence. Every figure here is a deduction from a property of the text
that a reader can verify for themselves, and each deduction is recorded with its
reason, so the evaluation can report why a requirement scored what it did instead
of only that it did.

The ceiling is below 100 on purpose. Nothing read from prose is certain, and a
requirement claiming certainty is the one nobody checks.
"""

import re
from dataclasses import dataclass, field

from .classify import Classification
from .lexicons import ACTION_VERBS, NOISE_WORDS, verb_stem

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'-]*")

#: Nothing read from prose is certain.
CEILING = 98

#: Below this a requirement is flagged for a closer look. The analysis decides
#: this, so the client never picks a threshold and two screens cannot disagree
#: about which rows are worth attention.
LOW_CONFIDENCE_BELOW = 70


@dataclass(frozen=True)
class Deduction:
    """One reason a requirement scored less than certain."""

    #: Stable name, so the same deduction can be counted across runs.
    rule: str
    points: int
    #: Written for a reader, not for a log.
    reason: str


@dataclass(frozen=True)
class ConfidenceScore:
    value: int
    deductions: tuple[Deduction, ...] = field(default=())

    @property
    def low(self) -> bool:
        return self.value < LOW_CONFIDENCE_BELOW

    @property
    def why(self) -> str:
        """The deductions as one sentence, for a tooltip or a report."""
        if not self.deductions:
            return "Read directly from your input, with every check passing."
        return " ".join(deduction.reason for deduction in self.deductions)


def _head_nouns(text: str) -> set[str]:
    """The content words of a sentence: what it is actually about."""
    return {
        word.strip(".,;:()").lower()
        for word in text.split()
        if len(word.strip(".,;:()")) > 3 and word.strip(".,;:()").lower() not in NOISE_WORDS
    }


def score(
    *,
    text: str,
    source: str,
    quote: str | None,
    classification: Classification,
    siblings: tuple[str, ...] = (),
) -> ConfidenceScore:
    """Score one requirement against the input it came from.

    `siblings` are the other requirements read from the same input, used only for
    the near duplicate check. Passing them keeps the rule pure: it does not reach
    for shared state to find out what else was extracted.
    """
    deductions: list[Deduction] = []

    # Inferred rather than read. The largest single deduction, because a
    # requirement with no sentence behind it is the one most likely to be wrong.
    if quote is None:
        deductions.append(
            Deduction(
                "inferred-not-read",
                28,
                "No sentence in your input says this directly, so it was inferred.",
            )
        )

    if classification.priority_is_default:
        deductions.append(
            Deduction(
                "no-modality",
                12,
                "The sentence does not say whether this is required or optional, "
                "so the priority is a default rather than a reading.",
            )
        )

    if classification.type_is_default:
        deductions.append(
            Deduction(
                "type-not-matched",
                8,
                "The sentence names no action, no prohibition and no quality, so "
                "nothing in it identifies what kind of requirement this is.",
            )
        )

    # A requirement that names nothing the system does is not a requirement, it
    # is an opinion. "It should be nice and modern" reads accurately off the
    # input and is still untestable, and a high score beside it reads as
    # endorsement rather than as "we read your words correctly".
    if not ({verb_stem(token) for token in _WORD.findall(text)} & ACTION_VERBS):
        deductions.append(
            Deduction(
                "no-action",
                22,
                "It does not say anything the system does, so there is nothing here "
                "to build or to test.",
            )
        )

    # A quality requirement with no number in it is an aspiration. "The system
    # is fast" cannot be tested, and the score should say so.
    if classification.type == "quality" and not any(ch.isdigit() for ch in text):
        deductions.append(
            Deduction(
                "quality-without-a-number",
                15,
                "This asks for a quality but names no measurable value, so nothing "
                "here can be tested as written.",
            )
        )

    # Head nouns absent from the input mean the requirement is about something
    # the reader never mentioned.
    if source:
        unseen = _head_nouns(text) - _head_nouns(source)
        if unseen:
            named = ", ".join(sorted(unseen)[:3])
            deductions.append(
                Deduction(
                    "words-not-in-the-input",
                    min(6 * len(unseen), 18),
                    f"It mentions {named}, which your input does not.",
                )
            )

    # Near duplicates. Two requirements saying the same thing means at least one
    # of them was invented to fill the budget.
    for sibling in siblings:
        if _overlap(text, sibling) >= 0.8:
            deductions.append(
                Deduction(
                    "near-duplicate",
                    20,
                    "Another requirement says nearly the same thing, so one of the "
                    "two is probably not distinct.",
                )
            )
            break

    total = sum(deduction.points for deduction in deductions)
    return ConfidenceScore(max(0, CEILING - total), tuple(deductions))


def _overlap(left: str, right: str) -> float:
    """How much two requirements say the same thing, by shared content words."""
    a, b = _head_nouns(left), _head_nouns(right)
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))
