"""Rewriting a stale test, under the same fence the fill is held to.

Only failures the classifier called brittle reach this. A regression is flagged
and left alone, because repairing a test that is telling the truth is the
failure this component exists to prevent, and the shape refuses to carry one.

What the model may do is narrow: change the body of the failing test so it
matches the behaviour the code now has, and leave everything else exactly as it
is. Every other test must survive under its own name, nothing may be added, and
the repaired body must assert something that could fail. Those are the fill's
checks, reused, because a repaired test and a newly written one can be wrong in
exactly the same ways.

**Two shapes for the same request, because the first one measured badly.** The
original asks for the whole file back and reuses the fill's checks to confirm
nothing else moved. That is the hardest possible form of the task: a small model
has to reproduce thirty lines character for character, and epoch 1 recorded the
pinned free model answering with a single import line, twice. That is a non
answer rather than a cheat, and it is a failure of transcription rather than of
judgement.

The `minimal` shape asks only for the replacement body, and this component
splices it into the original at the offsets the old body occupied. Every other
byte of the file is unchanged by construction, so "change nothing else" stops
being something a model has to get right and becomes something it cannot get
wrong. The static checks still run on the assembled file, so nothing is given
up.

Both shapes stay, and which one a repair used is recorded on the outcome. It is
not knowable in advance whether epoch 1 failed because the model is small or
because the task was posed badly, and the honest way to answer that is to run
both against the same model and report the acceptance rate of each. A fix that
is also an experiment is worth more than a fix.

What this file does not decide is whether the repair is any good. It produces a
draft that is well formed; the guard decides whether it is honest, and the guard
is the contribution. A draft that passes everything here and weakens its
assertion is precisely the case the mutant check exists to catch, under either
shape.
"""

import difflib
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models import Model
from sdlc_contracts import TestCase

from ..agents import MALFORMED_OUTPUT_RETRIES, log_rejected, model_for, output_for, settings_for
from ..generate.fill import (
    ASSERTION,
    UNREPEATABLE,
    VACUOUS,
    as_written,
    bodies,
    body_spans,
    code_of,
    written_names,
)
from ..model_use import records_answers
from .referee import Change

log = logging.getLogger(__name__)

#: A test switched off, left unwritten, or made the only one: `it.skip`,
#: `it.todo`, `.only`, on `it`, `test` or `describe`, with its name when it has
#: one. A carried file already holds some, because it declares the criteria its
#: version has not written yet and a person's quarantine is an `it.skip`, so a
#: repair is judged on the ones it adds.
_SWITCHED = re.compile(
    r"\b(?:it|test|describe)\.(?P<how>skip|todo|only)\b"
    r"(?:\(\s*(?P<quote>[\"'`])(?P<name>(?:\\.|(?!(?P=quote)).)*)(?P=quote))?",
    re.DOTALL,
)


def switched(source: str) -> Counter[tuple[str, str]]:
    """Every test a file skips, declares or makes the only one, by how and by name."""
    return Counter(
        (match.group("how"), as_written(match.group("name") or ""))
        for match in _SWITCHED.finditer(source)
    )


_CLOSES = {"(": ")", "[": "]", "{": "}"}


def bracket_problem(source: str) -> str | None:
    """Where the source's brackets stop matching, read outside strings and
    comments, or None when every one closes what it opened.

    A repaired file that does not parse runs no test, and the guard refuses it
    as still failing with no second draft (E-30), so this asks first, while the
    model can still be told why.
    """
    code = code_of(source)
    open_: list[tuple[str, int]] = []
    for index, char in enumerate(code):
        if char in _CLOSES:
            open_.append((char, index))
        elif char in _CLOSES.values():
            line = source.count("\n", 0, index) + 1
            if not open_:
                return f"line {line}: `{char}` closes nothing"
            opened, _ = open_.pop()
            if _CLOSES[opened] != char:
                return f"line {line}: `{char}` where `{_CLOSES[opened]}` was expected"
    if open_:
        char, index = open_[-1]
        return f"line {source.count(chr(10), 0, index) + 1}: `{char}` is never closed"
    return None


def _without_its_own_braces(body: str) -> str:
    """A body as the statements between the test's braces.

    A model told to write those statements sometimes adds the braces the file
    already has: both, or only the closing one of the arrow function, which
    every refused repair of epoch 17 did (E-30). Each is removed only when what
    is left matches, so a body that ends in a block of its own keeps its brace.
    """
    written = body.strip()
    if written.startswith("{") and written.endswith("}") and bracket_problem(written[1:-1]) is None:
        return written[1:-1].strip()
    if written.endswith("}") and bracket_problem(written[:-1]) is None:
        return written[:-1].strip()
    if written.startswith("{") and bracket_problem(written[1:]) is None:
        return written[1:].strip()
    return written


