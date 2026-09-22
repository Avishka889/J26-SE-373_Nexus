"""A person's decision about one failing generated test, made in its file.

A test review is not approved while a generated test fails, and a generated
test that asserts something the code does not do can fail for good. The healing
loop leaves a regression alone, a first run has nothing to compare against, and
the generator keeps every written body word for word. So one wrong test made a
project unreleasable. Real teams then do one of two things, with a reason on
the record, and these are those two.

- **Quarantine.** The test is skipped (`it.skip`), with who skipped it, when and
  why on the line above. It stays in the suite and in every later run, skipped
  rather than failing, until a person restores it. The staging build runs the
  same files, so Deployment honours the decision without being told it.
- **Write it again.** For a test that never passed, which nothing ever checked
  against the code: it goes back to a todo, with the reason on the line above,
  so the next run's fill writes it afresh from its criterion.

Made in the file because the file is what every later run and the staging build
read. The route that asks for it also records it where the page and Activity
read decisions.
"""

import json

from ..heal.repair import named_in
from .fill import _SKIPPED, _TEST, as_written, body_spans, skipped_names, written_names

#: The line above a skipped test, and the line above a test sent back to a todo.
#: Fixed words, because a reader looks for them and so do the parsers below.
QUARANTINED_BY = "// Quarantined by"
WRITE_AGAIN_FOR = "// To be written again, asked by"


class NoSuchTest(ValueError):
    """The decision names a test the file does not hold exactly once."""


def quarantine(source: str, name: str, *, by: str, reason: str, on: str) -> str:
    """The file with one written test skipped, and who skipped it, when and why above it."""
    return _skipped_with(
        source, name, f"{QUARANTINED_BY} {_one_line(by)} on {on}: {_one_line(reason)}"
    )


def _skipped_with(source: str, name: str, note: str) -> str:
    start, stop, line_start = _written(source, name)
    indent = source[line_start:start]
    skipped = source[start:stop].replace("it(", "it.skip(", 1)
    return source[:line_start] + f"{indent}{note}\n" + indent + skipped + source[stop:]


def restore(source: str, name: str) -> str:
    """The file with a quarantined test running again, and its note gone."""
    literal = _single(skipped_names(source), name)
    for match in _SKIPPED.finditer(source):
        if as_written(match.group("name")) != literal:
            continue
        line_start = source.rfind("\n", 0, match.start()) + 1
        running = source[: match.start()] + "it(" + source[match.start() + len("it.skip(") :]
        above = source.rfind("\n", 0, max(line_start - 1, 0)) + 1
        if line_start and running[above:line_start].strip().startswith(QUARANTINED_BY):
            return running[:above] + running[line_start:]
        return running
    raise NoSuchTest(f"the file has no skipped test named {name!r}")


def write_again(source: str, name: str, *, by: str, reason: str, on: str) -> str:
    """The file with one written test taken back to a todo, and the reason above it.

    The next run's fill writes every todo afresh from its criterion, so this is
    how a test that never passed is asked for again rather than kept for good.
    """
    start, stop, line_start = _written(source, name)
    indent = source[line_start:start]
    literal = named_in(source, name) or name
    note = f"{indent}{WRITE_AGAIN_FOR} {_one_line(by)} on {on}: {_one_line(reason)}\n"
    todo = f"it.todo({json.dumps(literal)});"
    return source[:line_start] + note + indent + todo + source[stop:]


def carry_quarantines(earlier: str, fresh: str) -> str:
    """A file written afresh, with the quarantines its earlier version carried.

    The oracle tests are written again from the contract on every run, so a
    quarantine made in their file would last until the next run and the test
    would fail again. Each one comes across with its note word for word, while
    the fresh file still has a test of that name; a test the contract no longer
    asks for takes its quarantine with it.
    """
    for literal in skipped_names(earlier):
        note = _note_above(earlier, literal)
        if note is None or written_names(fresh).count(literal) != 1:
            continue
        fresh = _skipped_with(fresh, literal, note)
    return fresh


def answered(source: str) -> str:
    """The file without the requests its fill has answered.

    A request to write a test again sits above its todo until the fill writes
    the test. Left above the written test, it would read as a request still
    open; the decision itself stays on the record, beside the run and in
    Activity.
    """
    lines = source.splitlines(keepends=True)
    kept = [
        line
        for index, line in enumerate(lines)
        if not (
            line.strip().startswith(WRITE_AGAIN_FOR)
            and index + 1 < len(lines)
            and _TEST.match(lines[index + 1].lstrip())
        )
    ]
    return "".join(kept)


def _note_above(source: str, literal: str) -> str | None:
    """The quarantine note on the line above a skipped test, when a person left one."""
    for match in _SKIPPED.finditer(source):
        if as_written(match.group("name")) != literal:
            continue
        line_start = source.rfind("\n", 0, match.start()) + 1
        above = source.rfind("\n", 0, max(line_start - 1, 0)) + 1
        line = source[above:line_start].strip() if line_start else ""
        return line if line.startswith(QUARANTINED_BY) else None
    return None


def _written(source: str, name: str) -> tuple[int, int, int]:
    """Where the named written test's whole statement starts and stops, and its line starts."""
    literal = named_in(source, name)
    if literal is None:
        raise NoSuchTest(
            f"the file does not hold exactly one written test named {name!r}, so nothing "
            "was changed rather than the wrong test"
        )
    for match in _TEST.finditer(source):
        if as_written(match.group("name")) != literal:
            continue
        _body_start, body_stop = body_spans(source)[literal]
        close = source.find(")", body_stop)
        if close == -1:
            raise NoSuchTest(f"the test {name!r} does not close, so nothing was changed")
        stop = close + 1
        if source[stop : stop + 1] == ";":
            stop += 1
        return match.start(), stop, source.rfind("\n", 0, match.start()) + 1
    raise NoSuchTest(f"the file has no written test named {name!r}")


def _single(names: list[str], name: str) -> str:
    """The file's own name for a test the report calls `name`, when there is exactly one."""
    if names.count(name) == 1:
        return name
    tails = {one for one in names if one and name.endswith(one)}
    if len(tails) == 1:
        only = tails.pop()
        if names.count(only) == 1:
            return only
    raise NoSuchTest(f"the file does not hold exactly one skipped test named {name!r}")


def _one_line(text: str) -> str:
    """A reason as one comment line: a newline in it would end the comment."""
    return " ".join(text.split())


def decide(source: str, name: str, decision: str, *, by: str, reason: str, on: str) -> str | None:
    """One decision made in one file: the file as it should now read, or None.

    None when the file does not hold the test as the decision needs it, so the
    caller refuses rather than writes a file with the wrong test changed. A
    quarantined test asked for again is restored first, then sent back.
    """
    try:
        if decision == "quarantined":
            return quarantine(source, name, by=by, reason=reason, on=on)
        if decision == "restored":
            return restore(source, name)
        if decision == "rewrite":
            if _skipped(source, name):
                source = restore(source, name)
            return write_again(source, name, by=by, reason=reason, on=on)
    except NoSuchTest:
        return None
    raise ValueError(f"{decision!r} is not a decision about a test")


def _skipped(source: str, name: str) -> bool:
    try:
        _single(skipped_names(source), name)
    except NoSuchTest:
        return False
    return True
