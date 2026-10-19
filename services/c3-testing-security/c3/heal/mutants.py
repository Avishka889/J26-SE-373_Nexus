"""Injecting one deliberate fault, and asking one test whether it notices.

This is the mechanism the honesty guard is built on, and it is deliberately
not the mutation pass the quality stage runs. That pass measures a whole suite
against a whole scope: it needs minutes, and it needs the suite to be green
before it will start, which is exactly the state a run in the middle of
repairing a failing test is not in. This asks a much smaller question, of one
test, in seconds, whatever the rest of the suite is doing.

**The question.** A repaired test is accepted only if it still kills a mutant,
because a repair that passes by weakening its assertion passes everything. So:
change one thing in the production code the test exercises, run that one test,
and see it go red. A test that stays green while the code under it is wrong is
watching nothing, and that is true whether the test was just repaired or just
written, which is why the weak fill gate uses the same call.

**Why the mutants are textual and small.** A parser per language would be more
precise and is not worth it here: the question is whether the test notices any
wrong answer, not which wrong answers exist. Every operator below produces
syntactically valid code in both TypeScript and Java, and they are ordered so
the safest go first. One that does not compile is not a survivor: it is a
mutant nobody could evaluate, and the next candidate is tried instead.

**Failing closed.** If no candidate could be decided, the answer is that the
test did not kill anything. A guard that accepted a repair because it ran out
of ways to test it would be a guard in name only.

**Nothing that stops a module loading** (E-28). Every generated test loads its
app afresh before each case, so a module that cannot load turns each of its
tests red whatever they assert, and the guard reads red as noticed. Two kinds
of candidate did that: a module's name changed (`"node:crypto"` became
`"node:crypto~"`, and the guard accepted a repair that asserts the bug), and a
type argument read as a comparison (`Promise<ToDo[]>` became
`Promise<=ToDo[]>`, which does not parse). So a line that names a module is
never broken, as Stryker's string mutator leaves imports alone, and a boundary
is broken only where it is spaced as a comparison is.
"""

import re
from collections.abc import Collection
from dataclasses import dataclass

#: How many candidates to try before giving up on a region. Each costs one run
#: of one test, so this is seconds rather than minutes, and a region where six
#: different faults all go unnoticed has answered the question.
MAX_ATTEMPTS = 6

#: Lines that are only a comment carry no behaviour to break.
_COMMENT = re.compile(r"^\s*(//|\*|/\*|#)")

#: A line that names a module rather than computes anything: an import, Java's
#: included, the `from "..."` that ends one or a re-export, and `import()` or
#: `require()`. Breaking one stops the module loading.
_MODULE_LINE = re.compile(r"""^\s*import\b|\bfrom\s*["']|\bimport\s*\(|\brequire\s*\(""")


@dataclass(frozen=True)
class Mutant:
    """One deliberate fault, small enough to be certain about.

    Carries the whole line before and after, because a reader deciding whether
    to trust a heal wants to see what was broken, and a diff of one character
    with no context is not evidence.
    """

    path: str
    #: One based, as every other line number in this component.
    line: int
    operator: str
    before: str
    after: str
    original_line: str
    mutated_line: str

    @property
    def id(self) -> str:
        return f"{self.path}:{self.line}:{self.operator}"

    def describe(self) -> str:
        return f"{self.operator} at {self.path}:{self.line}: {self.before!r} became {self.after!r}"


def _numeric(line: str) -> list[tuple[str, str]]:
    """A number, one larger. Always valid, always a different answer.

    The safest mutant there is: no operator changes, no types change, and a
    test that asserts a value cannot miss it.
    """
    found: list[tuple[str, str]] = []
    for match in re.finditer(r"(?<![\w.])(\d+)(?![\w.])", line):
        text = match.group(1)
        found.append((text, str(int(text) + 1)))
    return found


def _string(line: str) -> list[tuple[str, str]]:
    """A string literal, made different. Valid wherever a string was valid."""
    found: list[tuple[str, str]] = []
    for match in re.finditer(r'"([^"\\\n]{1,60})"', line):
        found.append((f'"{match.group(1)}"', f'"{match.group(1)}~"'))
    return found


def _boolean(line: str) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for word, other in (("true", "false"), ("false", "true")):
        if re.search(rf"(?<![\w.]){word}(?![\w.])", line):
            found.append((word, other))
    return found


def _boundary(line: str) -> list[tuple[str, str]]:
    """A comparison moved by one place.

    Only where it is spaced as a comparison is: `a < b`, never `Promise<ToDo>`,
    whose `<` read as one became `Promise<=ToDo>`, which does not parse. The
    spaces travel with the operator, so the first spaced one is the one changed
    rather than the first `<` on the line. `>=` and `<=` are tried before `>`
    and `<` so the two character form is never half rewritten, and an arrow
    (`=>`, `->`) has no space before its `>`.
    """
    for before, after in ((" >= ", " > "), (" <= ", " < "), (" > ", " >= "), (" < ", " <= ")):
        if before in line:
            return [(before, after)]
    return []


def _equality(line: str) -> list[tuple[str, str]]:
    for before, after in (("===", "!=="), ("!==", "==="), ("==", "!="), ("!=", "==")):
        if before in line:
            return [(before, after)]
    return []


def _arithmetic(line: str) -> list[tuple[str, str]]:
    """Last, because `+` is string concatenation as often as it is addition,
    and a mutant that does not compile costs a run to find out."""
    found: list[tuple[str, str]] = []
    for before, after in (("*", "/"), ("-", "+"), ("+", "-")):
        if re.search(rf"(?<![-+*/=<>!]){re.escape(before)}(?![-+*/=])", line):
            found.append((before, after))
    return found


#: In order of how certain they are to compile. A candidate that does not is
#: not a survivor, but it does cost a run to discover, so the safe ones lead.
OPERATORS = (
    ("numeric-literal", _numeric),
    ("boolean-literal", _boolean),
    ("string-literal", _string),
    ("boundary", _boundary),
    ("equality", _equality),
    ("arithmetic", _arithmetic),
)


def candidates(source: str, *, path: str, lines: Collection[int] | None = None) -> list[Mutant]:
    """Faults worth injecting into this source, safest first.

    `lines` narrows to the region a test is being asked about, which for the
    honesty guard is the production code that changed between the two versions:
    that is what made the test fail, so it is where the repaired test has to be
    watching.
    """
    found: list[Mutant] = []
    for operator, detect in OPERATORS:
        for number, text in enumerate(source.splitlines(), start=1):
            if lines is not None and number not in lines:
                continue
            if _COMMENT.match(text) or not text.strip() or _MODULE_LINE.search(text):
                continue
            for before, after in detect(text):
                mutated = text.replace(before, after, 1)
                if mutated == text:
                    continue
                found.append(
                    Mutant(
                        path=path,
                        line=number,
                        operator=operator,
                        before=before,
                        after=after,
                        original_line=text,
                        mutated_line=mutated,
                    )
                )
    return found


def inject(source: str, mutant: Mutant) -> str:
    """The source with the fault in it, and nothing else changed."""
    lines = source.splitlines(keepends=True)
    index = mutant.line - 1
    if not 0 <= index < len(lines):
        return source
    ending = "\n" if lines[index].endswith("\n") else ""
    lines[index] = mutant.mutated_line + ending
    return "".join(lines)
