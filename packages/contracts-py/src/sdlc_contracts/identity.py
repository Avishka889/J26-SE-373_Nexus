"""Ids that mean the same thing in every version of a design.

The requirement and story ids C1 produces are positional: the first requirement
it reads is R-1, and stories are numbered down the priority ranking. Within one
version that is fine and reads well. Across versions it is a trap, and the live
run walked into it. A change note saying "add a history screen, everything else
stays as it is" came back with three stories where there had been six, and with
R-1 to R-6 renumbered into R-1 to R-5, so `R-4` named one requirement before the
note and a different one after it.

That breaks the thing this platform claims. `diff_requirements` joins the two
versions on the id, and `diff_contracts` has the same shape, and both are the
self healing classifier's first signal: a failing test whose trace leads to
something that CHANGED is a brittleness candidate, one whose trace leads only to
unchanged artefacts is a regression candidate, and regressions are never healed.
Join two versions on an id that was reallocated in between and the answer is not
wrong in a way anybody notices: every requirement reads as changed, every test
reads as brittle, and the guard is asked to approve repairs to tests that were
catching real breakage.

So an id here is an identity and not an ordinal. It is decided against the
previous version of the same artefact, and an id that has been retired is never
handed to something else. C1 cannot do this: it is stateless and sees one brief,
not the project's history, which is why it lives beside `diff_requirements`
rather than inside the component, and why the orchestrator supplies the history.

**How identity is decided, strongest rung first.** Two versions of one
requirement are the same requirement when their text is the same word for word.
Failing that they are the same when they are clearly about the same thing and
nothing else is a plausible candidate. Failing that the current one is new. The
ladder matters because the extraction is not deterministic: the model rewords
what it reads between two runs over the same brief, so a rule that only matched
identical text would carry almost nothing forward and would leave the diff
reporting every requirement as removed and re-added. That is the failure this
module exists to prevent, arrived at by a different route.

The threshold errs high, and deliberately. Refusing to carry an id costs the
classifier a `changed` and gives it a `removed` plus an `added` instead, which
`RequirementDiff.touched` already treats the same way: a weaker signal, still an
honest one. Carrying an id onto something it does not belong to corrupts the
comparison silently, which is the defect. When the two readings disagree, the
one that loses information wins.

Every decision is reported, so a run can say how many ids were observed and how
many were inferred, and a number in the dissertation that rests on an inferred
identity can say so.
"""

import re
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel

from .requirements import RequirementsArtefact
from .sprint import AcceptanceCriterion, SprintPlan, UserStory

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9'-]*")
_NUMBER = re.compile(r"(\d+)$")

#: Words that say nothing about what a requirement is about, so two sentences
#: sharing them are not thereby similar. A copy of the component's own stop list
#: rather than an import of it: this package is what the components are built on,
#: so it cannot depend on one of them. Short and stable enough to duplicate, and
#: the duplication is visible here rather than implied.
_NOISE = frozenset(
    {
        "able",
        "also",
        "been",
        "both",
        "each",
        "either",
        "from",
        "have",
        "into",
        "must",
        "only",
        "should",
        "some",
        "such",
        "than",
        "that",
        "their",
        "them",
        "then",
        "there",
        "these",
        "they",
        "this",
        "those",
        "well",
        "what",
        "when",
        "where",
        "which",
        "will",
        "with",
        "would",
    }
)

#: How much of the smaller of two sentences has to be shared subject matter
#: before they count as the same thing reworded. High on purpose: see the module
#: docstring on which way to be wrong.
SAME_THING_ABOVE = 0.75

#: And how far clear of the runner up. Two previous requirements that score
#: within this of each other are not telling us which one this is, so neither
#: gets the id. Ambiguity resolves to "new", never to a coin toss.
UNAMBIGUOUS_BY = 0.15

Basis = Literal["kept", "matched", "fresh"]


