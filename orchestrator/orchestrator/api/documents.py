"""The one upload route: a document in, the text of it out.

Deliberately stateless. Nothing is written to disk or to a table, because the
extracted text's only home is `requirement_text` and the home composer has no
project to attach a document to yet. One endpoint therefore serves both
composers, and there is no document lifecycle to get wrong.
"""

from typing import Annotated

from fastapi import APIRouter, File, UploadFile

from ..documents.extract import BYTE_LIMIT, _megabytes, extract
from ..errors import DomainError

router = APIRouter(prefix="/documents", tags=["documents"])

#: Read in chunks so this function can stop once its own running total passes
#: the limit, rather than materialising however large the already spooled body
#: is in one read call.
_CHUNK = 64 * 1024


def _too_large(size: int) -> DomainError:
    return DomainError(
        f"That file is {_megabytes(size)}. The limit is {_megabytes(BYTE_LIMIT)}.",
        status_code=413,
    )


async def _read_capped(upload: UploadFile) -> bytes:
    """Read the body, refusing it once it passes the limit.

    By the time a route handler runs, FastAPI has already parsed the multipart
    body and Starlette has already spooled this upload to memory or a temporary
    file, so nothing here bounds what crosses the network: the whole body was
    already received before this function's first line executes. Bounding
    receipt itself would need middleware ahead of the multipart parser, and this
    endpoint does not have one. What this does bound is what reaches
    `extract()`'s own PDF and DOCX parsers, and what the caller is told: an
    oversize upload gets a 413 naming the limit rather than however pypdf or
    python-docx would fail on it.

    `upload.size` is the cheap early out, and it is trustworthy: Starlette sets
    it from bytes it has already written while spooling, not from a header. The
    loop below enforces the same limit again while this function does its own
    read.
    """
    if upload.size is not None and upload.size > BYTE_LIMIT:
        raise _too_large(upload.size)

    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(_CHUNK):
        total += len(chunk)
        if total > BYTE_LIMIT:
            raise _too_large(total)
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/extract")
async def extract_document(file: Annotated[UploadFile, File()]) -> dict[str, object]:
    data = await _read_capped(file)
    return extract(file.filename or "document", data).as_payload()
