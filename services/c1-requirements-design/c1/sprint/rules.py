"""The nine checks a sprint plan has to pass.

Smaller than the other catalogues, and deliberately so. Half the things worth
checking about a sprint plan cannot go wrong here, because the model was never
allowed to produce them: story ids are allocated in sequence so they cannot
collide, priorities are inherited so they cannot contradict the requirement, and
points are counted so they cannot be invented. A rule that can never fire is
worse than no rule, since it pads a catalogue whose whole value is that every
entry means something.

What is left is what the model actually writes, and the acceptance criteria carry
most of the weight. They are the seam to C3, which turns them into test cases, so
a criterion whose `then` restates its `when` is not a stylistic problem: it is a
test that passes without asserting anything.

Two findings do not block. Requirement coverage is the traceability metric and is
worth showing rather than refusing, the same as everywhere else in C1. A story
too big for the largest card is a planning observation, not a malformed artefact:
the plan is still correct, and splitting it is a decision for a person.
"""

import re
from collections.abc import Callable

from sdlc_contracts import ArchitectureGraph, ParsedRequirement

from ..rules.findings import Finding, Report
from .estimate import SCALE, estimate_story
from .schema import DraftPlan, DraftStory


def _title(story: DraftStory, index: int) -> str:
    return story.title or f"the story at position {index + 1}"


Rule = Callable[[DraftPlan, list[ParsedRequirement], ArchitectureGraph], list[Finding]]


def validate_plan(
    plan: DraftPlan,
    *,
    requirements: list[ParsedRequirement],
    graph: ArchitectureGraph,
) -> Report:
    """Run every rule over one plan, in catalogue order."""
    findings: list[Finding] = []
    for rule in ALL_RULES:
        findings.extend(rule(plan, requirements, graph))
    return Report(findings=tuple(findings))


def names_are_present(
    plan: DraftPlan, _requirements: list[ParsedRequirement], _graph: ArchitectureGraph
) -> list[Finding]:
    """1. The sprint has a goal, and every story has a sentence and an epic."""
    findings: list[Finding] = []
    if not plan.goal.strip():
        findings.append(
            Finding(
                rule_id="names-are-present",
                severity="error",
                reason="This sprint has no goal, so there is nothing to judge the plan against.",
                hint="Write one sentence saying what a user can do at the end of this sprint.",
            )
        )
    for index, story in enumerate(plan.stories):
        if not story.title.strip():
            findings.append(
                Finding(
                    rule_id="names-are-present",
                    severity="error",
                    reason=f"The story at position {index + 1} has no title.",
                    hint=(
                        f"Give the story at position {index + 1} a sentence from the reader's "
                        f"side, such as 'As a customer, I can pay with a saved card'."
                    ),
                )
            )
        if not story.epic.strip():
            findings.append(
                Finding(
                    rule_id="names-are-present",
                    severity="error",
                    reason=f"'{_title(story, index)}' does not say which epic it belongs to.",
                    hint=f"Give '{_title(story, index)}' an epic, such as 'Payments' or 'Accounts'.",
                )
            )
    return findings


def no_duplicate_story(
    plan: DraftPlan, _requirements: list[ParsedRequirement], _graph: ArchitectureGraph
) -> list[Finding]:
    """2. No two stories say the same thing.

    A duplicate inflates the point total and makes the sprint look fuller than it
    is, which is the quiet way a plan stops being a plan.
    """
    seen = [story.title.strip().lower() for story in plan.stories if story.title.strip()]
    findings: list[Finding] = []
    for duplicate in sorted({title for title in seen if seen.count(title) > 1}):
        original = next(s.title for s in plan.stories if s.title.strip().lower() == duplicate)
        findings.append(
            Finding(
                rule_id="no-duplicate-story",
                severity="error",
                reason=f"'{original}' is planned twice, which counts its points twice.",
                hint=(
                    f"The story '{original}' appears more than once. Keep one, or make them "
                    f"say different things."
                ),
            )
        )
    return findings


def story_is_traced(
    plan: DraftPlan, _requirements: list[ParsedRequirement], _graph: ArchitectureGraph
) -> list[Finding]:
    """3. Every story says which requirements it realises."""
    return [
        Finding(
            rule_id="story-is-traced",
            severity="error",
            reason=(
                f"'{_title(story, index)}' does not say which requirement it realises, so "
                f"there is no way to tell whether anybody asked for it."
            ),
            hint=(
                f"Story '{_title(story, index)}' has no traces. Add the requirement ids it "
                f"comes from, or remove it if nothing asked for it."
            ),
        )
        for index, story in enumerate(plan.stories)
        if not story.traces
    ]