@dataclass(frozen=True)
class Carry:
    """Where each id in a regenerated artefact came from.

    Three buckets rather than a count, because the three mean different things
    to a reader of the results. `kept` is an identity that was observed: the two
    versions say the same words. `matched` is an identity that was inferred from
    similarity, and a claim resting on one of these is weaker than a claim
    resting on a `kept`. `fresh` is the absence of an identity, which is also
    information: it is how many requirements the change note really added.
    """

    kept: tuple[str, ...] = ()
    matched: tuple[str, ...] = ()
    fresh: tuple[str, ...] = ()
    #: The previous version's ids that nothing in this one claimed. Retired, and
    #: never handed out again.
    retired: tuple[str, ...] = ()

    @property
    def notes(self) -> dict[str, int]:
        """For the audit note on the run, which is where honesty metrics live."""
        return {
            "ids_kept": len(self.kept),
            "ids_matched": len(self.matched),
            "ids_new": len(self.fresh),
            "ids_retired": len(self.retired),
        }


@dataclass(frozen=True)
class _Assignment:
    """One current item's id, and how it got it."""

    id: str
    basis: Basis


@dataclass(frozen=True)
class _Candidate:
    """One item to be identified, with everything identity is decided on."""

    #: The wording, which is what similarity is measured over.
    text: str
    #: An exact identity that does not depend on wording at all, when the item
    #: has one. A story's is the set of requirements it realises, and since
    #: those ids are already stable by the time stories are identified, two
    #: stories realising the same requirements are the same story whatever the
    #: model called them this time.
    anchor: frozenset[str] = field(default_factory=frozenset)


def normalise(text: str) -> str:
    """The wording, with everything that is not wording removed."""
    return " ".join(text.casefold().split()).rstrip(".!")


def content_words(text: str) -> frozenset[str]:
    """What a sentence is about: its words, less the ones every sentence has."""
    return frozenset(
        word
        for token in _WORD.findall(text.casefold())
        if len(word := token.strip("'-")) > 3 and word not in _NOISE
    )


def overlap(left: str, right: str) -> float:
    """How much two sentences are about the same thing, from 0 to 1.

    Over the smaller of the two rather than over the union, because a change
    note commonly adds a clause to a requirement rather than rewriting it, and
    the union would read a requirement that grew as a requirement that changed
    identity.
    """
    a, b = content_words(left), content_words(right)
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _next_number(reserved: Collection[str]) -> int:
    """One above the highest number ever used, so nothing is ever reused."""
    used = [int(match.group(1)) for value in reserved if (match := _NUMBER.search(value))]
    return max(used, default=0) + 1


def _only(values: Iterable[int]) -> int | None:
    """The single member, or nothing. How every exact rung avoids a coin toss."""
    found = list(values)
    return found[0] if len(found) == 1 else None


def _unique(values: Iterable[bool]) -> bool:
    """That exactly one thing on this side matches, so a rung has one reading."""
    return sum(1 for value in values if value) == 1


def _validated[T: BaseModel](model: T) -> T:
    """The model through its own validators, which `model_copy` does not run.

    Worth the round trip. `SprintPlan` refuses duplicate story ids and
    `RequirementsArtefact` refuses a trace that resolves to nothing, and those
    two rules are precisely what a mistake in here would break. A silently
    invalid artefact written to the database is the expensive version of this
    bug; a loud failure at the moment the ids were assigned is the cheap one.
    """
    return type(model).model_validate(model.model_dump(by_alias=True, mode="json"))