#: One retry with the reasons, then the test is left failing and the refusal is
#: reported. The same number as the fill and the referee, for the same reason.
REPAIR_ATTEMPTS = 2

#: Which form of the request a repair used. Recorded per repair, because the
#: study compares them: an acceptance rate is a fact about a model and a prompt
#: together, and reporting it against the model alone would credit or blame the
#: wrong one.
Shape = Literal["whole-file", "minimal"]

INSTRUCTIONS = (
    "You repair one stale test. The behaviour it checks changed on purpose, and "
    "the test still encodes the old behaviour. Rules:\n"
    "1. Change the body of the named test so it checks the behaviour the code "
    "has now. Change nothing else in the file.\n"
    "2. Every test in the file keeps its name, character for character. Add no "
    "tests and remove none.\n"
    "3. The repaired body must assert something that could fail. Weakening the "
    "assertion until it passes, for example replacing a value check with "
    "`toBeDefined`, is the one thing this loop exists to prevent, and it is "
    "checked by running the test against deliberately broken code.\n"
    "4. No sleeps, no randomness, no current time, no `.only`, no `.skip`.\n"
    "5. Change no file but this one, and no production code at all.\n"
    "Answer with the complete file content."
)


MINIMAL_INSTRUCTIONS = (
    "You repair one stale test. The behaviour it checks changed on purpose, and "
    "the test still encodes the old behaviour.\n"
    "Answer with the replacement body of the named test only: the statements "
    "that go between its braces. Do not repeat the test's name, the other "
    "tests, the imports, or the file. They are kept exactly as they are and "
    "your answer is put in place of the old body.\n"
    "Rules for the body you write:\n"
    "1. It must check the behaviour the code has now.\n"
    "2. It must assert something that could fail. Weakening the assertion until "
    "it passes, for example replacing a value check with `toBeDefined`, is the "
    "one thing this loop exists to prevent, and it is checked by running the "
    "test against deliberately broken code.\n"
    "3. No sleeps, no randomness, no current time, no `.only`, no `.skip`.\n"
    "4. Add no new tests. You are writing one body, not a file."
)


class RepairedFile(BaseModel):
    """The whole file, under the original shape."""

    content: str = Field(min_length=1)


class RepairedBody(BaseModel):
    """Just the replacement body, under the minimal shape.

    Deliberately the only field. A model that cannot be asked for the file
    cannot return the file, so the shape removes the failure rather than
    checking for it.
    """

    body: str = Field(min_length=1)


@dataclass(frozen=True)
class Draft:
    """One answer the loop looked at, kept whether or not it was taken."""

    content: str
    diff: str
    problems: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        return not self.problems

    def rendered(self) -> str:
        """The draft as the report keeps it: what it tried, and why it was
        refused. A convergence number computed from drafts nobody can read is
        not a number anybody can check."""
        if self.accepted:
            return self.diff
        return "refused: " + "; ".join(self.problems[:3]) + "\n" + self.diff


@dataclass
class RepairOutcome:
    """What the loop produced, and everything it looked at on the way."""

    content: str | None = None
    diff: str = ""
    attempts: int = 0
    drafts: list[Draft] = field(default_factory=list)
    #: Set when nothing usable came back, so the caller has a reason without
    #: having to infer one from an absence.
    refusal_reason: str | None = None
    #: Which form of the request produced this. Carried to the report, because
    #: an acceptance rate belongs to a model and a prompt together.
    shape: Shape = "whole-file"

    @property
    def repaired(self) -> bool:
        return self.content is not None


def unified(path: str, before: str, after: str) -> str:
    """The change, as a diff a person can read and an auditor can keep."""
    return "".join(
        difflib.unified_diff(
            before.splitlines(keepends=True),
            after.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=3,
        )
    )


