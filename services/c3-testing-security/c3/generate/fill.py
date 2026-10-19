"""The model fills the bodies the rules could only declare.

The rules wrote one `it.todo` per acceptance criterion, because they know what
a criterion says and nothing about how to observe it. This is the pass that
writes the observation, and it is the first thing in this component that spends
a model call, so what it is allowed to produce is fenced carefully.

**The incentive to name out loud.** A fill that is accepted when its tests pass
teaches a model to write tests that cannot fail, which is the exact behaviour
this component exists to catch in others. The fence is therefore not "it
passes": it is that every declared test still exists under the same name, every
one of them asserts something, and none of them asserts something vacuous. What
a test is worth beyond that is settled by mutation at the arm level, where a
suite that passes and kills nothing is visible as a number, rather than test by
test, where it would cost minutes each.

**Nothing here runs a test.** A fill is checked by parsing the file and asking
the runner to collect it, never by executing it, and the reason is the same
incentive read from the other end: if a fill were accepted for passing, the
cheapest way to be accepted would be to assert nothing that could fail. What a
filled test then does when it is run is a result, and it belongs to the stage
that runs things. A criterion test that turns red is the report doing its job:
it says the application does not do what the sprint said done means.
"""

import asyncio
import json
import logging
import re
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass, field

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models import Model

from ..agents import MALFORMED_OUTPUT_RETRIES, model_for, output_for, settings_for
from ..model_use import records_answers
from .criteria import SETUP_IMPORT, SUPERTEST_IMPORT, fresh_app_block, fresh_app_of

log = logging.getLogger(__name__)

#: `export interface X` and `export type X`, which exist only at compile time.
_EXPORTED_TYPE = re.compile(r"\bexport\s+(?:interface|type)\s+([A-Za-z_$][\w$]*)")

#: `export class X`, `export function X`, `export const X`, which are real at
#: run time and may legitimately be constructed or called.
_EXPORTED_VALUE = re.compile(
    r"\bexport\s+(?:abstract\s+)?(?:class|function|const|let|var|enum)\s+([A-Za-z_$][\w$]*)"
)

#: One retry with the reasons, then the skeleton ships. C2's number, for C2's
#: reason: a second refusal is a model that cannot satisfy the rule, and a
#: third attempt spends tokens to find that out again.
FILL_ATTEMPTS = 2

_TODO = re.compile(r"\bit\.todo\(\s*(?P<quote>[\"'`])(?P<name>(?:\\.|(?!\1).)*)\1", re.DOTALL)
_TEST = re.compile(r"\bit\(\s*(?P<quote>[\"'`])(?P<name>(?:\\.|(?!\1).)*)\1", re.DOTALL)
_SKIPPED = re.compile(r"\bit\.skip\(\s*(?P<quote>[\"'`])(?P<name>(?:\\.|(?!\1).)*)\1", re.DOTALL)
_ONLY = re.compile(r"\b(?:it|describe|test)\.only\b")

#: `new Thing(...)`, which is the one place a TypeScript type can be mistaken
#: for a value and survive to run time.
_CONSTRUCTED = re.compile(r"\bnew\s+([A-Za-z_$][\w$]*)\s*\(")

#: `new (anything)(...)`, which is how the rule above was routed around. The
#: captured group is the whole parenthesised expression, so a type only name
#: anywhere inside it is the same mistake wearing a disguise.
_CONSTRUCTED_EXPRESSION = re.compile(r"\bnew\s*\((.+?)\)\s*\(", re.DOTALL)

#: `expect` arriving from somewhere. Vitest does not make it global unless a
#: project turns that on, and the generated project does not.
_IMPORTS_EXPECT = re.compile(r"import\s*\{[^}]*\bexpect\b[^}]*\}|\bexpect\s*=\s*require")

#: A named import and where it comes from. Only the braced form: a default or a
#: namespace import brings in whatever the module has, and there is no single
#: name to check against the list.
_NAMED_IMPORT = re.compile(
    r"import\s*(?:type\s+)?\{(?P<names>[^}]*)\}\s*from\s*[\"'](?P<from>[^\"']+)[\"']"
)

