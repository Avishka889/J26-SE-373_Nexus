"""What the input did not say, and what to do about it.

Assumptions and clarifying questions come from the same place: a table of the
things a design needs decided, checked against what the input actually mentions.
An unfilled slot becomes a question if it is worth interrupting for, and an
assumption if it is not.

That is the whole mechanism, and it is why a seven word prompt produces
assumptions rather than confident requirements. The alternative, when the input
is thin, is to invent detail and present it as read.

Questions are capped at three. The cap is enforced twice: here by construction,
and again by a model validator on the artefact, so no code path can produce a
fourth. Above three this stops being a conversation and becomes a form, and
people stop reading forms.
"""

import re
from dataclasses import dataclass, field
from functools import cache
from typing import Final

from .lexicons import NOISE_WORDS

#: At most three unanswered questions. Also enforced by the contract.
MAX_QUESTIONS: Final = 3


@dataclass(frozen=True)
class Slot:
    """A decision a design needs, and how to tell whether the input made it."""

    id: str
    #: Words whose presence means the input already addressed this.
    filled_by: frozenset[str]
    #: Asked when the slot is worth interrupting for.
    question: str
    #: Recorded when it is not. Written as a statement the reader can correct.
    assumption: str
    #: How badly a wrong answer hurts, 1 to 5.
    criticality: int
    #: How much of the design a wrong answer changes, 1 to 5.
    blast_radius: int
    #: Only consider this slot when the input looks like it needs it. An empty
    #: set means always.
    relevant_when: frozenset[str] = frozenset()

    @property
    def weight(self) -> int:
        return self.criticality * self.blast_radius


#: The slots, in no particular order: ranking is computed, not authored.
#:
#: Each one is a question a designer would actually ask before drawing anything,
#: and each has a defensible default to fall back on. A slot with no sensible
#: default does not belong here, because the assumption branch would have nothing
#: honest to say.
SLOTS: Final[tuple[Slot, ...]] = (
    Slot(
        id="roles",
        # No lexicon can list every profession, and this one does not try. It
        # knows the words briefs actually use; anything else leaves the slot open,
        # which produces a question rather than a wrong assumption. Asking when
        # the answer was already given is the cheap failure; assuming one role
        # when there are three is the expensive one.
        filled_by=frozenset(
            {
                "role",
                "roles",
                "admin",
                "administrator",
                "administrators",
                "permission",
                "permissions",
                "manager",
                "staff",
                "customer",
                "customers",
                "clinician",
                "merchant",
                "operator",
                "doctor",
                "doctors",
                "nurse",
                "nurses",
                "patient",
                "patients",
                "member",
                "members",
                "guest",
                "owner",
                "shopper",
                "reviewer",
                "approver",
                "auditor",
                "teacher",
                "student",
                "driver",
                "seller",
                "buyer",
            }
        ),
        question="Who uses this, and is there more than one kind of person involved?",
        assumption="Assumed one kind of user, since the input does not separate roles.",
        criticality=4,
        blast_radius=5,
    ),
    Slot(
        id="persistence",
        filled_by=frozenset(
            {
                "save",
                "saved",
                "store",
                "stored",
                "storage",
                "database",
                "persist",
                "persisted",
                "history",
                "record",
                "records",
                "keep",
                "kept",
            }
        ),
        question="Does anything need to be kept between sessions, or is it enough to hold it while the app is open?",
        assumption="Assumed nothing is kept between sessions, since the input does not mention storing anything.",
        criticality=4,
        blast_radius=4,
    ),
    Slot(
        id="auth",
        filled_by=frozenset(
            {
                "login",
                "log in",
                "sign in",
                "signin",
                "authenticate",
                "authentication",
                "password",
                "account",
                "accounts",
                "session",
                "sso",
                "oauth",
            }
        ),
        question="Does anyone need to sign in, or is this open to whoever has the link?",
        assumption="Assumed no sign in is needed, since the input does not mention accounts.",
        criticality=4,
        blast_radius=4,
    ),
    Slot(
        id="platform",
        filled_by=frozenset(
            {
                "web",
                "browser",
                "mobile",
                "ios",
                "android",
                "desktop",
                "cli",
                "api",
                "service",
                "app",
            }
        ),
        question="Where does this run: a browser, a phone, or something else?",
        assumption="Assumed a single web application, since the input does not say where it runs.",
        criticality=3,
        blast_radius=4,
    ),
    Slot(
        id="scale",
        filled_by=frozenset(
            {
                "concurrent",
                "users",
                "scale",
                "load",
                "throughput",
                "traffic",
                "thousand",
                "million",
                "per second",
                "peak",
            }
        ),
        question="Roughly how many people use this at once?",
        assumption="Assumed a small number of users at once, since the input names no scale.",
        criticality=2,
        blast_radius=4,
    ),
    Slot(
        id="money-units",
        filled_by=frozenset(
            {"currency", "usd", "eur", "gbp", "lkr", "dollars", "pounds", "euros", "rupees"}
        ),
        question="What currency are those amounts in, and does conversion matter?",
        assumption="Assumed one currency throughout, with no conversion.",
        criticality=3,
        blast_radius=2,
        # Only when the input actually names money. The previous set included
        # "above", "below", "threshold", "limit" and "over", which are units of
        # nothing in particular: any brief with a bound of any kind was asked
        # which currency it was in.
        relevant_when=frozenset(
            {"$", "amount", "price", "cost", "fee", "invoice", "payment", "refund", "balance"}
        ),
    ),
    Slot(
        id="notification-channel",
        filled_by=frozenset({"email", "sms", "push", "notification", "notify", "alert", "message"}),
        question="How should people be told when something happens: email, SMS, or something else?",
        assumption="Assumed email only, since the input does not name a channel.",
        criticality=2,
        blast_radius=3,
        relevant_when=frozenset({"notify", "notified", "alert", "tell", "inform", "confirmation"}),
    ),
    Slot(
        id="failure-handling",
        filled_by=frozenset(
            {
                "fail",
                "fails",
                "failed",
                "failure",
                "error",
                "errors",
                "retry",
                "retries",
                "reject",
                "rejected",
                "decline",
                "declined",
                "invalid",
            }
        ),
        question="What should happen when this goes wrong: stop, retry, or carry on?",
        assumption="Assumed a failure stops the action and reports it, with no automatic retry.",
        criticality=3,
        blast_radius=3,
        relevant_when=frozenset(
            {"process", "payment", "send", "sync", "integrate", "external", "provider"}
        ),
    ),
    Slot(
        id="audit",
        filled_by=frozenset({"audit", "log", "logged", "trail", "history", "who did", "traceable"}),
        question="Does anyone need to see who did what, after the fact?",
        assumption="Assumed no audit trail is required beyond ordinary logging.",
        criticality=3,
        blast_radius=2,
        relevant_when=frozenset(
            {"payment", "money", "patient", "record", "approve", "delete", "admin"}
        ),
    ),
)