def repair_problems(original: str, repaired: str, *, target: str) -> list[str]:
    """Everything wrong with a repair that can be seen without running it.

    The fill's checks, aimed at a file that already has bodies rather than
    declarations. The one addition is that the test being repaired has to still
    be there: a loop that made a failure go away by deleting the test would
    satisfy every other rule in this file.
    """
    problems: list[str] = []
    before = written_names(original)
    after = written_names(repaired)
    # The caller's `target` is the name the runner reported, which carries the
    # `describe` the file's own name does not. Resolved against the file before
    # anything is compared, or every check below reads a test that is present as
    # missing and refuses a repair that is fine.
    target = named_in(original, target) or target

    if target not in after:
        problems.append(
            f'the test "{target}" is gone from the file; deleting a failing test is not '
            "repairing it, and the report counts cases by name"
        )
    for name in before:
        if name != target and name not in after:
            problems.append(
                f'the test "{name}" was not the one being repaired and is no longer in the file'
            )
    for name in after:
        if name not in before:
            problems.append(f'the test "{name}" was added; repair the named test and nothing else')

    # What the repair added, not what the file had: read over the whole file,
    # every draft for a file that declares an unwritten criterion was refused
    # (E-27), all 16 on E-2's second run. A name keeps a trade honest, so a
    # declaration dropped to make room for a skipped target still counts.
    added = switched(repaired) - switched(original)
    if any(how == "only" for how, _ in added):
        problems.append("`.only` disables every other test in the file")
    if any(how != "only" for how, _ in added):
        problems.append("a skipped or declared test is not a repaired one")

    # Only a mismatch the repair made: one the reader cannot follow in the file
    # already would refuse every repair to it, the mistake E-27 fixed.
    broken = bracket_problem(repaired)
    if broken is not None and bracket_problem(original) is None:
        problems.append(
            f"the repaired file's brackets do not match ({broken}), so it would not parse and "
            "no test in it could run. Return only the statements inside the test's braces, "
            "closing every bracket they open"
        )

    found = bodies(repaired)
    body = found.get(target, "")
    if body and not ASSERTION.search(body):
        problems.append(f'the repaired body of "{target}" asserts nothing, so it cannot fail')
    for pattern, why in VACUOUS:
        if body and pattern.search(body):
            problems.append(
                f'the repaired body of "{target}" asserts {why}, which holds for any program'
            )
            break
    for name, other in found.items():
        for pattern, why in UNREPEATABLE:
            if pattern.search(other):
                problems.append(f'the body of "{name}" uses something forbidden: {why}')
                break
    return problems


def named_in(source: str, name: str) -> str | None:
    """The file's own name for the test the report calls `name`.

    They are not the same string. A report names a test as the runner does,
    which for vitest is the `describe` and the `it` joined by a space, and a
    file names it by the `it` literal alone. So a lookup of the report's name
    in the file's names misses every test that lives inside a `describe`, which
    is every test this platform generates.

    That is not a near miss. The repair loop looked its target up that way, so
    on the first live healing run against generated code all six repairs were
    refused with "the file has no test named ...", after the model had written
    a repair for each. The drafts were fine and the lookup could not find where
    to put them. Checkpoint 2 never showed it because its scenario writes tests
    at the top level with no `describe` around them.

    Matched by suffix, and only when the answer is unique: the file's name is
    the tail of the runner's. Counted over the `it` literals rather than over
    `body_spans`, whose keys are a dict and so collapse two tests that share a
    name inside different `describe` blocks. Either kind of ambiguity refuses,
    because splicing a repair into the wrong test is worse than not repairing.
    """
    declared = written_names(source)
    if declared.count(name) == 1:
        return name
    tails = {one for one in declared if one and name.endswith(one)}
    if len(tails) != 1:
        return None
    only = tails.pop()
    return only if declared.count(only) == 1 else None


def splice(source: str, name: str, body: str) -> str | None:
    """The original file with one test's body replaced.

    Returns nothing when the named test is not in the file, which means the
    caller was asked to repair something that is not there and should say so
    rather than produce a file with an extra test in it.

    The body is accepted with or without its braces, because a model told to
    write "the statements between the braces" will sometimes include them, and
    refusing that would be refusing a correct answer over punctuation. That
    includes one of the two alone (`_without_its_own_braces`): left in, the
    closing one stopped the file parsing on every refused repair of epoch 17.
    """
    spans = body_spans(source)
    found = named_in(source, name)
    if found is None:
        return None
    start, end = spans[found]
    if end <= start:
        return None
    written = _without_its_own_braces(body)
    indent = _indent_of(source, start)
    lines = [f"{indent}  {line.strip()}" if line.strip() else "" for line in written.splitlines()]
    return source[:start] + "{\n" + "\n".join(lines) + f"\n{indent}}}" + source[end:]


def _indent_of(source: str, position: int) -> str:
    """The indentation of the line the body opens on, so the splice reads like
    the file it is going into rather than like something pasted."""
    line_start = source.rfind("\n", 0, position) + 1
    line = source[line_start:position]
    return line[: len(line) - len(line.lstrip())]


def build_repairer(
    model: str | Model,
    *,
    retries: int = MALFORMED_OUTPUT_RETRIES,
    thinking: str = "off",
    shape: Shape = "whole-file",
):
    """The agent for one shape of the request.

    `whole-file` is the original and asks for the file back. `minimal` asks for
    one body and lets this component put it in place, which is the shape a
    small model can actually satisfy.
    """
    if shape == "minimal":
        return Agent(
            model_for(model),
            output_type=output_for(RepairedBody, model, thinking=thinking),
            instructions=MINIMAL_INSTRUCTIONS,
            retries=retries,
            model_settings=settings_for(model, thinking=thinking),
            capabilities=[records_answers()],
        )
    return Agent(
        model_for(model),
        output_type=output_for(RepairedFile, model, thinking=thinking),
        instructions=INSTRUCTIONS,
        retries=retries,
        model_settings=settings_for(model, thinking=thinking),
        capabilities=[records_answers()],
    )


