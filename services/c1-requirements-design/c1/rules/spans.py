"""Checking that a quoted sentence is actually in the input.

One rule, and it is the one that stops fabricated evidence.

A model asked for the sentence it read a requirement from will happily produce a
plausible one that the input never contained. The fix is not a better prompt: it
is to make the model report offsets, slice the input at those offsets here, and
compare. A quote that does not match is discarded, and the requirement is marked
as inferred rather than read, which costs it confidence.

The comparison is deliberately forgiving about whitespace and quote characters
and nothing else. Normalising harder would start accepting paraphrases, which is
the failure this exists to catch.
"""

import re
from dataclasses import dataclass

_COLLAPSE = re.compile(r"\s+")
# The curly forms are the point of this table, so the ambiguous-character rule
# is silenced here rather than obeyed: replacing them with straight quotes would
# delete the mapping.
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"'})  # noqa: RUF001


def normalise(text: str) -> str:
    """Whitespace and curly quotes only. Never meaning."""
    return _COLLAPSE.sub(" ", text.translate(_QUOTES)).strip().lower()


@dataclass(frozen=True)
class SpanCheck:
    """What the input actually says at the offsets that were reported."""

    verified: bool
    #: The input's own words, taken from the input. Null when nothing matched, so
    #: a caller cannot accidentally pass the model's version through.
    quote: str | None
    #: Why it failed, for the evaluation. Empty when it did not.
    reason: str = ""


def verify_span(source: str, start: int, end: int, claimed: str) -> SpanCheck:
    """Slice the input at the reported offsets and compare with what was claimed.

    Offsets are the primary evidence. If they are out of range or the slice does
    not match the claim, the quote is refused even if the claimed text happens to
    appear elsewhere in the input: a requirement pointing at the wrong sentence is
    as wrong as one pointing at no sentence.
    """
    if start < 0 or end > len(source) or start >= end:
        return SpanCheck(False, None, f"offsets {start}:{end} are outside the input")

    actual = source[start:end]
    if normalise(actual) != normalise(claimed):
        return SpanCheck(
            False,
            None,
            "the input does not say that at those offsets",
        )
    return SpanCheck(True, actual.strip())


def find_span(source: str, claimed: str) -> SpanCheck:
    """Locate a claimed sentence in the input without being told where it is.

    Used by the rule-only path, which has no model to report offsets, and as the
    recovery step when a model's offsets are wrong but its quote is real. A quote
    that cannot be found at all is refused.
    """
    if not claimed.strip():
        return SpanCheck(False, None, "no quote was given")

    haystack = normalise(source)
    needle = normalise(claimed)
    if needle not in haystack:
        return SpanCheck(False, None, "that sentence does not appear in the input")

    # Map the normalised hit back onto the original text, so the quote returned
    # is the input's own characters rather than the normalised form.
    position = _original_offset(source, haystack.index(needle))
    end = position + len(claimed.strip())
    return SpanCheck(True, source[position:end].strip() or claimed.strip())


def _original_offset(source: str, normalised_index: int) -> int:
    """Where a normalised index lands in the original string."""
    seen = 0
    previous_was_space = True
    for index, character in enumerate(source):
        if character.isspace():
            if previous_was_space:
                continue
            previous_was_space = True
            if seen == normalised_index:
                return index
            seen += 1
            continue
        previous_was_space = False
        if seen == normalised_index:
            return index
        seen += 1
    return 0
