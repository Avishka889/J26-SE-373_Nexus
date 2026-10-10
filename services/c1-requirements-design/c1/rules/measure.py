"""How much the input actually contains, and how much may be read from it.

This is the arithmetic behind the component's first honesty claim: a seven word
prompt yields a handful of requirements with assumptions, never dozens of
confident ones.

It is arithmetic on purpose. Telling a language model "extract at most five
requirements" is the least reliable instruction you can give it, so the budget is
computed here from the input, passed into the prompt as a target, and then
enforced by truncation afterwards. An overrun is not an error to hide: it is
recorded and reported, because how often the model ignores its budget is a
publishable number about the model, not about this code.
"""

import re
from dataclasses import dataclass, field

from .lexicons import ACTION_VERBS, NOISE_WORDS, verb_stem

#: The floor and ceiling on how many requirements may be read from one input.
#:
#: Three, because below that the analysis has nothing to say even about a one
#: line prompt. Thirty, because a single free text input that genuinely contains
#: more than thirty distinct requirements is a document, and reading it as one
#: block would produce a list nobody checks.
MIN_BUDGET = 3
MAX_BUDGET = 30

#: How many requirements one piece of evidence is worth. Calibrated against two
#: anchors rather than chosen: "Build a simple calculator app" has to yield a
#: budget of 5, and the payments brief has to yield 12, which is the count its
#: hand written fixture arrived at independently.
PER_EVIDENCE = 1.5

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'-]*")

#: Requirements prose is full of the passive: "transactions must be audited",
#: "verification is required". The thing being acted on sits before the verb
#: there, so a forward-only reading loses it.
_BE_FORMS = frozenset({"is", "are", "was", "were", "be", "been", "being", "get", "gets"})


@dataclass(frozen=True)
class InputMeasurement:
    """What the input contains, before anything is read from it."""

    #: Sentences, or clause-like fragments when the writer used no punctuation.
    sentences: tuple[str, ...]
    #: Distinct verb and object pairs, which is what carries a requirement.
    verb_object_pairs: tuple[tuple[str, str], ...] = field(default=())
    #: The larger of the two counts. One long sentence listing six features has
    #: more in it than its single full stop suggests, and six terse sentences
    #: have more than their verbs suggest, so neither count alone is enough.
    evidence: int = 0
    budget: int = MIN_BUDGET

    @property
    def word_count(self) -> int:
        return sum(len(_WORD.findall(sentence)) for sentence in self.sentences)


def split_sentences(text: str) -> list[str]:
    """Sentences, falling back to clauses when the writer used no full stops.

    A prompt typed into a box rarely has punctuation, and treating "catalog,
    cart, checkout and orders" as one piece of evidence would budget it like a
    single feature.
    """
    cleaned = " ".join(text.split())
    if not cleaned:
        return []

    sentences = [part.strip() for part in _SENTENCE_SPLIT.split(cleaned) if part.strip()]
    if len(sentences) > 1:
        return sentences

    # One sentence: split on the connectives people list features with, but only
    # where both sides carry a real word, so "fast and reliable" stays whole.
    parts = [part.strip() for part in re.split(r",| and | plus | as well as ", cleaned)]
    parts = [part for part in parts if len(_WORD.findall(part)) >= 2]
    return parts if len(parts) > 1 else sentences


def find_verb_object_pairs(text: str) -> list[tuple[str, str]]:
    """Action verbs followed by something they act on.

    A deliberately shallow reading: a verb from the lexicon, then the next word
    that is not noise, within a short window. This is not parsing and does not
    claim to be. It is a count of how many distinct things the input asks for,
    and it only has to be stable enough to size a budget.

    Pairs are deduplicated on the stem and the object, so "process payments" and
    "processing payments" count once. Counting them twice would inflate the
    budget on repetitive prose, which is exactly the input that deserves less.

    Coordination inside one verb phrase counts once too: "integrate Stripe and
    PayPal" is a single thing being asked for, and reading it as two would budget
    a list of providers like a list of features.
    """
    words = _WORD.findall(text)
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def take(stem: str, candidates: list[str]) -> bool:
        for candidate in candidates:
            word = candidate.lower()
            if word in NOISE_WORDS or verb_stem(candidate) in ACTION_VERBS:
                continue
            key = (stem, word)
            if key not in seen:
                seen.add(key)
                pairs.append(key)
            return True
        return False

    for index, token in enumerate(words):
        stem = verb_stem(token)
        if stem not in ACTION_VERBS:
            continue

        # Passive: the subject is behind the verb, not in front of it. Reading
        # forward from "audited" in "transactions must be audited" finds the end
        # of the sentence.
        preceding = [w.lower() for w in words[max(0, index - 3) : index]]
        is_passive = any(word in _BE_FORMS for word in preceding)
        if is_passive and take(stem, list(reversed(words[max(0, index - 4) : index]))):
            continue

        take(stem, words[index + 1 : index + 5])

    return pairs


def measure(text: str) -> InputMeasurement:
    """Measure an input and decide how much may be read from it."""
    sentences = split_sentences(text)
    pairs = find_verb_object_pairs(text)
    evidence = max(len(sentences), len(pairs))
    return InputMeasurement(
        sentences=tuple(sentences),
        verb_object_pairs=tuple(pairs),
        evidence=evidence,
        budget=budget_for(evidence),
    )


def budget_for(evidence: int) -> int:
    """How many requirements this much evidence supports."""
    raw = MIN_BUDGET + round(PER_EVIDENCE * evidence)
    return max(MIN_BUDGET, min(MAX_BUDGET, raw))
