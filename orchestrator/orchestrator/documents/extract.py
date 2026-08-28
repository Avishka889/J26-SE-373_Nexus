"""Turning an uploaded document into the string Component 1 reads.

C1's entire intake is one string, and three things index into it: `measure()`
derives the extraction budget from it, `source_span` offsets are positions in it,
and `sourceQuote` is verified by slicing it. An upload's job is therefore to
become part of that string.

Every refusal here exists to stop a document becoming part of it silently or
wrongly. That is not defensiveness: the code this replaces kept the filename and
threw the file away, so an attached SRS was confirmed on screen and never read,
and a scanned PDF is the case where that failure is invisible.
"""

import io
import math
import re
import zipfile
from dataclasses import dataclass

from ..errors import DomainError

#: Where a document stops being read.
#:
#: `MAX_BUDGET` in c1/rules/measure.py caps the result at thirty requirements
#: however much text arrives, and `prompt_for()` puts the whole string in the
#: prompt, so a forty page SRS costs roughly twenty thousand tokens per attempt
#: and buys nothing. Forty thousand characters is fifteen to twenty pages.
#:
#: The browser applies the same limit to the text files it reads itself, in
#: entities/document/extract.ts. A shared test vector pins the two together.
#:
#: A character is a code point on both sides, which is what `len()` counts here
#: and what a reader means by "character": one emoji is one. The browser has to
#: walk for that, since `String.length` counts UTF-16 code units and would make
#: the same document two different lengths depending on which path read it.
CHAR_LIMIT = 40_000

#: Ten megabytes. Large enough for an image heavy SRS, small enough that this
#: endpoint is not a memory pump.
BYTE_LIMIT = 10 * 1024 * 1024

#: Non-whitespace characters below which one page has no text layer.
#:
#: Judged one page at a time, not as a document average: a four page PDF with
#: one typed page and three blank ones is not "seventy characters a page" on
#: average, it is one page that clears this floor and three that do not. A
#: document is refused only when no page clears it; otherwise it is read, and
#: `pages_without_text` reports the rest. A scanned page leaks a handful of
#: characters at most; a page of real text carries hundreds.
MIN_TEXT_CHARS_PER_PAGE = 25

SUPPORTED = ("pdf", "docx", "txt", "md")

_TRAILING_SPACE = re.compile(r"[ \t]+$", re.MULTILINE)
_MANY_NEWLINES = re.compile(r"\n{3,}")
_WHITESPACE = re.compile(r"\s")
_WORD = re.compile(r"\S+")


@dataclass(frozen=True)
class Extraction:
    """What one document turned out to be."""

    name: str
    format: str
    bytes: int
    #: Pages for a PDF; None for formats with no fixed pagination.
    pages: int | None
    #: How many of those pages did not clear `MIN_TEXT_CHARS_PER_PAGE`, PDF
    #: only, None otherwise. A document that is partly a scan is read partly:
    #: it has real text, so refusing it would be wrong, but reading three of
    #: four pages and saying nothing about the fourth is the same failure as
    #: reading none of it and saying nothing, so this is how the reader is
    #: told which pages were skipped.
    pages_without_text: int | None
    words: int
    chars: int
    #: Length after normalisation and before truncation, so a chip can say
    #: "first 40,000 of 92,400" rather than implying it read everything.
    chars_available: int
    truncated: bool
    text: str

    def as_payload(self) -> dict[str, object]:
        """camelCase, matching every other response the browser reads."""
        return {
            "name": self.name,
            "format": self.format,
            "bytes": self.bytes,
            "pages": self.pages,
            "pagesWithoutText": self.pages_without_text,
            "words": self.words,
            "chars": self.chars,
            "charsAvailable": self.chars_available,
            "truncated": self.truncated,
            "text": self.text,
        }


def normalise(text: str) -> str:
    """Tidy extracted text without changing what it says.

    PDF extraction is noisy: trailing spaces and runs of blank lines that no
    human typed. That noise would reach `split_sentences()` in C1 and inflate the
    evidence count, which sets the extraction budget, so it goes here.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _TRAILING_SPACE.sub("", text)
    text = _MANY_NEWLINES.sub("\n\n", text)
    return text.strip()


def format_of(filename: str) -> str:
    """The claimed format, from the extension, or a refusal naming the options."""
    head, dot, suffix = filename.rpartition(".")
    claimed = suffix.lower()
    if not dot or not head:
        raise DomainError(
            "That file has no extension. Attach a PDF, DOCX, TXT or MD file.",
            status_code=415,
        )
    if claimed not in SUPPORTED:
        raise DomainError(
            f"Cannot read .{claimed} files. Attach a PDF, DOCX, TXT or MD file.",
            status_code=415,
        )
    return claimed


def verify_magic(data: bytes, claimed: str) -> None:
    """Refuse a file whose contents contradict its name.

    Without this a text file renamed to .pdf reaches pypdf and comes back as a
    parser traceback, which tells the reader nothing they can act on.
    """
    if claimed == "pdf" and not data.startswith(b"%PDF-"):
        raise DomainError("This is named .pdf but is not a PDF file.", status_code=415)
    if claimed == "docx" and not data.startswith(b"PK\x03\x04"):
        raise DomainError("This is named .docx but is not a DOCX file.", status_code=415)


def _from_pdf(data: bytes) -> list[str]:
    """One string per page, kept apart so a reader can be told which pages had
    nothing on them rather than only a document wide total."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(data))
        return [page.extract_text() or "" for page in reader.pages]
    except (PdfReadError, ValueError, OSError) as exc:
        raise DomainError(
            "This file could not be read. It may be corrupt.", status_code=422
        ) from exc