#: A dynamic import inside a test body. The skeleton declares what a test may
#: reach; an import written into the body reaches past it.
_DYNAMIC_IMPORT = re.compile(r"\bimport\s*\(")

#: A type query on a module, which the compiler erases.
_TYPE_QUERY = re.compile(r"\btypeof\s+import\s*\(")
ASSERTION = re.compile(r"\bexpect\s*\(")

#: Assertions that cannot fail. Public because the quality catalogue reports
#: them in tests this component did not write: what it refuses to write, it
#: also refuses to stay quiet about.
#: Not a style rule: a test whose assertion holds
#: for every possible program is a test that reports success and measures
#: nothing, and it is the cheapest way for a fill to look successful.
VACUOUS = (
    (re.compile(r"expect\(\s*(true)\s*\)\.(?:toBe\(\s*true\s*\)|toBeTruthy\(\))"), "expect(true)"),
    (
        re.compile(r"expect\(\s*(false)\s*\)\.(?:toBe\(\s*false\s*\)|toBeFalsy\(\))"),
        "expect(false)",
    ),
    (re.compile(r"expect\(\s*(\d+)\s*\)\.toBe\(\s*\1\s*\)"), "a number compared with itself"),
    (
        re.compile(r"expect\(\s*([\"'`])(.*?)\1\s*\)\.toBe\(\s*\1\2\1\s*\)"),
        "a string compared with itself",
    ),
    (re.compile(r"expect\.assertions\(\s*0\s*\)"), "expect.assertions(0)"),
)

#: Things that make a suite unrepeatable rather than wrong. These are refused
#: at fill time and are also what the quality catalogue looks for in tests this
#: component did not write.
#: Ways to make the compiler stop looking, which make asking it pointless.
#:
#: The typecheck was added on 2026-09-26 and the next run came back with
#: `taskListsRepository.create({ title: "Groceries" } as any)` and
#: `(taskListsRepository as any)?.items`, in a draft that compiled cleanly and
#: failed the moment it ran. A cast to `any` is not a type error, so the check
#: passes and says nothing, and the discipline's word "compiles" becomes a
#: formality.
#:
#: **This is the component's own thesis, for the third time in one project.** A
#: static rule tells you what a model stopped writing, not what it stopped
#: doing: the type only constructor rule was routed around by
#: `new (await import(...))()`, and now the compiler is routed around by a cast.
#: It is the argument for running mutants over a repair rather than reading it,
#: and it keeps arriving unprompted.
ESCAPES = (
    (
        re.compile(r"\bas\s+any\b|<any>|:\s*any\b"),
        "a cast to `any`, which turns the compiler off for the line it is on. The modules "
        "you were given are typed; use what they declare",
    ),
    (
        re.compile(r"@ts-(?:ignore|expect-error|nocheck)"),
        "a compiler suppression, which is the same as not compiling this file",
    ),
)

UNREPEATABLE = (
    (re.compile(r"\bMath\.random\s*\("), "unseeded randomness makes a run unrepeatable"),
    (
        re.compile(r"\bsetTimeout\s*\(|\bawait\s+new\s+Promise\s*\(\s*\w*\s*=>\s*setTimeout"),
        "a sleep makes a test slow and flaky rather than deterministic",
    ),
    (
        re.compile(r"\bfetch\s*\(|\baxios\b|XMLHttpRequest|\bnew\s+WebSocket\s*\("),
        "a test may reach the application under test and nothing else",
    ),
    (
        re.compile(r"\bDate\.now\s*\(|\bnew\s+Date\s*\(\s*\)"),
        "the current time makes a test depend on when it runs",
    ),
)


class FilledFile(BaseModel):
    """The one thing the fill model may produce: the file's full content."""

    content: str = Field(min_length=1)


