"""One error shape, matching what the frontend already parses.

`lib/http.ts` throws an `HttpError` carrying the parsed JSON body, so the body
is the only place a caller can learn anything beyond the status. Keeping one
envelope means an error is as inspectable as a success.
"""

import logging
import re
from http import HTTPStatus
from typing import Any

import httpx
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class DomainError(Exception):
    """Something the caller did that the domain refuses, with a reason."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        detail: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        #: Structured reasons beside the sentence, such as each release guard's.
        self.detail = detail


class NotFound(DomainError):
    def __init__(self, what: str, identifier: str) -> None:
        super().__init__(f"{what} {identifier} does not exist", status_code=404)


class Conflict(DomainError):
    def __init__(self, message: str, *, detail: Any = None) -> None:
        super().__init__(message, status_code=409, detail=detail)


def _invalid_request_reason(errors: Any) -> str:
    """The sentence for a request that failed validation.

    A validator that explains itself ("Enter an email address, such as
    you@example.com.") is the reason a person can act on, so it is the sentence;
    anything else is the contract's general refusal, with the details beside it.
    """
    for error in errors or []:
        if error.get("type") == "value_error":
            message = str(error.get("msg", ""))
            return message.removeprefix("Value error, ") or "the request is not valid"
    return "the request body does not match the contract"


def _public_errors(errors: Any) -> list[dict[str, Any]]:
    """Which fields failed and why, without what was sent.

    Pydantic's errors carry the submitted `input`, which for a password field is
    the password, and a validator's exception object, which is not JSON at all.
    """
    return [
        {
            "loc": list(error.get("loc", ())),
            "msg": error.get("msg", ""),
            "type": error.get("type", ""),
        }
        for error in errors or []
    ]


def _envelope(message: str, *, detail: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {"error": message}
    if detail is not None:
        body["detail"] = detail
    return body


#: What the browser is told when the server fails in a way nothing planned for.
#: The exception's own text stays in the server's log: it can name a path or a
#: value on the server, and a reader can do nothing with it.
UNEXPECTED = "The server hit an unexpected problem and could not finish. Try again in a moment."

#: Sentences for the answers Starlette gives in its own words ("Not Found").
_HTTP_SENTENCES = {
    404: "There is nothing at this address.",
    405: "This address does not accept that request.",
}


class AnswerUnexpectedErrors:
    """An unhandled exception answered with the error envelope, inside CORS.

    Starlette answers an unhandled exception from its outermost layer, outside
    every middleware the app adds, CORS included. The browser got a plain text
    500 with no CORS headers, reported it as "Failed to fetch", and the page could
    not even tell that the server had answered. Added before CORS, this sits
    inside it, so the 500 carries the envelope and the headers. The exception is
    raised on afterwards, so the server still logs it with its traceback.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def watching(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, watching)
        except Exception:
            if not started:
                answer = JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content=_envelope(UNEXPECTED),
                )
                await answer(scope, receive, send)
            raise


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> Response:
        # A route that does not exist answered {"detail": "Not Found"}, the one
        # shape nothing in the browser reads.
        headers = getattr(exc, "headers", None)
        if exc.status_code < 200 or exc.status_code in (204, 304):
            return Response(status_code=exc.status_code, headers=headers)
        message = str(exc.detail)
        if message == HTTPStatus(exc.status_code).phrase:
            message = _HTTP_SENTENCES.get(exc.status_code, message)
        return JSONResponse(
            status_code=exc.status_code, content=_envelope(message), headers=headers
        )

    @app.exception_handler(DomainError)
    async def _domain(_: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code, content=_envelope(exc.message, detail=exc.detail)
        )

    @app.exception_handler(RequestValidationError)
    async def _request_invalid(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=_envelope(_invalid_request_reason(errors), detail=_public_errors(errors)),
        )

    @app.exception_handler(ValidationError)
    async def _artefact_invalid(_: Request, exc: ValidationError) -> JSONResponse:
        # A stored artefact that no longer validates is our bug, not the
        # caller's, so it is a 500 that says exactly which field broke rather
        # than a generic failure.
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_envelope("a stored artefact does not match its contract", detail=exc.errors()),
        )


#: Model provider failures we can say something useful about, by the status the
#: provider answered. Only the model client's own failures get them: the codes
#: were matched anywhere in any message, so a Render or Vercel 401 sent a reader
#: to the model's key, and a hash with "429" in it read as a rate limit.
_PROVIDER_HINTS: dict[int, str] = {
    429: (
        "The model provider is rate limiting this account, so the stage could not "
        "finish. Retry it when the limit clears."
    ),
    401: (
        "The model provider rejected the credentials. Check the API key the "
        "component is configured with."
    ),
    403: (
        "The model provider refused this request. The account may not have access "
        "to the configured model."
    ),
}
_OUT_OF_QUOTA = (
    "The model provider says this account is out of quota. Nothing is wrong "
    "with the design; the stage needs a provider that will answer."
)