def _from_docx(data: bytes) -> str:
    import docx

    try:
        document = docx.Document(io.BytesIO(data))
    except (zipfile.BadZipFile, KeyError, ValueError) as exc:
        raise DomainError(
            "This file could not be read. It may be corrupt.", status_code=422
        ) from exc

    parts = [paragraph.text for paragraph in document.paragraphs]
    # An SRS states its requirements in a table more often than not, and
    # python-docx keeps table text out of `paragraphs` entirely. Without this a
    # table shaped document extracts as empty and is refused as an empty file.
    for table in document.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells)
    return "\n".join(parts)


def _from_text(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        # Not a guess: latin-1 decodes any byte sequence, so this cannot fail and
        # a mojibake character is better than refusing a readable document.
        return data.decode("latin-1")


def _page_has_text(page: str) -> bool:
    """Whether one page clears the floor on its own, independent of every other
    page in the document."""
    return len(_WHITESPACE.sub("", page)) >= MIN_TEXT_CHARS_PER_PAGE


def _refuse_if_unreadable(text: str, claimed: str, page_texts: list[str] | None) -> None:
    """Empty output means different things for different formats.

    An empty text file is an empty text file. A PDF that parses cleanly and
    yields nothing is almost always a scan: the page images are present and the
    text layer is not. That is the exact case the old frontend shipped silently,
    so it gets a message saying what happened. Checked before the empty case
    because a scanned PDF's text is not just short, it is the empty string.

    Judged one page at a time, not as a document average: refused only when no
    page clears the floor, because a document with even one real page of text
    is not a scan and refusing it would be wrong. `page_texts` being an empty
    list means a PDF with zero pages, which is not a scan either, it is a
    broken file; `text` then joins to the empty string too, so this falls
    through to the empty file check below rather than claiming a scan.
    """
    if claimed == "pdf" and page_texts and not any(_page_has_text(page) for page in page_texts):
        # The only refusal that used to name no next step. Text is never read
        # out of page images: OCR is out of scope, deliberately, and a reader
        # meets that decision here rather than in a document they will not read.
        raise DomainError(
            "No readable text. This looks like a scanned document, and text is not "
            "read from scanned pages. Paste the text, or attach a text based version.",
            status_code=422,
        )
    if not text:
        raise DomainError("That file is empty.", status_code=422)


def _megabytes(count: int) -> str:
    """ "24 MB", "10.4 MB", matching `megabytes()` in the browser exactly.

    Rounded up to a tenth rather than to the nearest whole megabyte. Rounding to
    the nearest printed everything from 10 to 10.5 MB as "10 MB", so an oversize
    file was refused with "That file is 10 MB. The limit is 10 MB.", a sentence
    that contradicts itself, and that band is where an oversize file most often
    lands. Rounding up cannot understate, so a file can never print as the size
    of a limit it exceeds.

    It also settles a quieter disagreement: `round()` here is banker's rounding
    and `Math.round()` in the browser is not, so a file of exactly 10.5 MB
    printed as "10 MB" from this side and "11 MB" from the other.
    """
    tenths = math.ceil(count / (1024 * 1024) * 10)
    whole, remainder = divmod(tenths, 10)
    return f"{whole} MB" if remainder == 0 else f"{whole}.{remainder} MB"


def extract(filename: str, data: bytes) -> Extraction:
    """Bytes to the string C1 will read, or a refusal a reader can act on."""
    if len(data) > BYTE_LIMIT:
        raise DomainError(
            f"That file is {_megabytes(len(data))}. The limit is {_megabytes(BYTE_LIMIT)}.",
            status_code=413,
        )

    claimed = format_of(filename)
    verify_magic(data, claimed)

    page_texts: list[str] | None = None
    if claimed == "pdf":
        page_texts = _from_pdf(data)
        raw = "\n\n".join(page_texts)
    elif claimed == "docx":
        raw = _from_docx(data)
    else:
        raw = _from_text(data)

    text = normalise(raw)
    _refuse_if_unreadable(text, claimed, page_texts)

    available = len(text)
    truncated = available > CHAR_LIMIT
    if truncated:
        text = text[:CHAR_LIMIT]

    pages = len(page_texts) if page_texts is not None else None
    pages_without_text = (
        sum(1 for page in page_texts if not _page_has_text(page))
        if page_texts is not None
        else None
    )

    return Extraction(
        name=filename,
        format=claimed,
        bytes=len(data),
        pages=pages,
        pages_without_text=pages_without_text,
        words=len(_WORD.findall(text)),
        chars=len(text),
        chars_available=available,
        truncated=truncated,
        text=text,
    )
