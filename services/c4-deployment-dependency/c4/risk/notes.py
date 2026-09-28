"""Release notes as the model is shown them, and the check every quote must pass.

The notes for one update are a list of sections, one per release, each tagged
with its version. The model is shown them in that form and asked to quote; this
module decides whether a quote is really in them, and in which release.

**Character for character, up to whitespace.** A quote counts when it appears in
a section after runs of whitespace are collapsed on both sides, because a model
rewrapping a line has transcribed it, and a model that changes a word has not.
Nothing else is forgiven: not a dropped backtick, not an ellipsis, not two
sentences joined. The check is about invention, and a paraphrase is the most
common invention there is.

**The window is decided elsewhere.** Which releases fall between the installed
version (exclusive) and the target (inclusive) is a question for the ecosystem's
own ordering, answered where the notes are fetched. Here a window is just the
set of section versions that are in it.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

#: A release heading: `## 2.0.0`, `## [2.0.0] - 2026-01-01`, `# v2.0.0`.
_HEADING = re.compile(
    r"^#{1,6}\s*\[?v?(?P<version>\d+(?:\.\d+)*(?:[-+][0-9A-Za-z.+-]+)?)\]?(?:\s|$)",
    re.MULTILINE,
)


@dataclass(frozen=True)
class Section:
    """The notes of one release."""

    version: str
    text: str


def split_changelog(markdown: str) -> list[Section]:
    """One section per release heading, in document order.

    Text before the first heading belongs to no release and is dropped: a quote
    from a changelog's preamble is not evidence about any version.
    """
    headings = list(_HEADING.finditer(markdown))
    sections = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(markdown)
        sections.append(Section(heading.group("version"), markdown[heading.end() : end].strip()))
    return sections


def normalise(text: str) -> str:
    """Whitespace collapsed to single spaces, and nothing else changed."""
    return " ".join(text.split())


def locate(quote: str, sections: Sequence[Section]) -> Section | None:
    """The section a quote is in, or None when it is in none of them."""
    wanted = normalise(quote)
    if not wanted:
        return None
    for section in sections:
        if wanted in normalise(section.text):
            return section
    return None


def render(sections: Iterable[Section]) -> str:
    """The notes as the model is shown them: a heading per release, newest first."""
    return "\n\n".join(f"## {section.version}\n{section.text}" for section in sections)