def _carry(
    current: Sequence[_Candidate],
    previous: Sequence[tuple[str, _Candidate]],
    *,
    prefix: str,
    reserved: Collection[str],
    similar: bool = True,
) -> tuple[tuple[str, ...], Carry]:
    """An id for each current item, in the order they were given.

    Three passes, in falling order of how much they prove, and a pass never
    reconsiders what an earlier one settled. Running them in this order rather
    than scoring everything at once is what makes the result independent of the
    order either list happens to be in.

    `similar` turns off the last pass, for text where a shared wording is not
    evidence of a shared identity. Acceptance criteria are the case: they are
    formulaic, so two criteria of one story differ in a clause and agree on
    everything else, and measuring what they share would read them as one.
    """
    assigned: dict[int, _Assignment] = {}
    claimed: set[int] = set()

    def take(position: int, source: int, basis: Basis) -> None:
        assigned[position] = _Assignment(previous[source][0], basis)
        claimed.add(source)

    # One: the anchor, where there is one. A story's requirements are already
    # stable ids, so this rung does not depend on any wording at all.
    for position, candidate in enumerate(current):
        if not candidate.anchor:
            continue
        if not _unique(other.anchor == candidate.anchor for other in current):
            continue
        match = _only(
            index
            for index, (_, other) in enumerate(previous)
            if index not in claimed and other.anchor == candidate.anchor
        )
        if match is not None:
            take(position, match, "kept")

    # Two: the same words. Only when the wording picks out one item on each
    # side, so two requirements that happen to read alike do not swap ids.
    wording = [normalise(candidate.text) for candidate in current]
    for position in range(len(current)):
        if position in assigned:
            continue
        if not _unique(text == wording[position] for text in wording):
            continue
        match = _only(
            index
            for index, (_, other) in enumerate(previous)
            if index not in claimed and normalise(other.text) == wording[position]
        )
        if match is not None:
            take(position, match, "kept")

    # Three: the same thing, reworded. Best first across the whole remainder, so
    # a strong pair is never broken up by a weaker one that was considered
    # earlier, and only when the best is clear of the runner up.
    pairs: list[tuple[float, int, int]] = []
    for position, candidate in enumerate(current):
        if position in assigned or not similar:
            continue
        for index, (_, other) in enumerate(previous):
            if index in claimed:
                continue
            score = overlap(candidate.text, other.text)
            if score >= SAME_THING_ABOVE:
                pairs.append((score, position, index))
    # Descending score, then by the two positions, so ties resolve the same way
    # every time rather than by whatever order the lists arrived in.
    pairs.sort(key=lambda pair: (-pair[0], pair[1], pair[2]))
    for score, position, index in pairs:
        if position in assigned or index in claimed:
            continue
        rivals = [
            other
            for other, rival_position, rival_index in pairs
            if rival_position not in assigned
            and rival_index not in claimed
            and ((rival_position == position) != (rival_index == index))
        ]
        if rivals and max(rivals) > score - UNAMBIGUOUS_BY:
            # Something else scores nearly as well against one of this pair, so
            # the wording is not saying which of them this is.
            continue
        take(position, index, "matched")

    # Whatever is left is new, numbered above everything this project has ever
    # used. Retiring an id rather than filling the gap is the whole point: a gap
    # in the numbering is readable, an id that came back meaning something else
    # is not.
    number = _next_number(reserved)
    for position in range(len(current)):
        if position not in assigned:
            assigned[position] = _Assignment(f"{prefix}{number}", "fresh")
            number += 1

    order = [assigned[position] for position in range(len(current))]
    return tuple(one.id for one in order), Carry(
        kept=tuple(one.id for one in order if one.basis == "kept"),
        matched=tuple(one.id for one in order if one.basis == "matched"),
        fresh=tuple(one.id for one in order if one.basis == "fresh"),
        retired=tuple(
            identifier for index, (identifier, _) in enumerate(previous) if index not in claimed
        ),
    )


def carry_requirement_ids(
    current: RequirementsArtefact, history: Sequence[RequirementsArtefact]
) -> tuple[RequirementsArtefact, Carry]:
    """Give a freshly read artefact the ids this project already uses.

    `history` is every earlier version of the same artefact, oldest first. One
    argument rather than a previous version plus a set of used ids, because a
    caller that passed the first and forgot the second would get silent id
    reuse, which is the defect this module is here to remove.
    """
    previous = history[-1].requirements if history else []
    ids, carry = _carry(
        [_Candidate(text=one.text) for one in current.requirements],
        [(one.id, _Candidate(text=one.text)) for one in previous],
        prefix="R-",
        reserved=[one.id for version in history for one in version.requirements],
    )

    # Traces inside this artefact point at the placeholder ids, so they move
    # with them. Built from a mapping rather than rewritten in place, because
    # two requirements can swap ids and an in place pass would lose one.
    #
    # A trace to an id this artefact does not contain is left exactly as it is,
    # so `traces_resolve` refuses it and names it. Translating it to something
    # would hide the break, and dropping it would produce an assumption about
    # nothing; a `KeyError` here would be the same refusal with no message.
    renamed = dict(zip((one.id for one in current.requirements), ids, strict=True))
    return (
        _validated(
            current.model_copy(
                update={
                    "requirements": [
                        one.model_copy(update={"id": new})
                        for one, new in zip(current.requirements, ids, strict=True)
                    ],
                    "assumptions": [
                        one.model_copy(
                            update={"traces": [renamed.get(trace, trace) for trace in one.traces]}
                        )
                        for one in current.assumptions
                    ],
                    "questions": [
                        one.model_copy(
                            update={"traces": [renamed.get(trace, trace) for trace in one.traces]}
                        )
                        for one in current.questions
                    ],
                }
            )
        ),
        carry,
    )


