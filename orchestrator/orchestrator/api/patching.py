"""Applying an approved patch to a code version, or refusing to.

C3 proposes and does not write source. The orchestrator owns the artefact
store and the version axis, so it is what applies an approved patch and
allocates the version that carries it. That split is not bookkeeping: it is
what keeps one writer for generated code and makes a security fix reviewable by
the same machinery as any other change.

**A patch that no longer applies is refused, never forced.** Every context line
and every removed line has to match the file as it stands. A fuzzy apply that
slid a hunk to a nearby offset would be this component writing code nobody
reviewed, into the one place where being wrong is worst: the fix for a
vulnerability, applied to a file that moved underneath it.

**Refusal is the expected outcome often enough to design for.** A proposal is
made against one code version and applied against whatever is current. If the
code regenerated in between, the file it was written against is gone, and the
honest answer is that the fix has to be proposed again rather than jammed into
a file that no longer looks like the one it was written for.

Unified diffs are the interchange format because they are the one a reviewer
can read. The parser handles what `difflib.unified_diff` emits, which is what
produces every patch in this system, and refuses anything it does not
understand rather than guessing.
"""

import re
from dataclasses import dataclass, field

#: `@@ -12,7 +12,8 @@`, the only header shape difflib writes.
_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


# Not frozen, and not a detail: Python's exception machinery assigns to an
# exception while raising it, so a frozen dataclass raises FrozenInstanceError
# from inside the raise and buries the real failure.
@dataclass
class PatchRefused(Exception):
    """Why a patch may not be applied, in words a reader can act on."""

    path: str
    reason: str

    def __str__(self) -> str:
        return f"{self.path}: {self.reason}"


@dataclass
class Hunk:
    """One contiguous change, as the diff describes it."""

    start: int
    lines: list[str] = field(default_factory=list)


def parse(diff: str) -> list[Hunk]:
    """The hunks in a unified diff, or nothing for a diff with none.

    File headers are skipped rather than validated: the path travels beside the
    diff on the patch hunk, and trusting the `---` line instead would let a
    patch name one file and be applied to another.
    """
    hunks: list[Hunk] = []
    current: Hunk | None = None
    for line in diff.splitlines():
        header = _HUNK.match(line)
        if header:
            current = Hunk(start=int(header.group(1)))
            hunks.append(current)
            continue
        if current is None or line.startswith(("---", "+++")):
            continue
        if line[:1] in (" ", "+", "-") or line == "":
            current.lines.append(line if line else " ")
    return hunks


def apply_to(source: str, diff: str, *, path: str = "") -> str:
    """The file with the diff applied, or a refusal saying what did not match.

    Line endings are preserved by splitting without them and rejoining with
    the separator the file already used: a patch that silently converted a file
    to unix endings would show as a whole file change in the next diff a
    reviewer reads.
    """
    hunks = parse(diff)
    if not hunks:
        raise PatchRefused(path, "the patch contains no hunks")

    newline = "\r\n" if "\r\n" in source else "\n"
    ends_with_newline = source.endswith(("\n", "\r\n"))
    lines = source.replace("\r\n", "\n").split("\n")
    if ends_with_newline and lines and lines[-1] == "":
        lines.pop()

    # Applied back to front, so an earlier hunk's edit cannot move the line
    # numbers a later one was written against.
    for hunk in sorted(hunks, key=lambda one: -one.start):
        lines = _apply_one(lines, hunk, path)

    body = newline.join(lines)
    return body + newline if ends_with_newline else body


def _apply_one(lines: list[str], hunk: Hunk, path: str) -> list[str]:
    at = hunk.start - 1
    if at < 0 or at > len(lines):
        raise PatchRefused(path, f"the patch expects a line {hunk.start} this file does not have")

    before: list[str] = []
    after: list[str] = []
    for line in hunk.lines:
        marker, text = line[0], line[1:]
        if marker in (" ", "-"):
            before.append(text)
        if marker in (" ", "+"):
            after.append(text)

    found = lines[at : at + len(before)]
    if found != before:
        # Named precisely: a reviewer reading this needs to know the file
        # moved, not merely that something went wrong.
        mismatch = next(
            (
                index
                for index, pair in enumerate(zip(found, before, strict=False))
                if pair[0] != pair[1]
            ),
            len(found),
        )
        expected = before[mismatch] if mismatch < len(before) else "(end of hunk)"
        actual = found[mismatch] if mismatch < len(found) else "(end of file)"
        raise PatchRefused(
            path,
            f"line {hunk.start + mismatch} does not match the patch. "
            f"Expected {expected.strip()[:60]!r}, found {actual.strip()[:60]!r}. "
            "The file changed after this change was proposed, so it has to be proposed again",
        )
    return lines[:at] + after + lines[at + len(before) :]


def reverse(diff: str) -> str:
    """The diff that undoes this one, for putting a kept test repair back.

    What the diff added, its reverse removes, and the other way round; each
    hunk's two ranges swap. Applied to the file the diff produced, it is held
    to the same exact match the diff was held to against the original, so a
    file that moved on since is refused rather than half restored.
    """
    out: list[str] = []
    headers: list[str] = []
    removed: list[str] = []
    added: list[str] = []
    in_hunk = False

    def flush() -> None:
        # Removed lines before added ones, as a diff is read.
        out.extend(removed)
        out.extend(added)
        removed.clear()
        added.clear()

    for line in diff.splitlines():
        header = _HUNK.match(line)
        if header:
            flush()
            if not in_hunk:
                out.extend(_swapped(headers))
                in_hunk = True
            old_start, old_length, new_start, new_length = header.groups()
            out.append(f"@@ -{_range(new_start, new_length)} +{_range(old_start, old_length)} @@")
        elif not in_hunk:
            headers.append(line)
        elif line.startswith("+"):
            removed.append("-" + line[1:])
        elif line.startswith("-"):
            added.append("+" + line[1:])
        else:
            flush()
            out.append(line)
    flush()
    return "\n".join(out) + "\n"


def _swapped(headers: list[str]) -> list[str]:
    """`--- a/x` and `+++ b/x` become `--- b/x` and `+++ a/x`."""
    old = next((line[4:] for line in headers if line.startswith("--- ")), None)
    new = next((line[4:] for line in headers if line.startswith("+++ ")), None)
    if old is None or new is None:
        return headers
    return [f"--- {new}", f"+++ {old}"]


def _range(start: str, length: str | None) -> str:
    return start if length is None else f"{start},{length}"


def apply_all(files: dict[str, str], hunks: list[tuple[str, str]]) -> dict[str, str]:
    """Every hunk against the files it names, all or nothing.

    All or nothing because a half applied security fix is worse than none: the
    finding is closed in the report and the weakness is still there in the file
    the second hunk was meant to reach.
    """
    changed = dict(files)
    for path, diff in hunks:
        if path not in changed:
            raise PatchRefused(path, "the patch names a file this code version does not contain")
        changed[path] = apply_to(changed[path], diff, path=path)
    return changed