@dataclass(frozen=True)
class SlotFinding:
    """An unfilled slot, and which requirements left it unfilled."""

    slot: Slot
    traces: tuple[str, ...] = field(default=())

    @property
    def weight(self) -> int:
        return self.slot.weight


@cache
def _as_whole_word(token: str) -> re.Pattern[str]:
    """The token as a pattern that will not match inside a longer word.

    Substring matching is what asked a cold chain brief which currency its
    temperature threshold was in: "over" occurs inside "coverage", so the money
    slot fired on the phrase "areas with unreliable coverage". "limit" inside
    "unlimited" is the same bug waiting for a different brief.

    The boundary is applied only where the token's own edge is alphanumeric, so
    "$" still matches in "$50" while "over" no longer matches in "coverage".
    Multi word tokens like "per second" work unchanged.
    """
    left = r"\b" if token[:1].isalnum() else ""
    right = r"\b" if token[-1:].isalnum() else ""
    return re.compile(f"{left}{re.escape(token)}{right}")


def _mentions(haystack: str, tokens: frozenset[str]) -> bool:
    """Whether the text uses any of these words, as words."""
    return any(_as_whole_word(token).search(haystack) for token in tokens)


def unfilled_slots(source: str, requirement_ids: tuple[str, ...]) -> list[SlotFinding]:
    """Which decisions the input left open, most consequential first.

    Relevance comes first: a notification channel is not an open question for an
    app that never notifies anyone, and asking about it would be noise dressed as
    diligence.
    """
    haystack = f" {source.lower()} "
    findings: list[SlotFinding] = []

    for slot in SLOTS:
        if slot.relevant_when and not _mentions(haystack, slot.relevant_when):
            continue
        if _mentions(haystack, slot.filled_by):
            continue
        findings.append(SlotFinding(slot, requirement_ids))

    return rank(findings)


def rank(findings: list[SlotFinding]) -> list[SlotFinding]:
    """Most consequential first. The one ordering questions and assumptions share.

    Separate from `unfilled_slots` because model gaps are ranked by it too, and a
    second sort written at the merge site is a second sort that can disagree.
    """
    return sorted(findings, key=lambda finding: (-finding.weight, finding.slot.id))


#: What a gap the model found is worth, against a table whose highest slot is 20.
#:
#: Above every slot, and the reason is evidential rather than a preference. A slot
#: is a decision every project faces, asked because a lexicon did not find certain
#: words. A gap is grounded in a verified span of this brief. Input specific
#: evidence outranks a generic checklist, so when both compete for the three
#: question places the one that read this input wins.
#:
#: Slots are not lost by this: what does not make the cap is stated as an
#: assumption, which is where a generic default belongs anyway.
GAP_CRITICALITY: Final = 5
GAP_BLAST_RADIUS: Final = 5


def slot_for_gap(index: int, question: str, assumption: str) -> Slot:
    """A model's gap, in the shape the ranking and the split already understand.

    `filled_by` is empty because the question of whether the brief filled this
    was already settled: the model raised it against a span of that brief. The id
    is zero padded so ten gaps do not sort before two.
    """
    return Slot(
        id=f"input-gap-{index + 1:02d}",
        filled_by=frozenset(),
        question=question,
        assumption=assumption,
        criticality=GAP_CRITICALITY,
        blast_radius=GAP_BLAST_RADIUS,
    )


def split_questions_and_assumptions(
    findings: list[SlotFinding],
) -> tuple[list[SlotFinding], list[SlotFinding]]:
    """The top few become questions; the rest are stated as assumptions.

    Nothing is dropped. A slot that does not make the cut is still a decision
    somebody has to live with, so it is written down where it can be corrected
    rather than left silently open.
    """
    return findings[:MAX_QUESTIONS], findings[MAX_QUESTIONS:]


def content_words(text: str) -> set[str]:
    """Shared helper for callers that need the words a sentence is about."""
    return {
        word.strip(".,;:()").lower()
        for word in text.split()
        if len(word.strip(".,;:()")) > 3 and word.strip(".,;:()").lower() not in NOISE_WORDS
    }