@dataclass(frozen=True)
class FillOutcome:
    content: str | None
    attempts: int
    refused_reasons: tuple[str, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.content is not None


@dataclass
class FillContext:
    """What the model is told about the world it is writing a test in.

    Deliberately small. The criterion, the modules it may import with what they
    export, and the endpoints the contract declares. A model given the whole
    repository writes tests about the repository; a model given the criterion
    and the surface writes a test about the criterion.
    """

    story_title: str = ""
    criteria: list[str] = field(default_factory=list)
    modules: dict[str, list[str]] = field(default_factory=dict)
    endpoints: list[str] = field(default_factory=list)
    #: Exports that exist only at compile time, so the prompt can say so. A
    #: model told only that `CalculationHistory` is exported reaches for its
    #: constructor, which is what the first live fill did; the rule that
    #: refuses that draft then costs two attempts and produces nothing. Saying
    #: it up front is the difference between a refusal and a test.
    types_only: list[str] = field(default_factory=list)
    #: Modules the file's setup loads afresh before every test, and the names it
    #: binds from each. Offered as names to use, never as modules to import.
    bound: dict[str, list[str]] = field(default_factory=dict)
    #: What each offered module declares, as its source writes it: interfaces and
    #: types whole, classes and functions by their heading (`declarations_of`).
    #: Names alone were not enough on Movie Tracker's live run (2026-10-06): the
    #: model called `findAll` on a repository whose method is `list`, and built a
    #: `Movie` without the `id` its type requires.
    declarations: dict[str, list[str]] = field(default_factory=dict)


INSTRUCTIONS = (
    "You write the bodies of tests that have already been named. Rules:\n"
    '1. Every `it.todo("...")` becomes `it("...", async () => { ... })` with '
    "the name copied character for character. Never rename, drop, add or "
    "reorder a test.\n"
    "2. Every body asserts something that could fail. An assertion that holds "
    "for every possible program, such as expect(true).toBe(true), is worse "
    "than no test at all, and an answer containing one is refused.\n"
    "3. Import only from the modules you are told exist, and call only what "
    "they are said to export. Reach nothing over the network.\n"
    "4. No sleeps, no Math.random, no current time, no `.only`, and no `.skip` of "
    "your own. A test already skipped, with a `// Quarantined by` comment above "
    "it, was set aside by a person: leave it and its comment exactly as they are.\n"
    "5. Keep the header comments exactly as they are.\n"
    "6. If a criterion cannot be observed with what you were given, leave that "
    "one as `it.todo`. Saying so is a correct answer; guessing is not.\n"
    "7. A setup that loads the application before every test stays exactly as it "
    "is. Every test starts with empty stores, so each one creates whatever its "
    "`given` describes itself.\n"
    "8. A todo with a `// To be written again` comment above it was written once "
    "and judged wrong by a reviewer, for the reason the comment gives. Write it so "
    "that reason no longer holds.\n"
    "Answer with the complete file content."
)


def build_filler(
    model: str | Model, *, retries: int = MALFORMED_OUTPUT_RETRIES, thinking: str = "off"
):
    return Agent(
        model_for(model),
        output_type=output_for(FilledFile, model, thinking=thinking),
        instructions=INSTRUCTIONS,
        retries=retries,
        model_settings=settings_for(model, thinking=thinking),
        capabilities=[records_answers()],
    )


def as_written(literal: str) -> str:
    """A name as the runner will report it, from the literal in the source.

    The two are not the same string as soon as a criterion contains a quote,
    and acceptance criteria contain them constantly: `then the title "Buy milk"
    is shown`. The generator writes that with `json.dumps`, so the source holds
    `\\"Buy milk\\"` and vitest reports `"Buy milk"`, and a comparison between
    the two never matches.

    That is not cosmetic. The fill's collect check asks whether the runner can
    see the tests the draft claims to have, by name. Live on the task tracker
    every one of the four criteria files was refused twice and the run filled
    nothing, because every criterion in that design quotes a task title. The
    calculator's criteria happened to contain no quotes, which is the only
    reason the same check passed there.

    Decoded rather than pattern matched, because the escapes a model may write
    are the language's and not a list this function should be keeping.
    """
    try:
        return json.loads(f'"{literal}"') if "\\" in literal else literal
    except json.JSONDecodeError:
        # A literal that is not valid JSON, such as one carrying a template
        # expression. The raw text is the honest answer: it is what the source
        # says, and the check that follows will report it as not collected,
        # which is also true of a name nobody can predict.
        return literal


_DESCRIBE = re.compile(r"\bdescribe\(\s*(?P<quote>[\"'`])(?P<name>(?:\\.|(?!\1).)*)\1", re.DOTALL)


def describe_of(source: str) -> str:
    """The suite name the file opens with, as the runner will report it.

    Read from the file rather than rebuilt from the story, because a carried
    file keeps the title its story had when it was written and the runner will
    keep naming its tests with that. A case id built from today's title would
    not match the case the runner reports, which is the join the whole trace
    depends on.
    """
    match = _DESCRIBE.search(source)
    return as_written(match.group("name")) if match else ""


def declared_names(source: str) -> list[str]:
    """Every test the skeleton declares, in order, as the runner will name it."""
    return [as_written(match.group("name")) for match in _TODO.finditer(source)]


def written_names(source: str) -> list[str]:
    """Every test the fill actually wrote a body for, as the runner will name it."""
    return [as_written(match.group("name")) for match in _TEST.finditer(source)]


def skipped_names(source: str) -> list[str]:
    """Every skipped test in a file, as the runner will name it.

    Nothing this platform writes skips a test of its own accord, so each one is
    a test a person quarantined (`decisions.py`).
    """
    return [as_written(match.group("name")) for match in _SKIPPED.finditer(source)]


def code_of(source: str) -> str:
    """The source with what is text rather than code blanked to spaces.

    The insides of strings, template literals and comments, so a bracket in
    `toBe("}")` or in a comment is not read as structure. The same length as
    the source, with its line breaks kept, so an offset or a line number in one
    is the same in the other. A regular expression literal is not recognised.
    """
    blanked = list(source)

    def blank(start: int, end: int) -> None:
        for index in range(start, min(end, len(source))):
            if blanked[index] != "\n":
                blanked[index] = " "

    index = 0
    while index < len(source):
        pair = source[index : index + 2]
        if pair == "//":
            end = source.find("\n", index)
            end = len(source) if end == -1 else end
            blank(index, end)
            index = end
        elif pair == "/*":
            end = source.find("*/", index + 2)
            end = len(source) if end == -1 else end + 2
            blank(index, end)
            index = end
        elif source[index] in "\"'`":
            quote, end = source[index], index + 1
            while end < len(source) and source[end] != quote:
                end += 2 if source[end] == "\\" else 1
            blank(index + 1, end)
            index = end + 1
        else:
            index += 1
    return "".join(blanked)


def body_spans(source: str) -> dict[str, tuple[int, int]]:
    """Where each written test's body starts and ends, by name.

    Brace matching rather than a parser: this runs on a file a model just
    wrote and the questions asked of it, whether the body asserts anything and
    where to put a replacement, do not need an AST. An unbalanced file fails
    the compile check that follows. The braces are read from `code_of`, so a
    `}` in a string or a comment does not end a body early.

    Offsets rather than text, because the repair loop needs to put something
    back exactly where the old body was. `bodies` reads them off these, so the
    two cannot drift.

    Keyed by the name as the runner reports it, the same as `written_names`, or
    the two disagree the moment a criterion quotes something and every lookup
    between them raises.
    """
    code = code_of(source)
    found: dict[str, tuple[int, int]] = {}
    for match in _TEST.finditer(source):
        start = code.find("{", match.end())
        if start == -1:
            found[as_written(match.group("name"))] = (match.end(), match.end())
            continue
        depth = 0
        for index in range(start, len(code)):
            if code[index] == "{":
                depth += 1
            elif code[index] == "}":
                depth -= 1
                if depth == 0:
                    found[as_written(match.group("name"))] = (start, index + 1)
                    break
        else:
            found[as_written(match.group("name"))] = (start, len(source))
    return found


def bodies(source: str) -> dict[str, str]:
    """Each written test's body, roughly, by name."""
    return {
        name: source[start:end] if end > start else ""
        for name, (start, end) in body_spans(source).items()
    }


def type_only_names(sources: dict[str, str]) -> set[str]:
    """Names the project exports as types and never as values.

    TypeScript erases these, so `new CalculationHistory(...)` against an
    `export interface CalculationHistory` transpiles happily and throws "is not
    a constructor" when the test runs. The first live fill wrote exactly that,
    and nothing caught it: the collector imports the module but never executes
    the body, so the draft was accepted and the failure arrived in the report
    looking like the application's fault.

    A name exported as a class or a function anywhere is left out, in that
    direction deliberately. Missing a real mistake costs one red test with a
    clear message; refusing a legitimate `new` would send a model round the
    loop it cannot get out of.
    """
    types: set[str] = set()
    values: set[str] = set()
    for source in sources.values():
        types.update(match.group(1) for match in _EXPORTED_TYPE.finditer(source))
        values.update(match.group(1) for match in _EXPORTED_VALUE.finditer(source))
    return types - values


#: Where an exported declaration starts at the top of a module. `shape` is set
#: for the two kinds shown whole.
_DECLARATION = re.compile(
    r"^export\s+(?:(?P<shape>interface|type)\s+(?=[A-Za-z_$])"
    r"|(?:abstract\s+)?class\s|(?:async\s+)?function[\s*])",
    re.MULTILINE,
)


def declarations_of(source: str) -> list[str]:
    """What a module's exports look like, as its source declares them.

    Interfaces and type aliases whole, since they are the shapes a test builds
    and the methods it calls; classes and functions by their heading, since a
    body says how a thing works rather than how it is used. On Movie Tracker's
    live run (2026-10-06) the model was told the names alone: it called
    `findAll` on a repository whose method is `list`, and built a `Movie` without
    the `id` its type requires, and the compiler refused every draft.
    """
    found: list[str] = []
    for match in _DECLARATION.finditer(source):
        shape = match.group("shape")
        if shape == "interface":
            end = _closing_brace(source, source.find("{", match.end()))
        elif shape == "type":
            end = _statement_end(source, match.end())
        else:
            end = _heading_end(source, match.end())
        if end is not None:
            found.append(source[match.start() : end].strip())
    return found


def _closing_brace(source: str, opening: int) -> int | None:
    """Just past the brace that closes the one at `opening`."""
    if opening == -1:
        return None
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def _statement_end(source: str, start: int) -> int:
    """Just past the semicolon that ends a statement, outside any braces."""
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
        elif source[index] == ";" and depth == 0:
            return index + 1
        elif source.startswith("\n\n", index) and depth == 0:
            return index
    return len(source)


def _heading_end(source: str, start: int) -> int | None:
    """Where a class or function heading ends: its body's brace, outside the parameters."""
    depth = 0
    for index in range(start, len(source)):
        if source[index] == "(":
            depth += 1
        elif source[index] == ")":
            depth -= 1
        elif source[index] == "{" and depth == 0:
            return index
    return None


def imported_names(source: str) -> list[tuple[str, str]]:
    """Every braced import, as (specifier, name), with `as` aliases resolved.

    The alias is dropped on purpose: `{ app as server }` imports `app`, and the
    question here is whether the module exports what was asked of it.
    """
    found: list[tuple[str, str]] = []
    for match in _NAMED_IMPORT.finditer(source):
        for part in match.group("names").split(","):
            name = part.split(" as ")[0].strip().removeprefix("type ").strip()
            if name:
                found.append((match.group("from"), name))
    return found


def unknown_imports(filled: str, known: Mapping[str, Collection[str]]) -> list[str]:
    """Names taken from a module the prompt described, that it does not export.

    The prompt lists each module and what it exports and rule three says to call
    only those, so this is the rule being checked rather than a new one. It went
    unchecked until 2026-09-26, and the first live fill against generated code
    spent three of its tests on `inMemoryCalculationRepository` where the module
    exports `InMemoryCalculationRepository`. TypeScript would have caught it; the
    post checks do not typecheck, and the failure arrived as
    `TypeError: ... is not a function` in the report, reading as the
    application's fault rather than the draft's.

    Only modules the prompt named are checked. `vitest` and `supertest` are in
    the skeleton and are not this function's business, and a specifier nobody
    described is already rule three's problem rather than a spelling question.
    """
    problems: list[str] = []
    for specifier, name in imported_names(filled):
        exports = known.get(specifier)
        if exports is None or name in exports:
            continue
        near = [one for one in exports if one.lower() == name.lower()]
        if near:
            problems.append(
                f"`{name}` is imported from {specifier}, which exports `{near[0]}`. "
                "Names are case sensitive and this one compiles to undefined"
            )
        else:
            problems.append(
                f"`{name}` is imported from {specifier}, which does not export it. "
                f"It exports {', '.join(sorted(exports)) or 'nothing this pass could find'}"
            )
    return problems


def static_problems(
    skeleton: str,
    filled: str,
    *,
    types_only: Collection[str] = (),
    known: Mapping[str, Collection[str]] | None = None,
) -> list[str]:
    """Everything wrong with a fill that can be seen without running it.

    Ordered so the first reason a model reads is the one most likely to explain
    the rest: a dropped test first, then a body that cannot fail.
    """
    problems: list[str] = []
    declared = declared_names(skeleton)
    # Tests the file already had. A criteria file whose story survived a design
    # regeneration keeps them and gains todos for the criteria it now lacks, so
    # a fill is handed a file that is part written. They are the healing loop's
    # input, and the generator is the one component that may not change a test
    # without proving anything, so they are named here as things to leave alone
    # rather than as tests the answer invented.
    kept = written_names(skeleton)
    before = bodies(skeleton)
    written = written_names(filled)
    still_declared = declared_names(filled)

    for name in kept:
        if name not in written:
            problems.append(
                f'the test "{name}" was already written and is gone; it was not yours to '
                "remove, and the loop that may change it runs mutants over the result"
            )
    after = bodies(filled)
    for name in kept:
        if name in after and after[name].strip() != before.get(name, "").strip():
            problems.append(
                f'the body of "{name}" was already written and has been changed; write the '
                "todos and leave every test that has a body exactly as it is"
            )

    for name in declared:
        if name not in written and name not in still_declared:
            problems.append(
                f'the test "{name}" was declared and is now neither written nor left as a '
                "todo; a report counts cases by name, so a test that vanishes is a case "
                "that silently stops existing"
            )
    for name in written:
        if name not in declared and name not in kept:
            problems.append(
                f'the test "{name}" was not one of the declared names; add nothing, and '
                "copy each name character for character"
            )

    # A test a person quarantined stays skipped until a person restores it.
    # Dropped, it would vanish from every later run; run again, it would fail
    # the review its quarantine was recorded to let through.
    set_aside = skipped_names(skeleton)
    still_aside = skipped_names(filled)
    for name in set_aside:
        if name not in still_aside:
            problems.append(
                f'the test "{name}" was quarantined by a person, with the reason above it, '
                "and is no longer skipped; leave it and its comment exactly as they are"
            )
    for name in still_aside:
        if name not in set_aside:
            problems.append(f'the test "{name}" is skipped; skip nothing yourself')

    if declared and not any(name in written for name in declared):
        # Rule six lets a criterion stay a todo when it cannot be observed with
        # what the model was given. All of them staying is not that answer: it
        # is the skeleton back again, and the skeleton already exists.
        problems.append(
            "nothing was filled: every test is still a todo, and the skeleton this was "
            "built from already says that"
        )

    for match in _CONSTRUCTED.finditer(filled):
        name = match.group(1)
        if name in types_only:
            problems.append(
                f"`new {name}(...)` constructs {name}, which the project exports as a type "
                "rather than a class. TypeScript erases it, so this compiles and throws at "
                "run time. Build a plain object literal instead"
            )
    for match in _CONSTRUCTED_EXPRESSION.finditer(filled):
        named = [
            name for name in types_only if re.search(rf"\b{re.escape(name)}\b", match.group(1))
        ]
        if named:
            problems.append(
                f"`new (...)` constructs {named[0]} through an expression, and {named[0]} is a "
                "type rather than a class whichever way it is reached. Build a plain object "
                "literal instead"
            )
    problems.extend(unknown_imports(filled, known or {}))

    # The setup loads the application afresh before every test, which is the
    # one dynamic import a file may have. Without it every test shares one app,
    # and a criterion's "given" includes whatever the tests before it left.
    fresh = fresh_app_of(skeleton)
    reached = filled
    if fresh is not None:
        module, names = fresh
        if " ".join(fresh_app_block(names, module).split()) not in " ".join(filled.split()):
            problems.append(
                "the setup that loads the application afresh before every test was changed "
                "or dropped. Keep it exactly as it is: without it every test shares one "
                "application, and each test's `given` includes what the tests before it left"
            )
        if _imports_statically(filled, module):
            problems.append(
                f"{module} is imported directly, which gives every test in the file one "
                f"shared application. The setup binds {', '.join(names)} afresh before each "
                "test: use those names and import nothing from it"
            )
        reached = SETUP_IMPORT.sub("", filled)
    # `typeof import(...)` names a module's type and loads nothing, so it is not
    # a body reaching past the skeleton. The setup's own bindings are written so.
    reached = _TYPE_QUERY.sub("typeof ", reached)

    if _DYNAMIC_IMPORT.search(reached):
        problems.append(
            "the body imports a module at run time. Everything this test may reach is in the "
            "skeleton's imports already, and an import written into a body reaches past them"
        )

    if _ONLY.search(filled):
        problems.append(
            "`.only` disables every other test in the file, which turns a suite into one test"
        )

    # An assertion the file never imported throws before it can assert
    # anything. The first live run of the remediation loop broke a test with
    # `expect is not defined`, and the run counted it as a failing test.
    if ASSERTION.search(filled) and not _IMPORTS_EXPECT.search(filled):
        problems.append(
            "the body calls `expect` and nothing imports it. Add it to the vitest import "
            "the file already has"
        )

    for name, body in bodies(filled).items():
        if not ASSERTION.search(body):
            problems.append(f'the body of "{name}" asserts nothing, so it cannot fail')
        for pattern, why in VACUOUS:
            if pattern.search(body):
                problems.append(f'the body of "{name}" asserts {why}, which holds for any program')
                break
        for pattern, why in UNREPEATABLE:
            if pattern.search(body):
                problems.append(f'the body of "{name}" uses something forbidden: {why}')
                break
        for pattern, why in ESCAPES:
            if pattern.search(body):
                problems.append(f'the body of "{name}" uses {why}')
                break

    for line in _header_lines(skeleton):
        if line not in filled:
            problems.append(f"the header line `{line}` was dropped")
    return problems


def _imports_statically(source: str, module: str) -> bool:
    """Whether `source` imports a value from `module` with a static import.

    A type only import is erased at compile time and binds nothing that runs,
    so it shares nothing and is left alone.
    """
    quoted = re.escape(module)
    statement = re.compile(
        rf"^\s*import\s+(?!type\b)[^;]*?\bfrom\s*[\"']{quoted}[\"']|^\s*import\s*[\"']{quoted}[\"']",
        re.MULTILINE,
    )
    return statement.search(source) is not None


def _header_lines(skeleton: str) -> list[str]:
    return [
        line.strip()
        for line in skeleton.splitlines()
        if line.strip().startswith("// story:") or line.strip().startswith("// requirements:")
    ]


def prompt_for(skeleton: str, context: FillContext) -> str:
    lines = [
        "Write the bodies for the tests declared in this file.",
        "",
        f"The story: {context.story_title}" if context.story_title else "",
    ]
    if context.criteria:
        lines.append("What each test has to observe, in order:")
        lines.extend(f"  {index + 1}. {text}" for index, text in enumerate(context.criteria))
    if context.modules:
        lines.append("")
        lines.append("Modules you may import, and what they export:")
        for path, exports in sorted(context.modules.items()):
            named = ", ".join(
                f"{name} (a type, not a class: build a plain object literal)"
                if name in set(context.types_only)
                else name
                for name in exports
            )
            lines.append(f"  {path}: {named or 'nothing this pass could find'}")
    if context.bound:
        lines.append("")
        lines.append(
            "Loaded afresh before every test by the file's setup, so every test starts "
            "with empty stores. Use these names as they are and import nothing from "
            "these modules yourself:"
        )
        for path, names in sorted(context.bound.items()):
            lines.append(f"  {path}: {', '.join(names)}")
        lines.append(
            "A response body arrives untyped: give it one of the exported types above, never `any`."
        )
    if context.declarations:
        lines.append("")
        lines.append(
            "What they declare, as their source writes it. Call only these methods, and "
            "build a value with exactly the fields its type has:"
        )
        for path, declared in sorted(context.declarations.items()):
            lines.append(f"  {path}:")
            lines.extend(f"    {line}" for one in declared for line in one.splitlines())
    if SUPERTEST_IMPORT in skeleton:
        lines.append("")
        lines.append(
            "The file imports `request` from supertest, which calls the application in "
            "process, as the user does through the API: `await request(app).post(path)"
            ".send(body)` and `await request(app).get(path)` each answer with `.status` and "
            "`.body`. Act on the application that way; a repository may set up what a "
            "criterion's `given` describes."
        )
    if context.endpoints:
        lines.append("")
        lines.append("The API the application declares:")
        lines.extend(f"  {endpoint}" for endpoint in context.endpoints)
    lines.extend(["", "The file:", skeleton])
    return "\n".join(line for line in lines if line != "")


async def fill(
    agent: Agent[None, FilledFile],
    *,
    skeleton: str,
    context: FillContext,
    max_attempts: int = FILL_ATTEMPTS,
    types_only: Collection[str] = (),
    verify: Callable[[str], list[str]] | None = None,
) -> FillOutcome:
    """One file, filled and post checked, or refused with its reasons.

    A refusal keeps the skeleton, exactly as C2 keeps its rule body: which
    generator authored a file has to stay a fact, and a half accepted fill
    would make it a guess.

    `verify` is a check that needs the file on disk, which today means asking
    the runner to collect it. It runs only after the static checks pass, since
    starting a runner to find out that a body asserts nothing would be slow and
    would say less.

    **It is inside this loop rather than after it, and that is the point.** The
    collect check used to run in the caller: a draft the runner could not parse
    was refused once, with no reason handed back and no second attempt, while a
    draft that merely asserted nothing got the full three with the reason each
    time. The two checks are the same kind of thing and now get the same
    treatment. Live, four of four stories were lost that way on one run, each
    recorded as `attempts: 1`.
    """
    prompt = prompt_for(skeleton, context)
    refused: list[str] = []
    for attempt in range(1, max_attempts + 1):
        result = await agent.run(prompt)
        problems = static_problems(
            skeleton,
            result.output.content,
            types_only=types_only,
            # The same module list the prompt was built from, so the check asks
            # only what the model was told and the refusal can name the spelling
            # it should have used.
            known=context.modules,
        )
        if not problems and verify is not None:
            # On a worker thread: the check runs the compiler and the collector,
            # and the loop this waits on is the orchestrator's (`c3.service`).
            problems = await asyncio.to_thread(verify, result.output.content)
        if not problems:
            return FillOutcome(content=result.output.content, attempts=attempt)
        refused.extend(problems)
        prompt = f"{prompt}\n\nYour previous answer was refused:\n" + "\n".join(
            f"- {problem}" for problem in problems
        )
    log.warning(
        "fill refused %s times; the skeleton ships: %s", max_attempts, "; ".join(refused[:3])
    )
    return FillOutcome(content=None, attempts=max_attempts, refused_reasons=tuple(refused))