def traces_resolve(
    plan: DraftPlan, requirements: list[ParsedRequirement], _graph: ArchitectureGraph
) -> list[Finding]:
    """4. Every trace names a requirement that exists."""
    known = {requirement.id for requirement in requirements}
    findings: list[Finding] = []
    for index, story in enumerate(plan.stories):
        unknown = sorted(trace for trace in story.traces if trace not in known)
        if unknown:
            findings.append(
                Finding(
                    rule_id="traces-resolve",
                    severity="error",
                    reason=(
                        f"'{_title(story, index)}' traces to {', '.join(unknown)}, which "
                        f"{'is not a requirement' if len(unknown) == 1 else 'are not requirements'} "
                        f"of this project."
                    ),
                    hint=(
                        f"Story '{_title(story, index)}' names requirement ids that do not "
                        f"exist: {', '.join(unknown)}. Use only ids from the list you were given."
                    ),
                    traces=tuple(unknown),
                )
            )
    return findings


def story_has_acceptance(
    plan: DraftPlan, _requirements: list[ParsedRequirement], _graph: ArchitectureGraph
) -> list[Finding]:
    """5. Every story can be told apart from an unfinished one.

    The contract requires at least one criterion, and the reason is downstream: a
    story C3 cannot derive a test from is a story nobody can tell is done.
    """
    return [
        Finding(
            rule_id="story-has-acceptance",
            severity="error",
            reason=(
                f"'{_title(story, index)}' has no acceptance criteria, so nobody can say "
                f"when it is finished."
            ),
            hint=(
                f"Story '{_title(story, index)}' needs at least one given/when/then saying "
                f"how anyone can tell it works."
            ),
            traces=tuple(story.traces),
        )
        for index, story in enumerate(plan.stories)
        if not story.acceptance
    ]


def acceptance_is_well_formed(
    plan: DraftPlan, _requirements: list[ParsedRequirement], _graph: ArchitectureGraph
) -> list[Finding]:
    """6. Each criterion has all three parts, and the outcome is not the trigger.

    The second half is the one that matters. "When the customer pays, then the
    customer pays" is a criterion a test can be generated from and the test will
    assert nothing, which is worse than having no test because it reports green.
    """
    findings: list[Finding] = []
    for index, story in enumerate(plan.stories):
        for number, criterion in enumerate(story.acceptance, start=1):
            missing = [
                part
                for part, value in (
                    ("given", criterion.given),
                    ("when", criterion.when),
                    ("then", criterion.then),
                )
                if not value.strip()
            ]
            if missing:
                findings.append(
                    Finding(
                        rule_id="acceptance-is-well-formed",
                        severity="error",
                        reason=(
                            f"Criterion {number} of '{_title(story, index)}' is missing its "
                            f"{' and '.join(missing)}."
                        ),
                        hint=(
                            f"Criterion {number} of '{_title(story, index)}' needs a "
                            f"{', a '.join(missing)}. Every criterion has all three parts."
                        ),
                        traces=tuple(story.traces),
                    )
                )
                continue
            if criterion.then.strip().lower() == criterion.when.strip().lower():
                findings.append(
                    Finding(
                        rule_id="acceptance-is-well-formed",
                        severity="error",
                        reason=(
                            f"Criterion {number} of '{_title(story, index)}' says the same "
                            f"thing happens as the thing that triggers it, so it asserts nothing."
                        ),
                        hint=(
                            f"Criterion {number} of '{_title(story, index)}' repeats its 'when' "
                            f"as its 'then'. Say what is observably true afterwards instead."
                        ),
                        traces=tuple(story.traces),
                    )
                )
    return findings


