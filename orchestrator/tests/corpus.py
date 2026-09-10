"""The calculator corpus, and the two guards that read a whole snapshot.

The leakage guard exists because of how this repository is built rather than
because of anything a model does. There are four hand authored demo projects in
the frontend, full of payments and clinical and commerce vocabulary, and the
plausible ways for that to reach a real run are all in our code: a read model
that falls back to a seed, a stage summary written from a template that was
copied out of demo data, a prompt with an example in it that the model repeats.
None of those are visible in one artefact. They are visible in the assembled
snapshot, which is why the guard runs over the whole thing and over every string
in it, including the ones nobody thinks of as content: stage summaries, thread
messages, audit detail, the architecture rationale, the velocity basis.

It is paired with a grounding check, and the pairing is the important part. A
leakage guard on its own passes an empty snapshot, and an empty snapshot is the
most likely way for this to break: one stage fails, the artefacts are absent, no
foreign word appears, and the test goes green over nothing. So the same run has
to prove the calculator's own vocabulary is present.

The banned list is deliberately short and deliberately excludes near misses. The
word "order" is not on it, because "order of operations" is calculator
vocabulary; "currency" is not, because a calculator that converts currency is not
a contradiction. A guard that fires on a correct design is a guard people learn
to switch off.
"""

import re
from typing import Any

#: A thin one line input, which is the case that matters. Anything can produce a
#: reasonable design from a page of detail; the claim this component makes is
#: that a sentence produces a handful of requirements with the gaps named,
#: instead of thirty confident ones.
CALCULATOR_INPUT = "Build a simple calculator app."

#: Words that name somebody else's product. Every one appears in the frontend's
#: demo seeds and none of them can appear in a calculator design without
#: something having leaked.
FOREIGN_WORDS = (
    "payment",
    "card",
    "refund",
    "invoice",
    "checkout",
    "basket",
    "merchant",
    "shopper",
    "patient",
    "doctor",
    "clinician",
    "prescription",
    "appointment",
    "pharmacy",
    "subscriber",
    "webhook",
    "inventory",
    "warehouse",
    "shipment",
    "wallet",
    "kyc",
    "pci",
    "hipaa",
    "fhir",
    # The demo project names themselves, which is the bluntest leak of all.
    "nexuspay",
    "meditrack",
    "shopflow",
    "notifyhub",
)

#: The word the design is about. Matched as a stem so calculator, calculation
#: and calculations all count.
CALCULATOR_STEM = "calculat"

#: What a calculator design should be made of. Not all of them, because which
#: ones appear is the model's choice and pinning the set would be pinning the
#: answer rather than checking it.
ARITHMETIC_WORDS = (
    "number",
    "digit",
    "add",
    "subtract",
    "multiply",
    "divide",
    "arithmetic",
    "result",
    "sum",
    "operation",
    "operator",
    "expression",
    "equals",
    "total",
    "value",
)

#: How many of them have to appear. Three, because one could be a coincidence in
#: a sentence and requiring all of them would fail a design that chose different
#: words for the same thing.
MIN_ARITHMETIC_WORDS = 3


def every_string(value: Any) -> list[str]:
    """Every string anywhere in a nested structure.

    Walks rather than reading named fields, because the fields most likely to
    carry a leak are the ones nobody remembers are text: a stage summary, an
    audit detail, the basis line under a velocity assumption.
    """
    found: list[str] = []
    if isinstance(value, str):
        found.append(value)
    elif isinstance(value, dict):
        for key, item in value.items():
            # Keys too: a dict keyed by stage id or candidate id is content.
            found.append(str(key))
            found.extend(every_string(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            found.extend(every_string(item))
    return found


def text_of(payload: Any) -> str:
    """Everything a snapshot says, as one lowercase block to search."""
    return "\n".join(every_string(payload)).lower()


def leaked(payload: Any) -> list[str]:
    """Foreign vocabulary found, with a little of its context.

    The context is what makes a failure actionable. "payment" tells you
    something leaked; "the payment service records every payment" tells you
    which fixture it came from.
    """
    haystack = text_of(payload)
    hits: list[str] = []
    for word in FOREIGN_WORDS:
        for match in re.finditer(rf"\b{re.escape(word)}\w*", haystack):
            start = max(0, match.start() - 40)
            hits.append(f"{word}: ...{haystack[start : match.end() + 40]}...")
            break  # One example per word is enough to find the source.
    return hits


def grounding(payload: Any) -> tuple[bool, list[str]]:
    """Whether the design is about a calculator, and which words say so."""
    haystack = text_of(payload)
    names_it = CALCULATOR_STEM in haystack
    found = sorted({word for word in ARITHMETIC_WORDS if re.search(rf"\b{word}", haystack)})
    return names_it, found


def assert_no_leakage(payload: Any) -> None:
    hits = leaked(payload)
    assert not hits, "another project's vocabulary reached this design:\n  " + "\n  ".join(hits)


def assert_grounded(payload: Any) -> None:
    """The mirror assertion, without which an empty snapshot passes."""
    names_it, found = grounding(payload)
    assert names_it, f"nothing in this design mentions a {CALCULATOR_STEM}..."
    assert len(found) >= MIN_ARITHMETIC_WORDS, (
        f"only {len(found)} arithmetic word(s) in the whole design ({found}), "
        f"which reads more like an empty artefact than a calculator"
    )