#: The model client's HTTP failure as it reads once it is text: the status and
#: the model's name side by side, which nothing else writes.
_MODEL_FAILURE = re.compile(r"\bstatus_code: (\d{3}), model_name: ")


def _model_failure(error: BaseException, text: str) -> tuple[int, str] | None:
    """The status a model provider answered and what it said, for the model client's own failure.

    Its own exception carries the model's name beside the status, anywhere in
    the chain that led here, whichever provider it was, without the orchestrator
    depending on the client. Once a failure has crossed a process boundary as
    text, its message still reads that way. Anything else is not the model's.
    """
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        status = getattr(current, "status_code", None)
        if isinstance(status, int) and getattr(current, "model_name", None):
            return status, " ".join(str(current).split())
        current = current.__cause__ or current.__context__
    found = _MODEL_FAILURE.search(text)
    return (int(found.group(1)), text) if found else None


_MODEL_NO_ANSWER = (
    "The model provider did not answer in time, so the stage could not finish. "
    "Retrying it usually works."
)
_MODEL_UNREACHABLE = (
    "The stage could not reach the model provider, so it could not finish. "
    "Retrying it usually works."
)


def _model_unanswered(error: BaseException) -> str | None:
    """Why the model client's own request got no response, when none came.

    On the live run Test Generation stopped with "Request timed out.", which said
    neither what had timed out nor what to do. The model client's exception names
    the model and carries no status, since nothing answered, and is raised from
    the timeout or the failed connection underneath: that is what tells a model
    that did not answer apart from a registry or a GitHub call that timed out.
    """
    seen: set[int] = set()
    current: BaseException | None = error
    model = False
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if getattr(current, "model_name", None) and getattr(current, "status_code", None) is None:
            model = True
        elif model and isinstance(current, TimeoutError | httpx.TimeoutException):
            return _MODEL_NO_ANSWER
        elif model and isinstance(current, ConnectionError | httpx.TransportError):
            return _MODEL_UNREACHABLE
        current = current.__cause__ or current.__context__
    return None


#: Long enough for one of the component's own findings, short enough that a stack
#: trace or a JSON body cannot arrive whole.
_MAX_REASON = 300

log = logging.getLogger(__name__)

#: An absolute path on the server, from its first slash to its last name. Not the
#: path inside a URL: the character before it may not be a colon or a slash.
_SERVER_PATH = re.compile(r"(?<![\w.:/])/(?:[\w.@-]+/)+([\w.@-]+)")


def _without_a_message(error: BaseException) -> str:
    """What went wrong, in words, for an exception that says nothing itself.

    One said "The stage failed with ReadError and no message": the name of a
    class in a library, which tells a reader neither what happened nor whether
    to retry.
    """
    if isinstance(error, TimeoutError | httpx.TimeoutException):
        return (
            "The stage ran out of time waiting for a service it called. Retrying it usually works."
        )
    if isinstance(error, ConnectionError | httpx.TransportError):
        return "The stage lost its connection to a service it called. Retrying it usually works."
    return "The stage stopped on an unexpected error that gave no details. Retrying it may work."


def readable_failure(error: BaseException) -> str:
    """Why a stage failed, in words a reader can act on.

    Two jobs, and the second is the one that is easy to miss. A stage error is
    stored and then returned in a snapshot, so it reaches the browser: a raw
    provider body does not belong there. The one that prompted this carried the
    account's organisation id, the tier, the exact token counts and a billing
    link, all of which went into the database and out to the client.

    The first job is that it has to mean something. "status_code: 429,
    model_name: ..., body: {...}" tells a reader nothing they can do. Whether the
    provider is rate limiting is something they can act on.

    The component's own failures already read as sentences, because they are built
    from the rule that refused, so those pass through and are only trimmed, with
    any path on the server cut to its last name: one carried the full path of a
    project's workspace, the server account's user name in it.

    What a reader is not shown is logged here, so the server keeps it.
    """
    text = " ".join(str(error).split())
    model = _model_failure(error, text)
    if model is not None:
        status, said = model
        if "insufficient_quota" in said:
            return _OUT_OF_QUOTA
        # Any other status is said without the body, which carries the
        # account's own business as the rate limit's did.
        return _PROVIDER_HINTS.get(
            status,
            f"The model provider answered {status}, so the stage could not finish. "
            "Retrying it may work.",
        )
    unanswered = _model_unanswered(error)
    if unanswered is not None:
        return unanswered
    if not text:
        log.warning("A stage failed without a message", exc_info=error)
        return _without_a_message(error)
    shown = _SERVER_PATH.sub(r"\1", text)
    if shown != text:
        log.warning("A stage failed: %s", text)
    return shown[:_MAX_REASON] + ("..." if len(shown) > _MAX_REASON else "")