def prompt_for(
    case: TestCase, source: str, changes: list[Change], *, shape: Shape = "whole-file"
) -> str:
    message = case.message.strip().splitlines()
    lines = [
        f"The stale test: {case.name}",
        f"It fails with: {message[0] if message else 'no message'}",
        "",
        "What changed between the version it was written against and the version",
        "it now runs against:",
    ]
    lines.extend(f"  {change.line}" for change in changes)
    if not changes:
        lines.append("  nothing recorded")
    if shape == "minimal":
        # The whole file for context, then the one body it is replacing, so the
        # model can see what it is answering about without being asked to
        # reproduce any of it.
        lines.extend(["", "The file, for context only:", source])
        current = bodies(source).get(named_in(source, case.name) or case.name, "")
        lines.extend(["", f'The body of "{case.name}" as it is now:', current or "(not found)"])
        lines.extend(["", "Answer with its replacement body only."])
    else:
        lines.extend(["", "The file:", source])
    return "\n".join(lines)


async def repair(
    agent: Agent[None, RepairedFile] | Agent[None, RepairedBody],
    case: TestCase,
    *,
    source: str,
    path: str,
    changes: list[Change] | None = None,
    attempts: int = REPAIR_ATTEMPTS,
    shape: Shape = "whole-file",
) -> RepairOutcome:
    """One stale test, rewritten and post checked, or refused with its reasons.

    A refusal leaves the file exactly as it was. The test stays failing, which
    is the honest outcome: it is better than a suite that is green because
    something stopped checking.

    Both shapes converge here on the same assembled file and the same checks,
    so a repair accepted under one is a repair that would have been accepted
    under the other. The only thing the shape changes is how much of the file
    the model had to produce, which is the variable under study.
    """
    outcome = RepairOutcome(shape=shape)
    prompt = prompt_for(case, source, changes or [], shape=shape)
    for attempt in range(1, attempts + 1):
        outcome.attempts = attempt
        answer = (await agent.run(prompt)).output
        outcome.shape = shape_of(answer)
        content = _assembled(answer, source, case.name)
        if content is None:
            # The named test is not in the file at all, so there is nowhere to
            # put the body. A refusal rather than a guess: writing it in
            # somewhere would be inventing a test. Deliberately not phrased as
            # a deletion, because the model deleted nothing: the caller asked
            # about a test this file does not have, and blaming the model for
            # that would put a cheat in the study's counts that nobody made.
            problems = [f'the file has no test named "{case.name}", so there is no body to replace']
            content = source
        else:
            problems = repair_problems(source, content, target=case.name)
        draft = Draft(
            content=content,
            diff=unified(path, source, content),
            problems=tuple(problems),
        )
        outcome.drafts.append(draft)
        if not problems:
            outcome.content = content
            outcome.diff = draft.diff
            return outcome
        log_rejected("self-healing repair", attempt, problems)
        prompt = f"{prompt}\n\nYour previous answer was refused:\n" + "\n".join(
            f"- {problem}" for problem in problems
        )

    outcome.refusal_reason = _why(outcome.drafts)
    return outcome


def _assembled(answer: RepairedFile | RepairedBody, source: str, name: str) -> str | None:
    """The file this answer amounts to, whichever shape produced it."""
    if isinstance(answer, RepairedBody):
        return splice(source, name, answer.body)
    return answer.content


def shape_of(answer: RepairedFile | RepairedBody) -> Shape:
    """Which shape actually answered, read off the answer rather than the ask.

    The parameter says what was requested and this says what arrived. They can
    differ, if a caller points a whole file agent at a minimal prompt, and the
    report should carry what happened: an acceptance rate filed under the wrong
    shape is worse than no acceptance rate, because it will be compared.
    """
    return "minimal" if isinstance(answer, RepairedBody) else "whole-file"


def _why(drafts: list[Draft]) -> str:
    """Which refusal this was, in the report's vocabulary.

    The distinction between the last two is worth keeping and was learned from
    a live run: a model that returns a file with tests in it but not the one it
    was asked to repair has deleted a test, which is a documented cheat. A model
    that returns a file containing nothing but an import line has not cheated,
    it has failed to answer, and the study counts those separately because they
    say different things about the model.
    """
    problems = [problem for draft in drafts for problem in draft.problems]
    if any("holds for any program" in problem for problem in problems):
        return "assertion-weakened"
    if drafts and all(not written_names(draft.content) for draft in drafts):
        return "malformed-output"
    if any("is gone from the file" in problem for problem in problems):
        return "test-deleted"
    return "no-repair-produced"