def _criterion_ids(
    current: Sequence[AcceptanceCriterion],
    previous: Sequence[AcceptanceCriterion],
    *,
    story_number: str,
    reserved: Collection[str],
) -> tuple[str, ...]:
    """The same rule one level down, within a story that kept its id.

    A criterion is short and formulaic, so only the exact rung is used here.
    "given a basket with two items, when the customer views it, then the total is
    shown" and the same sentence ending "then tax is included" are two different
    criteria that share four content words out of five, so the similarity rung
    scores them as one and hands the second the first one's id. A criterion that
    changed by a word is treated as a new criterion, which loses a little
    history and cannot claim the wrong one.
    """
    ids, _ = _carry(
        [_Candidate(text=_triple(one)) for one in current],
        [(one.id, _Candidate(text=_triple(one))) for one in previous],
        prefix=f"AC-{story_number}-",
        reserved=reserved,
        similar=False,
    )
    return ids


def _triple(criterion: AcceptanceCriterion) -> str:
    return f"{criterion.given} | {criterion.when} | {criterion.then}"


def _story_number(story_id: str) -> str:
    match = _NUMBER.search(story_id)
    return match.group(1) if match else story_id


def carry_story_ids(current: SprintPlan, history: Sequence[SprintPlan]) -> tuple[SprintPlan, Carry]:
    """Give a freshly planned sprint the story ids this project already uses.

    Stories are identified across both lists at once, because a story that slid
    from the sprint into the backlog is the same story and has to keep its id;
    that move is exactly what a change note causes, and it is the reader's most
    likely question about two versions side by side.

    A story's anchor is the set of requirements it realises. Those ids are
    stable by the time this runs, so the strongest rung here does not depend on
    the model's wording at all.
    """
    previous = [*history[-1].proposed, *history[-1].backlog] if history else []
    stories = [*current.proposed, *current.backlog]
    ids, carry = _carry(
        [_Candidate(text=one.title, anchor=frozenset(one.traces)) for one in stories],
        [(one.id, _Candidate(text=one.title, anchor=frozenset(one.traces))) for one in previous],
        prefix="US-",
        reserved=[one.id for version in history for one in (*version.proposed, *version.backlog)],
    )

    was = {one.id: one for one in previous}
    every_criterion = [
        one.id
        for version in history
        for story in (*version.proposed, *version.backlog)
        for one in story.acceptance
    ]

    def rebuilt(story: UserStory, new_id: str) -> UserStory:
        number = _story_number(new_id)
        criteria = _criterion_ids(
            story.acceptance,
            was[new_id].acceptance if new_id in was else [],
            story_number=number,
            # Every criterion id this project has used, so a criterion added to
            # a story that kept its id cannot take a retired sibling's number.
            reserved=[one for one in every_criterion if one.startswith(f"AC-{number}-")],
        )
        return story.model_copy(
            update={
                "id": new_id,
                "acceptance": [
                    one.model_copy(update={"id": new})
                    for one, new in zip(story.acceptance, criteria, strict=True)
                ],
            }
        )

    rebuilt_stories = [rebuilt(story, new) for story, new in zip(stories, ids, strict=True)]
    split = len(current.proposed)
    return (
        _validated(
            current.model_copy(
                update={"proposed": rebuilt_stories[:split], "backlog": rebuilt_stories[split:]}
            )
        ),
        carry,
    )