def requirement_coverage(
    plan: DraftPlan, requirements: list[ParsedRequirement], _graph: ArchitectureGraph
) -> list[Finding]:
    """7. Which requirements no story plans to deliver.

    Reported, not enforced. This is the traceability completeness figure for the
    sprint plan, and a figure that can only ever read zero is not a measurement.
    A gap here is a real fact about the plan and belongs in front of a reader.
    """
    planned = {trace for story in plan.stories for trace in story.traces}
    uncovered = [r for r in requirements if r.id not in planned]
    if not uncovered:
        return []

    musts = [r.id for r in uncovered if r.priority == "must"]
    tail = f", including must-haves {', '.join(musts)}" if musts else ""
    return [
        Finding(
            rule_id="requirement-coverage",
            severity="warning",
            reason=(
                f"{len(uncovered)} requirement(s) have no story in this plan{tail}: "
                f"{', '.join(r.id for r in uncovered)}."
            ),
            hint=(
                f"These requirements have no story: {', '.join(r.id for r in uncovered)}. "
                f"Add one for each, or leave them if they are genuinely out of scope."
            ),
            traces=tuple(r.id for r in uncovered),
        )
    ]


def story_is_small_enough(
    plan: DraftPlan, requirements: list[ParsedRequirement], graph: ArchitectureGraph
) -> list[Finding]:
    """8. No story is bigger than the largest card.

    A warning rather than an error, because the plan is not malformed: this story
    is real and it is too big to size, which is an observation for a person
    rather than a reason to refuse the artefact. Splitting it is their decision.
    """
    findings: list[Finding] = []
    for index, story in enumerate(plan.stories):
        estimate = estimate_story(story, graph=graph, requirements=requirements)
        if estimate.too_big_to_plan:
            findings.append(
                Finding(
                    rule_id="story-is-small-enough",
                    severity="warning",
                    reason=(
                        f"'{_title(story, index)}' works out at {estimate.raw}, past the "
                        f"largest card of {SCALE[-1]}, so it is too big to plan as one story: "
                        f"{'; '.join(estimate.because[1:])}."
                    ),
                    hint=(
                        f"Story '{_title(story, index)}' is too big. Split it into stories "
                        f"that each deliver something on their own."
                    ),
                    traces=tuple(story.traces),
                )
            )
    return findings


#: All eight, in the order they are reported.
#: "As a warehouse operator, the system ingests readings from sensors."
#:
#: A role is named and then abandoned: the sentence is about the system, not
#: about the person it claims to be for. Four of sixteen stories in one real run
#: read this way, all of them describing background work that has no actor, and
#: the invented role was always something like "system administrator" that
#: appears nowhere in the requirements.
#:
#: The pattern is specific on purpose. "As the system, I quarantine the
#: consignment" is fine and is how honest background work should read, so the
#: rule looks for a named role followed by the system doing something, not for
#: the word "system".
_ROLE_THEN_SYSTEM = re.compile(r"^\s*As\s+(?:an?|the)\s+([^,]+),\s*the\s+system\b", re.IGNORECASE)


def story_has_a_real_role(
    plan: DraftPlan, _requirements: list[ParsedRequirement], _graph: ArchitectureGraph
) -> list[Finding]:
    """9. A story that names a role is written from that role's point of view."""
    findings: list[Finding] = []
    for index, story in enumerate(plan.stories):
        match = _ROLE_THEN_SYSTEM.match(story.title or "")
        if not match:
            continue
        role = match.group(1).strip()
        if role.lower() in {"system", "platform"}:
            # "As the system, the system ..." is clumsy, not dishonest.
            continue
        findings.append(
            Finding(
                rule_id="story-has-a-real-role",
                severity="error",
                reason=(
                    f"{_title(story, index)} is written for a {role} and then describes "
                    "what the system does, so it is nobody's story."
                ),
                hint=(
                    f"The story at position {index + 1} says 'As a {role}, the system ...'. "
                    f"Either write what the {role} does, or drop the role and write "
                    "'As the system, I ...' if no person is involved."
                ),
                traces=tuple(story.traces),
            )
        )
    return findings


ALL_RULES: tuple[Rule, ...] = (
    names_are_present,
    no_duplicate_story,
    story_is_traced,
    traces_resolve,
    story_has_acceptance,
    acceptance_is_well_formed,
    requirement_coverage,
    story_is_small_enough,
    story_has_a_real_role,
)

#: The names, for the evaluation and for the test that pins the catalogue.
RULE_IDS = (
    "names-are-present",
    "no-duplicate-story",
    "story-is-traced",
    "traces-resolve",
    "story-has-acceptance",
    "acceptance-is-well-formed",
    "requirement-coverage",
    "story-is-small-enough",
    "story-has-a-real-role",
)
